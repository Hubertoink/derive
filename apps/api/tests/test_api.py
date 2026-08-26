import asyncio
from datetime import UTC, datetime

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import app, get_session, migrate_legacy_data, stream_with_keepalives
from app.auth import current_user
from app.models import (
    Article,
    AppSettings,
    Artwork,
    Author,
    PodcastEpisode,
    Source,
    User,
    UserArticle,
    UserArtwork,
    UserPodcastEpisode,
    UserSourceMemory,
)
from app.discovery import DiscoveryRunResult
from app.seed import seed_demo_content


def test_home_exposes_article_first_curation(isolated_client):
    response = isolated_client.get("/api/v1/home")

    assert response.status_code == 200
    payload = response.json()
    assert payload["for_you"]
    assert payload["for_you"][0]["reason"]
    assert "content_html" not in payload["for_you"][0]


def test_article_state_can_be_saved_and_read(isolated_client):
    article = isolated_client.get("/api/v1/articles").json()[0]
    response = isolated_client.patch(
        f"/api/v1/articles/{article['id']}",
        json={"is_saved": True, "is_read": True},
    )

    assert response.status_code == 200
    assert response.json()["is_saved"] is True
    assert response.json()["is_read"] is True


@pytest.fixture
def isolated_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_demo_content(session)
        user = User(username="tester", email="tester@example.org", password_hash="not-used")
        session.add(user)
        session.flush()
        for article in session.scalars(select(Article)).all():
            session.add(UserArticle(user_id=user.id, article_id=article.id))
        podcast = PodcastEpisode(
            title="Eine Folge ueber neugieriges Hoeren",
            show_name="Testpodcast",
            description="Ein vertiefendes Gespraech.",
            canonical_url="https://example.org/podcast/testfolge",
            spotify_url="https://open.spotify.com/episode/test",
            published_at=datetime.now(UTC),
            duration_minutes=48,
            topics_csv="Musik,Kultur",
        )
        artwork = Artwork(
            provider="artic",
            provider_id="test-artwork",
            title="Eine Testlandschaft",
            artist_display="Ada Kuenstlerin",
            image_url="https://www.artic.edu/iiif/2/test/full/843,/0/default.jpg",
            source_url="https://www.artic.edu/artworks/test-artwork",
            attribution="Digital image courtesy of the Art Institute of Chicago",
            license_label="Public Domain / CC0",
        )
        session.add_all([podcast, artwork])
        session.flush()
        session.add_all([
            UserPodcastEpisode(user_id=user.id, podcast_episode_id=podcast.id),
            UserArtwork(user_id=user.id, artwork_id=artwork.id),
        ])
        session.commit()
        user_id, username, email = user.id, user.username, user.email

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[current_user] = lambda: User(id=user_id, username=username, email=email, password_hash="not-used", role="admin")
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_first_start_can_use_ai_without_feeds(isolated_client, monkeypatch):
    monkeypatch.setattr("app.main.encrypt_secret", lambda value: f"encrypted:{value}")
    response = isolated_client.post(
        "/api/v1/setup",
        json={
            "display_name": "Ada",
            "preferred_languages": ["Deutsch"],
            "discovery_languages": ["Deutsch", "Englisch"],
            "interests": ["Technologie"],
            "discovery_prompt": "Lange, sorgfältig recherchierte Reportagen",
            "reading_length": "long",
            "theme": "light",
            "pexels_api_key": "pexels-test-secret",
            "spotify": {
                "client_id": "spotify-client-id",
                "client_secret": "spotify-client-secret",
            },
            "ai": {
                "provider": "ollama",
                "base_url": "http://ollama:11434",
                "model": "llama3.2",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["setup_completed"] is True
    assert response.json()["feed_count"] == 0
    assert response.json()["pexels"] == {"has_api_key": True}
    assert response.json()["spotify"]["has_client_id"] is True
    assert response.json()["spotify"]["has_client_secret"] is True
    assert "pexels-test-secret" not in response.text
    assert "spotify-client-secret" not in response.text


def test_ai_connection_returns_selectable_models_without_a_preselected_model(isolated_client, monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "llama3.2"}, {"model": "mistral"}]}

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _endpoint, headers=None):
            return FakeResponse()

    monkeypatch.setattr("app.main.httpx.AsyncClient", FakeAsyncClient)
    response = isolated_client.post(
        "/api/v1/setup/ai/test",
        json={
            "provider": "ollama",
            "base_url": "http://ollama:11434",
            "model": None,
        },
    )

    assert response.status_code == 200
    assert response.json()["connected"] is True
    assert response.json()["model_found"] is False
    assert response.json()["models"] == ["llama3.2", "mistral"]


