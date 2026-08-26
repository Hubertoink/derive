"""Server-side Spotify catalog search without user OAuth.

Spotify results are deliberately kept out of all model prompts. The AI may
provide the user's search phrase, but returned Spotify metadata is only mapped
and displayed by dérive itself.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from .models import AppSettings
from .secrets import decrypt_secret

logger = logging.getLogger(__name__)

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_SEARCH_URL = "https://api.spotify.com/v1/search"
_token_cache: dict[str, tuple[str, datetime]] = {}


class SpotifyError(Exception):
    """A Spotify request could not be completed."""


def spotify_is_configured(settings: AppSettings) -> bool:
    return bool(
        decrypt_secret(settings.spotify_client_id_encrypted)
        and decrypt_secret(settings.spotify_client_secret_encrypted)
    )


def _credentials(settings: AppSettings) -> tuple[str, str] | None:
    client_id = decrypt_secret(settings.spotify_client_id_encrypted)
    client_secret = decrypt_secret(settings.spotify_client_secret_encrypted)
    if not client_id or not client_secret:
        return None
    return client_id, client_secret


async def _access_token(client_id: str, client_secret: str) -> str:
    cache_key = hashlib.sha256(f"{client_id}\0{client_secret}".encode()).hexdigest()
    cached = _token_cache.get(cache_key)
    if cached and cached[1] > datetime.now(UTC):
        return cached[0]
    try:
        async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
            response = await client.post(
                SPOTIFY_TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(client_id, client_secret),
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise SpotifyError(f"Spotify-Verbindung fehlgeschlagen: {str(error)[:260]}") from error
    token = str(payload.get("access_token", "")).strip()
    if not token:
        raise SpotifyError("Spotify hat keinen Zugriffstoken zurückgegeben.")
    try:
        expires_in = max(60, int(payload.get("expires_in", 3600)))
    except (TypeError, ValueError):
        expires_in = 3600
    _token_cache[cache_key] = (token, datetime.now(UTC) + timedelta(seconds=expires_in - 30))
    return token


async def test_spotify_connection(client_id: str, client_secret: str) -> dict[str, bool | str]:
    await _access_token(client_id.strip(), client_secret.strip())
    return {"connected": True, "message": "Spotify-Katalog ist verbunden."}


def _profile_query(settings: AppSettings, prompt_override: str | None) -> str:
    prompt = (prompt_override or settings.discovery_prompt or "").strip()
    interests = [part.strip() for part in settings.interests_csv.split(",") if part.strip()]
    parts = [prompt[:280], *interests[:3]]
    return " ".join(part for part in parts if part)[:420] or "longform podcast"


def episode_candidate(
    episode: dict[str, Any], *, query: str, interests: list[str]
) -> dict[str, Any] | None:
    external_url = str((episode.get("external_urls") or {}).get("spotify", "")).strip()
    show = episode.get("show") if isinstance(episode.get("show"), dict) else {}
    title = str(episode.get("name", "")).strip()
    show_name = str(show.get("name", "")).strip()
    if not external_url.startswith("https://open.spotify.com/episode/") or not title or not show_name:
        return None
    try:
        duration_minutes = max(0, min(1440, round(int(episode.get("duration_ms", 0)) / 60000)))
    except (TypeError, ValueError):
        duration_minutes = 0
    return {
        "title": title,
        "show_name": show_name,
        "url": external_url,
        "spotify_url": external_url,
        "published_at": str(episode.get("release_date", "")),
        "duration_minutes": duration_minutes,
        "topics": interests[:3],
        "reason": f"Im Spotify-Katalog für „{query[:120]}“ gefunden.",
        "summary": str(episode.get("description", "")).strip()[:1200],
    }


async def search_spotify_episodes(
    settings: AppSettings, prompt_override: str | None, limit: int
) -> list[dict[str, Any]]:
    credentials = _credentials(settings)
    if not credentials:
        return []
    client_id, client_secret = credentials
    token = await _access_token(client_id, client_secret)
    query = _profile_query(settings, prompt_override)
    interests = [part.strip() for part in settings.interests_csv.split(",") if part.strip()]
    try:
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            response = await client.get(
                SPOTIFY_SEARCH_URL,
                headers={"Authorization": f"Bearer {token}"},
                params={"q": query, "type": "episode", "market": "DE", "limit": max(1, min(limit, 10))},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise SpotifyError(f"Spotify-Podcastsuche fehlgeschlagen: {str(error)[:260]}") from error
    episodes = (payload.get("episodes") or {}).get("items", []) if isinstance(payload, dict) else []
    candidates = [
        candidate
        for episode in episodes if isinstance(episode, dict)
        for candidate in [episode_candidate(episode, query=query, interests=interests)]
        if candidate is not None
    ]
    return candidates[:limit]
