"""Local-history multi-turn chat for refining the discovery profile."""

from __future__ import annotations

import json
import re

import httpx
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .discovery import (
    DiscoveryRunResult,
    import_candidates,
    import_podcast_candidates,
    reading_memory,
    request_candidates,
    request_podcast_candidates,
)
from .models import AppSettings, DiscoveryChatMessage, User
from .visuals import refresh_hero_visual
from .secrets import decrypt_secret


CHAT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "reply": {"type": "string"},
        "suggested_profile": {"type": ["string", "null"]},
    },
    "required": ["reply", "suggested_profile"],
}


class ChatError(RuntimeError):
    pass


def serialize_message(message: DiscoveryChatMessage) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "profile_suggestion": message.profile_suggestion,
        "created_at": message.created_at.isoformat(),
    }


def chat_history(session: Session, limit: int = 40, user: User | None = None) -> list[DiscoveryChatMessage]:
    query = select(DiscoveryChatMessage)
    if user:
        query = query.where(DiscoveryChatMessage.user_id == user.id)
    messages = session.scalars(
        query.order_by(desc(DiscoveryChatMessage.id)).limit(limit)
    ).all()
    history = list(reversed(messages))
    # Retries of the same ad-hoc request used to leave duplicate user bubbles
    # in the local history. Keep the oldest occurrence for context and display.
    seen_user_messages: set[str] = set()
    result: list[DiscoveryChatMessage] = []
    for message in history:
        if message.role == "user":
            if message.content in seen_user_messages:
                continue
            seen_user_messages.add(message.content)
        result.append(message)
    return result


def _instructions(settings: AppSettings) -> str:
    return f"""
Du bist der persönliche Lesekurator in dérive. Führe ein natürliches, knappes Gespräch,
um herauszufinden, welche langen Reportagen, Essays und Analysen der Nutzer lesen möchte.
Frage sinnvoll nach Themen, Perspektiven, Regionen, Sprachen und unerwünschten Mustern.
Aktuelles Suchprofil: {settings.discovery_prompt}
Mindestlesezeit: {settings.discovery_min_minutes} Minuten.
Paywall-Empfehlungen: {'erlaubt' if settings.discovery_include_paywalled else 'nicht erwünscht'}.
Seltener gewünschte Quellen: {settings.discovery_deprioritized_sources_csv or 'keine'}.

Wenn die Präferenz hinreichend konkret ist, liefere in suggested_profile nur eine kurze,
konkrete Ergänzung zum bestehenden Suchprofil. Wiederhole das bestehende Profil nicht und
verwirf keine bisherigen Kriterien. Sonst setze suggested_profile auf null. Behaupte nicht, auf
Abo-Inhalte zugreifen zu können, und fordere niemals Passwörter, Cookies oder Session-Tokens an.
""".strip()


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


def _parse_reply(value: str) -> tuple[str, str | None]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return value.strip(), None
    if not isinstance(payload, dict):
        return value.strip(), None
    reply = str(payload.get("reply") or "").strip()
    suggestion = payload.get("suggested_profile")
    suggestion = str(suggestion).strip() if suggestion else None
    return reply, suggestion


async def _openai_turn(settings: AppSettings, messages: list[dict]) -> tuple[str, str | None]:
    api_key = decrypt_secret(settings.ai_api_key_encrypted)
    if not api_key or not settings.ai_base_url or not settings.ai_model:
        raise ChatError("Die OpenAI-Verbindung ist nicht vollständig eingerichtet.")
    body = {
        "model": settings.ai_model,
        "instructions": _instructions(settings),
        "input": messages,
        "store": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "reado_curator_chat",
                "strict": True,
                "schema": CHAT_SCHEMA,
            }
        },
    }
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        response = await client.post(
            f"{settings.ai_base_url.rstrip('/')}/responses",
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
        )
        response.raise_for_status()
        return _parse_reply(_output_text(response.json()))


