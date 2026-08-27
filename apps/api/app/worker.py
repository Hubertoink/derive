import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from .art import refresh_artwork_impression
from .database import Base, SessionLocal, engine, schema_initialization_lock
from .discovery import DiscoveryError, backfill_source_memory, run_discovery, sync_manual_source_memory
from .main import discovery_interval_days, discovery_next_due, ensure_schema, record_discovery_run
from .models import AppSettings, Article, DiscoveryRun, User, UserArticle
from .visuals import refresh_hero_visual

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BACKGROUND_INTERVAL = timedelta(hours=3)


def main() -> None:
    with schema_initialization_lock():
        Base.metadata.create_all(bind=engine)
        ensure_schema()
    with SessionLocal() as session:
        for user in session.scalars(select(User).where(User.is_active.is_(True))).all():
            settings = session.scalar(select(AppSettings).where(AppSettings.user_id == user.id))
            if settings is not None:
                backfill_source_memory(session, user)
                sync_manual_source_memory(session, user, settings)
        session.commit()
    logging.info("dérive worker is ready for enrichment jobs.")
    next_discovery_attempt = datetime.now(UTC)
    while True:
        with SessionLocal() as session:
            now = datetime.now(UTC)
            if now >= next_discovery_attempt:
                due_settings = session.scalars(select(AppSettings).where(AppSettings.user_id.is_not(None))).all()
                attempted = False
                for settings in due_settings:
                    user = session.get(User, settings.user_id)
                    if (
                        user is None
                        or not user.is_active
                        or settings.ai_provider != "openai"
                        or discovery_interval_days(settings) is None
                    ):
                        continue
                    target = max(1, min(int(settings.discovery_max_articles or 1), 12))
                    prepared = prepared_discoveries(session, user)
                    available = len(prepared)
                    if discovery_is_due(settings, now):
                        attempted = True
                        needed = max(0, target - available)
                        if needed == 0:
                            deliver_prepared_for_user(session, settings, user, prepared, now=now)
                            record_discovery_run(
                                session,
                                trigger="automatic",
                                status="success",
                                imported_count=available,
                                user=user,
                            )
                            continue
                        run_discovery_for_user(
                            session, settings, user, max_articles=needed,
                            trigger="automatic", include_podcasts=True,
                            prepared=prepared,
                        )
                        continue
                    if available >= target or not background_is_due(session, user, now):
                        continue
                    attempted = True
                    run_discovery_for_user(
                        session, settings, user, max_articles=target - available,
                        trigger="background", include_podcasts=False,
                    )
                    recovery_stock = prepared_discoveries(session, user)
                    if recovery_stock and last_automatic_delivery_was_empty(session, user):
                        deliver_prepared_for_user(
                            session, settings, user, recovery_stock, now=datetime.now(UTC)
                        )
                        record_discovery_run(
                            session,
                            trigger="automatic",
                            status="success",
                            imported_count=len(recovery_stock),
                            message="Nachlieferung nach einem leeren regulären Lauf.",
                            user=user,
                        )
                next_discovery_attempt = now + (timedelta(hours=1) if attempted else timedelta(minutes=15))
        time.sleep(60)


def discovery_is_due(settings: AppSettings, now: datetime) -> bool:
    due_at = discovery_next_due(settings, now)
    return bool(due_at and due_at <= now.astimezone(UTC))


def prepared_discoveries(session, user: User) -> list[tuple[UserArticle, Article]]:
    """Return only the hidden stock built by background searches.

    Old unread recommendations and ad-hoc chat results are deliberately not
    stock for a future scheduled delivery.
    """
    return list(session.execute(
        select(UserArticle, Article)
        .join(Article, Article.id == UserArticle.article_id)
        .where(
            UserArticle.user_id == user.id,
            UserArticle.is_read.is_(False),
            Article.discovery_method == "ai_web",
            UserArticle.discovery_origin == "background",
        )
        .order_by(UserArticle.discovered_at)
    ).all())


