import asyncio
from contextlib import asynccontextmanager, suppress
from collections import Counter
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime, parsedate_to_datetime
import hashlib
import json
import logging
import os
import re
from typing import Annotated, AsyncGenerator, Literal
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response as FastAPIResponse
from fastapi.responses import Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import delete, desc, func, inspect, or_, select, text
from sqlalchemy.orm import Session, joinedload

from .database import Base, SessionLocal, engine, schema_initialization_lock
from .chat import ChatError, chat_history, chat_research, chat_turn, serialize_message
from .discovery import (
    DiscoveryError,
    _candidate_text,
    backfill_source_memory,
    normalize_source_domain,
    run_discovery,
    run_discovery_stream,
    serialize_source_memory,
    sync_manual_source_memory,
)
from .feeds import (
    ParsedFeed,
    fetch_feed,
    parse_feed,
    plain_text,
    sanitize_html,
    validate_public_url,
)
from .auth import COOKIE_NAME, SESSION_TTL_DAYS, bootstrap_admin, create_invitation, create_session, current_admin, current_user, password_hasher, redeem_invitation, revoke_session, session_token_from_request, validate_account_fields, verify_password
from .art import museum_name
from .models import AppSettings, Article, ArticleFeedback, Artwork, Author, DiscoveryChatMessage, DiscoveryRun, Feed, PodcastEpisode, ReadingInsight, Source, User, UserArticle, UserArticleFeedback, UserArtwork, UserArtworkFeedback, UserFeed, UserInvitation, UserPodcastEpisode, UserPodcastFeedback, UserReadingInsight, UserReadingQuestion, UserSoulRevision, UserSourceMemory
from .outbound_feed import build_rss_feed
from .secrets import decrypt_secret, encrypt_secret
from .spotify import SpotifyError, spotify_is_configured, test_spotify_connection
from .visuals import assign_article_visual

logger = logging.getLogger(__name__)


async def stream_with_keepalives(
    events: AsyncGenerator[dict, None], heartbeat_seconds: float = 10.0
) -> AsyncGenerator[dict, None]:
    """Keep a discovery response alive while an upstream AI request is pending."""
    iterator = events.__aiter__()
    pending_event: asyncio.Task[dict] | None = None
    try:
        # Flush response headers and a first body byte immediately. This avoids
        # idle timeouts before OpenAI returns the first search result.
        yield {"type": "keepalive"}
        pending_event = asyncio.create_task(anext(iterator))
        while True:
            done, _ = await asyncio.wait({pending_event}, timeout=heartbeat_seconds)
            if not done:
                yield {"type": "keepalive"}
                continue
            try:
                yield pending_event.result()
            except StopAsyncIteration:
                return
            pending_event = asyncio.create_task(anext(iterator))
    finally:
        if pending_event is not None and not pending_event.done():
            pending_event.cancel()
            with suppress(asyncio.CancelledError):
                await pending_event
        await iterator.aclose()


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


SessionDependency = Annotated[Session, Depends(get_session)]
CurrentUserDependency = Annotated[User, Depends(current_user)]
AdminUserDependency = Annotated[User, Depends(current_admin)]


@asynccontextmanager
async def lifespan(_: FastAPI):
    with schema_initialization_lock():
        Base.metadata.create_all(bind=engine)
        ensure_schema()
    with SessionLocal() as session:
        bootstrap_user = bootstrap_admin(session)
        migrate_legacy_data(session, bootstrap_user)
        if bootstrap_user:
            backfill_source_memory(session, bootstrap_user)
            settings = get_or_create_settings(session, bootstrap_user)
            sync_manual_source_memory(session, bootstrap_user, settings)
            session.commit()
    yield


app = FastAPI(title="dérive API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "READO_CORS_ORIGINS",
            "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001",
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["DELETE", "GET", "PATCH", "POST", "PUT"],
    allow_headers=["Content-Type", "X-Derive-Session"],
)


class ArticleStateUpdate(BaseModel):
    is_read: bool | None = None
    is_saved: bool | None = None


class PodcastStateUpdate(BaseModel):
    is_saved: bool


class ArticleFeedbackRequest(BaseModel):
    rating: Literal["great", "yes", "not_quite", "no"]
    reasons: list[Literal["topic", "perspective", "depth", "style", "source", "timing", "too_shallow", "too_familiar", "too_current"]] = Field(default_factory=list, max_length=9)
    note: str | None = Field(default=None, max_length=2000)


class PreferenceFeedbackRequest(BaseModel):
    rating: Literal["great", "yes", "not_quite", "no"]
    reasons: list[Literal["topic", "perspective", "depth", "style", "source", "timing", "too_shallow", "too_familiar", "too_current"]] = Field(default_factory=list, max_length=9)
    note: str | None = Field(default=None, max_length=2000)


class SoulUpdateRequest(BaseModel):
    markdown: str = Field(default="", max_length=12000)
    art_enabled: bool = True


class InsightStatusRequest(BaseModel):
    status: Literal["confirmed", "dismissed"]


class ReadingQuestionRequest(BaseModel):
    status: Literal["answered", "skipped"]
    option: str | None = Field(default=None, max_length=120)
    answer: str | None = Field(default=None, max_length=2000)


class FreshRSSSyncRequest(BaseModel):
    base_url: HttpUrl
    username: str
    api_password: str


class FeedRequest(BaseModel):
    url: str


class OPMLRequest(BaseModel):
    content: str


class AISetupRequest(BaseModel):
    provider: Literal["disabled", "openai", "openai_compatible", "ollama"] = "disabled"
    base_url: str | None = Field(default=None, max_length=2048)
    model: str | None = Field(default=None, max_length=255)
    api_key: str | None = Field(default=None, max_length=1000)


class SpotifySetupRequest(BaseModel):
    client_id: str | None = Field(default=None, max_length=500)
    client_secret: str | None = Field(default=None, max_length=1000)


class SetupRequest(BaseModel):
    display_name: str = Field(default="", max_length=120)
    preferred_languages: list[str] = Field(min_length=1, max_length=12)
    discovery_languages: list[str] = Field(min_length=1, max_length=12)
    interests: list[str] = Field(min_length=1, max_length=30)
    discovery_prompt: str = Field(default="", max_length=4000)
    reading_length: Literal["mixed", "short", "medium", "long"] = "mixed"
    theme: Literal["system", "light", "dark"] = "system"
    ai: AISetupRequest = Field(default_factory=AISetupRequest)
    pexels_api_key: str | None = Field(default=None, max_length=1000)
    spotify: SpotifySetupRequest = Field(default_factory=SpotifySetupRequest)


class DiscoveryProfileUpdate(BaseModel):
    prompt: str = Field(min_length=10, max_length=4000)
    frequency: Literal["manual", "interval", "daily", "every_3_days", "weekly"] = "interval"
    interval_days: int = Field(default=1, ge=1, le=30)
    delivery_time: str = Field(default="09:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str = Field(default="Europe/Berlin", min_length=1, max_length=64)
    min_minutes: int = Field(default=15, ge=5, le=120)
    max_articles: int = Field(default=5, ge=1, le=12)
    open_access_only: bool = True
    include_paywalled: bool = True
    deprioritized_sources: list[str] = Field(default_factory=list, max_length=20)


class SourceMemoryUpdate(BaseModel):
    status: Literal["active", "deprioritized", "excluded"]


class DiscoveryRunRequest(BaseModel):
    prompt: str | None = Field(default=None, max_length=4000)


class DiscoveryChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class DiscoveryChatResearchRequest(BaseModel):
    message: str = Field(min_length=10, max_length=4000)
    max_articles: int = Field(default=3, ge=1, le=12)
    max_podcasts: int | None = Field(default=None, ge=0, le=3)
    breadth: Literal["focused", "balanced", "expansive"] = "balanced"


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class RegisterRequest(BaseModel):
    invitation_token: str | None = Field(default=None, max_length=500)
    username: str = Field(min_length=3, max_length=80)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=1024)


class InvitationRequest(BaseModel):
    email: str | None = Field(default=None, max_length=320)


class AccountPasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