async def _compatible_turn(settings: AppSettings, messages: list[dict]) -> tuple[str, str | None]:
    if not settings.ai_base_url or not settings.ai_model:
        raise ChatError("Die KI-Verbindung ist nicht vollständig eingerichtet.")
    api_key = decrypt_secret(settings.ai_api_key_encrypted)
    system = _instructions(settings) + "\nAntworte als JSON mit reply und suggested_profile."
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        if settings.ai_provider == "ollama":
            response = await client.post(
                f"{settings.ai_base_url.rstrip('/')}/api/chat",
                json={
                    "model": settings.ai_model,
                    "stream": False,
                    "format": "json",
                    "messages": [{"role": "system", "content": system}, *messages],
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
                    "messages": [{"role": "system", "content": system}, *messages],
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            value = str(response.json()["choices"][0]["message"]["content"])
    return _parse_reply(value)


async def chat_turn(
    session: Session, settings: AppSettings, user_content: str, *, user: User | None = None
) -> DiscoveryChatMessage:
    if settings.ai_provider == "disabled":
        raise ChatError("Aktiviere zuerst einen KI-Provider in den Einstellungen.")
    history = [
        {"role": message.role, "content": message.content}
        for message in chat_history(session, limit=20, user=user)
    ]
    messages = [*history, {"role": "user", "content": user_content}]
    try:
        reply, suggestion = (
            await _openai_turn(settings, messages)
            if settings.ai_provider == "openai"
            else await _compatible_turn(settings, messages)
        )
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
        raise ChatError(f"Der KI-Chat ist fehlgeschlagen: {str(error)[:300]}") from error
    if not reply:
        raise ChatError("Der KI-Chat hat keine Antwort geliefert.")

    session.add(DiscoveryChatMessage(user_id=user.id if user else None, role="user", content=user_content))
    assistant = DiscoveryChatMessage(
        user_id=user.id if user else None, role="assistant",
        content=reply[:8000],
        profile_suggestion=suggestion[:4000] if suggestion else None,
    )
    session.add(assistant)
    session.commit()
    session.refresh(assistant)
    return assistant


def _research_context(session: Session, user: User | None) -> str:
    history = chat_history(session, limit=8, user=user)
    if not history:
        return "Noch kein weiterer Chat-Kontext."
    return "\n".join(
        f"{('Nutzer' if message.role == 'user' else 'dérive')}: {message.content[:700]}"
        for message in history
    )


def requested_podcast_count(user_content: str, selection: int | None) -> int:
    """Let an explicit UI choice win, otherwise read a small count from the prompt."""
    if selection is not None:
        return max(0, min(selection, 3))
    lowered = user_content.casefold()
    if "podcast" not in lowered:
        return 0
    request_word = r"(?:bitte|suche|finde|empf(?:iehl|ehl)|möchte|will|gern|kannst|könntest)"
    for pattern in (
        rf"{request_word}\b.{{0,50}}\b([0-3])\s+(?:podcast|episode)",
        rf"{request_word}\b.{{0,50}}(?:podcast|episode)\w*\s+(?:mit\s+)?([0-3])\b",
    ):
        match = re.search(pattern, lowered)
        if match:
            return int(match.group(1))
    words = {"ein": 1, "eine": 1, "einen": 1, "zwei": 2, "drei": 3}
    for word, count in words.items():
        if re.search(rf"{request_word}\b.{{0,50}}\b{word}\w*\s+(?:podcast|episode)", lowered):
            return count
    if re.search(rf"{request_word}\b.{{0,50}}\b(?:podcast|episode)", lowered):
        return 3
    return 0


def podcast_only_request(user_content: str, requested_podcasts: int) -> bool:
    """Distinguish an episode request from requests for texts about podcasts."""
    if not requested_podcasts or "podcast" not in user_content.casefold():
        return False
    return re.search(
        r"\b(?:artikel|texte?|reportage\w*|essays?|studie\w*|aufs(?:atz|ätze)\w*|lektüre)\b",
        user_content.casefold(),
    ) is None


async def chat_research(
    session: Session,
    settings: AppSettings,
    user_content: str,
    *,
    max_articles: int = 3,
    max_podcasts: int | None = None,
    breadth: str = "balanced",
    user: User,
) -> DiscoveryRunResult:
    """Run immediate, scoped web research without touching the regular cadence."""
    if settings.ai_provider != "openai":
        raise ChatError("Die Ad-hoc-Webrecherche benötigt aktuell den OpenAI-Provider.")
    requested_podcasts = requested_podcast_count(user_content, max_podcasts)
    # An ad-hoc research request always needs at least one text. A zero value
    # is not useful in this UI and is clamped defensively for older clients.
    requested_articles = max(1, min(max_articles, 12))
    breadth_guidance = {
        "focused": "Bleibe eng bei der Anfrage und priorisiere fachliche Tiefe vor Themenvielfalt.",
        "balanced": "Streue Quellen, Perspektiven und Formate sinnvoll, bleibe aber klar bei der Anfrage.",
        "expansive": (
            "Erweitere den Horizont bewusst: kombiniere direkte Treffer mit angrenzenden, erkenntnisreichen "
            "Perspektiven aus anderen Regionen, Disziplinen oder Quellen. Jeder Text muss den Zusammenhang erklären."
        ),
    }.get(breadth, "Streue Quellen und Perspektiven sinnvoll.")
    prompt = f"""
Ad-hoc-Recherche aus dem Kurator-Chat. Finde bis zu {requested_articles} besonders passende Texte für
diese konkrete Anfrage: {user_content}

Streuung: {breadth_guidance}

Nutze den bisherigen Chat nur als zusätzlichen Kontext, nicht als Anlass, das gespeicherte
Suchprofil oder den Suchrhythmus zu verändern:
{_research_context(session, user)}
""".strip()
    candidates: list[dict] = []
    usage = (0, 0, 0)
    articles = []
    if requested_articles:
        try:
            candidates, usage = await request_candidates(
                settings,
                prompt,
                reading_memory(session, user),
                max_articles=requested_articles,
                session=session,
                user=user,
            )
        except Exception as error:
            if isinstance(error, ChatError):
                raise
            raise ChatError(str(error)) from error

        articles = import_candidates(
            session,
            settings,
            candidates,
            max_articles=requested_articles,
            update_schedule=False,
            user=user,
        )
    podcasts = []
    podcast_usage = (0, 0, 0)
    if requested_podcasts:
        try:
            podcast_candidates, podcast_usage = await request_podcast_candidates(
                settings,
                f"Ad-hoc-Podcast-Recherche zu dieser konkreten Anfrage: {user_content}\n\nStreuung: {breadth_guidance}\n\nBisheriger Chat-Kontext:\n{_research_context(session, user)}",
                reading_memory(session, user),
                max_podcasts=requested_podcasts,
            )
            podcasts = import_podcast_candidates(
                session, podcast_candidates, max_podcasts=requested_podcasts, user=user
            )
        except Exception:
            # Podcast results are optional; keep valid article research usable.
            podcast_usage = (0, 0, 0)
    try:
        if candidates:
            await refresh_hero_visual(settings, candidates)
    except Exception:
        # A decorative hero image must not turn a completed research request
        # into an API 500 after the article metadata was saved.
        session.rollback()
    # A retry of the same ad-hoc request should not add a second identical
    # user bubble to the persistent conversation. The new assistant result is
    # still kept, so the user can compare what changed after a retry.
    already_logged = session.scalar(
        select(DiscoveryChatMessage.id)
        .where(
            DiscoveryChatMessage.role == "user",
            DiscoveryChatMessage.user_id == user.id,
            DiscoveryChatMessage.content == user_content,
        )
        .limit(1)
    )
    if already_logged is None:
        session.add(DiscoveryChatMessage(user_id=user.id, role="user", content=user_content))
    session.add(
        DiscoveryChatMessage(
            user_id=user.id, role="assistant",
            content=(
                f"Ich habe {len(articles)} neue {'Text' if len(articles) == 1 else 'Texte'} "
                f"und {len(podcasts)} neue {'Podcast-Episode' if len(podcasts) == 1 else 'Podcast-Episoden'} "
                "für diese einmalige Recherche gefunden. Sie erscheinen direkt unter dieser Nachricht "
                "und im Archiv; dein regelmäßiges Profil bleibt unverändert."
            ),
        )
    )
    session.commit()
    return DiscoveryRunResult(
        articles=articles,
        podcasts=podcasts,
        input_tokens=usage[0] + podcast_usage[0],
        output_tokens=usage[1] + podcast_usage[1],
        total_tokens=usage[2] + podcast_usage[2],
    )
