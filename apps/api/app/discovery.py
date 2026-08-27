"""AI-assisted article discovery without copying restricted article text."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
import html
import json
import logging
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .feeds import plain_text, validate_public_url
from .art import refresh_artwork_impression
from .models import AppSettings, Article, ArticleFeedback, Artwork, Author, PodcastEpisode, Source, User, UserArticle, UserArticleFeedback, UserArtworkFeedback, UserPodcastEpisode, UserPodcastFeedback, UserReadingInsight, UserReadingQuestion, UserSourceMemory
from .secrets import decrypt_secret
from .spotify import SpotifyError, search_spotify_episodes, spotify_is_configured
from .visuals import refresh_hero_visual


DISCOVERY_BATCH_SIZE = 3
INTER_BATCH_DELAY_SECONDS = 2.5
RATE_LIMIT_RETRIES = 3
NETWORK_RETRIES = 2
NETWORK_RETRY_DELAY_SECONDS = 1.5
MAX_PODCASTS_PER_RUN = 3
MAX_PODCAST_LINK_REDIRECTS = 6
MAX_PODCAST_VALIDATION_BYTES = 160_000

logger = logging.getLogger(__name__)

DISCOVERY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "articles": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "author": {"type": "string"},
                    "source": {"type": "string"},
                    "published_at": {"type": "string"},
                    "reading_minutes": {"type": "integer"},
                    "topics": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                    "summary": {"type": "string"},
                    "visual_query": {"type": "string"},
                    "access_status": {
                        "type": "string",
                        "enum": ["free", "paywalled", "unknown"],
                    },
                },
                "required": [
                    "title", "url", "author", "source", "published_at",
                    "reading_minutes", "topics", "reason", "summary", "visual_query", "access_status",
                ],
            },
        }
    },
    "required": ["articles"],
}

PODCAST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "podcasts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "show_name": {"type": "string"},
                    "url": {"type": "string"},
                    "spotify_url": {"type": "string"},
                    "published_at": {"type": "string"},
                    "duration_minutes": {"type": "integer"},
                    "topics": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": [
                    "title", "show_name", "url", "spotify_url", "published_at",
                    "duration_minutes", "topics", "reason", "summary",
                ],
            },
        }
    },
    "required": ["podcasts"],
}


class DiscoveryError(RuntimeError):
    pass


@dataclass
class DiscoveryRunResult:
    articles: list[Article]
    podcasts: list[PodcastEpisode]
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    candidates: list[dict] = field(default_factory=list)


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def normalize_source_domain(value: str | None) -> str:
    """Return a stable, human-usable source key for URLs and manual entries."""
    raw = str(value or "").strip().casefold()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    hostname = (parsed.hostname or "").strip().rstrip(".").casefold()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname or raw.strip("/")


def _manual_source_keys(settings: AppSettings) -> set[str]:
    return {
        key
        for item in _csv(settings.discovery_deprioritized_sources_csv)
        for key in {normalize_source_domain(item), item.casefold().strip()}
        if key
    }


def backfill_source_memory(session: Session, user: User) -> None:
    """Seed source memory once from already imported AI recommendations."""
    rows = session.execute(
        select(Article, Source)
        .join(UserArticle, UserArticle.article_id == Article.id)
        .join(Source, Source.id == Article.source_id)
        .where(UserArticle.user_id == user.id, Article.discovery_method == "ai_web")
    ).all()
    grouped: dict[str, dict[str, object]] = {}
    for article, source in rows:
        domain = normalize_source_domain(source.url) or normalize_source_domain(article.canonical_url)
        if not domain:
            continue
        item = grouped.setdefault(domain, {"name": source.name, "count": 0, "last": None})
        item["count"] = int(item["count"]) + 1
        observed_at = article.discovered_at or article.published_at
        if observed_at and (item["last"] is None or observed_at > item["last"]):
            item["last"] = observed_at
    for domain, item in grouped.items():
        memory = session.scalar(
            select(UserSourceMemory).where(
                UserSourceMemory.user_id == user.id,
                UserSourceMemory.domain == domain,
            )
        )
        count = int(item["count"])
        if memory is None:
            memory = UserSourceMemory(
                user_id=user.id,
                domain=domain,
                display_name=str(item["name"] or domain),
                observed_count=count,
                source_score=min(100, count * 10),
                last_observed_at=item["last"],
            )
            session.add(memory)
        elif memory.observed_count < count:
            memory.observed_count = count
            memory.source_score = max(memory.source_score, min(100, count * 10))
            memory.last_observed_at = item["last"] or memory.last_observed_at


def sync_manual_source_memory(session: Session, user: User, settings: AppSettings) -> None:
    """Keep the legacy manual source field linked to normalized source memory."""
    manual_items = _csv(settings.discovery_deprioritized_sources_csv)
    manual_keys = {normalize_source_domain(item) or item.casefold() for item in manual_items}
    rows = session.scalars(select(UserSourceMemory).where(UserSourceMemory.user_id == user.id)).all()
    rows_by_domain = {row.domain: row for row in rows}
    for item in manual_items:
        domain = normalize_source_domain(item) or item.casefold()
        memory = rows_by_domain.get(domain)
        if memory is None:
            memory = UserSourceMemory(
                user_id=user.id,
                domain=domain,
                display_name=item,
                origin="manual",
            )
            session.add(memory)
            rows_by_domain[domain] = memory
        memory.status = "deprioritized"
        memory.manual_override = True
    for memory in rows:
        # A learned source can have an explicit status chosen in the source
        # memory UI. Keep that choice across worker/app restarts. Only remove
        # the legacy manual deprioritization when its input field no longer
        # contains a source created as a manual entry.
        if memory.origin == "manual" and memory.manual_override and memory.domain not in manual_keys:
            memory.manual_override = False
            if memory.status == "deprioritized":
                memory.status = "active"


def serialize_source_memory(session: Session, user: User) -> list[dict]:
    rows = session.scalars(
        select(UserSourceMemory)
        .where(UserSourceMemory.user_id == user.id)
        .order_by(UserSourceMemory.source_score.desc(), UserSourceMemory.observed_count.desc(), UserSourceMemory.domain)
    ).all()
    return [
        {
            "domain": row.domain,
            "name": row.display_name or row.domain,
            "origin": row.origin,
            "status": row.status,
            "observed_count": row.observed_count,
            "positive_count": row.positive_count,
            "negative_count": row.negative_count,
            "search_count": row.search_count,
            "score": row.source_score,
            "last_observed_at": row.last_observed_at.isoformat() if row.last_observed_at else None,
            "last_selected_at": row.last_selected_at.isoformat() if row.last_selected_at else None,
        }
        for row in rows
    ]


def _source_memory_guidance(
    session: Session, user: User | None, settings: AppSettings
) -> tuple[str, list[str]]:
    if user is None:
        return "", []
    manual_keys = _manual_source_keys(settings)
    rows = [
        row for row in session.scalars(
            select(UserSourceMemory).where(
                UserSourceMemory.user_id == user.id,
                UserSourceMemory.status == "active",
                UserSourceMemory.observed_count >= 1,
            )
        ).all()
        if row.domain not in manual_keys
    ]
    rows.sort(key=lambda row: (
        row.last_selected_at is not None,
        row.last_selected_at or datetime.max.replace(tzinfo=UTC),
        -row.source_score,
        -row.observed_count,
    ))
    selected = rows[:8]
    if not selected:
        return (
            "Quellenstrategie: Es gibt noch keinen etablierten persönlichen Quellenpool. Suche offen im Web und entdecke neue Publikationen.",
            [],
        )
    now = datetime.now(UTC)
    for row in selected:
        row.last_selected_at = now
        row.search_count += 1
    session.commit()
    labels = ", ".join(f"{row.display_name or row.domain} ({row.domain})" for row in selected)
    return (
        "Quellenstrategie für diesen Lauf: Nutze die folgenden etablierten Publikationen als wichtigen "
        f"Suchansatz, aber nicht ausschließlich: {labels}. Liefere höchstens etwa zwei Drittel der Treffer "
        "aus diesem Pool und reserviere mindestens ein Drittel für offene Websuche, neue Publikationen und "
        "angrenzende Perspektiven. Wenn eine Pool-Quelle nichts Aktuelles oder Passendes bietet, überspringe sie.",
        [row.domain for row in selected],
    )


def record_source_observation(
    session: Session,
    user: User,
    domain: str,
    display_name: str,
    observed_at: datetime | None = None,
) -> None:
    if not domain:
        return
    memory = session.scalar(
        select(UserSourceMemory).where(
            UserSourceMemory.user_id == user.id,
            UserSourceMemory.domain == domain,
        )
    )
    if memory is None:
        memory = UserSourceMemory(
            user_id=user.id,
            domain=domain,
            display_name=display_name or domain,
            observed_count=0,
            source_score=0,
        )
        session.add(memory)
    memory.display_name = display_name or memory.display_name or domain
    memory.observed_count += 1
    memory.source_score = min(100, memory.source_score + 8)
    memory.last_observed_at = observed_at or datetime.now(UTC)


def reading_memory(session: Session, user: User, settings: AppSettings | None = None) -> str:
    """Build a weighted, inspectable memory without equating reading with liking."""
    settings = settings or session.scalar(select(AppSettings).where(AppSettings.user_id == user.id))
    saved_articles = session.scalars(
        select(Article).join(UserArticle, UserArticle.article_id == Article.id)
        .where(UserArticle.user_id == user.id, UserArticle.is_saved.is_(True))
        .order_by(desc(UserArticle.saved_at), desc(Article.published_at)).limit(24)
    ).all()
    read_only_articles = session.scalars(
        select(Article).join(UserArticle, UserArticle.article_id == Article.id)
        .where(
            UserArticle.user_id == user.id,
            UserArticle.is_read.is_(True),
            UserArticle.is_saved.is_(False),
        )
        .order_by(desc(UserArticle.read_at), desc(Article.published_at)).limit(18)
    ).all()
    feedback_rows = session.execute(
        select(UserArticleFeedback, Article)
        .join(Article, Article.id == UserArticleFeedback.article_id)
        .where(UserArticleFeedback.user_id == user.id)
        .order_by(desc(UserArticleFeedback.updated_at), desc(UserArticleFeedback.id))
        .limit(24)
    ).all()
    recent_ai_titles = session.scalars(
        select(Article.title)
        .join(UserArticle, UserArticle.article_id == Article.id)
        .where(UserArticle.user_id == user.id, Article.discovery_method == "ai_web")
        .order_by(desc(UserArticle.discovered_at))
        .limit(36)
    ).all()
    podcast_feedback_rows = session.execute(
        select(UserPodcastFeedback, PodcastEpisode)
        .join(PodcastEpisode, PodcastEpisode.id == UserPodcastFeedback.podcast_episode_id)
        .where(UserPodcastFeedback.user_id == user.id)
        .order_by(desc(UserPodcastFeedback.updated_at)).limit(18)
    ).all()
    artwork_feedback_rows = session.execute(
        select(UserArtworkFeedback, Artwork)
        .join(Artwork, Artwork.id == UserArtworkFeedback.artwork_id)
        .where(UserArtworkFeedback.user_id == user.id)
        .order_by(desc(UserArtworkFeedback.updated_at)).limit(18)
    ).all()
    confirmed_insights = session.scalars(
        select(UserReadingInsight).where(
            UserReadingInsight.user_id == user.id,
            UserReadingInsight.status == "confirmed",
        ).order_by(desc(UserReadingInsight.updated_at)).limit(12)
    ).all()
    answered_questions = session.scalars(
        select(UserReadingQuestion).where(
            UserReadingQuestion.user_id == user.id,
            UserReadingQuestion.status == "answered",
        ).order_by(desc(UserReadingQuestion.updated_at)).limit(12)
    ).all()
    soul = settings.soul_markdown.strip() if settings else ""
    if not saved_articles and not read_only_articles and not feedback_rows and not podcast_feedback_rows and not artwork_feedback_rows and not confirmed_insights and not answered_questions and not recent_ai_titles and not soul:
        return "Noch keine lokalen Lesesignale vorhanden."

    sections: list[str] = []
    if soul:
        sections.append(
            "Vom Nutzer festgelegte kuratorische Haltung (höchste Priorität; keine bloße Verhaltensableitung):\n"
            + soul[:6000]
        )
    if confirmed_insights:
        statements = " | ".join(insight.text for insight in confirmed_insights if insight.text)
        if statements:
            sections.append("Vom Nutzer bestätigte Langzeiterinnerungen: " + statements[:3000])
    if answered_questions:
        answers = " | ".join(
            f"{question.question} → {question.answer}"
            for question in answered_questions
            if question.answer
        )
        if answers:
            sections.append("Vom Nutzer beantwortete Profilfragen (explizites Signal): " + answers[:3000])

    if feedback_rows:
        positive = [(feedback, article) for feedback, article in feedback_rows if feedback.rating in {"great", "yes"}]
        negative = [(feedback, article) for feedback, article in feedback_rows if feedback.rating not in {"great", "yes"}]
        liked_topics = Counter(topic.strip() for _, article in positive for topic in article.topics_csv.split(",") if topic.strip())
        disliked_topics = Counter(topic.strip() for _, article in negative for topic in article.topics_csv.split(",") if topic.strip())
        liked = ", ".join(topic for topic, _ in liked_topics.most_common(4))
        disliked = ", ".join(topic for topic, _ in disliked_topics.most_common(3))
        feedback_summary = f"Explizite Artikelrückmeldungen (starkes Signal): {len(positive)} positiv, {len(negative)} kritisch."
        if liked:
            feedback_summary += f" Positiv markierte Themen: {liked}."
        if disliked:
            feedback_summary += f" Weniger passend: {disliked}."
        notes = [feedback.note.strip() for feedback, _ in feedback_rows if feedback.note and feedback.note.strip()][:3]
        if notes:
            feedback_summary += " Freie Hinweise des Lesers: " + " | ".join(note[:300] for note in notes) + "."
        reasons = Counter(
            reason.strip() for feedback, _ in feedback_rows
            for reason in feedback.reasons_csv.split(",") if reason.strip()
        )
        if reasons:
            feedback_summary += " Häufig genannte Gründe: " + ", ".join(reason for reason, _ in reasons.most_common(5)) + "."
        sections.append(feedback_summary)

    if saved_articles:
        topics = Counter(topic.strip() for article in saved_articles for topic in article.topics_csv.split(",") if topic.strip())
        sources = Counter(article.source.name for article in saved_articles)
        sections.append(
            "Gemerkte Texte (mittleres positives Signal): "
            f"häufige Themen {', '.join(topic for topic, _ in topics.most_common(6)) or 'keine'}; "
            f"häufige Quellen {', '.join(source for source, _ in sources.most_common(4)) or 'keine'}."
        )
    if read_only_articles:
        topics = Counter(topic.strip() for article in read_only_articles for topic in article.topics_csv.split(",") if topic.strip())
        sections.append(
            "Nur als gelesen markiert (schwaches Nutzungssignal, ausdrücklich nicht als Gefallen interpretieren): "
            + (", ".join(topic for topic, _ in topics.most_common(5)) or "keine Themenangaben") + "."
        )

    if podcast_feedback_rows:
        positive_podcasts = [episode for feedback, episode in podcast_feedback_rows if feedback.rating in {"great", "yes"}]
        negative_podcasts = [episode for feedback, episode in podcast_feedback_rows if feedback.rating not in {"great", "yes"}]
        liked = ", ".join(episode.title[:120] for episode in positive_podcasts[:4])
        disliked = ", ".join(episode.title[:120] for episode in negative_podcasts[:3])
        sections.append(
            f"Explizites Podcastfeedback: {len(positive_podcasts)} positiv, {len(negative_podcasts)} kritisch. "
            f"Passend: {liked or 'noch nichts'}. Weniger passend: {disliked or 'noch nichts'}."
        )
    if artwork_feedback_rows:
        liked_art = [artwork for feedback, artwork in artwork_feedback_rows if feedback.rating in {"great", "yes"}]
        disliked_art = [artwork for feedback, artwork in artwork_feedback_rows if feedback.rating not in {"great", "yes"}]
        sections.append(
            f"Explizites Kunstfeedback: passend {', '.join(art.title[:100] for art in liked_art[:4]) or 'noch nichts'}; "
            f"weniger passend {', '.join(art.title[:100] for art in disliked_art[:3]) or 'noch nichts'}."
        )
    if recent_ai_titles:
        previous = " | ".join(title[:180] for title in recent_ai_titles if title)
        if previous:
            sections.append("Bereits vorgeschlagene Titel nicht erneut liefern: " + previous + ".")
    return "\n".join(sections)


def _prompt(
    settings: AppSettings,
    prompt_override: str | None = None,
    article_count: int | None = None,
    reader_memory: str = "",
) -> str:
    access = (
        "Nimm sowohl frei zugängliche als auch herausragende Artikel hinter einer Paywall auf. "
        "Kennzeichne jeden Fund ehrlich als free, paywalled oder unknown."
        if settings.discovery_include_paywalled
        else "Nimm nur frei und ohne Anmeldung zugängliche Artikel auf und kennzeichne sie als free."
    )
    return f"""