def ensure_schema() -> None:
    """Add columns introduced after the initial local PostgreSQL volume."""
    columns = {column["name"] for column in inspect(engine).get_columns("articles")}
    additions = {
        "image_source_url": "VARCHAR(2048)",
        "image_query": "VARCHAR(240)",
        "external_id": "VARCHAR(1000)",
        "feed_id": "INTEGER REFERENCES feeds(id)",
        "discovery_method": "VARCHAR(32) NOT NULL DEFAULT 'feed'",
        "curation_reason": "TEXT",
        "discovered_at": "TIMESTAMP WITH TIME ZONE",
        "access_status": "VARCHAR(32) NOT NULL DEFAULT 'unknown'",
        "fulltext_source": "VARCHAR(32) NOT NULL DEFAULT 'feed'",
        "rights_basis": "VARCHAR(64)",
        "captured_at": "TIMESTAMP WITH TIME ZONE",
    }
    settings_columns = {column["name"] for column in inspect(engine).get_columns("app_settings")}
    settings_additions = {
        "discovery_prompt": "TEXT NOT NULL DEFAULT 'Lange Reportagen mit erzählerischer Tiefe, sorgfältiger Recherche und neuen Perspektiven.'",
        "discovery_frequency": "VARCHAR(32) NOT NULL DEFAULT 'daily'",
        "discovery_interval_days": "INTEGER NOT NULL DEFAULT 1",
        "discovery_time": "VARCHAR(5) NOT NULL DEFAULT '09:00'",
        "discovery_timezone": "VARCHAR(64) NOT NULL DEFAULT 'Europe/Berlin'",
        "discovery_min_minutes": "INTEGER NOT NULL DEFAULT 15",
        "discovery_max_articles": "INTEGER NOT NULL DEFAULT 5",
        "discovery_open_access_only": "BOOLEAN NOT NULL DEFAULT TRUE",
        "discovery_include_paywalled": "BOOLEAN NOT NULL DEFAULT TRUE",
        "discovery_deprioritized_sources_csv": "VARCHAR(2000) NOT NULL DEFAULT ''",
        "discovery_last_run_at": "TIMESTAMP WITH TIME ZONE",
        "hero_image_url": "VARCHAR(2048)",
        "hero_image_source_url": "VARCHAR(2048)",
        "hero_image_credit": "VARCHAR(500)",
        "hero_image_alt": "VARCHAR(500)",
        "hero_image_id": "INTEGER",
        "pexels_api_key_encrypted": "TEXT",
        "spotify_client_id_encrypted": "TEXT",
        "spotify_client_secret_encrypted": "TEXT",
        "soul_markdown": "TEXT NOT NULL DEFAULT ''",
        "soul_revision": "INTEGER NOT NULL DEFAULT 0",
        "art_enabled": "BOOLEAN NOT NULL DEFAULT TRUE",
        "ownership_repair_completed": "BOOLEAN NOT NULL DEFAULT FALSE",
        "featured_artwork_id": "INTEGER REFERENCES artworks(id) ON DELETE SET NULL",
    }
    run_columns = {column["name"] for column in inspect(engine).get_columns("discovery_runs")}
    run_additions = {
        "input_tokens": "INTEGER NOT NULL DEFAULT 0",
        "output_tokens": "INTEGER NOT NULL DEFAULT 0",
        "total_tokens": "INTEGER NOT NULL DEFAULT 0",
    }
    podcast_columns = {column["name"] for column in inspect(engine).get_columns("podcast_episodes")}
    podcast_additions = {
        "is_saved": "BOOLEAN NOT NULL DEFAULT FALSE",
    }
    chat_columns = {column["name"] for column in inspect(engine).get_columns("discovery_chat_messages")}
    run_identity_columns = {column["name"] for column in inspect(engine).get_columns("discovery_runs")}
    settings_identity_columns = {column["name"] for column in inspect(engine).get_columns("app_settings")}
    article_feedback_columns = {column["name"] for column in inspect(engine).get_columns("user_article_feedback")}
    user_article_columns = {column["name"] for column in inspect(engine).get_columns("user_articles")}
    insight_columns = {column["name"] for column in inspect(engine).get_columns("user_reading_insights")}
    with engine.begin() as connection:
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE articles ADD COLUMN {name} {definition}"))
        for name, definition in settings_additions.items():
            if name not in settings_columns:
                connection.execute(text(f"ALTER TABLE app_settings ADD COLUMN {name} {definition}"))
        for name, definition in run_additions.items():
            if name not in run_columns:
                connection.execute(text(f"ALTER TABLE discovery_runs ADD COLUMN {name} {definition}"))
        if "discovery_origin" not in user_article_columns:
            connection.execute(text(
                "ALTER TABLE user_articles ADD COLUMN discovery_origin "
                "VARCHAR(24) NOT NULL DEFAULT 'legacy'"
            ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_user_articles_discovery_origin "
            "ON user_articles (discovery_origin)"
        ))
        for name, definition in podcast_additions.items():
            if name not in podcast_columns:
                connection.execute(text(f"ALTER TABLE podcast_episodes ADD COLUMN {name} {definition}"))
        if "user_id" not in chat_columns:
            connection.execute(text("ALTER TABLE discovery_chat_messages ADD COLUMN user_id INTEGER REFERENCES users(id)"))
        if "user_id" not in run_identity_columns:
            connection.execute(text("ALTER TABLE discovery_runs ADD COLUMN user_id INTEGER REFERENCES users(id)"))
        if "user_id" not in settings_identity_columns:
            connection.execute(text("ALTER TABLE app_settings ADD COLUMN user_id INTEGER REFERENCES users(id)"))
        if "reasons_csv" not in article_feedback_columns:
            connection.execute(text("ALTER TABLE user_article_feedback ADD COLUMN reasons_csv VARCHAR(500) NOT NULL DEFAULT ''"))
        insight_additions = {
            "status": "VARCHAR(24) NOT NULL DEFAULT 'suggested'",
            "text": "TEXT",
            "basis": "TEXT",
            "confidence": "VARCHAR(16) NOT NULL DEFAULT 'medium'",
            "source_type": "VARCHAR(32) NOT NULL DEFAULT 'reading_feedback'",
        }
        for name, definition in insight_additions.items():
            if name not in insight_columns:
                connection.execute(text(f"ALTER TABLE user_reading_insights ADD COLUMN {name} {definition}"))
        connection.execute(text("UPDATE user_reading_insights SET status = 'dismissed' WHERE dismissed = TRUE"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_app_settings_user_id_unique ON app_settings (user_id) WHERE user_id IS NOT NULL"))
        # Preserve the cadence represented by the original preset values when
        # upgrading an existing local database.
        connection.execute(text("UPDATE app_settings SET discovery_interval_days = 3 WHERE discovery_frequency = 'every_3_days' AND discovery_interval_days = 1"))
        connection.execute(text("UPDATE app_settings SET discovery_interval_days = 7 WHERE discovery_frequency = 'weekly' AND discovery_interval_days = 1"))
        # The original model used a client-side id=1 default. Existing
        # PostgreSQL installations therefore have no server-side default (and
        # sometimes no sequence at all) for app_settings.id. Repair both before
        # user-scoped settings start using normal auto-increment IDs.
        if engine.dialect.name == "postgresql":
            connection.execute(text("CREATE SEQUENCE IF NOT EXISTS app_settings_id_seq"))
            connection.execute(text("ALTER SEQUENCE app_settings_id_seq OWNED BY app_settings.id"))
            connection.execute(text("""
                ALTER TABLE app_settings
                ALTER COLUMN id SET DEFAULT nextval('app_settings_id_seq'::regclass)
            """))
            connection.execute(text("""
                SELECT setval(
                    'app_settings_id_seq'::regclass,
                    COALESCE(MAX(id), 1),
                    COUNT(*) > 0
                )
                FROM app_settings
            """))


def repair_legacy_cross_user_links(session: Session, bootstrap_user: User) -> dict[str, int]:
    """Remove conservative matches created by the repeated legacy migration.

    Older releases attached every global catalog item to the first admin on
    every API restart. A link is considered migration leakage only when a
    different user owned the same item first and the admin has neither saved,
    read nor explicitly rated it. The repair is recorded per installation so
    legitimate future overlap between two searches remains untouched.
    """
    settings = session.scalar(select(AppSettings).where(AppSettings.user_id == bootstrap_user.id))
    if settings is None:
        settings = AppSettings(user_id=bootstrap_user.id)
        session.add(settings)
        session.flush()
    if settings.ownership_repair_completed:
        return {"articles": 0, "podcasts": 0, "feeds": 0, "sources": 0}

    removed = {"articles": 0, "podcasts": 0, "feeds": 0, "sources": 0}
    for link in session.scalars(select(UserArticle).where(UserArticle.user_id == bootstrap_user.id)).all():
        earlier_other = session.scalar(
            select(UserArticle.id).where(
                UserArticle.article_id == link.article_id,
                UserArticle.user_id != bootstrap_user.id,
                UserArticle.id < link.id,
            ).limit(1)
        )
        has_feedback = session.scalar(select(UserArticleFeedback.id).where(
            UserArticleFeedback.user_id == bootstrap_user.id,
            UserArticleFeedback.article_id == link.article_id,
        ).limit(1))
        if earlier_other is not None and not link.is_read and not link.is_saved and has_feedback is None:
            session.delete(link)
            removed["articles"] += 1

    for link in session.scalars(select(UserPodcastEpisode).where(
        UserPodcastEpisode.user_id == bootstrap_user.id
    )).all():
        earlier_other = session.scalar(
            select(UserPodcastEpisode.id).where(
                UserPodcastEpisode.podcast_episode_id == link.podcast_episode_id,
                UserPodcastEpisode.user_id != bootstrap_user.id,
                UserPodcastEpisode.id < link.id,
            ).limit(1)
        )
        has_feedback = session.scalar(select(UserPodcastFeedback.id).where(
            UserPodcastFeedback.user_id == bootstrap_user.id,
            UserPodcastFeedback.podcast_episode_id == link.podcast_episode_id,
        ).limit(1))
        if earlier_other is not None and not link.is_saved and has_feedback is None:
            session.delete(link)
            removed["podcasts"] += 1

    for link in session.scalars(select(UserFeed).where(UserFeed.user_id == bootstrap_user.id)).all():
        earlier_other = session.scalar(
            select(UserFeed.id).where(
                UserFeed.feed_id == link.feed_id,
                UserFeed.user_id != bootstrap_user.id,
                UserFeed.id < link.id,
            ).limit(1)
        )
        if earlier_other is not None:
            session.delete(link)
            removed["feeds"] += 1

    # Flush the catalog corrections before rebuilding the visible source
    # counts. Manual source rules and sources with explicit feedback survive.
    session.flush()
    source_counts: Counter[str] = Counter()
    source_rows = session.execute(
        select(Article, Source)
        .join(UserArticle, UserArticle.article_id == Article.id)
        .join(Source, Source.id == Article.source_id)
        .where(UserArticle.user_id == bootstrap_user.id, Article.discovery_method == "ai_web")
    ).all()
    for article, source in source_rows:
        domain = normalize_source_domain(source.url) or normalize_source_domain(article.canonical_url)
        if domain:
            source_counts[domain] += 1
    for memory in session.scalars(select(UserSourceMemory).where(
        UserSourceMemory.user_id == bootstrap_user.id
    )).all():
        if memory.manual_override or memory.origin == "manual":
            continue
        count = source_counts.get(memory.domain, 0)
        if count == 0 and not memory.positive_count and not memory.negative_count:
            session.delete(memory)
            removed["sources"] += 1
            continue
        memory.observed_count = count

    settings.ownership_repair_completed = True
    logger.info(
        "Repaired legacy cross-user links for bootstrap user %s: %s",
        bootstrap_user.id,
        removed,
    )
    return removed


def migrate_legacy_data(session: Session, bootstrap_user: User | None = None) -> None:
    """Attach only genuinely unowned legacy rows to the initial admin."""
    user = bootstrap_user or session.scalar(select(User).order_by(User.id).limit(1))
    if user is None:
        return

    # First claim only records that predate user ownership. These nullable
    # rows are the reliable marker of the original single-reader schema.
    for settings in session.scalars(select(AppSettings).where(AppSettings.user_id.is_(None))).all():
        settings.user_id = user.id
    for message in session.scalars(select(DiscoveryChatMessage).where(DiscoveryChatMessage.user_id.is_(None))).all():
        message.user_id = user.id
    for run in session.scalars(select(DiscoveryRun).where(DiscoveryRun.user_id.is_(None))).all():
        run.user_id = user.id
    session.flush()
    repair_legacy_cross_user_links(session, user)

    # The legacy columns remain for backwards-compatible local DB upgrades;
    # all requests now read state from the user-specific tables below.
    for article in session.scalars(select(Article)).all():
        owner = session.scalar(select(UserArticle.id).where(UserArticle.article_id == article.id).limit(1))
        if owner is None:
            session.add(UserArticle(
                user_id=user.id,
                article_id=article.id,
                is_read=article.is_read,
                is_saved=article.is_saved,
                discovered_at=article.discovered_at or article.published_at,
            ))
    for episode in session.scalars(select(PodcastEpisode)).all():
        owner = session.scalar(select(UserPodcastEpisode.id).where(
            UserPodcastEpisode.podcast_episode_id == episode.id
        ).limit(1))
        if owner is None:
            session.add(UserPodcastEpisode(
                user_id=user.id,
                podcast_episode_id=episode.id,
                is_saved=episode.is_saved,
                discovered_at=episode.discovered_at or episode.published_at,
            ))
    for feed in session.scalars(select(Feed)).all():
        owner = session.scalar(select(UserFeed.id).where(UserFeed.feed_id == feed.id).limit(1))
        if owner is None:
            session.add(UserFeed(user_id=user.id, feed_id=feed.id))

    existing_feedback = set(session.scalars(select(UserArticleFeedback.article_id).where(UserArticleFeedback.user_id == user.id)).all())
    for feedback in session.scalars(select(ArticleFeedback)).all():
        if feedback.article_id not in existing_feedback:
            session.add(UserArticleFeedback(
                user_id=user.id, article_id=feedback.article_id, rating=feedback.rating,
                note=feedback.note, created_at=feedback.created_at, updated_at=feedback.updated_at,
            ))
    existing_insights = set(session.scalars(select(UserReadingInsight.key).where(UserReadingInsight.user_id == user.id)).all())
    for insight in session.scalars(select(ReadingInsight)).all():
        if insight.key not in existing_insights:
            session.add(UserReadingInsight(user_id=user.id, key=insight.key, dismissed=insight.dismissed))
    session.commit()


def serialize_article(article: Article, include_content: bool = False, state: UserArticle | None = None) -> dict:
    # Older AI imports may already contain a provider citation in their
    # summary. Sanitize on read as well as on import so existing rows are
    # corrected without a destructive data migration.
    clean_ai_copy = article.discovery_method == "ai_web"
    dek = _candidate_text(article.dek, 1000) if clean_ai_copy else article.dek
    curation_reason = _candidate_text(article.curation_reason, 1000) if clean_ai_copy else article.curation_reason
    payload = {
        "id": article.id,
        "title": article.title,
        "dek": dek,
        "canonical_url": article.canonical_url,
        "published_at": article.published_at.isoformat(),
        "reading_minutes": article.reading_minutes,
        "topics": [topic.strip() for topic in article.topics_csv.split(",") if topic.strip()],
        "image_url": article.image_url,
        "image_credit": article.image_credit,
        "image_source_url": article.image_source_url,
        "image_query": article.image_query,
        "is_read": state.is_read if state is not None else article.is_read,
        "is_saved": state.is_saved if state is not None else article.is_saved,
        "author": article.author.name,
        "source": article.source.name,
        "source_url": article.source.url,
        "discovery_method": article.discovery_method,
        "curation_reason": curation_reason,
        "discovered_at": (
            state.discovered_at.isoformat()
            if state is not None and state.discovered_at
            else article.discovered_at.isoformat() if article.discovered_at else None
        ),
        "access_status": article.access_status,
        "fulltext_source": article.fulltext_source,
        "rights_basis": article.rights_basis,
        "captured_at": article.captured_at.isoformat() if article.captured_at else None,
    }
    if include_content:
        payload["content_html"] = article.content_html
    return payload


def serialize_podcast(podcast: PodcastEpisode, state: UserPodcastEpisode | None = None) -> dict:
    discovered_at = podcast.discovered_at or podcast.published_at
    return {
        "id": podcast.id,
        "title": podcast.title,
        "show_name": podcast.show_name,
        "description": podcast.description,
        "canonical_url": podcast.canonical_url,
        "spotify_url": podcast.spotify_url,
        "is_saved": state.is_saved if state is not None else podcast.is_saved,
        "published_at": podcast.published_at.isoformat(),
        "duration_minutes": podcast.duration_minutes,
        "topics": [topic.strip() for topic in podcast.topics_csv.split(",") if topic.strip()],
        "curation_reason": podcast.curation_reason,
        "discovered_at": discovered_at.isoformat(),
    }


def article_query():
    return select(Article).options(joinedload(Article.author), joinedload(Article.source))


def user_article_query(user: User):
    return article_query().join(UserArticle, UserArticle.article_id == Article.id).where(
        UserArticle.user_id == user.id,
        UserArticle.discovery_origin != "background",
    )


def article_states(session: Session, user: User, article_ids: list[int]) -> dict[int, UserArticle]:
    if not article_ids:
        return {}
    return {
        state.article_id: state
        for state in session.scalars(
            select(UserArticle).where(UserArticle.user_id == user.id, UserArticle.article_id.in_(article_ids))
        ).all()
    }


def podcast_states(session: Session, user: User, podcast_ids: list[int]) -> dict[int, UserPodcastEpisode]:
    if not podcast_ids:
        return {}
    return {
        state.podcast_episode_id: state
        for state in session.scalars(
            select(UserPodcastEpisode).where(
                UserPodcastEpisode.user_id == user.id,
                UserPodcastEpisode.podcast_episode_id.in_(podcast_ids),
            )
        ).all()
    }


def recommendation_reason(article: Article) -> str:
    if article.curation_reason:
        return article.curation_reason
    topic = article.topics_csv.split(",")[0].strip()
    if topic:
        return f"Aus dem Themenraum {topic}: eine neue Perspektive aus {article.source.name}."
    return f"Eine neue Perspektive aus {article.source.name}."


def personal_relevance(article: Article, settings: AppSettings) -> int:
    interests = {interest.casefold() for interest in _list(settings.interests_csv)}
    article_topics = {topic.casefold() for topic in _list(article.topics_csv)}
    score = len(interests & article_topics) * 10
    length_matches = {
        "short": article.reading_minutes <= 5,
        "medium": 5 < article.reading_minutes <= 15,
        "long": article.reading_minutes > 15,
        "mixed": True,
    }
    if length_matches.get(settings.reading_length, True):
        score += 2
    return score


def home_rank(article: Article, settings: AppSettings) -> tuple[int, int, float, float]:
    """Rank active unread material, preferring fresh curator discoveries."""
    source_priority = {
        "ai_web": 2,
        "subscriber_import": 1,
    }.get(article.discovery_method, 0)

    def timestamp(value: datetime | None) -> float:
        if value is None:
            return 0.0
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).timestamp()

    return (
        source_priority,
        personal_relevance(article, settings),
        timestamp(article.discovered_at or article.published_at),
        timestamp(article.published_at),
    )


def is_home_eligible(article: Article) -> bool:
    # Removing a feed intentionally keeps its articles in the archive. Those
    # orphaned feed imports should no longer compete with active curation on
    # the home page.
    return article.discovery_method != "feed" or article.feed_id is not None


def serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


def set_session_cookie(response: FastAPIResponse, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=os.getenv("DERIVE_AUTH_SECURE_COOKIE", "false").casefold() == "true",
        samesite="lax",
        path="/",
        max_age=60 * 60 * 24 * SESSION_TTL_DAYS,
    )


@app.get("/api/v1/auth/session")
def auth_session(user: CurrentUserDependency) -> dict:
    return {"user": serialize_user(user)}


@app.post("/api/v1/auth/login")
def auth_login(request: LoginRequest, response: FastAPIResponse, session: SessionDependency) -> dict:
    identifier = request.identifier.strip().casefold()
    user = session.scalar(select(User).where((func.lower(User.email) == identifier) | (func.lower(User.username) == identifier)))
    if user is None or not user.is_active or not verify_password(user, request.password):
        raise HTTPException(status_code=401, detail="Benutzername/E-Mail oder Passwort stimmt nicht.")
    token, _ = create_session(session, user)
    set_session_cookie(response, token)
    return {"user": serialize_user(user)}


@app.post("/api/v1/auth/logout")
def auth_logout(request: Request, response: FastAPIResponse, session: SessionDependency) -> dict[str, bool]:
    revoke_session(session, session_token_from_request(request))
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@app.post("/api/v1/auth/register")
def auth_register(request: RegisterRequest, response: FastAPIResponse, session: SessionDependency) -> dict:
    allow_public = os.getenv("DERIVE_ALLOW_PUBLIC_SIGNUP", "false").casefold() == "true"
    try:
        username, email = validate_account_fields(request.username, request.email, request.password)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if session.scalar(select(User.id).where((func.lower(User.username) == username.casefold()) | (func.lower(User.email) == email))):
        raise HTTPException(status_code=409, detail="Benutzername oder E-Mail-Adresse wird bereits verwendet.")
    invitation = None
    if not allow_public:
        if not request.invitation_token:
            raise HTTPException(status_code=403, detail="Für die Registrierung wird eine Einladung benötigt.")
        invitation = redeem_invitation(session, request.invitation_token, email)
        if invitation is None:
            raise HTTPException(status_code=403, detail="Die Einladung ist ungültig, abgelaufen oder gehört zu einer anderen E-Mail-Adresse.")
    user = User(username=username, email=email, password_hash=password_hasher.hash(request.password))
    session.add(user)
    if invitation:
        invitation.used_at = datetime.now(UTC)
    session.commit()
    session.refresh(user)
    token, _ = create_session(session, user)
    set_session_cookie(response, token)
    return {"user": serialize_user(user)}


@app.post("/api/v1/auth/password")
def change_password(request: AccountPasswordRequest, user: CurrentUserDependency, session: SessionDependency) -> dict[str, bool]:
    account = session.get(User, user.id)
    if account is None:
        raise HTTPException(status_code=401, detail="Sitzung ist nicht mehr gültig.")
    if not verify_password(account, request.current_password):
        raise HTTPException(status_code=401, detail="Das aktuelle Passwort stimmt nicht.")
    try:
        validate_account_fields(account.username, account.email, request.new_password)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    account.password_hash = password_hasher.hash(request.new_password)
    session.execute(
        text("UPDATE user_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE user_id = :user_id AND revoked_at IS NULL"),
        {"user_id": user.id},
    )
    session.commit()
    return {"ok": True}


@app.get("/api/v1/admin/users")
def list_users(_: AdminUserDependency, session: SessionDependency) -> dict:
    return {"users": [serialize_user(user) for user in session.scalars(select(User).order_by(User.created_at)).all()]}


@app.post("/api/v1/admin/invitations")
def invite_user(request: InvitationRequest, admin: AdminUserDependency, session: SessionDependency) -> dict:
    token, invitation = create_invitation(session, admin, request.email)
    return {
        "invitation": {
            "id": invitation.id,
            "email": invitation.email,
            "expires_at": invitation.expires_at.isoformat(),
            "url": f"/registrieren?invite={token}",
        }
    }


@app.patch("/api/v1/admin/users/{user_id}")
def set_user_active(user_id: int, request: dict, _: AdminUserDependency, session: SessionDependency) -> dict:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Nutzer wurde nicht gefunden.")
    if "is_active" in request:
        user.is_active = bool(request["is_active"])
    session.commit()
    return {"user": serialize_user(user)}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _csv(values: list[str]) -> str:
    cleaned = []
    for value in values:
        item = " ".join(value.strip().split())[:100]
        if item and item.casefold() not in {existing.casefold() for existing in cleaned}:
            cleaned.append(item)
    return ",".join(cleaned)


def _list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def get_or_create_settings(session: Session, user: User) -> AppSettings:
    settings = session.scalar(select(AppSettings).where(AppSettings.user_id == user.id))
    if settings is None:
        settings = AppSettings(user_id=user.id)
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings


def serialize_settings(settings: AppSettings, session: Session, user: User) -> dict:
    discovery = {
        "prompt": settings.discovery_prompt,
        "frequency": settings.discovery_frequency,
        "min_minutes": settings.discovery_min_minutes,
        "max_articles": settings.discovery_max_articles,
        "open_access_only": settings.discovery_open_access_only,
        "include_paywalled": settings.discovery_include_paywalled,
        "deprioritized_sources": _list(settings.discovery_deprioritized_sources_csv),
        "last_run_at": (
            settings.discovery_last_run_at.isoformat()
            if settings.discovery_last_run_at else None
        ),
    }
    if settings.discovery_frequency == "interval":
        discovery.update({
            "interval_days": settings.discovery_interval_days,
            "delivery_time": settings.discovery_time,
            "timezone": settings.discovery_timezone,
        })
    return {
        "setup_completed": settings.setup_completed,
        "display_name": settings.display_name,
        "preferred_languages": _list(settings.preferred_languages_csv),
        "discovery_languages": _list(settings.discovery_languages_csv),
        "interests": _list(settings.interests_csv),
        "discovery_prompt": settings.discovery_prompt,
        "reading_length": settings.reading_length,
        "theme": settings.theme,
        "feed_count": session.scalar(select(func.count()).select_from(UserFeed).where(UserFeed.user_id == user.id)) or 0,
        "ai": {
            "provider": settings.ai_provider,
            "base_url": settings.ai_base_url,
            "model": settings.ai_model,
            "has_api_key": bool(settings.ai_api_key_encrypted),
        },
        "pexels": {
            "has_api_key": bool(settings.pexels_api_key_encrypted or os.getenv("PEXELS_API_KEY", "").strip()),
        },
        "spotify": {
            "has_client_id": bool(settings.spotify_client_id_encrypted),
            "has_client_secret": bool(settings.spotify_client_secret_encrypted),
            "configured": spotify_is_configured(settings),
        },
        "discovery": discovery,
    }


def _normalise_ai_base_url(ai: AISetupRequest) -> str | None:
    if ai.provider == "disabled":
        return None
    default_url = (
        "https://api.openai.com/v1"
        if ai.provider == "openai"
        else "http://ollama:11434" if ai.provider == "ollama" else None
    )
    base_url = (ai.base_url or default_url or "").strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise HTTPException(status_code=422, detail="Die KI-Basis-URL ist ungültig.")
    return base_url


def _normalise_ai(ai: AISetupRequest) -> tuple[str | None, str | None]:
    base_url = _normalise_ai_base_url(ai)
    if ai.provider == "disabled":
        return None, None
    model = (ai.model or "").strip()
    if not model:
        raise HTTPException(status_code=422, detail="Bitte wähle ein KI-Modell aus.")
    return base_url, model


def _selectable_ai_models(provider: str, available: list[object]) -> list[str]:
    model_ids = {
        str(item.get("name") or item.get("model") or item.get("id") or "").strip()
        for item in available
        if isinstance(item, dict)
    }
    model_ids.discard("")
    if provider == "openai":
        text_prefixes = ("gpt-", "o1", "o3", "o4")
        excluded = (
            "audio", "realtime", "transcribe", "tts", "image", "moderation",
            "embedding", "search", "codex",
        )
        model_ids = {
            model_id for model_id in model_ids
            if model_id.startswith(text_prefixes)
            and not any(fragment in model_id.lower() for fragment in excluded)
        }

    def sort_key(model_id: str) -> tuple[int, str]:
        preferred = ("gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.5", "gpt-5.4")
        try:
            return preferred.index(model_id), model_id
        except ValueError:
            return len(preferred), model_id

    return sorted(model_ids, key=sort_key)[:200]


@app.get("/api/v1/setup")
def setup_status(user: CurrentUserDependency, session: SessionDependency) -> dict:
    return serialize_settings(get_or_create_settings(session, user), session, user)


@app.post("/api/v1/setup/ai/test")
async def test_ai_connection(request: AISetupRequest, user: CurrentUserDependency, session: SessionDependency) -> dict:
    if request.provider == "disabled":
        return {"connected": True, "model_found": True, "models": [], "message": "KI ist deaktiviert."}
    base_url = _normalise_ai_base_url(request)
    model = (request.model or "").strip()
    settings = get_or_create_settings(session, user)
    api_key = request.api_key or decrypt_secret(settings.ai_api_key_encrypted)
    if request.provider == "openai" and not api_key:
        raise HTTPException(status_code=422, detail="Für OpenAI wird ein API-Schlüssel benötigt.")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    endpoint = (
        f"{base_url}/api/tags"
        if request.provider == "ollama"
        else f"{base_url}/models"
    )
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            response = await client.get(endpoint, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(
            status_code=502, detail=f"KI-Verbindung fehlgeschlagen: {str(error)[:300]}"
        ) from error
    available = payload.get("models", []) if request.provider == "ollama" else payload.get("data", [])
    model_ids = _selectable_ai_models(request.provider, available)
    model_found = bool(model) and model in model_ids
    if not model:
        message = f"Verbindung hergestellt. {len(model_ids)} verfügbare Modelle geladen."
    elif model_found:
        message = f"Verbindung hergestellt, Modell {model} gefunden."
    else:
        message = f"Verbindung hergestellt; Modell {model} wurde nicht in der Modellliste gefunden. Bitte wähle ein verfügbares Modell."
    return {
        "connected": True,
        "model_found": model_found,
        "models": model_ids,
        "message": message,
    }


def serialize_artwork(artwork: Artwork, state: UserArtwork | None = None) -> dict:
    return {
        "id": artwork.id,
        "provider": artwork.provider,
        "museum_name": museum_name(artwork.provider),
        "provider_id": artwork.provider_id,
        "title": artwork.title,
        "artist_display": artwork.artist_display,
        "date_display": artwork.date_display,
        "medium_display": artwork.medium_display,
        "place_of_origin": artwork.place_of_origin,
        "image_url": artwork.image_url,
        "source_url": artwork.source_url,
        "attribution": artwork.attribution,
        "license": artwork.license_label,
        "context": artwork.context,
        "curation_reason": artwork.curation_reason,
        "is_saved": state.is_saved if state is not None else False,
    }


@app.post("/api/v1/setup/spotify/test")
async def test_spotify_setup(
    request: SpotifySetupRequest, user: CurrentUserDependency, session: SessionDependency
) -> dict:
    settings = get_or_create_settings(session, user)
    client_id = (request.client_id or decrypt_secret(settings.spotify_client_id_encrypted) or "").strip()
    client_secret = (request.client_secret or decrypt_secret(settings.spotify_client_secret_encrypted) or "").strip()
    if not client_id or not client_secret:
        raise HTTPException(status_code=422, detail="Für Spotify werden Client-ID und Client Secret benötigt.")
    try:
        return await test_spotify_connection(client_id, client_secret)
    except SpotifyError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.post("/api/v1/setup")
async def save_setup(request: SetupRequest, user: CurrentUserDependency, session: SessionDependency) -> dict:
    base_url, model = _normalise_ai(request.ai)
    settings = get_or_create_settings(session, user)
    if request.ai.provider == "openai" and not (
        request.ai.api_key or settings.ai_api_key_encrypted
    ):
        raise HTTPException(status_code=422, detail="Für OpenAI wird ein API-Schlüssel benötigt.")
    spotify_client_id = (request.spotify.client_id or decrypt_secret(settings.spotify_client_id_encrypted) or "").strip()
    spotify_client_secret = (request.spotify.client_secret or decrypt_secret(settings.spotify_client_secret_encrypted) or "").strip()
    if bool(spotify_client_id) != bool(spotify_client_secret):
        raise HTTPException(status_code=422, detail="Für Spotify bitte Client-ID und Client Secret gemeinsam eintragen.")

    settings.display_name = " ".join(request.display_name.strip().split())
    settings.preferred_languages_csv = _csv(request.preferred_languages)
    settings.discovery_languages_csv = _csv(request.discovery_languages)
    settings.interests_csv = _csv(request.interests)
    discovery_prompt = " ".join(request.discovery_prompt.strip().split())
    if discovery_prompt:
        settings.discovery_prompt = discovery_prompt
    settings.reading_length = request.reading_length
    settings.theme = request.theme
    settings.ai_provider = request.ai.provider
    settings.ai_base_url = base_url
    settings.ai_model = model
    if request.ai.provider == "disabled":
        settings.ai_api_key_encrypted = None
    elif request.ai.api_key:
        settings.ai_api_key_encrypted = encrypt_secret(request.ai.api_key)
    if request.pexels_api_key:
        settings.pexels_api_key_encrypted = encrypt_secret(request.pexels_api_key.strip())
    if request.spotify.client_id:
        settings.spotify_client_id_encrypted = encrypt_secret(request.spotify.client_id.strip())
    if request.spotify.client_secret:
        settings.spotify_client_secret_encrypted = encrypt_secret(request.spotify.client_secret.strip())
    has_content_source = request.ai.provider != "disabled"
    settings.setup_completed = has_content_source
    session.commit()
    session.refresh(settings)
    return {
        **serialize_settings(settings, session, user),
    }


def serialize_discovery_run(run: DiscoveryRun) -> dict:
    return {
        "id": run.id,
        "trigger": run.trigger,
        "status": run.status,
        "imported_count": run.imported_count,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "total_tokens": run.total_tokens,
        "message": run.message,
        "ran_at": run.ran_at.isoformat(),
    }


def discovery_interval_days(settings: AppSettings) -> int | None:
    if settings.discovery_frequency == "manual":
        return None
    legacy = {"daily": 1, "every_3_days": 3, "weekly": 7}
    stored = int(getattr(settings, "discovery_interval_days", 1) or 1)
    if stored == 1 and settings.discovery_frequency in legacy:
        stored = legacy[settings.discovery_frequency]
    return max(1, min(30, stored))


def discovery_timezone(settings: AppSettings) -> ZoneInfo:
    try:
        return ZoneInfo(settings.discovery_timezone or "Europe/Berlin")
    except ZoneInfoNotFoundError:
        return ZoneInfo("Europe/Berlin")


def discovery_next_due(settings: AppSettings, now: datetime | None = None) -> datetime | None:
    interval_days = discovery_interval_days(settings)
    if interval_days is None or settings.ai_provider != "openai":
        return None
    now_utc = now or datetime.now(UTC)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=UTC)
    tz = discovery_timezone(settings)
    local_now = now_utc.astimezone(tz)
    try:
        hour, minute = (int(part) for part in (settings.discovery_time or "09:00").split(":", 1))
    except (ValueError, TypeError):
        hour, minute = 9, 0
    last_run = settings.discovery_last_run_at
    if last_run is None:
        # A missing last-run timestamp means the first scheduled run has not
        # happened yet. Keep today's slot when it is already overdue so a
        # worker that starts after the delivery time catches it immediately.
        candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    else:
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=UTC)
        last_local = last_run.astimezone(tz)
        candidate = last_local.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=interval_days)
    return candidate.astimezone(UTC)