def test_spotify_connection_can_be_checked_without_saving_credentials(isolated_client, monkeypatch):
    async def fake_spotify_test(client_id, client_secret):
        assert client_id == "spotify-client-id"
        assert client_secret == "spotify-client-secret"
        return {"connected": True, "message": "Spotify-Katalog ist verbunden."}

    monkeypatch.setattr("app.main.test_spotify_connection", fake_spotify_test)
    response = isolated_client.post(
        "/api/v1/setup/spotify/test",
        json={"client_id": "spotify-client-id", "client_secret": "spotify-client-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"connected": True, "message": "Spotify-Katalog ist verbunden."}


def test_discovery_profile_can_be_configured_for_longform(isolated_client):
    response = isolated_client.patch(
        "/api/v1/discovery/profile",
        json={
            "prompt": "Lange investigative Reportagen über Technologie und Gesellschaft",
            "frequency": "every_3_days",
            "min_minutes": 20,
            "max_articles": 4,
            "open_access_only": True,
            "include_paywalled": True,
            "deprioritized_sources": ["zeit.de"],
        },
    )

    assert response.status_code == 200
    assert response.json()["profile"] == {
        "prompt": "Lange investigative Reportagen über Technologie und Gesellschaft",
        "frequency": "every_3_days",
        "min_minutes": 20,
        "max_articles": 4,
        "open_access_only": True,
        "include_paywalled": True,
        "deprioritized_sources": ["zeit.de"],
        "last_run_at": None,
    }
    assert response.json()["sources"][0]["domain"] == "zeit.de"
    assert response.json()["sources"][0]["status"] == "deprioritized"


def test_discovery_explains_when_web_search_is_not_configured(isolated_client):
    response = isolated_client.post("/api/v1/discovery/run", json={})

    assert response.status_code == 422
    assert "OpenAI-Provider" in response.json()["detail"]
    status = isolated_client.get("/api/v1/discovery").json()
    assert status["runs"][0]["trigger"] == "manual"
    assert status["runs"][0]["status"] == "failed"


def test_discovery_stream_sends_keepalives_while_waiting_for_ai():
    async def slow_events():
        await asyncio.sleep(0.03)
        yield {"type": "done", "imported": 2}

    async def collect_events():
        return [
            event
            async for event in stream_with_keepalives(slow_events(), heartbeat_seconds=0.01)
        ]

    events = asyncio.run(collect_events())

    assert events[0] == {"type": "keepalive"}
    assert {"type": "keepalive"} in events[1:]
    assert events[-1] == {"type": "done", "imported": 2}


def test_chat_research_keeps_response_successful_if_run_log_fails(isolated_client, monkeypatch):
    async def fake_chat_research(*_args, **_kwargs):
        return DiscoveryRunResult(articles=[], podcasts=[])

    def fail_to_record(*_args, **_kwargs):
        raise RuntimeError("temporary run-log failure")

    monkeypatch.setattr("app.main.chat_research", fake_chat_research)
    monkeypatch.setattr("app.main.record_discovery_run", fail_to_record)

    response = isolated_client.post(
        "/api/v1/discovery/chat/research",
        json={"message": "Suche einen langen Text über Stadtentwicklung."},
    )

    assert response.status_code == 200
    assert response.json()["articles"] == []
    assert response.json()["podcasts"] == []


def test_soul_is_versioned_and_art_can_be_disabled(isolated_client):
    first = isolated_client.put(
        "/api/v1/reading-profile/soul",
        json={
            "markdown": "# Meine Haltung\n\nUeberrasche mich mit Gegenpositionen.",
            "art_enabled": True,
        },
    )
    second = isolated_client.put(
        "/api/v1/reading-profile/soul",
        json={
            "markdown": "# Meine Haltung\n\nUeberrasche mich, aber vermeide Hype.",
            "art_enabled": False,
        },
    )

    assert first.status_code == 200
    assert first.json()["soul"]["revision"] == 1
    assert second.status_code == 200
    assert second.json()["soul"]["revision"] == 2
    assert second.json()["soul"]["art_enabled"] is False
    assert [item["revision"] for item in second.json()["soul"]["revisions"]] == [2, 1]


def test_article_feedback_reasons_and_confirmed_memory_are_transparent(isolated_client):
    article = isolated_client.get("/api/v1/articles").json()[0]
    saved = isolated_client.put(
        f"/api/v1/articles/{article['id']}/feedback",
        json={
            "rating": "great",
            "reasons": ["depth", "perspective"],
            "note": "Bitte mehr davon, aber aus anderen Quellen.",
        },
    )

    assert saved.status_code == 200
    assert saved.json()["reasons"] == ["depth", "perspective"]
    profile = isolated_client.get("/api/v1/reading-profile").json()
    assert profile["stats"]["feedback_count"] == 1
    assert profile["insights"]
    insight = profile["insights"][0]

    confirmed = isolated_client.patch(
        f"/api/v1/reading-profile/insights/{insight['key']}",
        json={"status": "confirmed"},
    )

    assert confirmed.status_code == 200
    confirmed_item = next(item for item in confirmed.json()["insights"] if item["key"] == insight["key"])
    assert confirmed_item["status"] == "confirmed"
    assert confirmed_item["basis"]


def test_podcast_and_artwork_feedback_use_the_same_explicit_vocabulary(isolated_client):
    podcast = isolated_client.get("/api/v1/podcasts").json()[0]
    home = isolated_client.get("/api/v1/home").json()
    # The fixture artwork belongs to the user but is not featured; use its
    # deterministic SQLite id to exercise the ownership-protected endpoint.
    artwork_id = 1
    podcast_response = isolated_client.put(
        f"/api/v1/podcasts/{podcast['id']}/feedback",
        json={"rating": "yes", "reasons": ["depth", "style"], "note": "Gute Stimme."},
    )
    artwork_response = isolated_client.put(
        f"/api/v1/artworks/{artwork_id}/feedback",
        json={"rating": "not_quite", "reasons": ["too_familiar"], "note": "Zu erwartbar."},
    )

    assert home["artwork"] is None
    assert podcast_response.status_code == 200
    assert podcast_response.json()["reasons"] == ["depth", "style"]
    assert artwork_response.status_code == 200
    assert artwork_response.json()["reasons"] == ["too_familiar"]
    assert isolated_client.get(f"/api/v1/podcasts/{podcast['id']}/feedback").json()["rating"] == "yes"
    assert isolated_client.get(f"/api/v1/artworks/{artwork_id}/feedback").json()["rating"] == "not_quite"
    profile = isolated_client.get("/api/v1/reading-profile").json()
    assert profile["stats"]["feedback_count"] == 2
    assert len(profile["podcast_feedback"]) == 1
    assert len(profile["artwork_feedback"]) == 1


def test_legacy_migration_never_claims_another_users_catalog():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as session:
        admin = User(username="admin-reader", email="admin@example.org", password_hash="unused", role="admin")
        member = User(username="member-reader", email="member@example.org", password_hash="unused")
        author = Author(name="Test Autor")
        foreign_source = Source(name="ZDF", url="https://zdf.de")
        admin_source = Source(name="The Guardian", url="https://theguardian.com")
        foreign_article = Article(
            canonical_url="https://zdf.de/member-article",
            title="Nur fuer den anderen Nutzer",
            content_html="<p>Text</p>",
            published_at=now,
            reading_minutes=12,
            discovery_method="ai_web",
            discovered_at=now,
            author=author,
            source=foreign_source,
        )
        engaged_overlap = Article(
            canonical_url="https://zdf.de/shared-article",
            title="Vom Admin bereits gelesen",
            content_html="<p>Text</p>",
            published_at=now,
            reading_minutes=12,
            discovery_method="ai_web",
            discovered_at=now,
            author=author,
            source=admin_source,
        )
        legacy_unowned = Article(
            canonical_url="https://example.org/legacy",
            title="Alter Einzelnutzer-Artikel",
            content_html="<p>Text</p>",
            published_at=now,
            reading_minutes=10,
            author=author,
            source=admin_source,
        )
        session.add_all([admin, member, foreign_article, engaged_overlap, legacy_unowned])
        session.flush()
        settings = AppSettings(user_id=admin.id, ownership_repair_completed=False)
        session.add(settings)
        session.add_all([
            UserArticle(user_id=member.id, article_id=foreign_article.id, discovered_at=now),
            UserArticle(user_id=member.id, article_id=engaged_overlap.id, discovered_at=now),
        ])
        session.flush()
        leaked_link = UserArticle(user_id=admin.id, article_id=foreign_article.id, discovered_at=now)
        kept_link = UserArticle(
            user_id=admin.id,
            article_id=engaged_overlap.id,
            discovered_at=now,
            is_read=True,
            read_at=now,
        )
        session.add_all([leaked_link, kept_link, UserSourceMemory(
            user_id=admin.id,
            domain="zdf.de",
            display_name="ZDF",
            observed_count=2,
            source_score=20,
        )])
        session.commit()

        migrate_legacy_data(session, admin)

        assert session.scalar(select(UserArticle.id).where(
            UserArticle.user_id == admin.id,
            UserArticle.article_id == foreign_article.id,
        )) is None
        assert session.scalar(select(UserArticle.id).where(
            UserArticle.user_id == member.id,
            UserArticle.article_id == foreign_article.id,
        )) is not None
        assert session.scalar(select(UserArticle.id).where(
            UserArticle.user_id == admin.id,
            UserArticle.article_id == engaged_overlap.id,
        )) is not None
        assert session.scalar(select(UserArticle.id).where(
            UserArticle.user_id == admin.id,
            UserArticle.article_id == legacy_unowned.id,
        )) is not None
        assert session.scalar(select(UserSourceMemory.id).where(
            UserSourceMemory.user_id == admin.id,
            UserSourceMemory.domain == "zdf.de",
        )) is None
        assert settings.ownership_repair_completed is True

        # A later restart must not attach the member's article again.
        migrate_legacy_data(session, admin)
        assert session.scalar(select(UserArticle.id).where(
            UserArticle.user_id == admin.id,
            UserArticle.article_id == foreign_article.id,
        )) is None

