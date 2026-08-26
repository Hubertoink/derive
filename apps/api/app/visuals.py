"""Licensed, attributed hero-image selection for successful discovery runs."""

from __future__ import annotations

import os
import random
from typing import Any

import httpx

from .feeds import plain_text
from .models import AppSettings, Article
from .secrets import decrypt_secret


PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"


def _pexels_api_key(settings: AppSettings | None = None) -> str:
    stored = decrypt_secret(settings.pexels_api_key_encrypted) if settings else None
    return (stored or os.getenv("PEXELS_API_KEY", "")).strip()


def _search_query(candidates: list[dict[str, Any]]) -> str:
    """Make a restrained editorial query without another model request."""
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        visual_query = plain_text(str(candidate.get("visual_query") or "")).strip()
        if visual_query:
            return visual_query[:120]
        topics = candidate.get("topics")
        if isinstance(topics, list):
            topic_query = " ".join(plain_text(str(topic)) for topic in topics[:3]).strip()
            if topic_query:
                return topic_query[:120]
        title = plain_text(str(candidate.get("title") or "")).strip()
        if title:
            return title[:120]
    return "quiet editorial landscape"


async def refresh_hero_visual(settings: AppSettings, candidates: list[dict[str, Any]]) -> bool:
    """Select one Pexels landscape image and retain its full attribution locally.

    The feature is opt-in through the user's encrypted key or PEXELS_API_KEY. A provider failure must never make an
    otherwise successful article-discovery run fail.
    """
    api_key = _pexels_api_key(settings)
    if not api_key:
        return False

    try:
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            response = await client.get(
                PEXELS_SEARCH_URL,
                headers={"Authorization": api_key},
                params={
                    "query": _search_query(candidates),
                    "orientation": "landscape",
                    "size": "large",
                    "locale": "de-DE",
                    "per_page": 9,
                },
            )
            response.raise_for_status()
            photos = response.json().get("photos", [])
    except (httpx.HTTPError, TypeError, ValueError, AttributeError, KeyError):
        return False

    if not isinstance(photos, list):
        return False
    usable = [
        photo for photo in photos
        if isinstance(photo, dict)
        and isinstance(photo.get("id"), int)
        and isinstance(photo.get("url"), str)
        and isinstance(photo.get("src"), dict)
        and isinstance(photo["src"].get("landscape"), str)
    ]
    if not usable:
        return False
    alternatives = [photo for photo in usable if photo["id"] != settings.hero_image_id] or usable
    photo = random.choice(alternatives)
    photographer = plain_text(str(photo.get("photographer") or "Unbekannt"))[:180]
    alt = plain_text(str(photo.get("alt") or "Kuratiertes Titelbild"))[:500]

    settings.hero_image_id = photo["id"]
    settings.hero_image_url = photo["src"]["landscape"]
    settings.hero_image_source_url = photo["url"]
    settings.hero_image_credit = f"Foto: {photographer} / Pexels"
    settings.hero_image_alt = alt or "Kuratiertes Titelbild von Pexels"
    return True


async def assign_article_visual(article: Article, settings: AppSettings | None = None) -> bool:
    """Give a saved article one attributed Pexels image without changing its content."""
    api_key = _pexels_api_key(settings)
    if not api_key or article.image_url:
        return False
    query = plain_text(article.image_query or "").strip()
    if not query:
        query = " ".join(part for part in [article.topics_csv.replace(",", " "), article.title] if part).strip()
    query = query[:120]
    try:
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            response = await client.get(
                PEXELS_SEARCH_URL,
                headers={"Authorization": api_key},
                params={
                    "query": query or "quiet editorial landscape",
                    "orientation": "landscape",
                    "size": "large",
                    "locale": "de-DE",
                    "per_page": 1,
                },
            )
            response.raise_for_status()
            photos = response.json().get("photos", [])
    except (httpx.HTTPError, TypeError, ValueError, AttributeError, KeyError):
        return False
    if not isinstance(photos, list) or not photos or not isinstance(photos[0], dict):
        return False
    photo = photos[0]
    source = photo.get("src")
    if not isinstance(source, dict) or not isinstance(source.get("landscape"), str) or not isinstance(photo.get("url"), str):
        return False
    photographer = plain_text(str(photo.get("photographer") or "Unbekannt"))[:180]
    article.image_url = source["landscape"]
    article.image_source_url = photo["url"]
    article.image_credit = f"Foto: {photographer} / Pexels"
    return True