Finde bis zu {article_count or settings.discovery_max_articles} aktuelle, hochwertige Longform-Artikel oder
Reportagen für einen persönlichen Leseraum. Gesucht werden Texte ab ungefähr
{settings.discovery_min_minutes} Minuten Lesezeit.

Interessen: {', '.join(_csv(settings.interests_csv)) or 'breit kuratiert'}
Entdeckungssprachen: {', '.join(_csv(settings.discovery_languages_csv)) or 'Deutsch, Englisch'}
Persönlicher Wunsch: {(prompt_override or settings.discovery_prompt).strip()}
Quellen, die der Nutzer ohnehin liest und deshalb seltener empfohlen bekommen möchte: {', '.join(_csv(settings.discovery_deprioritized_sources_csv)) or 'keine'}
{reader_memory}

{access}
Wenn Quellen als bereits regelmäßig gelesen genannt sind, priorisiere ausdrücklich unabhängige,
vergleichbar hochwertige Perspektiven von anderen Publikationen. Schließe die genannten Quellen
nicht kategorisch aus: Empfehle sie nur, wenn ein Fund außergewöhnlich gut zum Wunsch passt und
eine gleichwertige Alternative fehlt.
Verwende ausschließlich direkte, kanonische Links zur Originalpublikation. Umgehe keine
Paywall, Anmeldung, robots.txt-Regel oder andere Zugriffsbeschränkung. Kopiere keinen
Volltext. Die Zusammenfassung muss eine kurze eigene Einordnung in höchstens zwei Sätzen
sein. Prüfe Titel, Publikation und Link anhand der Websuche.
Leite zusätzlich für jeden Artikel selbstständig ein Feld visual_query ab: eine kurze,
assoziative Bildidee für die Pexels-Suche mit 4 bis 8 konkreten Begriffen, vorzugsweise auf
Englisch. Denke an Motive, Materialien, Licht, Ort und Stimmung des Textes, nicht nur an
seinen Titel. Vermeide generische KI-, Roboter-, Logo- oder Screenshot-Motive, sofern der
Artikel sie nicht ausdrücklich verlangt. Dieses Feld wird automatisch verwendet und ist
nicht als Nutzereinstellung gedacht. Gib nur das geforderte JSON aus.
""".strip()


def _podcast_prompt(
    settings: AppSettings,
    prompt_override: str | None = None,
    reader_memory: str = "",
    max_podcasts: int = MAX_PODCASTS_PER_RUN,
) -> str:
    return f"""
