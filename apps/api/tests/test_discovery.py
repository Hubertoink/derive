import asyncio

import httpx
from datetime import UTC, datetime
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.chat import podcast_only_request, requested_podcast_count
from app.discovery import _candidate_text, _podcast_prompt, _prompt, _rate_limit_delay, _source_memory_guidance, _verified_podcast_candidate, candidate_batch_sizes, import_candidates, import_podcast_candidates, normalize_source_domain, reading_memory, serialize_source_memory
from app.models import (
    AppSettings,
    Article,
    Author,
    PodcastEpisode,
    Source,
    User,
    UserArticle,
    UserArticleFeedback,
    UserReadingInsight,
    UserReadingQuestion,
    UserSourceMemory,
)
from app.publisher_access import import_subscriber_article, update_rule
from app.visuals import _search_query


def test_discovery_uses_three_article_batches():
    assert candidate_batch_sizes(1) == [1]
    assert candidate_batch_sizes(3) == [3]
    assert candidate_batch_sizes(8) == [3, 3, 2]


def test_source_domain_normalizes_urls_and_www_prefix():
    assert normalize_source_domain("https://www.Example.org/reportage?utm_source=ai") == "example.org"
    assert normalize_source_domain("example.org") == "example.org"


def test_source_memory_rotates_sources_and_respects_manual_deprioritization():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = User(username="source-user", email="source@example.org", password_hash="not-used")
        settings = AppSettings(
            id=1,
            user_id=1,
            ai_provider="openai",
            discovery_deprioritized_sources_csv="zeit.de",
        )
        session.add_all([user, settings])
        session.flush()
        for index in range(11):
            session.add(UserSourceMemory(
                user_id=user.id,
                domain="zeit.de" if index == 0 else f"magazin-{index}.org",
                display_name="Die Zeit" if index == 0 else f"Magazin {index}",
                observed_count=2,
                source_score=20 - index,
            ))
        session.commit()

        first_guidance, first_domains = _source_memory_guidance(session, user, settings)
        second_guidance, second_domains = _source_memory_guidance(session, user, settings)

        assert "zeit.de" not in first_domains
        assert len(first_domains) == 8
        assert "magazin-9.org" in second_domains
        assert first_guidance != second_guidance


def test_source_memory_is_strictly_scoped_to_its_user():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        admin = User(username="admin-source", email="admin-source@example.org", password_hash="unused", role="admin")
        member = User(username="member-source", email="member-source@example.org", password_hash="unused")
        session.add_all([admin, member])
        session.flush()
        session.add_all([
            UserSourceMemory(user_id=admin.id, domain="theguardian.com", display_name="The Guardian", observed_count=2),
            UserSourceMemory(user_id=member.id, domain="zdf.de", display_name="ZDF", observed_count=1),
        ])
        session.commit()

        assert [item["domain"] for item in serialize_source_memory(session, admin)] == ["theguardian.com"]
        assert [item["domain"] for item in serialize_source_memory(session, member)] == ["zdf.de"]


def test_discovery_honours_rate_limit_reset_headers():
    response = httpx.Response(429, headers={"x-ratelimit-reset-requests": "7s"})
    assert _rate_limit_delay(response, 0) == 7


def test_search_copy_removes_markdown_source_urls():
    text = "Einordnung ([theguardian.com](https://www.theguardian.com/a?utm_source=openai))"
    assert _candidate_text(text, 1000) == "Einordnung"


def test_visual_search_prefers_associative_ai_query():
    assert _search_query([{
        "title": "What AI Will Do to Art",
        "topics": ["Künstliche Intelligenz"],
        "visual_query": "experimental musician, circular speakers, studio shadows, tactile sound",
    }]) == "experimental musician, circular speakers, studio shadows, tactile sound"