def discovery_automation(settings: AppSettings) -> dict:
    interval_days = discovery_interval_days(settings)
    enabled = bool(interval_days and settings.ai_provider == "openai")
    return {
        "enabled": enabled,
        "interval_days": interval_days,
        "delivery_time": settings.discovery_time,
        "timezone": settings.discovery_timezone,
        "background_interval_hours": 3 if enabled else None,
        "next_due_at": discovery_next_due(settings).isoformat() if enabled else None,
    }


def record_discovery_run(
    session: Session,
    *,
    trigger: str,
    status: str,
    imported_count: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    message: str | None = None,
    user: User | None = None,
) -> None:
    session.add(
        DiscoveryRun(
            user_id=user.id if user else None,
            trigger=trigger,
            status=status,
            imported_count=imported_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            message=message[:2000] if message else None,
        )
    )
    session.commit()


def record_discovery_run_safely(
    session: Session,
    *,
    trigger: str,
    status: str,
    imported_count: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    message: str | None = None,
    user: User | None = None,
) -> None:
    """Record a run without turning a completed request into a server error.

    Discovery results are committed independently from the run history. A
    transient database/logging failure must therefore not hide results that
    have already been saved successfully.
    """
    try:
        record_discovery_run(
            session,
            trigger=trigger,
            status=status,
            imported_count=imported_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            message=message,
            user=user,
        )
    except Exception:
        session.rollback()
        logger.exception("Could not record %s discovery run", trigger)


