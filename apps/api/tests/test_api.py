import asyncio

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import app, get_session, stream_with_keepalives
from app.auth import current_user
from app.models import Article, User, UserArticle
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