def test_reader_memory_separates_declared_explicit_saved_and_read_signals():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as session:
        user = User(username="memory-reader", email="memory@example.org", password_hash="unused")
        author = Author(name="Ada Autorin")
        source = Source(name="Testquelle", url="https://example.org")
        liked = Article(
            canonical_url="https://example.org/liked",
            title="Tiefe Perspektiven",
            content_html="<p>Text</p>",
            published_at=now,
            reading_minutes=22,
            topics_csv="Stadt,Gesellschaft",
            author=author,
            source=source,
        )
        read_only = Article(
            canonical_url="https://example.org/read-only",
            title="Nur gelesen",
            content_html="<p>Text</p>",
            published_at=now,
            reading_minutes=8,
            topics_csv="Technologie",
            author=author,
            source=source,
        )
        session.add_all([user, liked, read_only])
        session.flush()
        settings = AppSettings(user_id=user.id, soul_markdown="# Haltung\nKeine Hype-Texte.")
        session.add_all([
            settings,
            UserArticle(user_id=user.id, article_id=liked.id, is_saved=True, saved_at=now),
            UserArticle(user_id=user.id, article_id=read_only.id, is_read=True, read_at=now),
            UserArticleFeedback(
                user_id=user.id,
                article_id=liked.id,
                rating="great",
                reasons_csv="depth,perspective",
                note="Mehr Gegenpositionen.",
            ),
            UserReadingInsight(
                user_id=user.id,
                key="confirmed-depth",
                status="confirmed",
                text="Ich bevorzuge argumentierende Langformen.",
                basis="Vom Nutzer bestaetigt",
            ),
            UserReadingQuestion(
                user_id=user.id,
                key="reading-length-v1",
                kind="format",
                question="Was soll stärker zählen?",
                answer="Ausführliche Texte",
                answer_value="long",
                status="answered",
            ),
        ])
        session.commit()

        memory = reading_memory(session, user, settings)

        assert "höchste Priorität" in memory
        assert "Keine Hype-Texte" in memory
        assert "bestätigte Langzeiterinnerungen" in memory
        assert "Explizite Artikelrückmeldungen (starkes Signal)" in memory
        assert "Gemerkte Texte (mittleres positives Signal)" in memory
        assert "schwaches Nutzungssignal" in memory
        assert "nicht als Gefallen interpretieren" in memory
        assert "beantwortete Profilfragen" in memory
        assert "Ausführliche Texte" in memory