Finde bis zu {max(1, min(max_podcasts, MAX_PODCASTS_PER_RUN))} konkrete, hochwertige Podcast-Episoden, die zum selben
persönlichen Kurationsprofil passen wie die Artikelsuche.

Interessen: {', '.join(_csv(settings.interests_csv)) or 'breit kuratiert'}
Entdeckungssprachen: {', '.join(_csv(settings.discovery_languages_csv)) or 'Deutsch, Englisch'}
Persönlicher Wunsch: {(prompt_override or settings.discovery_prompt).strip()}
{reader_memory}

Bevorzuge eigenständige Podcasts mit erzählerischer oder analytischer Tiefe: lange
Gespräche, Features, Essays, Reportagen sowie journalistische oder akademische Formate.
Ergänze sie bei passender Qualität um originär für Audio produzierte Audio-Longreads,
ordne diese aber hinter Podcasts ein.
Eine bloße Audioversion, Hörfassung oder Text-to-Speech-Lesung eines bereits erschienenen
Artikels ist keine reguläre Podcast-Empfehlung und darf nicht ausgewählt werden. Ziehe sie
nur als klar gekennzeichneten Notfall in Betracht, wenn keine passende eigenständige
Podcast- oder Audio-Longread-Produktion auffindbar ist; benenne sie dann in der Zusammenfassung ausdrücklich als
„Audioversion eines Artikels“. Verwende als url ausschließlich den direkten Link zur
konkreten Episode beim Podcast oder Publisher. Trage spotify_url nur ein, wenn ein direkter, verifizierter Link
zu genau dieser Episode auf open.spotify.com/episode/... gefunden wurde; andernfalls gib
einen leeren String aus. Erfinde weder Episoden noch Metadaten. Kopiere kein Transkript.
Die Zusammenfassung und Begründung bestehen jeweils aus höchstens zwei eigenen Sätzen.
Prüfe Titel, Podcastname und Links anhand der Websuche. Die Episodenseite muss zum
Zeitpunkt der Suche tatsächlich erreichbar sein; historische Treffer, gelöschte Folgen
und Suchergebnis- oder Übersichtsseiten sind nicht zulässig. Gib nur das geforderte JSON aus.
""".strip()


def candidate_batch_sizes(max_articles: int) -> list[int]:
    """Keep each web-search response deliberately small and predictable."""
    return [
        min(DISCOVERY_BATCH_SIZE, max_articles - offset)
        for offset in range(0, max_articles, DISCOVERY_BATCH_SIZE)
    ]


def _output_text(payload: dict) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    parts: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                parts.append(str(content.get("text", "")))
    return "".join(parts)


def _usage(payload: dict) -> tuple[int, int, int]:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return 0, 0, 0
    try:
        input_tokens = max(0, int(usage.get("input_tokens", 0)))
        output_tokens = max(0, int(usage.get("output_tokens", 0)))
        total_tokens = max(0, int(usage.get("total_tokens", input_tokens + output_tokens)))
    except (TypeError, ValueError):
        return 0, 0, 0
    return input_tokens, output_tokens, total_tokens


def _published_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return datetime.now(UTC)
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC)


def _candidate_text(value: object, limit: int) -> str:
    """Remove web-search citation syntax that should never appear in the UI copy."""
    text = plain_text(str(value or ""))
    text = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", text)
    text = re.sub(r"\(?https?://[^\s)]+\)?", "", text)
    # Search providers occasionally leave the source domain in parentheses
    # after removing a markdown citation, e.g. ``(theguardian.com)``.
    text = re.sub(r"\(\s*(?:www\.)?[a-z0-9.-]+\.[a-z]{2,}\s*\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\(\s*\)", "", text)
    return re.sub(r"\s{2,}", " ", text).strip()[:limit]


def _canonical_candidate_url(value: str) -> str:
    parsed = urlparse(value)
    query = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True) if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid", "mc_cid", "mc_eid"}]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", urlencode(query), ""))


def _rate_limit_delay(response: httpx.Response, attempt: int) -> float:
    for header in ("retry-after", "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
        value = response.headers.get(header)
        if not value:
            continue
        match = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m)?", value.strip())
        if not match:
            continue
        amount = float(match.group(1))
        unit = match.group(2)
        seconds = amount / 1000 if unit == "ms" else amount * 60 if unit == "m" else amount
        return min(30.0, max(2.0, seconds))
    return float(2 ** (attempt + 1))


async def _request_batch(
    client: httpx.AsyncClient,
    settings: AppSettings,
    api_key: str,
    prompt_override: str | None,
    batch_size: int,
    reader_memory: str,
) -> tuple[list[dict], tuple[int, int, int]]:
    body = {
        "model": settings.ai_model,
        "input": _prompt(settings, prompt_override, batch_size, reader_memory),
        "tools": [{"type": "web_search"}],
        "tool_choice": "auto",
        "max_tool_calls": batch_size,
        "include": ["web_search_call.action.sources"],
        "store": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "reado_article_discovery",
                "strict": True,
                "schema": DISCOVERY_SCHEMA,
            }
        },
    }
    for attempt in range(max(RATE_LIMIT_RETRIES, NETWORK_RETRIES) + 1):
        try:
            response = await client.post(
                f"{settings.ai_base_url.rstrip('/')}/responses",
                headers={"Authorization": f"Bearer {api_key}"},
                json=body,
            )
            response.raise_for_status()
            response_payload = response.json()
            result = json.loads(_output_text(response_payload))
            articles = result.get("articles", []) if isinstance(result, dict) else []
            return (articles if isinstance(articles, list) else []), _usage(response_payload)
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 429 and attempt < RATE_LIMIT_RETRIES:
                await asyncio.sleep(_rate_limit_delay(error.response, attempt))
                continue
            raise DiscoveryError(f"Die KI-Suche ist fehlgeschlagen: {str(error)[:300]}") from error
        except httpx.RequestError as error:
            if attempt < NETWORK_RETRIES:
                await asyncio.sleep(NETWORK_RETRY_DELAY_SECONDS * (attempt + 1))
                continue
            raise DiscoveryError(f"Die KI-Suche ist fehlgeschlagen: {str(error)[:300]}") from error
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise DiscoveryError(f"Die KI-Suche ist fehlgeschlagen: {str(error)[:300]}") from error
    return [], (0, 0, 0)


async def request_candidates(
    settings: AppSettings,
    prompt_override: str | None = None,
    reader_memory: str = "",
    max_articles: int | None = None,
    *,
    session: Session | None = None,
    user: User | None = None,
) -> tuple[list[dict], tuple[int, int, int]]:
    if settings.ai_provider != "openai":
        raise DiscoveryError(
            "Die automatische Websuche benötigt aktuell den OpenAI-Provider. "
            "Ollama und kompatible APIs kuratieren weiterhin deine eingerichteten Feeds."
        )
    api_key = decrypt_secret(settings.ai_api_key_encrypted)
    if not api_key:
        raise DiscoveryError("Für die Websuche fehlt ein gespeicherter OpenAI API-Schlüssel.")
    if not settings.ai_base_url or not settings.ai_model:
        raise DiscoveryError("Die KI-Verbindung ist noch nicht vollständig eingerichtet.")

    candidates: list[dict] = []
    input_tokens = output_tokens = total_tokens = 0
    requested_articles = max(1, min(max_articles or settings.discovery_max_articles, 12))
    source_guidance = ""
    if session is not None:
        source_guidance, _ = _source_memory_guidance(session, user, settings)
    combined_memory = f"{reader_memory}\n\n{source_guidance}".strip()
    async for batch_candidates, batch_usage, _index, _total in request_candidate_batches(
        settings, prompt_override, combined_memory, requested_articles
    ):
        candidates.extend(batch_candidates)
        input_tokens += batch_usage[0]
        output_tokens += batch_usage[1]
        total_tokens += batch_usage[2]
    return candidates[:requested_articles], (input_tokens, output_tokens, total_tokens)


async def request_candidate_batches(
    settings: AppSettings,
    prompt_override: str | None = None,
    reader_memory: str = "",
    max_articles: int | None = None,
):
    """Yield each small search batch so callers can report/import results immediately."""
    if settings.ai_provider != "openai":
        raise DiscoveryError(
            "Die automatische Websuche benötigt aktuell den OpenAI-Provider. "
            "Ollama und kompatible APIs kuratieren weiterhin deine eingerichteten Feeds."
        )
    api_key = decrypt_secret(settings.ai_api_key_encrypted)
    if not api_key:
        raise DiscoveryError("Für die Websuche fehlt ein gespeicherter OpenAI API-Schlüssel.")
    if not settings.ai_base_url or not settings.ai_model:
        raise DiscoveryError("Die KI-Verbindung ist noch nicht vollständig eingerichtet.")

    requested_articles = max(1, min(max_articles or settings.discovery_max_articles, 12))
    batch_sizes = candidate_batch_sizes(requested_articles)
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        for index, batch_size in enumerate(batch_sizes):
            batch_candidates, batch_usage = await _request_batch(
                client, settings, api_key, prompt_override, batch_size, reader_memory
            )
            yield batch_candidates, batch_usage, index, len(batch_sizes)
            if index < len(batch_sizes) - 1:
                await asyncio.sleep(INTER_BATCH_DELAY_SECONDS)


async def request_podcast_candidates(
    settings: AppSettings,
    prompt_override: str | None = None,
    reader_memory: str = "",
    max_podcasts: int = MAX_PODCASTS_PER_RUN,
) -> tuple[list[dict], tuple[int, int, int]]:
    """Find podcasts without ever passing Spotify metadata to an AI model."""
    api_key = decrypt_secret(settings.ai_api_key_encrypted)
    if settings.ai_provider != "openai" or not api_key or not settings.ai_base_url or not settings.ai_model:
        raise DiscoveryError("Die Podcast-Suche benötigt eine vollständig eingerichtete OpenAI-Verbindung.")
    requested = max(1, min(max_podcasts, MAX_PODCASTS_PER_RUN))
    spotify_candidates: list[dict] = []
    if spotify_is_configured(settings):
        try:
            spotify_candidates = await search_spotify_episodes(settings, prompt_override, requested)
        except SpotifyError as error:
            # Spotify enriches the catalogue. A temporary API error must not
            # prevent the existing web-based podcast search from working.
            logger.warning("Optional Spotify podcast search failed: %s", error)
    remaining = requested - len(spotify_candidates)
    if remaining <= 0:
        return spotify_candidates[:requested], (0, 0, 0)
    body = {
        "model": settings.ai_model,
        "input": _podcast_prompt(settings, prompt_override, reader_memory, remaining),
        "tools": [{"type": "web_search"}],
        "tool_choice": "auto",
        "max_tool_calls": remaining,
        "include": ["web_search_call.action.sources"],
        "store": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "derive_podcast_discovery",
                "strict": True,
                "schema": PODCAST_SCHEMA,
            }
        },
    }
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                response = await client.post(
                    f"{settings.ai_base_url.rstrip('/')}/responses",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
                result = json.loads(_output_text(payload))
                podcasts = result.get("podcasts", []) if isinstance(result, dict) else []
                raw_candidates = (podcasts if isinstance(podcasts, list) else [])[:remaining]
                checks = await asyncio.gather(
                    *(_verified_podcast_candidate(client, candidate) for candidate in raw_candidates)
                )
                candidates = spotify_candidates + [candidate for candidate in checks if candidate is not None]
                seen_urls: set[str] = set()
                unique_candidates = []
                for candidate in candidates:
                    url = str(candidate.get("url", ""))
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    unique_candidates.append(candidate)
                return unique_candidates[:requested], _usage(payload)
            except httpx.HTTPStatusError as error:
                if error.response.status_code == 429 and attempt < RATE_LIMIT_RETRIES:
                    await asyncio.sleep(_rate_limit_delay(error.response, attempt))
                    continue
                raise DiscoveryError(f"Die Podcast-Suche ist fehlgeschlagen: {str(error)[:300]}") from error
            except (httpx.RequestError, ValueError, TypeError, json.JSONDecodeError) as error:
                raise DiscoveryError(f"Die Podcast-Suche ist fehlgeschlagen: {str(error)[:300]}") from error
    return [], (0, 0, 0)


async def _verified_podcast_candidate(
    client: httpx.AsyncClient, candidate: object
) -> dict | None:
    """Resolve a direct episode URL and reject dead or soft-404 pages before import."""
    if not isinstance(candidate, dict):
        return None
    raw_url = str(candidate.get("url", "")).strip()
    try:
        current_url = _canonical_candidate_url(validate_public_url(raw_url))
    except ValueError:
        return None

    try:
        for _ in range(MAX_PODCAST_LINK_REDIRECTS + 1):
            validate_public_url(current_url)
            async with client.stream(
                "GET",
                current_url,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/json;q=0.8,*/*;q=0.5",
                    "User-Agent": "Mozilla/5.0 (compatible; derive-link-check/1.0)",
                },
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        return None
                    current_url = _canonical_candidate_url(
                        validate_public_url(urljoin(current_url, location))
                    )
                    continue
                if response.status_code < 200 or response.status_code >= 300:
                    return None

                content_type = response.headers.get("content-type", "").casefold()
                if "html" not in content_type and "json" not in content_type:
                    verified = dict(candidate)
                    verified["url"] = _canonical_candidate_url(str(response.url))
                    return verified

                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    remaining = MAX_PODCAST_VALIDATION_BYTES - size
                    if remaining <= 0:
                        break
                    chunks.append(chunk[:remaining])
                    size += min(len(chunk), remaining)
                preview = b"".join(chunks).decode(response.encoding or "utf-8", errors="ignore").casefold()
                soft_not_found = (
                    "<title>404" in preview
                    or "404 not found" in preview
                    or "seite nicht gefunden" in preview
                    or "episode nicht gefunden" in preview
                    or "folge nicht gefunden" in preview
                    or "episode is no longer available" in preview
                )
                if soft_not_found:
                    return None
                verified = dict(candidate)
                verified["url"] = _canonical_candidate_url(str(response.url))
                return verified
        return None
    except (httpx.HTTPError, UnicodeError, ValueError):
        return None


def _spotify_episode_url(value: object) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        validated = _canonical_candidate_url(validate_public_url(raw))
    except ValueError:
        return None
    parsed = urlparse(validated)
    if parsed.hostname not in {"open.spotify.com", "www.open.spotify.com"} or not parsed.path.startswith("/episode/"):
        return None
    return validated


def import_podcast_candidates(
    session: Session,
    candidates: list[dict],
    max_podcasts: int = MAX_PODCASTS_PER_RUN,
    user: User | None = None,
) -> list[PodcastEpisode]:
    imported: list[PodcastEpisode] = []
    known_urls = {
        _canonical_candidate_url(url)
        for url in session.scalars(select(PodcastEpisode.canonical_url)).all()
    }
    now = datetime.now(UTC)
    for candidate in candidates[:max(1, min(max_podcasts, MAX_PODCASTS_PER_RUN))]:
        if not isinstance(candidate, dict):
            continue
        try:
            canonical_url = _canonical_candidate_url(validate_public_url(str(candidate.get("url", ""))))
        except ValueError:
            continue
        if canonical_url in known_urls:
            existing = session.scalar(select(PodcastEpisode).where(PodcastEpisode.canonical_url == canonical_url))
            if existing and user and session.scalar(select(UserPodcastEpisode.id).where(UserPodcastEpisode.user_id == user.id, UserPodcastEpisode.podcast_episode_id == existing.id)) is None:
                session.add(UserPodcastEpisode(user_id=user.id, podcast_episode_id=existing.id, discovered_at=now))
                imported.append(existing)
            continue
        try:
            duration_minutes = max(0, min(1440, int(candidate.get("duration_minutes", 0))))
        except (TypeError, ValueError):
            duration_minutes = 0
        topics = [
            _candidate_text(topic, 100)
            for topic in candidate.get("topics", [])
            if _candidate_text(topic, 100)
        ]
        episode = PodcastEpisode(
            title=_candidate_text(candidate.get("title"), 500) or "Unbenannte Episode",
            show_name=_candidate_text(candidate.get("show_name"), 500) or "Unbekannter Podcast",
            description=_candidate_text(candidate.get("summary"), 1200) or None,
            canonical_url=canonical_url,
            spotify_url=_spotify_episode_url(candidate.get("spotify_url")),
            published_at=_published_at(str(candidate.get("published_at", ""))),
            duration_minutes=duration_minutes,
            topics_csv=",".join(topics)[:500],
            curation_reason=_candidate_text(candidate.get("reason"), 1000) or None,
            discovered_at=now,
        )
        try:
            with session.begin_nested():
                session.add(episode)
                session.flush()
                if user:
                    session.add(UserPodcastEpisode(user_id=user.id, podcast_episode_id=episode.id, discovered_at=now))
            imported.append(episode)
            known_urls.add(canonical_url)
        except Exception:
            session.expire_all()
            continue
    session.commit()
    return imported


def import_candidates(
    session: Session,
    settings: AppSettings,
    candidates: list[dict],
    *,
    max_articles: int | None = None,
    update_schedule: bool = True,
    user: User | None = None,
    discovery_origin: str = "manual",
) -> list[Article]:
    imported: list[Article] = []
    known_urls = {
        _canonical_candidate_url(url)
        for url in session.scalars(select(Article.canonical_url)).all()
    }
    now = datetime.now(UTC)
    requested_articles = max(1, min(max_articles or settings.discovery_max_articles, 12))
    for candidate in candidates[:requested_articles]:
        if not isinstance(candidate, dict):
            continue
        try:
            canonical_url = _canonical_candidate_url(validate_public_url(str(candidate.get("url", ""))))
        except ValueError:
            continue
        if canonical_url in known_urls:
            existing = session.scalar(select(Article).where(Article.canonical_url == canonical_url))
            if existing and user and session.scalar(select(UserArticle.id).where(UserArticle.user_id == user.id, UserArticle.article_id == existing.id)) is None:
                session.add(UserArticle(
                    user_id=user.id,
                    article_id=existing.id,
                    discovered_at=now,
                    discovery_origin=discovery_origin,
                ))
                imported.append(existing)
            continue

        try:
            # A savepoint keeps one malformed/duplicate result from aborting a
            # larger run. This is especially important when a run has 6–12 URLs.
            with session.begin_nested():
                source_name = _candidate_text(candidate.get("source"), 255) or "Unbekannte Publikation"
                author_name = _candidate_text(candidate.get("author"), 255) or "Unbekannter Autor"
                title = _candidate_text(candidate.get("title"), 500) or "Unbenannter Artikel"
                summary = _candidate_text(candidate.get("summary"), 1000)
                reason = _candidate_text(candidate.get("reason"), 1000)
                access_status = str(candidate.get("access_status") or "unknown")
                if access_status not in {"free", "paywalled", "unknown"}:
                    access_status = "unknown"
                topics = [_candidate_text(topic, 100) for topic in candidate.get("topics", []) if _candidate_text(topic, 100)]
                visual_query = _candidate_text(candidate.get("visual_query"), 240)
                try:
                    reading_minutes = max(settings.discovery_min_minutes, int(candidate.get("reading_minutes", 0)))
                except (TypeError, ValueError):
                    reading_minutes = settings.discovery_min_minutes

                source = session.scalar(select(Source).where(Source.name == source_name))
                if source is None:
                    parsed = urlparse(canonical_url)
                    source = Source(name=source_name, url=f"{parsed.scheme}://{parsed.netloc}")
                    session.add(source)
                author = session.scalar(select(Author).where(Author.name == author_name))
                if author is None:
                    author = Author(name=author_name)
                    session.add(author)

                article = Article(
                    canonical_url=canonical_url,
                    title=title,
                    dek=summary or reason or None,
                    content_html=(f"<p>{html.escape(summary)}</p>" if summary else ""),
                    published_at=_published_at(str(candidate.get("published_at", ""))),
                    reading_minutes=reading_minutes,
                    topics_csv=",".join(topics)[:500],
                    image_query=visual_query or None,
                    discovery_method="ai_web",
                    curation_reason=reason or None,
                    discovered_at=now,
                    access_status=access_status,
                    fulltext_source="ai_summary",
                    author=author,
                    source=source,
                )
                session.add(article)
                session.flush()
                if user:
                    session.add(UserArticle(
                        user_id=user.id,
                        article_id=article.id,
                        discovered_at=now,
                        discovery_origin=discovery_origin,
                    ))
            imported.append(article)
            known_urls.add(canonical_url)
            if user:
                record_source_observation(
                    session,
                    user,
                    normalize_source_domain(canonical_url),
                    source_name,
                    now,
                )
        except Exception:
            # Keep searching even if a single candidate cannot be persisted.
            session.expire_all()
            continue
    if update_schedule:
        settings.discovery_last_run_at = now
    session.commit()
    return imported


async def run_discovery(
    session: Session,
    settings: AppSettings,
    prompt_override: str | None = None,
    user: User | None = None,
    *,
    max_articles: int | None = None,
    update_schedule: bool = True,
    include_podcasts: bool = True,
    discovery_origin: str = "manual",
    refresh_presentation: bool = True,
) -> DiscoveryRunResult:
    if user is None and settings.user_id:
        user = session.get(User, settings.user_id)
    if user is None:
        raise DiscoveryError("Die Suche benötigt ein Nutzerkonto.")
    memory = reading_memory(session, user, settings)
    candidates, usage = await request_candidates(
        settings, prompt_override, memory, max_articles=max_articles, session=session, user=user
    )
    articles = import_candidates(
        session,
        settings,
        candidates,
        max_articles=max_articles,
        update_schedule=update_schedule,
        user=user,
        discovery_origin=discovery_origin,
    )
    podcasts: list[PodcastEpisode] = []
    podcast_usage = (0, 0, 0)
    if include_podcasts:
        try:
            podcast_candidates, podcast_usage = await request_podcast_candidates(
                settings, prompt_override, memory
            )
            podcasts = import_podcast_candidates(session, podcast_candidates, user=user)
        except DiscoveryError as error:
            # Podcasts enrich a run but must never discard already imported texts.
            logger.warning("Optional podcast discovery failed: %s", error)
    if refresh_presentation and await refresh_hero_visual(settings, candidates):
        session.commit()
    try:
        if refresh_presentation and await refresh_artwork_impression(session, settings, candidates, user):
            session.commit()
    except Exception:
        logger.warning("Optional artwork discovery failed", exc_info=True)
        session.rollback()
    return DiscoveryRunResult(
        articles=articles,
        podcasts=podcasts,
        input_tokens=usage[0] + podcast_usage[0],
        output_tokens=usage[1] + podcast_usage[1],
        total_tokens=usage[2] + podcast_usage[2],
        candidates=candidates,
    )


async def run_discovery_stream(
    session: Session, settings: AppSettings, prompt_override: str | None = None, user: User | None = None
):
    """Run discovery batch-by-batch and yield serializable progress events."""
    from .main import serialize_article, serialize_podcast

    if user is None and settings.user_id:
        user = session.get(User, settings.user_id)
    if user is None:
        raise DiscoveryError("Die Suche benötigt ein Nutzerkonto.")
    requested = max(1, min(settings.discovery_max_articles, 12))
    memory = reading_memory(session, user, settings)
    imported_count = 0
    input_tokens = output_tokens = total_tokens = 0
    all_candidates: list[dict] = []
    source_guidance, _ = _source_memory_guidance(session, user, settings)
    combined_memory = f"{memory}\n\n{source_guidance}".strip()
    async for candidates, usage, index, total_batches in request_candidate_batches(
        settings, prompt_override, combined_memory, requested
    ):
        input_tokens += usage[0]
        output_tokens += usage[1]
        total_tokens += usage[2]
        all_candidates.extend(candidates)
        articles = import_candidates(
            session,
            settings,
            candidates,
            max_articles=requested,
            update_schedule=False,
            user=user,
            discovery_origin="manual",
        )
        imported_count += len(articles)
        yield {
            "type": "progress",
            "batch": index + 1,
            "batches": total_batches,
            "searched": min(requested, (index + 1) * DISCOVERY_BATCH_SIZE),
            "found_count": imported_count,
            "found": [serialize_article(article, state=session.scalar(select(UserArticle).where(UserArticle.user_id == user.id, UserArticle.article_id == article.id))) for article in articles],
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }
    podcast_imported = 0
    try:
        podcast_candidates, usage = await request_podcast_candidates(
            settings, prompt_override, memory
        )
        input_tokens += usage[0]
        output_tokens += usage[1]
        total_tokens += usage[2]
        podcasts = import_podcast_candidates(session, podcast_candidates, user=user)
        podcast_imported = len(podcasts)
        yield {
            "type": "progress",
            "phase": "podcasts",
            "batch": total_batches,
            "batches": total_batches,
            "searched": requested,
            "found_count": imported_count,
            "found": [],
            "podcasts_found": podcast_imported,
            "podcasts": [serialize_podcast(podcast, state=session.scalar(select(UserPodcastEpisode).where(UserPodcastEpisode.user_id == user.id, UserPodcastEpisode.podcast_episode_id == podcast.id))) for podcast in podcasts],
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }
    except DiscoveryError as error:
        logger.warning("Optional podcast discovery failed: %s", error)
    settings.discovery_last_run_at = datetime.now(UTC)
    session.commit()
    try:
        await refresh_hero_visual(settings, all_candidates)
        session.commit()
    except Exception:
        # Visual enrichment is optional and must never turn a successful
        # article search into a 500 response.
        session.rollback()
    try:
        await refresh_artwork_impression(session, settings, all_candidates, user)
        session.commit()
    except Exception:
        # Museum enrichment is optional and must obey the same failure boundary.
        logger.warning("Optional artwork discovery failed", exc_info=True)
        session.rollback()
    yield {
        "type": "done",
        "imported": imported_count,
        "podcasts_imported": podcast_imported,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }
