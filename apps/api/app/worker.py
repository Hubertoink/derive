import asyncio
import logging
import os
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from .database import Base, SessionLocal, engine, schema_initialization_lock
from .discovery import DiscoveryError, backfill_source_memory, run_discovery, sync_manual_source_memory
from .main import discovery_interval_days, discovery_next_due, ensure_schema, record_discovery_run
from .models import AppSettings, Article, DiscoveryRun, User, UserArticle

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
                    available = unread_discovery_count(session, user)
                    if discovery_is_due(settings, now):
                        attempted = True
                        needed = max(0, target - available)
                        if needed == 0:
                            # The background replenishment already prepared enough
                            # material; advance the delivery clock without another
                            # model call.
                            settings.discovery_last_run_at = now
                            session.commit()
                            record_discovery_run(session, trigger="automatic", status="success", user=user)
                            continue
                        run_discovery_for_user(
                            session, settings, user, max_articles=needed,
                            trigger="automatic", include_podcasts=True,
                        )
                        continue
                    if available >= target or not background_is_due(session, user, now):
                        continue
                    attempted = True
                    run_discovery_for_user(
                        session, settings, user, max_articles=target - available,
                        trigger="background", include_podcasts=False,
                    )
                next_discovery_attempt = now + (timedelta(hours=1) if attempted else timedelta(minutes=15))
        time.sleep(60)


def discovery_is_due(settings: AppSettings, now: datetime) -> bool:
    due_at = discovery_next_due(settings, now)
    return bool(due_at and due_at <= now.astimezone(UTC))


def unread_discovery_count(session, user: User) -> int:
    return int(session.scalar(
        select(func.count(UserArticle.id))
        .join(Article, Article.id == UserArticle.article_id)
        .where(
            UserArticle.user_id == user.id,
            UserArticle.is_read.is_(False),
            Article.discovery_method == "ai_web",
        )
    ) or 0)


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


def run_discovery_for_user(
    session,
    settings: AppSettings,
    user: User,
    *,
    max_articles: int,
    trigger: str,
    include_podcasts: bool,
) -> None:
    try:
        result = asyncio.run(run_discovery(
            session,
            settings,
            user=user,
            max_articles=max_articles,
            update_schedule=trigger == "automatic",
            include_podcasts=include_podcasts,
        ))
        record_discovery_run(
            session,
            trigger=trigger,
            status="success",
            imported_count=len(result.articles),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.total_tokens,
            user=user,
        )
        logging.info("AI %s discovery imported %d articles for user %s.", trigger, len(result.articles), user.id)
    except DiscoveryError as error:
        session.rollback()
        record_discovery_run(session, trigger=trigger, status="failed", message=str(error), user=user)
        logging.warning("AI %s discovery skipped for %s: %s", trigger, user.id, error)
    except Exception:
        session.rollback()
        record_discovery_run(session, trigger=trigger, status="failed", message="Unerwarteter Fehler bei der KI-Suche. Details stehen im Worker-Log.", user=user)
        logging.exception("AI %s discovery failed for %s.", trigger, user.id)


if __name__ == "__main__":
    main()
