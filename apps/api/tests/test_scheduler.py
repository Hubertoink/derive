from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.main import discovery_next_due, user_article_query
from app.models import AppSettings, Article, Author, DiscoveryRun, Source, User, UserArticle
from app.worker import deliver_prepared_for_user, last_automatic_delivery_was_empty, prepared_discoveries


def test_first_scheduled_run_is_due_after_worker_starts_late(monkeypatch):
    monkeypatch.setattr("app.main.discovery_timezone", lambda _settings: UTC)
    settings = AppSettings(
        ai_provider="openai",
        discovery_frequency="interval",
        discovery_interval_days=1,
        discovery_time="09:00",
        discovery_timezone="test",
    )
    started_at = datetime(2026, 8, 26, 9, 17, tzinfo=UTC)

    assert discovery_next_due(settings, started_at) == datetime(2026, 8, 26, 9, 0, tzinfo=UTC)


def test_background_stock_excludes_old_and_chat_recommendations():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 27, 6, 0, tzinfo=UTC)
    with Session(engine) as session:
        user = User(username="scheduled-reader", email="scheduled@example.org", password_hash="unused")
        author = Author(name="Ada Autorin")
        source = Source(name="Testquelle", url="https://example.org")
        session.add_all([user, author, source])
        session.flush()
        articles = [
            Article(
                canonical_url=f"https://example.org/{origin}",
                title=origin,
                content_html="",
                published_at=now,
                reading_minutes=20,
                discovery_method="ai_web",
                author=author,
                source=source,
            )
            for origin in ("background", "chat", "legacy")
        ]
        session.add_all(articles)
        session.flush()
        session.add_all([
            UserArticle(
                user_id=user.id,
                article_id=article.id,
                discovery_origin=origin,
                discovered_at=now,
            )
            for article, origin in zip(articles, ("background", "chat", "legacy"), strict=True)
        ])
        session.commit()

        prepared = prepared_discoveries(session, user)
        visible = session.scalars(user_article_query(user)).all()

        assert [article.title for _link, article in prepared] == ["background"]
        assert {article.title for article in visible} == {"chat", "legacy"}


def test_scheduled_delivery_publishes_stock_and_refreshes_art(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    staged_at = datetime(2026, 8, 27, 6, 0, tzinfo=UTC)
    delivered_at = datetime(2026, 8, 27, 9, 1, tzinfo=UTC)
    captured: list[dict] = []

    async def fake_refresh(_session, _settings, _user, candidates):
        captured.extend(candidates)

    monkeypatch.setattr("app.worker.refresh_delivery_presentation", fake_refresh)
    with Session(engine) as session:
        user = User(username="delivery-reader", email="delivery@example.org", password_hash="unused")
        settings = AppSettings(user_id=1, art_enabled=True)
        author = Author(name="Ada Autorin")
        source = Source(name="Testquelle", url="https://example.org")
        article = Article(
            canonical_url="https://example.org/staged",
            title="Vorbereitete Reportage",
            content_html="",
            published_at=staged_at,
            reading_minutes=20,
            topics_csv="Gesellschaft,Kunst",
            image_query="quiet city geometry",
            discovery_method="ai_web",
            author=author,
            source=source,
        )
        session.add_all([user, settings, article])
        session.flush()
        link = UserArticle(
            user_id=user.id,
            article_id=article.id,
            discovery_origin="background",
            discovered_at=staged_at,
        )
        session.add(link)
        session.commit()

        deliver_prepared_for_user(
            session,
            settings,
            user,
            [(link, article)],
            now=delivered_at,
        )

        session.refresh(link)
        session.refresh(settings)
        assert link.discovery_origin == "automatic"
        assert link.discovered_at.replace(tzinfo=UTC) == delivered_at
        assert settings.discovery_last_run_at.replace(tzinfo=UTC) == delivered_at
        assert captured[0]["visual_query"] == "quiet city geometry"
        assert [item.title for item in session.scalars(user_article_query(user)).all()] == [
            "Vorbereitete Reportage"
        ]


def test_empty_automatic_run_requests_a_late_recovery():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(username="recovery-reader", email="recovery@example.org", password_hash="unused")
        session.add(user)
        session.flush()
        assert last_automatic_delivery_was_empty(session, user) is False

        session.add(DiscoveryRun(
            user_id=user.id,
            trigger="automatic",
            status="success",
            imported_count=0,
        ))
        session.commit()
        assert last_automatic_delivery_was_empty(session, user) is True

        session.add(DiscoveryRun(
            user_id=user.id,
            trigger="automatic",
            status="success",
            imported_count=3,
        ))
        session.commit()
        assert last_automatic_delivery_was_empty(session, user) is False
