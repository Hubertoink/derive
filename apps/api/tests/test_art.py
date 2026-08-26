import asyncio

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.art import _art_queries, _provider_searches, _usable_artworks, refresh_artwork_impression
from app.database import Base
from app.models import AppSettings, Artwork, User, UserArtwork


def test_art_queries_keep_an_associative_fallback():
    queries = _art_queries([{
        "title": "Eine Stadt im Wandel",
        "visual_query": "rainy city reflections, evening pedestrians, quiet geometry",
    }])

    assert queries[0] == "rainy city reflections, evening pedestrians, quiet geometry"
    assert queries[-1] == "landscape"


def test_art_queries_periodically_prioritize_abstract_compositions():
    queries = _art_queries([{"visual_query": "quiet geometry and color"}], abstract_first=True)

    assert queries[0].startswith("abstract art ")


def test_artwork_filter_requires_public_domain_and_image():
    usable = _usable_artworks([
        {"provider": "met", "provider_id": "1", "image_url": "image-one", "source_url": "source-one", "rights_confirmed": True},
        {"provider": "met", "provider_id": "2", "image_url": "image-two", "source_url": "source-two", "rights_confirmed": False},
        {"provider": "cleveland", "provider_id": "3", "image_url": "", "source_url": "source-three", "rights_confirmed": True},
    ])

    assert [item["provider_id"] for item in usable] == ["1"]


def test_artwork_impression_persists_museum_metadata(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    async def fake_search(query: str):
        assert query
        return [{
            "provider": "artic",
            "provider_id": "27992",
            "title": "Paris Street; Rainy Day",
            "artist_display": "Gustave Caillebotte\nFrench, 1848-1894",
            "date_display": "1877",
            "medium_display": "Oil on canvas",
            "place_of_origin": "France",
            "image_url": "https://www.artic.edu/iiif/2/demo-image/full/843,/0/default.jpg",
            "source_url": "https://www.artic.edu/artworks/27992",
            "attribution": "Digital image courtesy of the Art Institute of Chicago",
            "license_label": "Public Domain / CC0",
            "context": "People cross a broad rainy street.",
            "rights_confirmed": True,
        }]

    monkeypatch.setattr("app.art._search_artic", fake_search)
    with Session(engine) as session:
        user = User(username="art-reader", email="art@example.org", password_hash="unused")
        session.add(user)
        session.flush()
        settings = AppSettings(user_id=user.id, art_enabled=True)
        session.add(settings)
        session.flush()

        result = asyncio.run(refresh_artwork_impression(
            session,
            settings,
            [{"title": "Stadtleben", "visual_query": "rainy city street"}],
            user,
        ))
        session.commit()

        assert result is not None
        assert result.title == "Paris Street; Rainy Day"
        assert result.license_label == "Public Domain / CC0"
        assert result.image_url.endswith("/demo-image/full/843,/0/default.jpg")
        assert settings.featured_artwork_id == result.id
        assert session.scalar(select(UserArtwork).where(UserArtwork.artwork_id == result.id)) is not None
        assert session.scalar(select(Artwork).where(Artwork.provider_id == "27992")) is not None


def test_provider_rotation_prefers_a_museum_not_yet_seen_by_the_user():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(username="museum-reader", email="museum@example.org", password_hash="unused")
        artwork = Artwork(
            provider="artic",
            provider_id="seen-artwork",
            title="Seen",
            image_url="https://example.org/image.jpg",
            source_url="https://example.org/artwork",
            attribution="Museum",
        )
        session.add_all([user, artwork])
        session.flush()
        session.add(UserArtwork(user_id=user.id, artwork_id=artwork.id))
        session.flush()

        providers = [provider for provider, _search in _provider_searches(session, user)]

        assert providers == ["met", "cleveland", "artic"]
