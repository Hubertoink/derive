"""Rights-confirmed artwork impressions from public museum APIs."""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .feeds import plain_text
from .models import AppSettings, Artwork, User, UserArtwork
from .visuals import _search_query

ARTIC_SEARCH_URL = "https://api.artic.edu/api/v1/artworks/search"
MET_SEARCH_URL = "https://collectionapi.metmuseum.org/public/collection/v1/search"
MET_OBJECT_URL = "https://collectionapi.metmuseum.org/public/collection/v1/objects/{object_id}"
CLEVELAND_SEARCH_URL = "https://openaccess-api.clevelandart.org/api/artworks/"
PROVIDER_NAMES = {
    "artic": "Art Institute of Chicago",
    "met": "The Metropolitan Museum of Art",
    "cleveland": "Cleveland Museum of Art",
}
PROVIDER_ORDER = tuple(PROVIDER_NAMES)
USER_AGENT = "derive-curator/1.0 (rights-confirmed artwork discovery)"


def museum_name(provider: str) -> str:
    return PROVIDER_NAMES.get(provider, provider)


def _art_queries(candidates: list[dict[str, Any]], abstract_first: bool = False) -> list[str]:
    primary = _search_query(candidates).strip()[:120]
    words = [word.strip(" ,.;:()[]") for word in primary.split() if len(word.strip(" ,.;:()[]")) > 3]
    compact = " ".join(words[:3])[:80]
    abstract = f"abstract art {compact}".strip()[:120]
    queries = [primary, compact, abstract, "landscape"]
    if abstract_first:
        queries.insert(0, abstract)
    return list(dict.fromkeys(query for query in queries if query))


def _clean(value: Any, fallback: str = "") -> str:
    return plain_text(str(value or fallback)).strip()


def _artwork(
    provider: str, provider_id: Any, title: Any, artist: Any, date: Any,
    medium: Any, place: Any, image_url: Any, source_url: Any,
    attribution: str, license_label: str, context: Any, rights_confirmed: bool,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "provider_id": str(provider_id),
        "title": _clean(title, "Ohne Titel"),
        "artist_display": _clean(artist, "Unbekannte Urheberschaft"),
        "date_display": _clean(date),
        "medium_display": _clean(medium),
        "place_of_origin": _clean(place),
        "image_url": str(image_url or "").strip(),
        "source_url": str(source_url or "").strip(),
        "attribution": attribution,
        "license_label": license_label,
        "context": _clean(context),
        "rights_confirmed": rights_confirmed,
    }