def serialize_discovery(settings: AppSettings, session: Session, user: User) -> dict:
    articles = session.scalars(
        user_article_query(user)
        .where(Article.discovery_method == "ai_web")
        .order_by(desc(Article.discovered_at))
        .limit(12)
    ).all()
    runs = session.scalars(
        select(DiscoveryRun).where(DiscoveryRun.user_id == user.id).order_by(desc(DiscoveryRun.ran_at)).limit(4)
    ).all()
    podcasts = session.scalars(
        select(PodcastEpisode).join(UserPodcastEpisode, UserPodcastEpisode.podcast_episode_id == PodcastEpisode.id).where(UserPodcastEpisode.user_id == user.id).order_by(desc(UserPodcastEpisode.discovered_at)).limit(3)
    ).all()
    states = article_states(session, user, [article.id for article in articles])
    podcast_state = podcast_states(session, user, [podcast.id for podcast in podcasts])
    return {
        "profile": serialize_settings(settings, session, user)["discovery"],
        "provider": settings.ai_provider,
        "provider_ready": bool(
            settings.ai_provider == "openai"
            and settings.ai_base_url
            and settings.ai_model
            and settings.ai_api_key_encrypted
        ),
        "articles": [serialize_article(article, state=states.get(article.id)) for article in articles],
        "podcasts": [serialize_podcast(podcast, state=podcast_state.get(podcast.id)) for podcast in podcasts],
        "sources": serialize_source_memory(session, user),
        "automation": discovery_automation(settings),
        "runs": [serialize_discovery_run(run) for run in runs],
    }


@app.get("/api/v1/discovery")
def discovery_status(user: CurrentUserDependency, session: SessionDependency) -> dict:
    return serialize_discovery(get_or_create_settings(session, user), session, user)


@app.patch("/api/v1/discovery/profile")
def update_discovery_profile(
    update: DiscoveryProfileUpdate, user: CurrentUserDependency, session: SessionDependency
) -> dict:
    settings = get_or_create_settings(session, user)
    settings.discovery_prompt = " ".join(update.prompt.strip().split())
    settings.discovery_frequency = update.frequency
    settings.discovery_interval_days = update.interval_days
    if update.frequency in {"every_3_days", "weekly"} and update.interval_days == 1:
        settings.discovery_interval_days = {"every_3_days": 3, "weekly": 7}[update.frequency]
    settings.discovery_time = update.delivery_time
    settings.discovery_timezone = update.timezone
    settings.discovery_min_minutes = update.min_minutes
    settings.discovery_max_articles = update.max_articles
    settings.discovery_open_access_only = update.open_access_only
    settings.discovery_include_paywalled = update.include_paywalled
    settings.discovery_deprioritized_sources_csv = _csv(update.deprioritized_sources)
    sync_manual_source_memory(session, user, settings)
    session.commit()
    session.refresh(settings)
    return serialize_discovery(settings, session, user)


@app.patch("/api/v1/discovery/sources/{domain}")
def update_discovery_source(
    domain: str,
    update: SourceMemoryUpdate,
    user: CurrentUserDependency,
    session: SessionDependency,
) -> dict:
    normalized = normalize_source_domain(domain)
    if not normalized or "/" in normalized:
        raise HTTPException(status_code=422, detail="Ungültige Quellen-Domain.")
    memory = session.scalar(
        select(UserSourceMemory).where(
            UserSourceMemory.user_id == user.id,
            UserSourceMemory.domain == normalized,
        )
    )
    if memory is None:
        memory = UserSourceMemory(
            user_id=user.id,
            domain=normalized,
            display_name=normalized,
            origin="manual",
        )
        session.add(memory)
    memory.status = update.status
    memory.manual_override = True
    session.commit()
    return serialize_discovery(get_or_create_settings(session, user), session, user)


