"""Public-domain artwork impressions from the Art Institute of Chicago."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .feeds import plain_text
from .models import AppSettings, Artwork, User, UserArtwork
from .visuals import _search_query


ARTIC_SEARCH_URL = "https://api.artic.edu/api/v1/artworks/search"
ARTIC_ATTRIBUTION = "Digital image courtesy of the Art Institute of Chicago"


def _art_queries(candidates: list[dict[str, Any]]) -> list[str]:
    primary = _search_query(candidates).strip()[:120]
    words = [word.strip(" ,.;:()[]") for word in primary.split() if len(word.strip(" ,.;:()[]")) > 3]
    compact = " ".join(words[:3])[:80]
    return list(dict.fromkeys(query for query in [primary, compact, "landscape"] if query))


def _artic_fields() -> str:
    return ",".join([
        "id", "title", "artist_display", "date_display", "medium_display",
        "place_of_origin", "image_id", "is_public_domain", "thumbnail",
    ])


async def _search_artic(query: str) -> tuple[list[dict[str, Any]], str]:
    async with httpx.AsyncClient(timeout=18, trust_env=False) as client:
        response = await client.get(
            ARTIC_SEARCH_URL,
            params={
                "q": query,
                "query[term][is_public_domain]": "true",
                "limit": 12,
                "fields": _artic_fields(),
            },
            headers={"User-Agent": "derive-curator/1.0 (public-domain artwork discovery)"},
        )
        response.raise_for_status()
        payload = response.json()
    data = payload.get("data", []) if isinstance(payload, dict) else []
    config = payload.get("config", {}) if isinstance(payload, dict) else {}
    iiif_url = config.get("iiif_url", "https://www.artic.edu/iiif/2") if isinstance(config, dict) else "https://www.artic.edu/iiif/2"
    return data if isinstance(data, list) else [], str(iiif_url).rstrip("/")


def _usable_artworks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item for item in items
        if isinstance(item, dict)
        and isinstance(item.get("id"), int)
        and isinstance(item.get("image_id"), str)
        and bool(item.get("image_id"))
        and item.get("is_public_domain") is True
    ]


async def refresh_artwork_impression(
    session: Session,
    settings: AppSettings,
    candidates: list[dict[str, Any]],
    user: User,
) -> Artwork | None:
    """Select and persist one explainable public-domain artwork.

    The museum API is an optional enrichment. Callers deliberately treat any
    network or payload failure as non-fatal to the underlying discovery run.
    """
    if not settings.art_enabled or not candidates:
        return None

    selected: dict[str, Any] | None = None
    selected_query = ""
    iiif_url = "https://www.artic.edu/iiif/2"
    seen_ids = set(session.scalars(
        select(Artwork.provider_id)
        .join(UserArtwork, UserArtwork.artwork_id == Artwork.id)
        .where(UserArtwork.user_id == user.id, Artwork.provider == "artic")
    ).all())
    try:
        fallback: dict[str, Any] | None = None
        for query in _art_queries(candidates):
            items, iiif_url = await _search_artic(query)
            usable = _usable_artworks(items)
            if usable and fallback is None:
                fallback = usable[0]
                selected_query = query
            selected = next((item for item in usable if str(item["id"]) not in seen_ids), None)
            if selected is not None:
                selected_query = query
                break
        selected = selected or fallback
    except (httpx.HTTPError, TypeError, ValueError, AttributeError, KeyError):
        return None
    if selected is None:
        return None

    provider_id = str(selected["id"])
    artwork = session.scalar(select(Artwork).where(
        Artwork.provider == "artic", Artwork.provider_id == provider_id
    ))
    if artwork is None:
        artwork = Artwork(provider="artic", provider_id=provider_id)
        session.add(artwork)

    thumbnail = selected.get("thumbnail") if isinstance(selected.get("thumbnail"), dict) else {}
    artwork.title = plain_text(str(selected.get("title") or "Ohne Titel"))[:500]
    artwork.artist_display = plain_text(str(selected.get("artist_display") or "Unbekannte Urheberschaft"))[:1000]
    artwork.date_display = plain_text(str(selected.get("date_display") or ""))[:255]
    artwork.medium_display = plain_text(str(selected.get("medium_display") or ""))[:1000]
    artwork.place_of_origin = plain_text(str(selected.get("place_of_origin") or ""))[:500]
    artwork.image_url = f"{iiif_url}/{selected['image_id']}/full/843,/0/default.jpg"
    artwork.source_url = f"https://www.artic.edu/artworks/{provider_id}"
    artwork.attribution = ARTIC_ATTRIBUTION
    artwork.license_label = "Public Domain / CC0"
    artwork.context = plain_text(str(thumbnail.get("alt_text") or ""))[:1000] or None
    artwork.search_query = selected_query[:240]
    artwork.curation_reason = (
        f"Als visueller Seitenblick zur Bildidee „{selected_query}“ ausgewählt. "
        "Werkdaten und Rechteangabe stammen direkt aus der Museumssammlung."
    )[:1000]
    session.flush()

    state = session.scalar(select(UserArtwork).where(
        UserArtwork.user_id == user.id, UserArtwork.artwork_id == artwork.id
    ))
    if state is None:
        session.add(UserArtwork(user_id=user.id, artwork_id=artwork.id, discovered_at=datetime.now(UTC)))
    settings.featured_artwork_id = artwork.id
    return artwork