def background_is_due(session, user: User, now: datetime) -> bool:
    latest = session.scalar(
        select(DiscoveryRun.ran_at)
        .where(DiscoveryRun.user_id == user.id, DiscoveryRun.trigger == "background")
        .order_by(DiscoveryRun.ran_at.desc())
        .limit(1)
    )
    if latest is None:
        return True
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=UTC)
    return now - latest.astimezone(UTC) >= BACKGROUND_INTERVAL


def last_automatic_delivery_was_empty(session, user: User) -> bool:
    latest = session.scalar(
        select(DiscoveryRun)
        .where(DiscoveryRun.user_id == user.id, DiscoveryRun.trigger == "automatic")
        .order_by(DiscoveryRun.ran_at.desc(), DiscoveryRun.id.desc())
        .limit(1)
    )
    return bool(latest and latest.imported_count == 0)


def run_discovery_for_user(
    session,
    settings: AppSettings,
    user: User,
    *,
    max_articles: int,
    trigger: str,
    include_podcasts: bool,
    prepared: list[tuple[UserArticle, Article]] | None = None,
) -> None:
    prepared = prepared or []
    try:
        result = asyncio.run(run_discovery(
            session,
            settings,
            user=user,
            max_articles=max_articles,
            update_schedule=False,
            include_podcasts=include_podcasts,
            discovery_origin=trigger,
            refresh_presentation=False,
        ))
        delivered_count = len(result.articles)
        if trigger == "automatic":
            deliver_prepared_for_user(
                session,
                settings,
                user,
                prepared,
                now=datetime.now(UTC),
                new_candidates=result.candidates,
            )
            delivered_count += len(prepared)
        record_discovery_run(
            session,
            trigger=trigger,
            status="success",
            imported_count=delivered_count,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.total_tokens,
            user=user,
        )
        logging.info("AI %s discovery delivered/staged %d articles for user %s.", trigger, delivered_count, user.id)
    except DiscoveryError as error:
        session.rollback()
        delivered_count = 0
        if trigger == "automatic" and prepared:
            deliver_prepared_for_user(
                session, settings, user, prepared, now=datetime.now(UTC)
            )
            delivered_count = len(prepared)
        record_discovery_run(
            session,
            trigger=trigger,
            status="failed",
            imported_count=delivered_count,
            message=str(error),
            user=user,
        )
        logging.warning("AI %s discovery skipped for %s: %s", trigger, user.id, error)
    except Exception:
        session.rollback()
        record_discovery_run(session, trigger=trigger, status="failed", message="Unerwarteter Fehler bei der KI-Suche. Details stehen im Worker-Log.", user=user)
        logging.exception("AI %s discovery failed for %s.", trigger, user.id)


def _article_candidate(article: Article) -> dict:
    return {
        "title": article.title,
        "topics": [topic.strip() for topic in article.topics_csv.split(",") if topic.strip()],
        "visual_query": article.image_query or "",
    }


async def refresh_delivery_presentation(
    session,
    settings: AppSettings,
    user: User,
    candidates: list[dict],
) -> None:
    if await refresh_hero_visual(settings, candidates):
        session.commit()
    try:
        if await refresh_artwork_impression(session, settings, candidates, user):
            session.commit()
    except Exception:
        session.rollback()
        logging.warning("Optional scheduled artwork discovery failed for %s.", user.id, exc_info=True)


def deliver_prepared_for_user(
    session,
    settings: AppSettings,
    user: User,
    prepared: list[tuple[UserArticle, Article]],
    *,
    now: datetime,
    new_candidates: list[dict] | None = None,
) -> None:
    """Publish staged articles together and refresh the scheduled art trail."""
    articles = []
    for link, article in prepared:
        link.discovery_origin = "automatic"
        link.discovered_at = now
        articles.append(article)
    settings.discovery_last_run_at = now
    session.commit()
    candidates = [*[_article_candidate(article) for article in articles], *(new_candidates or [])]
    if candidates:
        asyncio.run(refresh_delivery_presentation(session, settings, user, candidates))


if __name__ == "__main__":
    main()