@app.post("/api/v1/discovery/run")
async def run_discovery_now(
    request: DiscoveryRunRequest, user: CurrentUserDependency, session: SessionDependency
) -> StreamingResponse:
    settings = get_or_create_settings(session, user)
    prompt = " ".join(request.prompt.strip().split()) if request.prompt else None
    # Keep configuration errors as a normal JSON response; once a search has
    # started, progress and partial results are delivered through the stream.
    if settings.ai_provider != "openai":
        message = "Die automatische Websuche benötigt aktuell den OpenAI-Provider."
        record_discovery_run(session, trigger="manual", status="failed", message=message, user=user)
        raise HTTPException(status_code=422, detail=message)
    if not decrypt_secret(settings.ai_api_key_encrypted):
        message = "Für die Websuche fehlt ein gespeicherter OpenAI API-Schlüssel."
        record_discovery_run(session, trigger="manual", status="failed", message=message, user=user)
        raise HTTPException(status_code=422, detail=message)
    if not settings.ai_base_url or not settings.ai_model:
        message = "Die KI-Verbindung ist noch nicht vollständig eingerichtet."
        record_discovery_run(session, trigger="manual", status="failed", message=message, user=user)
        raise HTTPException(status_code=422, detail=message)

    async def events():
        imported_count = input_tokens = output_tokens = total_tokens = 0
        try:
            async for event in stream_with_keepalives(
                run_discovery_stream(session, settings, prompt, user=user)
            ):
                if event.get("type") == "progress":
                    imported_count = int(event.get("found_count", imported_count))
                    input_tokens = int(event.get("input_tokens", input_tokens))
                    output_tokens = int(event.get("output_tokens", output_tokens))
                    total_tokens = int(event.get("total_tokens", total_tokens))
                elif event.get("type") == "done":
                    imported_count = int(event.get("imported", imported_count))
                    input_tokens = int(event.get("input_tokens", input_tokens))
                    output_tokens = int(event.get("output_tokens", output_tokens))
                    total_tokens = int(event.get("total_tokens", total_tokens))
                yield __import__("json").dumps(event, ensure_ascii=False) + "\n"
            record_discovery_run(
                session,
                trigger="manual",
                status="success",
                imported_count=imported_count,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                user=user,
            )
            final = {"imported": imported_count, "discovery": serialize_discovery(settings, session, user)}
            yield __import__("json").dumps({"type": "status", **final}, ensure_ascii=False) + "\n"
        except DiscoveryError as error:
            logger.warning("Discovery run failed after %s imported articles: %s", imported_count, error)
            session.rollback()
            record_discovery_run(
                session, trigger="manual", status="failed", imported_count=imported_count,
                input_tokens=input_tokens, output_tokens=output_tokens,
                total_tokens=total_tokens, message=str(error), user=user,
            )
            yield __import__("json").dumps({"type": "error", "message": str(error), "imported": imported_count}, ensure_ascii=False) + "\n"
        except Exception as error:
            logger.exception("Unexpected discovery failure after %s imported articles", imported_count)
            session.rollback()
            message = f"dérive API-Fehler während der Suche: {str(error)[:300]}"
            record_discovery_run(
                session, trigger="manual", status="failed", imported_count=imported_count,
                input_tokens=input_tokens, output_tokens=output_tokens,
                total_tokens=total_tokens, message=message, user=user,
            )
            yield __import__("json").dumps({"type": "error", "message": message, "imported": imported_count}, ensure_ascii=False) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


def serialize_chat_status(settings: AppSettings, session: Session, user: User) -> dict:
    return {
        "provider": settings.ai_provider,
        "provider_ready": bool(
            settings.ai_provider != "disabled"
            and settings.ai_base_url
            and settings.ai_model
            and (settings.ai_provider != "openai" or settings.ai_api_key_encrypted)
        ),
        "messages": [serialize_message(message) for message in chat_history(session, user=user)],
    }


@app.get("/api/v1/discovery/chat")
def get_discovery_chat(user: CurrentUserDependency, session: SessionDependency) -> dict:
    return serialize_chat_status(get_or_create_settings(session, user), session, user)


@app.post("/api/v1/discovery/chat")
async def send_discovery_chat(
    request: DiscoveryChatRequest, user: CurrentUserDependency, session: SessionDependency
) -> dict:
    settings = get_or_create_settings(session, user)
    message = " ".join(request.message.strip().split())
    try:
        await chat_turn(session, settings, message, user=user)
    except ChatError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return serialize_chat_status(settings, session, user)


@app.post("/api/v1/discovery/chat/research")
async def research_from_discovery_chat(
    request: DiscoveryChatResearchRequest, user: CurrentUserDependency, session: SessionDependency
) -> dict:
    settings = get_or_create_settings(session, user)
    message = " ".join(request.message.strip().split())
    try:
        result = await chat_research(
            session,
            settings,
            message,
            max_articles=request.max_articles,
            max_podcasts=request.max_podcasts,
            breadth=request.breadth,
            user=user,
        )
        # Build the response before recording the run. The run-log commit
        # expires ORM objects; serializing first avoids a late response error
        # after valid results have already been persisted.
        response_payload = {
            "articles": [serialize_article(article, state=article_states(session, user, [article.id]).get(article.id)) for article in result.articles],
            "podcasts": [serialize_podcast(podcast, state=podcast_states(session, user, [podcast.id]).get(podcast.id)) for podcast in result.podcasts],
            "chat": serialize_chat_status(settings, session, user),
            "discovery": serialize_discovery(settings, session, user),
        }
    except ChatError as error:
        session.rollback()
        record_discovery_run_safely(session, trigger="chat", status="failed", message=str(error), user=user)
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        session.rollback()
        logger.exception("Unexpected ad-hoc research failure")
        message = f"Die Ad-hoc-Recherche konnte nicht abgeschlossen werden: {str(error)[:300]}"
        record_discovery_run_safely(session, trigger="chat", status="failed", message=message, user=user)
        raise HTTPException(status_code=422, detail=message) from error
    record_discovery_run_safely(
        session,
        trigger="chat",
        status="success",
        imported_count=len(result.articles),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        total_tokens=result.total_tokens,
        message=f"Ad-hoc-Recherche aus dem Kurator-Chat · bis zu {request.max_articles} Texte · {request.breadth}",
        user=user,
    )
    return response_payload


@app.delete("/api/v1/discovery/chat")
def clear_discovery_chat(user: CurrentUserDependency, session: SessionDependency) -> dict[str, bool]:
    session.execute(delete(DiscoveryChatMessage).where(DiscoveryChatMessage.user_id == user.id))
    session.commit()
    return {"cleared": True}


@app.get("/api/v1/home")
def home(user: CurrentUserDependency, session: SessionDependency) -> dict:
    articles = session.scalars(user_article_query(user).order_by(desc(Article.published_at))).all()
    states = article_states(session, user, [article.id for article in articles])
    settings = get_or_create_settings(session, user)
    eligible_articles = [article for article in articles if is_home_eligible(article)] or articles
    unread = [article for article in eligible_articles if not states[article.id].is_read]
    ranked = sorted(unread, key=lambda article: home_rank(article, settings), reverse=True)
    # Four items cover the hero plus all three cards in "Die Auswahl". A
    # separate, larger pool lets the UI remove overlaps and still fill three
    # suggestions without falling back to archived RSS imports.
    for_you = ranked[:4]
    today = unread[:5]
    discover = [article for article in ranked if article not in for_you][:6]
    authors = {}
    for article in eligible_articles:
        authors.setdefault(article.author.name, {"name": article.author.name, "count": 0})
        authors[article.author.name]["count"] += 1
    topic_counts: dict[str, int] = {}
    for article in eligible_articles:
        for topic in article.topics_csv.split(","):
            topic = topic.strip()
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
    podcasts = session.scalars(
        select(PodcastEpisode).join(UserPodcastEpisode, UserPodcastEpisode.podcast_episode_id == PodcastEpisode.id).where(UserPodcastEpisode.user_id == user.id).order_by(desc(UserPodcastEpisode.discovered_at)).limit(3)
    ).all()
    podcast_state = podcast_states(session, user, [podcast.id for podcast in podcasts])
    artwork = session.get(Artwork, settings.featured_artwork_id) if settings.art_enabled and settings.featured_artwork_id else None
    artwork_state = session.scalar(select(UserArtwork).where(
        UserArtwork.user_id == user.id, UserArtwork.artwork_id == artwork.id
    )) if artwork else None
    return {
        "for_you": [
            {**serialize_article(article, state=states.get(article.id)), "reason": recommendation_reason(article)}
            for article in for_you
        ],
        "today": [serialize_article(article, state=states.get(article.id)) for article in today],
        "discover": [serialize_article(article, state=states.get(article.id)) for article in discover],
        "podcasts": [serialize_podcast(podcast, state=podcast_state.get(podcast.id)) for podcast in podcasts],
        "artwork": serialize_artwork(artwork, artwork_state) if artwork else None,
        "authors": sorted(authors.values(), key=lambda author: author["count"], reverse=True)[:4],
        "topics": [
            {"name": name, "article_count": count}
            for name, count in sorted(topic_counts.items(), key=lambda item: (-item[1], item[0]))[:6]
        ],
        "hero_visual": {
            "url": settings.hero_image_url,
            "source_url": settings.hero_image_source_url,
            "credit": settings.hero_image_credit,
            "alt": settings.hero_image_alt,
        },
    }


@app.get("/api/v1/articles")
def list_articles(user: CurrentUserDependency, session: SessionDependency) -> list[dict]:
    articles = session.scalars(user_article_query(user).order_by(desc(Article.published_at))).all()
    states = article_states(session, user, [article.id for article in articles])
    return [serialize_article(article, state=states.get(article.id)) for article in articles]


@app.get("/api/v1/podcasts")
def list_podcasts(user: CurrentUserDependency, session: SessionDependency) -> list[dict]:
    podcasts = session.scalars(
        select(PodcastEpisode).join(UserPodcastEpisode, UserPodcastEpisode.podcast_episode_id == PodcastEpisode.id).where(UserPodcastEpisode.user_id == user.id).order_by(desc(UserPodcastEpisode.discovered_at))
    ).all()
    states = podcast_states(session, user, [podcast.id for podcast in podcasts])
    return [serialize_podcast(podcast, state=states.get(podcast.id)) for podcast in podcasts]


@app.get("/api/v1/podcasts/{podcast_id}")
def get_podcast(podcast_id: int, user: CurrentUserDependency, session: SessionDependency) -> dict:
    state = session.scalar(select(UserPodcastEpisode).where(UserPodcastEpisode.user_id == user.id, UserPodcastEpisode.podcast_episode_id == podcast_id))
    podcast = session.get(PodcastEpisode, podcast_id) if state else None
    if podcast is None:
        raise HTTPException(status_code=404, detail="Podcast episode not found.")
    return serialize_podcast(podcast, state=state)


@app.patch("/api/v1/podcasts/{podcast_id}")
def update_podcast_state(
    podcast_id: int, update: PodcastStateUpdate, user: CurrentUserDependency, session: SessionDependency
) -> dict:
    state = session.scalar(select(UserPodcastEpisode).where(UserPodcastEpisode.user_id == user.id, UserPodcastEpisode.podcast_episode_id == podcast_id))
    podcast = session.get(PodcastEpisode, podcast_id) if state else None
    if podcast is None or state is None:
        raise HTTPException(status_code=404, detail="Podcast episode not found.")
    state.is_saved = update.is_saved
    state.saved_at = datetime.now(UTC) if update.is_saved else None
    session.commit()
    session.refresh(state)
    return serialize_podcast(podcast, state=state)


@app.get("/api/v1/podcasts/{podcast_id}/feedback")
def get_podcast_feedback(podcast_id: int, user: CurrentUserDependency, session: SessionDependency) -> dict | None:
    state = session.scalar(select(UserPodcastEpisode.id).where(
        UserPodcastEpisode.user_id == user.id,
        UserPodcastEpisode.podcast_episode_id == podcast_id,
    ))
    podcast = session.get(PodcastEpisode, podcast_id) if state else None
    if podcast is None:
        raise HTTPException(status_code=404, detail="Podcast episode not found.")
    feedback = session.scalar(select(UserPodcastFeedback).where(
        UserPodcastFeedback.user_id == user.id,
        UserPodcastFeedback.podcast_episode_id == podcast_id,
    ))
    return serialize_podcast_feedback(feedback, podcast) if feedback else None


@app.put("/api/v1/podcasts/{podcast_id}/feedback")
def save_podcast_feedback(
    podcast_id: int, request: PreferenceFeedbackRequest,
    user: CurrentUserDependency, session: SessionDependency,
) -> dict:
    state = session.scalar(select(UserPodcastEpisode.id).where(
        UserPodcastEpisode.user_id == user.id,
        UserPodcastEpisode.podcast_episode_id == podcast_id,
    ))
    podcast = session.get(PodcastEpisode, podcast_id) if state else None
    if podcast is None:
        raise HTTPException(status_code=404, detail="Podcast episode not found.")
    feedback = session.scalar(select(UserPodcastFeedback).where(
        UserPodcastFeedback.user_id == user.id,
        UserPodcastFeedback.podcast_episode_id == podcast_id,
    ))
    if feedback is None:
        feedback = UserPodcastFeedback(user_id=user.id, podcast_episode_id=podcast_id)
        session.add(feedback)
    feedback.rating = request.rating
    feedback.reasons_csv = _csv(request.reasons)
    feedback.note = " ".join(request.note.strip().split()) if request.note else None
    session.commit()
    session.refresh(feedback)
    return serialize_podcast_feedback(feedback, podcast)