async def _search_artic(query: str) -> list[dict[str, Any]]:
    fields = ",".join([
        "id", "title", "artist_display", "date_display", "medium_display",
        "place_of_origin", "image_id", "is_public_domain", "thumbnail",
    ])
    async with httpx.AsyncClient(timeout=18, trust_env=False) as client:
        response = await client.get(
            ARTIC_SEARCH_URL,
            params={"q": query, "query[term][is_public_domain]": "true", "limit": 12, "fields": fields},
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        payload = response.json()
    data = payload.get("data", []) if isinstance(payload, dict) else []
    config = payload.get("config", {}) if isinstance(payload, dict) else {}
    iiif = str(config.get("iiif_url", "https://www.artic.edu/iiif/2")).rstrip("/")
    results = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        thumbnail = item.get("thumbnail") if isinstance(item.get("thumbnail"), dict) else {}
        image_id = item.get("image_id")
        results.append(_artwork(
            "artic", item.get("id", ""), item.get("title"), item.get("artist_display"),
            item.get("date_display"), item.get("medium_display"), item.get("place_of_origin"),
            f"{iiif}/{image_id}/full/843,/0/default.jpg" if image_id else "",
            f"https://www.artic.edu/artworks/{item.get('id')}",
            "Digital image courtesy of the Art Institute of Chicago", "Public Domain / CC0",
            thumbnail.get("alt_text"), item.get("is_public_domain") is True,
        ))
    return results


async def _search_met(query: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=18, trust_env=False) as client:
        response = await client.get(
            MET_SEARCH_URL, params={"hasImages": "true", "q": query}, headers={"User-Agent": USER_AGENT}
        )
        response.raise_for_status()
        payload = response.json()
        object_ids = payload.get("objectIDs", []) if isinstance(payload, dict) else []
        details = await asyncio.gather(*[
            client.get(MET_OBJECT_URL.format(object_id=value), headers={"User-Agent": USER_AGENT})
            for value in (object_ids or [])[:12]
        ], return_exceptions=True)
    results = []
    for response in details:
        if isinstance(response, Exception) or response.status_code != 200:
            continue
        item = response.json()
        if not isinstance(item, dict):
            continue
        results.append(_artwork(
            "met", item.get("objectID", ""), item.get("title"),
            item.get("artistDisplayName") or item.get("artistDisplayBio"), item.get("objectDate"),
            item.get("medium"), item.get("culture") or item.get("country") or item.get("city"),
            item.get("primaryImageSmall") or item.get("primaryImage"), item.get("objectURL"),
            "The Metropolitan Museum of Art, Open Access", "Public Domain", item.get("creditLine"),
            item.get("isPublicDomain") is True,
        ))
    return results


def _cleveland_artist(item: dict[str, Any]) -> str:
    creators = item.get("creators")
    if not isinstance(creators, list):
        return ""
    names = [
        str(value.get("description") or value.get("name") or "").strip()
        for value in creators if isinstance(value, dict)
    ]
    return "; ".join(value for value in names if value)


async def _search_cleveland(query: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=18, trust_env=False) as client:
        response = await client.get(
            CLEVELAND_SEARCH_URL,
            params={"q": query, "has_image": 1, "cc0": 1, "limit": 12},
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        payload = response.json()
    data = payload.get("data", []) if isinstance(payload, dict) else []
    results = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        images = item.get("images") if isinstance(item.get("images"), dict) else {}
        web = images.get("web") if isinstance(images.get("web"), dict) else {}
        results.append(_artwork(
            "cleveland", item.get("id", ""), item.get("title"), _cleveland_artist(item),
            item.get("creation_date"), item.get("technique") or item.get("type"),
            item.get("culture") or item.get("collection"), web.get("url"), item.get("url"),
            "Cleveland Museum of Art, Open Access", "CC0",
            item.get("wall_description") or item.get("creditline"),
            str(item.get("share_license_status") or "").casefold() == "cc0",
        ))
    return results


def _usable_artworks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if (
        isinstance(item, dict)
        and item.get("provider") in PROVIDER_NAMES
        and bool(str(item.get("provider_id") or "").strip())
        and bool(str(item.get("image_url") or "").strip())
        and bool(str(item.get("source_url") or "").strip())
        and item.get("rights_confirmed") is True
    )]


def _provider_searches(
    session: Session, user: User
) -> list[tuple[str, Callable[[str], Awaitable[list[dict[str, Any]]]]]]:
    counts = Counter(session.scalars(
        select(Artwork.provider).join(UserArtwork).where(UserArtwork.user_id == user.id)
    ).all())
    searches = {"artic": _search_artic, "met": _search_met, "cleveland": _search_cleveland}
    return [(name, searches[name]) for name in sorted(PROVIDER_ORDER, key=lambda value: counts[value])]


async def refresh_artwork_impression(
    session: Session, settings: AppSettings, candidates: list[dict[str, Any]], user: User,
) -> Artwork | None:
    """Select one rights-confirmed work without making discovery depend on a museum API."""
    if not settings.art_enabled or not candidates:
        return None
    artwork_count = session.scalar(
        select(UserArtwork.id).where(UserArtwork.user_id == user.id).order_by(UserArtwork.id.desc()).limit(1)
    )
    abstract_first = bool(artwork_count and artwork_count % 3 == 0)
    seen = set(session.execute(
        select(Artwork.provider, Artwork.provider_id).join(UserArtwork).where(UserArtwork.user_id == user.id)
    ).all())
    fallback: tuple[dict[str, Any], str] | None = None
    selected: tuple[dict[str, Any], str] | None = None
    for query in _art_queries(candidates, abstract_first=abstract_first):
        for _provider, search in _provider_searches(session, user):
            try:
                usable = _usable_artworks(await search(query))
            except (httpx.HTTPError, TypeError, ValueError, AttributeError, KeyError):
                continue
            if usable and fallback is None:
                fallback = (usable[0], query)
            fresh = next((item for item in usable if (item["provider"], item["provider_id"]) not in seen), None)
            if fresh is not None:
                selected = (fresh, query)
                break
        if selected is not None:
            break
    selected = selected or fallback
    if selected is None:
        return None

    item, selected_query = selected
    artwork = session.scalar(select(Artwork).where(
        Artwork.provider == item["provider"], Artwork.provider_id == item["provider_id"]
    ))
    if artwork is None:
        artwork = Artwork(provider=item["provider"], provider_id=item["provider_id"])
        session.add(artwork)
    artwork.title = item["title"][:500]
    artwork.artist_display = item["artist_display"][:1000]
    artwork.date_display = item["date_display"][:255]
    artwork.medium_display = item["medium_display"][:1000]
    artwork.place_of_origin = item["place_of_origin"][:500]
    artwork.image_url = item["image_url"][:2048]
    artwork.source_url = item["source_url"][:2048]
    artwork.attribution = item["attribution"][:500]
    artwork.license_label = item["license_label"][:120]
    artwork.context = item["context"][:1000] or None
    artwork.search_query = selected_query[:240]
    artwork.curation_reason = (
        f"Als visueller Seitenblick zur Bildidee „{selected_query}“ ausgewählt. "
        f"Werkdaten und Rechteangabe stammen direkt aus der Sammlung von {museum_name(item['provider'])}."
    )[:1000]
    session.flush()
    state = session.scalar(select(UserArtwork).where(
        UserArtwork.user_id == user.id, UserArtwork.artwork_id == artwork.id
    ))
    if state is None:
        session.add(UserArtwork(user_id=user.id, artwork_id=artwork.id, discovered_at=datetime.now(UTC)))
    settings.featured_artwork_id = artwork.id
    return artwork
