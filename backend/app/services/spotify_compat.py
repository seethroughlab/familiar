"""Compatibility wrapper for spotipy after Spotify API breaking changes.

Spotify made breaking changes in Nov 2024 and Feb 2026:
- playlist_tracks() renamed to playlist_items(), response uses 'item' instead of 'track'
- preview_url, popularity, and ISRC removed from most endpoints for new/dev apps

This wrapper delegates working calls to spotipy and replaces broken ones
with direct httpx calls to the new endpoints.
"""

import logging
from typing import Any

import httpx
import spotipy

logger = logging.getLogger(__name__)


class SpotifyCompat:
    """Wraps spotipy.Spotify to handle broken/renamed endpoints."""

    def __init__(self, client: spotipy.Spotify, token: str) -> None:
        self._client = client
        self._token = token

    def __getattr__(self, name: str) -> Any:
        """Delegate all unhandled attributes to the underlying spotipy client."""
        return getattr(self._client, name)

    def playlist_items(
        self,
        playlist_id: str,
        limit: int = 100,
        offset: int = 0,
        fields: str | None = None,
        market: str | None = None,
    ) -> dict[str, Any]:
        """Replacement for playlist_tracks() using the new /items endpoint.

        The response uses 'item' instead of 'track' in each entry.
        We normalize it back to 'track' so downstream code doesn't change.
        """
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/items"
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if fields:
            params["fields"] = fields
        if market:
            params["market"] = market

        headers = {"Authorization": f"Bearer {self._token}"}

        try:
            response = httpx.get(url, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Spotify API error for playlist_items: {e.response.status_code}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error for playlist_items: {e}")
            raise

        # Normalize: map 'item' -> 'track' in each entry
        return self._normalize_playlist_response(data)

    def current_user_playlists(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Delegate to spotipy but normalize playlist track counts.

        The API renamed 'tracks' to 'items' in playlist objects.
        """
        result = self._client.current_user_playlists(limit=limit, offset=offset)

        # Normalize: ensure each playlist has 'tracks' field with total
        for playlist in result.get("items", []):
            if "items" in playlist and "tracks" not in playlist:
                playlist["tracks"] = playlist.pop("items")

        return result

    def _normalize_playlist_response(self, data: dict[str, Any]) -> dict[str, Any]:
        """Normalize playlist items response to match old playlist_tracks format.

        Maps 'item' -> 'track' in each entry and sets safe defaults for removed fields.
        """
        for entry in data.get("items", []):
            # Map 'item' -> 'track' if needed
            if "item" in entry and "track" not in entry:
                entry["track"] = entry.pop("item")

            track = entry.get("track")
            if track:
                self._set_safe_defaults(track)

        return data

    @staticmethod
    def _set_safe_defaults(track: dict[str, Any]) -> None:
        """Set safe defaults for fields removed from the Spotify API.

        Prevents KeyError / None crashes in downstream code that calls .get().
        """
        track.setdefault("preview_url", None)
        track.setdefault("popularity", None)
        if "external_ids" not in track:
            track["external_ids"] = {}