@app.put("/api/v1/artworks/{artwork_id}/feedback")
def save_artwork_feedback(
    artwork_id: int, request: PreferenceFeedbackRequest,
    user: CurrentUserDependency, session: SessionDependency,
) -> dict:
    state = session.scalar(select(UserArtwork.id).where(
        UserArtwork.user_id == user.id, UserArtwork.artwork_id == artwork_id,
    ))
    artwork = session.get(Artwork, artwork_id) if state else None
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found.")
    feedback = session.scalar(select(UserArtworkFeedback).where(
        UserArtworkFeedback.user_id == user.id,
        UserArtworkFeedback.artwork_id == artwork_id,
    ))
    if feedback is None:
        feedback = UserArtworkFeedback(user_id=user.id, artwork_id=artwork_id)
        session.add(feedback)
    feedback.rating = request.rating
    feedback.reasons_csv = _csv(request.reasons)
    feedback.note = " ".join(request.note.strip().split()) if request.note else None
    session.commit()
    session.refresh(feedback)
    return serialize_artwork_feedback(feedback, artwork)


@app.get("/api/v1/artworks/{artwork_id}/feedback")
def get_artwork_feedback(
    artwork_id: int, user: CurrentUserDependency, session: SessionDependency
) -> dict | None:
    state = session.scalar(select(UserArtwork.id).where(
        UserArtwork.user_id == user.id, UserArtwork.artwork_id == artwork_id,
    ))
    artwork = session.get(Artwork, artwork_id) if state else None
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found.")
    feedback = session.scalar(select(UserArtworkFeedback).where(
        UserArtworkFeedback.user_id == user.id,
        UserArtworkFeedback.artwork_id == artwork_id,
    ))
    return serialize_artwork_feedback(feedback, artwork) if feedback else None


def serialize_feedback(feedback: UserArticleFeedback, article: Article) -> dict:
    return {
        "id": feedback.id,
        "article_id": article.id,
        "article_title": article.title,
        "source": article.source.name,
        "rating": feedback.rating,
        "reasons": _list(feedback.reasons_csv),
        "note": feedback.note,
        "created_at": feedback.created_at.isoformat(),
        "updated_at": feedback.updated_at.isoformat() if feedback.updated_at else None,
    }


def serialize_podcast_feedback(feedback: UserPodcastFeedback, podcast: PodcastEpisode) -> dict:
    return {
        "id": feedback.id,
        "podcast_id": podcast.id,
        "title": podcast.title,
        "source": podcast.show_name,
        "rating": feedback.rating,
        "reasons": _list(feedback.reasons_csv),
        "note": feedback.note,
        "created_at": feedback.created_at.isoformat(),
        "updated_at": feedback.updated_at.isoformat() if feedback.updated_at else None,
    }


def serialize_artwork_feedback(feedback: UserArtworkFeedback, artwork: Artwork) -> dict:
    return {
        "id": feedback.id,
        "artwork_id": artwork.id,
        "title": artwork.title,
        "source": artwork.artist_display,
        "rating": feedback.rating,
        "reasons": _list(feedback.reasons_csv),
        "note": feedback.note,
        "created_at": feedback.created_at.isoformat(),
        "updated_at": feedback.updated_at.isoformat() if feedback.updated_at else None,
    }


def _reading_question_candidates(
    session: Session,
    user: User,
    feedback_rows: list[tuple[UserArticleFeedback, Article]],
) -> list[dict]:
    """Return a small, deterministic set of useful preference questions.

    The question wording can evolve later, but the trigger stays inspectable:
    questions only appear when existing signals are ambiguous enough to affect
    recommendations.
    """
    positive_rows = [(feedback, article) for feedback, article in feedback_rows if feedback.rating in {"great", "yes"}]
    engaged_articles = session.scalars(
        select(Article).join(UserArticle, UserArticle.article_id == Article.id).where(
            UserArticle.user_id == user.id,
            or_(UserArticle.is_read.is_(True), UserArticle.is_saved.is_(True)),
        ).order_by(desc(Article.published_at)).limit(60)
    ).all()
    candidates: list[dict] = []

    long_count = sum(1 for article in engaged_articles if article.reading_minutes >= 15)
    short_count = sum(1 for article in engaged_articles if article.reading_minutes < 8)
    if len(engaged_articles) >= 4 and long_count and short_count:
        candidates.append({
            "key": "reading-length-v1",
            "kind": "format",
            "question": "Was soll bei deiner nächsten Auswahl stärker zählen?",
            "context": "Du liest sowohl kurze als auch ausführliche Texte. dérive möchte unterscheiden, ob die Länge selbst oder vor allem das Thema entscheidend ist.",
            "basis": f"{long_count} ausführliche und {short_count} kurze gelesene oder gemerkte Texte",
            "options": [
                {"value": "long", "label": "Ausführliche Texte"},
                {"value": "short", "label": "Kurze Texte"},
                {"value": "mixed", "label": "Eine Mischung"},
                {"value": "topic", "label": "Kommt aufs Thema an"},
            ],
        })

    if len(positive_rows) >= 2 and not any(feedback.reasons_csv.strip() for feedback, _ in positive_rows):
        candidates.append({
            "key": "feedback-dimension-v1",
            "kind": "quality",
            "question": "Was macht einen Text für dich besonders lesenswert?",
            "context": "Du hast zuletzt mehrere Texte positiv bewertet. Eine kurze Einordnung hilft dérive, ähnliche Qualitäten gezielter zu finden.",
            "basis": f"{len(positive_rows)} positive Artikelrückmeldungen ohne Qualitätsgrund",
            "options": [
                {"value": "topic", "label": "Das Thema"},
                {"value": "perspective", "label": "Die Perspektive"},
                {"value": "depth", "label": "Die Tiefe"},
                {"value": "style", "label": "Die Erzählweise"},
            ],
        })

    if len(positive_rows) >= 3 or len(engaged_articles) >= 6:
        candidates.append({
            "key": "exploration-v1",
            "kind": "discovery",
            "question": "Wie viel Raum darf dérive für Überraschungen lassen?",
            "context": "Dein Profil wird klarer. Jetzt kann dérive besser zwischen vertrauten Treffern und bewussten Entdeckungen abwägen.",
            "basis": f"{len(positive_rows)} positive Rückmeldungen und {len(engaged_articles)} Lese- oder Merksignale",
            "options": [
                {"value": "focused", "label": "Eng am Profil bleiben"},
                {"value": "some_surprise", "label": "Gelegentlich überraschen"},
                {"value": "open", "label": "Bewusst neue Felder öffnen"},
            ],
        })

    return candidates[:3]


def _serialize_reading_question(question: UserReadingQuestion | dict) -> dict:
    if isinstance(question, UserReadingQuestion):
        try:
            options = json.loads(question.options_json or "[]")
        except json.JSONDecodeError:
            options = []
        return {
            "key": question.key,
            "kind": question.kind,
            "question": question.question,
            "context": question.context,
            "basis": question.basis,
            "options": options,
            "status": question.status,
            "answer": question.answer,
        }
    return {**question, "status": "open"}


def reading_questions_payload(
    session: Session,
    user: User,
    feedback_rows: list[tuple[UserArticleFeedback, Article]],
) -> list[dict]:
    candidates = _reading_question_candidates(session, user, feedback_rows)
    stored = {
        question.key: question
        for question in session.scalars(
            select(UserReadingQuestion).where(UserReadingQuestion.user_id == user.id)
        ).all()
    }
    stored_visible = [
        _serialize_reading_question(question)
        for question in stored.values()
        if question.status in {"open", "answered"}
    ]
    visible_keys = {question["key"] for question in stored_visible}
    open_questions = [question for question in stored_visible if question["status"] == "open"]
    answered_questions = [question for question in stored_visible if question["status"] == "answered"]
    for candidate in candidates:
        if candidate["key"] not in stored and candidate["key"] not in visible_keys:
            open_questions.append(_serialize_reading_question(candidate))
    return open_questions[:3] + answered_questions


def reading_profile_payload(session: Session, user: User) -> dict:
    settings = get_or_create_settings(session, user)
    rows = session.execute(
        select(UserArticleFeedback, Article)
        .join(Article, Article.id == UserArticleFeedback.article_id)
        .where(UserArticleFeedback.user_id == user.id)
        .order_by(desc(UserArticleFeedback.updated_at), desc(UserArticleFeedback.id))
    ).all()
    feedback = [serialize_feedback(item, article) for item, article in rows]
    podcast_rows = session.execute(
        select(UserPodcastFeedback, PodcastEpisode)
        .join(PodcastEpisode, PodcastEpisode.id == UserPodcastFeedback.podcast_episode_id)
        .where(UserPodcastFeedback.user_id == user.id)
        .order_by(desc(UserPodcastFeedback.updated_at), desc(UserPodcastFeedback.id))
    ).all()
    podcast_feedback = [serialize_podcast_feedback(item, podcast) for item, podcast in podcast_rows]
    artwork_rows = session.execute(
        select(UserArtworkFeedback, Artwork)
        .join(Artwork, Artwork.id == UserArtworkFeedback.artwork_id)
        .where(UserArtworkFeedback.user_id == user.id)
        .order_by(desc(UserArtworkFeedback.updated_at), desc(UserArtworkFeedback.id))
    ).all()
    artwork_feedback = [serialize_artwork_feedback(item, artwork) for item, artwork in artwork_rows]
    positive = {"great", "yes"}
    positive_rows = [(item, article) for item, article in rows if item.rating in positive]
    negative_rows = [(item, article) for item, article in rows if item.rating not in positive]
    topic_positive = Counter(topic.strip() for _, article in positive_rows for topic in article.topics_csv.split(",") if topic.strip())
    topic_negative = Counter(topic.strip() for _, article in negative_rows for topic in article.topics_csv.split(",") if topic.strip())
    source_positive = Counter(article.source.name for _, article in positive_rows)
    insights: list[dict] = []

    def slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:80]

    def add_insight(key: str, text_value: str, basis: str, confidence: str = "medium") -> None:
        insights.append({"key": key, "text": text_value, "basis": basis, "confidence": confidence})

    if topic_positive:
        topic, count = topic_positive.most_common(1)[0]
        add_insight(f"topic-positive-{slug(topic)}", f"Du reagierst positiv auf Texte über {topic}.", f"{count} positive Rückmeldung{'en' if count != 1 else ''}")
    if topic_negative:
        topic, count = topic_negative.most_common(1)[0]
        add_insight(f"topic-negative-{slug(topic)}", f"Texte über {topic} waren zuletzt weniger passend.", f"{count} kritische Rückmeldung{'en' if count != 1 else ''}")
    if source_positive:
        source, count = source_positive.most_common(1)[0]
        add_insight(f"source-positive-{slug(source)}", f"{source} trifft deinen Lesegeschmack besonders oft.", f"{count} positive Rückmeldung{'en' if count != 1 else ''}")
    long_positive = sum(1 for _, article in positive_rows if article.reading_minutes >= 15)
    short_positive = sum(1 for _, article in positive_rows if article.reading_minutes < 8)
    if long_positive > short_positive and long_positive:
        add_insight("length-long", "Du scheinst ausführliche Texte mit mindestens 15 Minuten Lesezeit zu bevorzugen.", f"{long_positive} positive lange{'r' if long_positive == 1 else ''} Text{' ' if long_positive == 1 else 'e'}")
    elif short_positive > long_positive and short_positive:
        add_insight("length-short", "Kurze Texte passen in deinen bisherigen Rückmeldungen häufiger.", f"{short_positive} positive kurze Texte")

    stored_insights = {
        item.key: item for item in session.scalars(
            select(UserReadingInsight).where(UserReadingInsight.user_id == user.id)
        ).all()
    }
    visible_insights = []
    for item in insights:
        stored = stored_insights.get(item["key"])
        status = stored.status if stored else "suggested"
        if status == "dismissed" or (stored and stored.dismissed):
            continue
        visible_insights.append({**item, "status": status})
    current_keys = {item["key"] for item in visible_insights}
    for stored in stored_insights.values():
        if stored.status == "confirmed" and stored.key not in current_keys and stored.text:
            visible_insights.append({
                "key": stored.key,
                "text": stored.text,
                "basis": stored.basis or "Vom Nutzer bestätigt",
                "confidence": stored.confidence,
                "status": "confirmed",
            })
    read_count = session.scalar(select(func.count()).select_from(UserArticle).where(UserArticle.user_id == user.id, UserArticle.is_read.is_(True))) or 0
    saved_articles = session.scalar(select(func.count()).select_from(UserArticle).where(UserArticle.user_id == user.id, UserArticle.is_saved.is_(True))) or 0
    saved_podcasts = session.scalar(select(func.count()).select_from(UserPodcastEpisode).where(UserPodcastEpisode.user_id == user.id, UserPodcastEpisode.is_saved.is_(True))) or 0
    saved_count = saved_articles + saved_podcasts
    revisions = session.scalars(
        select(UserSoulRevision).where(UserSoulRevision.user_id == user.id)
        .order_by(desc(UserSoulRevision.revision)).limit(12)
    ).all()
    return {
        "stats": {
            "read_count": read_count,
            "saved_count": saved_count,
            "feedback_count": len(feedback) + len(podcast_feedback) + len(artwork_feedback),
        },
        "soul": {
            "markdown": settings.soul_markdown,
            "revision": settings.soul_revision,
            "art_enabled": settings.art_enabled,
            "revisions": [
                {"revision": revision.revision, "markdown": revision.markdown, "created_at": revision.created_at.isoformat()}
                for revision in revisions
            ],
        },
        "feedback": feedback,
        "podcast_feedback": podcast_feedback,
        "artwork_feedback": artwork_feedback,
        "insights": visible_insights,
        "questions": reading_questions_payload(session, user, rows),
    }


