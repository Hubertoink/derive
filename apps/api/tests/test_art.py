import asyncio

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.art import _art_queries, _usable_artworks, refresh_artwork_impression
from app.database import Base
from app.models import AppSettings, Artwork, User, UserArtwork


def test_art_queries_keep_an_associative_fallback():
    queries = _art_queries([{
        "title": "Eine Stadt im Wandel",
        "visual_query": "rainy city reflections, evening pedestrians, quiet geometry",
    }])

    assert queries[0] == "rainy city reflections, evening pedestrians, quiet geometry"
    assert queries[-1] == "landscape"


def test_artwork_filter_requires_public_domain_and_image():
    usable = _usable_artworks([
        {"id": 1, "image_id": "image-one", "is_public_domain": True},
        {"id": 2, "image_id": "image-two", "is_public_domain": False},
        {"id": 3, "image_id": None, "is_public_domain": True},
    ])

    assert [item["id"] for item in usable] == [1]


def test_artwork_impression_persists_museum_metadata(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    async def fake_search(query: str):
        assert query
        return ([{
            "id": 27992,
            "title": "Paris Street; Rainy Day",
            "artist_display": "Gustave Caillebotte\nFrench, 1848-1894",
            "date_display": "1877",
            "medium_display": "Oil on canvas",
            "place_of_origin": "France",
            "image_id": "demo-image",
            "is_public_domain": True,
            "thumbnail": {"alt_text": "People cross a broad rainy street."},
        }], "https://www.artic.edu/iiif/2")

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
