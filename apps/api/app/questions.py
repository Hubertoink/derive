"""Dynamic, structured preference questions for the reader profile."""

from __future__ import annotations

import json
import re

import httpx

from .models import AppSettings
from .secrets import decrypt_secret


QUESTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["format", "topic", "perspective", "quality", "source", "discovery", "rhythm"],
                    },
                    "question": {"type": "string"},
                    "context": {"type": "string"},
                    "basis": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "value": {"type": "string"},
                                "label": {"type": "string"},
                            },
                            "required": ["value", "label"],
                        },
                    },
                },
                "required": ["kind", "question", "context", "basis", "options"],
            },
        },
    },
    "required": ["questions"],
}

ALLOWED_KINDS = {"format", "topic", "perspective", "quality", "source", "discovery", "rhythm"}


class QuestionGenerationError(RuntimeError):
    pass


def _output_text(payload: dict) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    for item in payload.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                return str(content.get("text", ""))
    return ""


def _compact(value: object, limit: int) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _validated_questions(value: str) -> list[dict]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as error:
        raise QuestionGenerationError("Die KI-Antwort war kein gültiges JSON.") from error
    raw_questions = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(raw_questions, list):
        raise QuestionGenerationError("Die KI-Antwort enthielt keine Fragenliste.")

    questions: list[dict] = []
    seen_questions: set[str] = set()
    for raw in raw_questions:
        if not isinstance(raw, dict):
            continue
        question = _compact(raw.get("question"), 280)
        context = _compact(raw.get("context"), 600)
        basis = _compact(raw.get("basis"), 300)
        kind = str(raw.get("kind") or "quality")
        if kind not in ALLOWED_KINDS:
            kind = "quality"
        normalized_question = question.casefold()
        if not question or normalized_question in seen_questions:
            continue

        options: list[dict] = []
        seen_values: set[str] = set()
        for raw_option in raw.get("options", []):
            if not isinstance(raw_option, dict):
                continue
            label = _compact(raw_option.get("label"), 100)
            value = re.sub(r"[^a-z0-9_-]+", "_", str(raw_option.get("value") or "").casefold()).strip("_")[:80]
            if not value or not label or value in seen_values:
                continue
            options.append({"value": value, "label": label})
            seen_values.add(value)
        if len(options) < 2:
            continue
        seen_questions.add(normalized_question)
        questions.append({
            "kind": kind,
            "question": question,
            "context": context or "Eine kurze Antwort hilft dérive, deine nächste Auswahl genauer abzustimmen.",
            "basis": basis or "Aktuelle Lese- und Rückmeldesignale",
            "options": options[:4],
        })
    if not questions:
        raise QuestionGenerationError("Die KI hat keine verwendbare Rückfrage erzeugt.")
    return questions[:3]


def _instructions() -> str:
    return """
Du bist der persönliche Lesekurator von dérive. Formuliere ein bis drei kurze,
respektvolle Rückfragen, die echte Unsicherheiten im aktuellen Leseprofil klären.
Frage nur nach Informationen, die künftige Artikel-, Podcast- oder Kunstempfehlungen
merklich verändern können. Wiederhole keine bereits beantwortete Frage und frage nicht
nach sensiblen persönlichen Eigenschaften. Formuliere auf Deutsch, ruhig und konkret.

Jede Frage braucht zwei bis vier knappe, gegenseitig unterscheidbare Antwortoptionen.
Das freie Textfeld der Oberfläche ergänzt diese Optionen. "basis" erklärt transparent,
welche vorhandenen Signale die Frage ausgelöst haben, ohne technische Interna zu nennen.
Gib ausschließlich das geforderte JSON aus.
""".strip()


def _input(reader_memory: str, seed_questions: list[dict]) -> str:
    seeds = "\n".join(
        f"- {item['question']} (Grundlage: {item['basis']})"
        for item in seed_questions
    ) or "- Keine vorformulierte Unsicherheit; prüfe Widersprüche und Lücken selbst."
    return f"""
Aktuelles, lokal aufgebautes Leseprofil:
{reader_memory[:9000]}

Regelbasiert erkannte mögliche Unsicherheiten. Sie sind Hinweise, keine Pflichtfragen:
{seeds}

Erzeuge nur Fragen, deren Antwort einen klaren Unterschied für die nächste Kuratierung macht.
""".strip()


async def generate_profile_questions(
    settings: AppSettings,
    reader_memory: str,
    seed_questions: list[dict],
) -> list[dict]:
    if not settings.ai_base_url or not settings.ai_model or settings.ai_provider == "disabled":
        raise QuestionGenerationError("Die KI-Verbindung ist nicht vollständig eingerichtet.")
    api_key = decrypt_secret(settings.ai_api_key_encrypted)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    instructions = _instructions()
    user_input = _input(reader_memory, seed_questions)

    try:
        async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
            if settings.ai_provider == "openai":
                if not api_key:
                    raise QuestionGenerationError("Für die Fragengenerierung fehlt der OpenAI API-Schlüssel.")
                response = await client.post(
                    f"{settings.ai_base_url.rstrip('/')}/responses",
                    headers=headers,
                    json={
                        "model": settings.ai_model,
                        "instructions": instructions,
                        "input": user_input,
                        "store": False,
                        "max_output_tokens": 1200,
                        "text": {
                            "format": {
                                "type": "json_schema",
                                "name": "derive_reader_questions",
                                "strict": True,
                                "schema": QUESTION_SCHEMA,
                            }
                        },
                    },
                )
                response.raise_for_status()
                value = _output_text(response.json())
            elif settings.ai_provider == "ollama":
                response = await client.post(
                    f"{settings.ai_base_url.rstrip('/')}/api/chat",
                    json={
                        "model": settings.ai_model,
                        "stream": False,
                        "format": "json",
                        "messages": [
                            {"role": "system", "content": instructions},
                            {"role": "user", "content": user_input},
                        ],
                    },
                )
                response.raise_for_status()
                value = str(response.json().get("message", {}).get("content", ""))
            else:
                response = await client.post(
                    f"{settings.ai_base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json={
                        "model": settings.ai_model,
                        "messages": [
                            {"role": "system", "content": instructions},
                            {"role": "user", "content": user_input},
                        ],
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
                value = str(response.json()["choices"][0]["message"]["content"])
    except QuestionGenerationError:
        raise
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
        raise QuestionGenerationError(f"Die KI-Fragengenerierung ist fehlgeschlagen: {str(error)[:300]}") from error
    return _validated_questions(value)