@app.get("/api/v1/articles/{article_id}/feedback")
def get_article_feedback(article_id: int, user: CurrentUserDependency, session: SessionDependency) -> dict | None:
    article = session.scalar(user_article_query(user).where(Article.id == article_id))
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    feedback = session.scalar(select(UserArticleFeedback).where(UserArticleFeedback.user_id == user.id, UserArticleFeedback.article_id == article_id))
    return serialize_feedback(feedback, article) if feedback else None


@app.put("/api/v1/articles/{article_id}/feedback")
def save_article_feedback(article_id: int, request: ArticleFeedbackRequest, user: CurrentUserDependency, session: SessionDependency) -> dict:
    article = session.scalar(user_article_query(user).where(Article.id == article_id))
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    feedback = session.scalar(select(UserArticleFeedback).where(UserArticleFeedback.user_id == user.id, UserArticleFeedback.article_id == article_id))
    previous_rating = feedback.rating if feedback is not None else None
    if feedback is None:
        feedback = UserArticleFeedback(user_id=user.id, article_id=article_id)
        session.add(feedback)
    feedback.rating = request.rating
    feedback.reasons_csv = _csv(request.reasons)
    feedback.note = " ".join(request.note.strip().split()) if request.note else None
    domain = normalize_source_domain(article.source.url)
    if domain:
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
                display_name=article.source.name,
                observed_count=1,
                positive_count=0,
                negative_count=0,
                source_score=8,
            )
            session.add(memory)
        if previous_rating in {"great", "yes"}:
            memory.positive_count = max(0, (memory.positive_count or 0) - 1)
            memory.source_score = max(0, (memory.source_score or 0) - 20)
        elif previous_rating is not None:
            memory.negative_count = max(0, (memory.negative_count or 0) - 1)
            memory.source_score = min(100, (memory.source_score or 0) + 10)
        if request.rating in {"great", "yes"}:
            memory.positive_count = (memory.positive_count or 0) + 1
            memory.source_score = min(100, (memory.source_score or 0) + 20)
        else:
            memory.negative_count = (memory.negative_count or 0) + 1
            memory.source_score = max(0, (memory.source_score or 0) - 10)
    session.commit()
    session.refresh(feedback)
    return serialize_feedback(feedback, article)


@app.get("/api/v1/reading-profile")
def get_reading_profile(user: CurrentUserDependency, session: SessionDependency) -> dict:
    return reading_profile_payload(session, user)


@app.patch("/api/v1/reading-questions/{question_key}")
def update_reading_question(
    question_key: str,
    request: ReadingQuestionRequest,
    user: CurrentUserDependency,
    session: SessionDependency,
) -> dict:
    profile = reading_profile_payload(session, user)
    candidate = next((item for item in profile["questions"] if item["key"] == question_key), None)
    question = session.scalar(select(UserReadingQuestion).where(
        UserReadingQuestion.user_id == user.id,
        UserReadingQuestion.key == question_key,
    ))
    if candidate is None and (question is None or question.status != "open"):
        raise HTTPException(status_code=404, detail="Reading question not found.")
    if question is None:
        question = UserReadingQuestion(
            user_id=user.id,
            key=question_key,
            kind=candidate["kind"],
            question=candidate["question"],
            context=candidate["context"],
            basis=candidate["basis"],
            options_json=json.dumps(candidate["options"], ensure_ascii=False),
        )
        session.add(question)

    if request.status == "answered":
        option_label = None
        if request.option:
            selected = next((item for item in candidate["options"] if item["value"] == request.option), None) if candidate else None
            if selected is None:
                raise HTTPException(status_code=422, detail="Diese Antwortoption ist nicht gültig.")
            question.answer_value = selected["value"]
            option_label = selected["label"]
        answer_text = " ".join((request.answer or "").strip().split())
        if not option_label and not answer_text:
            raise HTTPException(status_code=422, detail="Bitte wähle eine Antwort oder schreibe einen kurzen Gedanken dazu.")
        question.answer = f"{option_label}: {answer_text}" if option_label and answer_text else option_label or answer_text
        question.status = "answered"
        question.answered_at = datetime.now(UTC)
        question.skipped_at = None
    else:
        question.status = "skipped"
        question.skipped_at = datetime.now(UTC)
        question.answered_at = None
    session.commit()
    return reading_profile_payload(session, user)


@app.put("/api/v1/reading-profile/soul")
def update_soul(
    request: SoulUpdateRequest, user: CurrentUserDependency, session: SessionDependency
) -> dict:
    settings = get_or_create_settings(session, user)
    markdown = request.markdown.replace("\r\n", "\n").strip()
    if markdown != settings.soul_markdown:
        settings.soul_revision = max(0, settings.soul_revision) + 1
        settings.soul_markdown = markdown
        session.add(UserSoulRevision(
            user_id=user.id,
            revision=settings.soul_revision,
            markdown=markdown,
        ))
    settings.art_enabled = request.art_enabled
    session.commit()
    return reading_profile_payload(session, user)


@app.patch("/api/v1/reading-profile/insights/{insight_key}")
def update_reading_insight(
    insight_key: str, request: InsightStatusRequest,
    user: CurrentUserDependency, session: SessionDependency,
) -> dict:
    payload = reading_profile_payload(session, user)
    candidate = next((item for item in payload["insights"] if item["key"] == insight_key), None)
    insight = session.scalar(select(UserReadingInsight).where(
        UserReadingInsight.user_id == user.id, UserReadingInsight.key == insight_key
    ))
    if candidate is None and insight is None:
        raise HTTPException(status_code=404, detail="Reading insight not found.")
    if insight is None:
        insight = UserReadingInsight(user_id=user.id, key=insight_key)
        session.add(insight)
    insight.status = request.status
    insight.dismissed = request.status == "dismissed"
    if candidate:
        insight.text = candidate["text"]
        insight.basis = candidate["basis"]
        insight.confidence = candidate["confidence"]
    session.commit()
    return reading_profile_payload(session, user)


@app.delete("/api/v1/reading-profile/insights/{insight_key}")
def dismiss_reading_insight(insight_key: str, user: CurrentUserDependency, session: SessionDependency) -> dict[str, bool]:
    insight = session.scalar(select(UserReadingInsight).where(UserReadingInsight.user_id == user.id, UserReadingInsight.key == insight_key))
    if insight is None:
        insight = UserReadingInsight(user_id=user.id, key=insight_key, dismissed=True, status="dismissed")
        session.add(insight)
    else:
        insight.dismissed = True
        insight.status = "dismissed"
    session.commit()
    return {"dismissed": True}


@app.get("/api/v1/articles/{article_id}")
def get_article(article_id: int, user: CurrentUserDependency, session: SessionDependency) -> dict:
    article = session.scalar(user_article_query(user).where(Article.id == article_id))
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    state = article_states(session, user, [article.id]).get(article.id)
    return serialize_article(article, include_content=True, state=state)


@app.patch("/api/v1/articles/{article_id}")
async def update_article_state(
    article_id: int, update: ArticleStateUpdate, user: CurrentUserDependency, session: SessionDependency
) -> dict:
    article = session.scalar(user_article_query(user).where(Article.id == article_id))
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    if update.is_read is not None:
        state = article_states(session, user, [article.id]).get(article.id)
        if state is None:
            raise HTTPException(status_code=404, detail="Article not found.")
        state.is_read = update.is_read
        state.read_at = datetime.now(UTC) if update.is_read else None
    if update.is_saved is not None:
        state = article_states(session, user, [article.id]).get(article.id)
        if state is None:
            raise HTTPException(status_code=404, detail="Article not found.")
        state.is_saved = update.is_saved
        state.saved_at = datetime.now(UTC) if update.is_saved else None
    session.commit()
    session.refresh(article)
    return serialize_article(article, state=article_states(session, user, [article.id]).get(article.id))


@app.post("/api/v1/articles/saved/visuals")
async def enrich_saved_article_visuals(user: CurrentUserDependency, session: SessionDependency) -> list[dict]:
    """Backfill a small number of saved article images when the saved list is opened."""
    articles = session.scalars(
        user_article_query(user)
        .where(UserArticle.is_saved.is_(True), Article.image_url.is_(None))
        .order_by(desc(Article.published_at))
        .limit(8)
    ).all()
    changed = False
    for article in articles:
        changed = await assign_article_visual(article, get_or_create_settings(session, user)) or changed
    if changed:
        session.commit()
        for article in articles:
            session.refresh(article)
    states = article_states(session, user, [article.id for article in articles])
    return [serialize_article(article, state=states.get(article.id)) for article in articles if article.image_url]


@app.get("/api/v1/articles/{article_id}/export/markdown")
def export_markdown(article_id: int, user: CurrentUserDependency, session: SessionDependency) -> dict[str, str]:
    article = session.scalar(user_article_query(user).where(Article.id == article_id))
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    markdown = (
        f"# {article.title}\n\n"
        f"**{article.author.name}** â€” [{article.source.name}]({article.canonical_url})\n\n"
        f"> {article.dek}\n\n"
        f"Quelle: {article.canonical_url}\n"
    )
    return {"filename": f"reado-{article.id}.md", "content": markdown}


def parse_freshrss_item(item: dict) -> dict[str, str | datetime]:
    alternate = item.get("alternate", [])
    url = next((link.get("href") for link in alternate if link.get("href")), None)
    if url is None:
        raise ValueError("FreshRSS item has no canonical URL.")
    origin = item.get("origin", {})
    author = item.get("author") or origin.get("title") or "Unbekannter Autor"
    source_name = origin.get("title") or "Unbekannte Publikation"
    content = item.get("content", {}).get("content") or item.get("summary", {}).get("content") or ""
    timestamp = item.get("published") or item.get("crawlTimeMsec", "0")
    published_at = datetime.fromtimestamp(int(timestamp) / (1000 if len(str(timestamp)) > 10 else 1), tz=UTC)
    return {
        "fresh_rss_id": str(item["id"]),
        "url": url,
        "title": item.get("title") or "Ohne Titel",
        "author": author,
        "source": source_name,
        "source_url": origin.get("htmlUrl") or url,
        "content": sanitize_html(content),
        "published_at": published_at,
    }


def serialize_feed(feed: Feed) -> dict:
    return {
        "id": feed.id,
        "url": feed.url,
        "title": feed.title,
        "site_url": feed.site_url,
        "type": feed.feed_type,
        "sync_status": feed.sync_status,
        "last_synced_at": feed.last_synced_at.isoformat() if feed.last_synced_at else None,
        "last_error": feed.last_error,
        "article_count": len(feed.articles),
    }