def test_imports_paywalled_recommendation_as_link_metadata(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.discovery.validate_public_url", lambda value: value)

    with Session(engine) as session:
        settings = AppSettings(
            id=1,
            discovery_min_minutes=15,
            discovery_max_articles=5,
            discovery_include_paywalled=True,
        )
        session.add(settings)
        imported = import_candidates(session, settings, [{
            "title": "Eine lange Reportage",
            "url": "https://example.com/reportage",
            "author": "Ada Autorin",
            "source": "Die Testzeitung",
            "published_at": "2026-08-23T12:00:00Z",
            "reading_minutes": 24,
            "topics": ["Gesellschaft"],
            "reason": "Passt zum Longform-Profil.",
            "summary": "Eine kurze Einordnung, aber kein kopierter Volltext.",
            "access_status": "paywalled",
        }])

        article = session.scalar(select(Article))
        assert len(imported) == 1
        assert article is not None
        assert article.access_status == "paywalled"
        assert article.canonical_url == "https://example.com/reportage"
        assert "kurze Einordnung" in article.content_html


def test_one_off_research_does_not_move_the_regular_schedule(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.discovery.validate_public_url", lambda value: value)

    with Session(engine) as session:
        settings = AppSettings(id=1, discovery_max_articles=5)
        session.add(settings)
        imported = import_candidates(
            session,
            settings,
            [
                {
                    "title": f"Text {index}", "url": f"https://example.com/text-{index}",
                    "author": f"Autorin {index}", "source": "Testquelle",
                    "published_at": "2026-08-23T12:00:00Z", "reading_minutes": 18,
                    "topics": ["Demokratie"], "reason": "Passt zur Ad-hoc-Frage.",
                    "summary": "Kurze Einordnung.", "access_status": "free",
                }
                for index in range(4)
            ],
            max_articles=3,
            update_schedule=False,
        )

        assert len(imported) == 3
        assert settings.discovery_last_run_at is None


def test_import_marks_background_results_as_staged(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.discovery.validate_public_url", lambda value: value)

    with Session(engine) as session:
        user = User(username="stock-reader", email="stock@example.org", password_hash="unused")
        settings = AppSettings(discovery_min_minutes=15, discovery_max_articles=5)
        session.add_all([user, settings])
        session.flush()
        imported = import_candidates(
            session,
            settings,
            [{
                "title": "Eine vorbereitete Reportage",
                "url": "https://example.com/prepared",
                "author": "Ada Autorin",
                "source": "Testquelle",
                "published_at": "2026-08-27T05:00:00Z",
                "reading_minutes": 20,
                "topics": ["Gesellschaft"],
                "reason": "Passt.",
                "summary": "Kurze Einordnung.",
                "access_status": "free",
            }],
            user=user,
            discovery_origin="background",
            update_schedule=False,
        )

        link = session.scalar(select(UserArticle).where(UserArticle.article_id == imported[0].id))
        assert link.discovery_origin == "background"
        assert settings.discovery_last_run_at is None


def test_import_skips_tracking_url_duplicates(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.discovery.validate_public_url", lambda value: value)

    candidate = {
        "title": "Ein Text", "author": "Autor", "source": "Quelle",
        "published_at": "2026-08-23T12:00:00Z", "reading_minutes": 18,
        "topics": ["Gesellschaft"], "reason": "Passt.", "summary": "Kurz.",
        "access_status": "free",
    }
    with Session(engine) as session:
        settings = AppSettings(id=1, discovery_min_minutes=15, discovery_max_articles=5)
        session.add(settings)
        first = {**candidate, "url": "https://example.com/text?utm_source=openai"}
        second = {**candidate, "url": "https://example.com/text?utm_source=retry"}
        imported = import_candidates(session, settings, [first, second])
        assert len(imported) == 1


def test_podcast_prompt_count_is_explicit_or_selected():
    assert requested_podcast_count("Bitte suche mir 2 Podcasts über Ambient-Musik.", None) == 2
    assert requested_podcast_count("Ich hörte einen Podcast; suche mir drei Texte dazu.", None) == 0
    assert requested_podcast_count("Suche mir passende Podcasts über Demokratie.", None) == 3
    assert requested_podcast_count("Kannst du mir hierzu Podcasts empfehlen?", None) == 3
    assert requested_podcast_count("Bitte suche mir 2 Podcasts.", 1) == 1
    assert requested_podcast_count("Bitte suche mir 2 Podcasts.", 0) == 0
    assert podcast_only_request("Kannst du mir hierzu Podcasts empfehlen?", 3) is True
    assert podcast_only_request("Suche mir Podcasts und Artikel hierzu.", 3) is False


def test_podcast_prompt_prioritizes_podcasts_over_audio_longreads():
    prompt = _podcast_prompt(AppSettings(
        id=1,
        interests_csv="Gesellschaft",
        discovery_languages_csv="Deutsch,Englisch",
        discovery_prompt="Vertiefende Erzählformate",
    ))

    assert "Bevorzuge eigenständige Podcasts" in prompt
    assert "ordne diese aber hinter Podcasts ein" in prompt
    assert "keine reguläre Podcast-Empfehlung" in prompt
    assert "Notfall" in prompt
    assert "Audioversion eines Artikels" in prompt


def test_article_prompt_deprioritizes_sources_the_reader_already_reads():
    prompt = _prompt(AppSettings(
        id=1,
        interests_csv="Gesellschaft",
        discovery_languages_csv="Deutsch,Englisch",
        discovery_prompt="Vertiefende Erzählformate",
        discovery_deprioritized_sources_csv="zeit.de",
        discovery_include_paywalled=True,
    ))

    assert "zeit.de" in prompt
    assert "priorisiere ausdrücklich unabhängige" in prompt


def test_imports_podcast_metadata_and_verified_spotify_link(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.discovery.validate_public_url", lambda value: value)
    with Session(engine) as session:
        imported = import_podcast_candidates(session, [{
            "title": "Eine lange Folge",
            "show_name": "Testpodcast",
            "url": "https://example.com/podcast/folge?utm_source=openai",
            "spotify_url": "https://open.spotify.com/episode/abc123?utm_source=openai",
            "published_at": "2026-08-24T08:00:00Z",
            "duration_minutes": 64,
            "topics": ["Gesellschaft"],
            "reason": "Passt zum Lesegeschmack.",
            "summary": "Ein vertiefendes Gespräch.",
        }])
        episode = session.scalar(select(PodcastEpisode))
        assert len(imported) == 1
        assert episode is not None
        assert episode.canonical_url == "https://example.com/podcast/folge"
        assert episode.spotify_url == "https://open.spotify.com/episode/abc123"


def test_podcast_link_check_follows_redirects_and_rejects_gone_episode(monkeypatch):
    monkeypatch.setattr("app.discovery.validate_public_url", lambda value: value)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old-episode":
            return httpx.Response(308, headers={"location": "/gone-episode"})
        return httpx.Response(410, text="Diese Folge ist nicht mehr verfügbar.")

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await _verified_podcast_candidate(
                client, {"title": "Alte Folge", "url": "https://example.com/old-episode"}
            )

    assert asyncio.run(check()) is None


def test_podcast_link_check_keeps_reachable_episode(monkeypatch):
    monkeypatch.setattr("app.discovery.validate_public_url", lambda value: value)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text="<html><title>Eine Folge</title></html>")
    )

    async def check():
        async with httpx.AsyncClient(transport=transport) as client:
            return await _verified_podcast_candidate(
                client, {"title": "Eine Folge", "url": "https://example.com/episode"}
            )

    result = asyncio.run(check())
    assert result is not None
    assert result["url"] == "https://example.com/episode"


def test_personal_subscription_import_requires_enabled_allowlist(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.publisher_access.validate_public_url", lambda value: value)
    words = " ".join(f"Wort{i}" for i in range(100))

    with Session(engine) as session:
        rule = update_rule(session, "zeit", enabled=True, terms_confirmed=True)
        article = import_subscriber_article(
            session,
            url="https://www.zeit.de/kultur/2026-08/reportage",
            title="Eine abonnierte Reportage",
            author_name="Ada Autorin",
            content_html=words,
            published_at="2026-08-23T12:00:00Z",
        )

        assert rule.enabled is True
        assert article.access_status == "subscriber"
        assert article.fulltext_source == "subscriber_capture"
        assert article.rights_basis == "personal_subscription"
        assert article.content_html.startswith("<p>")