async def load_and_parse(url: str, *, etag: str | None = None, last_modified: str | None = None) -> tuple[ParsedFeed, httpx.Headers, int]:
    try:
        data, headers, status = await fetch_feed(url, etag=etag, last_modified=last_modified)
        if status == 304:
            raise ValueError("not-modified")
        parsed = parse_feed(data, headers.get("content-type", ""))
        return parsed, headers, status
    except httpx.HTTPError as error:
        raise ValueError(f"Feed request failed: {error}") from error


def add_items(session: Session, feed: Feed, parsed: ParsedFeed) -> int:
    imported = 0
    authors_by_name: dict[str, Author] = {}
    sources_by_name: dict[str, Source] = {}
    seen_urls: set[str] = set()
    seen_external_ids: set[str] = set()
    for item in parsed.items:
        try:
            canonical_url = validate_public_url(item.url)
        except ValueError:
            continue
        if canonical_url in seen_urls or item.external_id in seen_external_ids:
            continue
        existing = session.scalar(
            select(Article).where(
                (Article.canonical_url == canonical_url)
                | ((Article.feed_id == feed.id) & (Article.external_id == item.external_id))
            )
        )
        if existing is not None:
            continue
        author = authors_by_name.get(item.author)
        if author is None:
            author = session.scalar(select(Author).where(Author.name == item.author))
            if author is None:
                author = Author(name=item.author)
                session.add(author)
            authors_by_name[item.author] = author
        source_name = parsed.title or "Unknown publication"
        source = sources_by_name.get(source_name)
        if source is None:
            source = session.scalar(select(Source).where(Source.name == source_name))
            if source is None:
                source = Source(name=source_name, url=parsed.site_url or feed.url)
                session.add(source)
            sources_by_name[source_name] = source
        content = sanitize_html(item.content_html)
        article = Article(
                external_id=item.external_id,
                canonical_url=canonical_url,
                title=plain_text(item.title)[:500] or "Untitled",
                dek=plain_text(content)[:500] or None,
                content_html=content,
                published_at=item.published_at,
                discovered_at=datetime.now(UTC),
                reading_minutes=max(1, len(plain_text(content).split()) // 220),
                feed_id=feed.id,
                author=author,
                source=source,
            )
        session.add(article)
        session.flush()
        for subscription in session.scalars(select(UserFeed).where(UserFeed.feed_id == feed.id)).all():
            if session.scalar(select(UserArticle.id).where(UserArticle.user_id == subscription.user_id, UserArticle.article_id == article.id)) is None:
                session.add(UserArticle(user_id=subscription.user_id, article_id=article.id, discovered_at=article.discovered_at or datetime.now(UTC)))
        seen_urls.add(canonical_url)
        seen_external_ids.add(item.external_id)
        imported += 1
    return imported


def feed_import_error_message(error: Exception) -> str:
    message = str(error)
    if "uq_articles_canonical_url" in message:
        return "Der Feed enthält doppelte Artikel-Links. dérive hat den Import nicht übernommen; bitte erneut versuchen."
    if "uq_authors_name" in message or "sources_name_key" in message:
        return "Der Feed enthält wiederholte Autoren oder Quellen. dérive hat den Import nicht übernommen; bitte erneut versuchen."
    if isinstance(error, (ValueError, httpx.HTTPError)):
        return message[:500]
    return "Der Feed konnte nicht importiert werden. Bitte prüfe die URL oder versuche es später erneut."


async def sync_feed(feed: Feed, session: Session) -> int:
    try:
        data, headers, status = await fetch_feed(
            feed.url, etag=feed.etag, last_modified=feed.last_modified
        )
        if status == 304:
            imported = 0
        else:
            parsed = parse_feed(data, headers.get("content-type", ""))
            imported = add_items(session, feed, parsed)
            feed.title = parsed.title
            feed.site_url = parsed.site_url
            feed.feed_type = parsed.feed_type
        feed.etag = headers.get("etag", feed.etag)
        feed.last_modified = headers.get("last-modified", feed.last_modified)
        feed.last_synced_at = datetime.now(UTC)
        feed.last_error = None
        feed.sync_status = "ok"
        session.commit()
        return imported
    except Exception as error:
        session.rollback()
        feed.last_error = str(error)[:2000]
        feed.sync_status = "error"
        session.commit()
        raise


async def validate_feed(request: FeedRequest, _: CurrentUserDependency) -> dict:
    try:
        validate_public_url(request.url)
        parsed, headers, _ = await load_and_parse(request.url)
    except (ValueError, httpx.HTTPError) as error:
        if str(error) == "not-modified":
            raise HTTPException(status_code=422, detail="The feed could not be previewed.") from error
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "url": validate_public_url(request.url),
        "title": parsed.title,
        "site_url": parsed.site_url,
        "type": parsed.feed_type,
        "article_count": len(parsed.items),
        "etag": headers.get("etag"),
        "last_modified": headers.get("last-modified"),
    }


async def create_feed(request: FeedRequest, user: CurrentUserDependency, session: SessionDependency) -> dict:
    try:
        url = validate_public_url(request.url)
        parsed, headers, _ = await load_and_parse(url)
    except (ValueError, httpx.HTTPError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    existing = session.scalar(select(Feed).where(Feed.url == url))
    if existing is not None:
        subscription = session.scalar(select(UserFeed).where(UserFeed.user_id == user.id, UserFeed.feed_id == existing.id))
        if subscription is None:
            session.add(UserFeed(user_id=user.id, feed_id=existing.id))
            for article in existing.articles:
                if session.scalar(select(UserArticle.id).where(UserArticle.user_id == user.id, UserArticle.article_id == article.id)) is None:
                    session.add(UserArticle(user_id=user.id, article_id=article.id, discovered_at=article.discovered_at or article.published_at))
            session.commit()
        return {"feed": serialize_feed(existing), "imported": 0}
    feed = Feed(
        url=url,
        title=parsed.title,
        site_url=parsed.site_url,
        feed_type=parsed.feed_type,
        etag=headers.get("etag"),
        last_modified=headers.get("last-modified"),
        sync_status="syncing",
    )
    session.add(feed)
    session.flush()
    session.add(UserFeed(user_id=user.id, feed_id=feed.id))
    try:
        imported = add_items(session, feed, parsed)
        feed.last_synced_at = datetime.now(UTC)
        feed.sync_status = "ok"
        session.commit()
    except Exception as error:
        session.rollback()
        raise HTTPException(status_code=502, detail=f"Initial feed sync failed: {error}") from error
    session.refresh(feed)
    return {"feed": serialize_feed(feed), "imported": imported}


def list_feeds(user: CurrentUserDependency, session: SessionDependency) -> list[dict]:
    return [serialize_feed(feed) for feed in session.scalars(select(Feed).join(UserFeed, UserFeed.feed_id == Feed.id).where(UserFeed.user_id == user.id).order_by(Feed.title)).all()]


async def refresh_feed(feed_id: int, user: CurrentUserDependency, session: SessionDependency) -> dict:
    feed = session.scalar(select(Feed).join(UserFeed, UserFeed.feed_id == Feed.id).where(UserFeed.user_id == user.id, Feed.id == feed_id))
    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found.")
    try:
        imported = await sync_feed(feed, session)
    except Exception:
        session.refresh(feed)
        return {"feed": serialize_feed(feed), "imported": 0}
    session.refresh(feed)
    return {"feed": serialize_feed(feed), "imported": imported}


def delete_feed(feed_id: int, user: CurrentUserDependency, session: SessionDependency) -> dict[str, bool]:
    feed = session.scalar(select(Feed).join(UserFeed, UserFeed.feed_id == Feed.id).where(UserFeed.user_id == user.id, Feed.id == feed_id))
    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found.")
    subscription = session.scalar(select(UserFeed).where(UserFeed.user_id == user.id, UserFeed.feed_id == feed_id))
    if subscription:
        session.delete(subscription)
    session.commit()
    return {"deleted": True}


async def import_opml(request: OPMLRequest, user: CurrentUserDependency, session: SessionDependency) -> dict:
    try:
        root = ElementTree.fromstring(request.content)
    except ElementTree.ParseError as error:
        raise HTTPException(status_code=422, detail="The OPML content is invalid XML.") from error
    outlines = [outline for outline in root.iter() if outline.attrib.get("xmlUrl")]
    imported_feeds = []
    errors = []
    for outline in outlines:
        raw_url = outline.attrib["xmlUrl"]
        try:
            url = validate_public_url(raw_url)
            existing = session.scalar(select(Feed).where(Feed.url == url))
            if existing:
                if session.scalar(select(UserFeed).where(UserFeed.user_id == user.id, UserFeed.feed_id == existing.id)) is None:
                    session.add(UserFeed(user_id=user.id, feed_id=existing.id))
                    session.commit()
                    imported_feeds.append(serialize_feed(existing))
                continue
            parsed, headers, _ = await load_and_parse(url)
            feed = Feed(url=url, title=parsed.title, site_url=parsed.site_url, feed_type=parsed.feed_type, etag=headers.get("etag"), last_modified=headers.get("last-modified"), sync_status="ok", last_synced_at=datetime.now(UTC))
            session.add(feed)
            session.flush()
            session.add(UserFeed(user_id=user.id, feed_id=feed.id))
            add_items(session, feed, parsed)
            imported_feeds.append(serialize_feed(feed))
            session.commit()
        except Exception as error:
            session.rollback()
            errors.append({"url": raw_url, "error": str(error)})
    return {"imported": len(imported_feeds), "feeds": imported_feeds, "errors": errors}


def export_opml(user: CurrentUserDependency, session: SessionDependency) -> Response:
    root = ElementTree.Element("opml", {"version": "2.0"})
    head = ElementTree.SubElement(root, "head")
    ElementTree.SubElement(head, "title").text = "dérive feeds"
    body = ElementTree.SubElement(root, "body")
    for feed in session.scalars(select(Feed).join(UserFeed, UserFeed.feed_id == Feed.id).where(UserFeed.user_id == user.id).order_by(Feed.title)).all():
        ElementTree.SubElement(
            body,
            "outline",
            {"text": feed.title, "title": feed.title, "type": "rss", "xmlUrl": feed.url, **({"htmlUrl": feed.site_url} if feed.site_url else {})},
        )
    content = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(content=content, media_type="application/xml", headers={"Content-Disposition": "attachment; filename=reado-feeds.opml"})


async def sync_freshrss(request: FreshRSSSyncRequest, user: CurrentUserDependency, session: SessionDependency) -> dict[str, int]:
    base_url = str(request.base_url).rstrip("/") + "/"
    endpoint = urljoin(
        base_url, "api/greader.php/reader/api/0/stream/contents/reading-list?n=1000&output=json"
    )
    try:
        async with httpx.AsyncClient(auth=(request.username, request.api_password), timeout=20) as client:
            response = await client.get(endpoint)
            response.raise_for_status()
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail=f"FreshRSS request failed: {error}") from error

    items = response.json().get("items", [])
    imported = 0
    for item in items:
        try:
            parsed = parse_freshrss_item(item)
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=f"Invalid FreshRSS item: {error}") from error
        article = session.scalar(select(Article).where(Article.fresh_rss_id == parsed["fresh_rss_id"]))
        if article is not None:
            if session.scalar(select(UserArticle.id).where(UserArticle.user_id == user.id, UserArticle.article_id == article.id)) is None:
                session.add(UserArticle(user_id=user.id, article_id=article.id, discovered_at=article.discovered_at or article.published_at))
            continue
        author = session.scalar(select(Author).where(Author.name == parsed["author"]))
        if author is None:
            author = Author(name=str(parsed["author"]))
        source = session.scalar(select(Source).where(Source.name == parsed["source"]))
        if source is None:
            source = Source(name=str(parsed["source"]), url=str(parsed["source_url"]))
        article = Article(
                fresh_rss_id=str(parsed["fresh_rss_id"]),
                canonical_url=str(parsed["url"]),
                title=str(parsed["title"]),
                content_html=str(parsed["content"]),
                published_at=parsed["published_at"],
                discovered_at=datetime.now(UTC),
                reading_minutes=max(1, len(str(parsed["content"]).split()) // 220),
                author=author,
                source=source,
            )
        session.add(article)
        session.flush()
        session.add(UserArticle(user_id=user.id, article_id=article.id, discovered_at=article.discovered_at or article.published_at))
        imported += 1
    session.commit()
    return {"imported": imported, "received": len(items)}
