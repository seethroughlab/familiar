"""Compatibility wrapper for spotipy after Spotify API breaking changes.

Spotify made breaking changes in Nov 2024 and Feb 2026:
- playlist_tracks() renamed to playlist_items(), response uses 'item' instead of 'track'
- preview_url, popularity, and ISRC removed from most endpoints for new/dev apps

This wrapper delegates working calls to spotipy and replaces broken ones
with direct httpx calls to the new endpoints.

It also enforces centralized rate limiting (1 req/sec) across all Spotify API
calls to avoid 429 responses and escalating rate-limit penalties.
"""

import logging
import time
from typing import Any

import httpx
import spotipy

logger = logging.getLogger(__name__)

# Minimum seconds between Spotify API requests.
# These are background operations so speed doesn't matter — safety does.
_MIN_REQUEST_INTERVAL = 1.0


class SpotifyRateLimitError(Exception):
    """Raised when Spotify returns persistent 429 rate limiting.

    Callers should stop making requests and let the rate limit expire.
    """

    def __init__(self, retry_after: int | None = None, message: str = "Spotify rate limit exceeded"):
        self.retry_after = retry_after
        super().__init__(f"{message} (retry_after={retry_after}s)" if retry_after else message)


class SpotifyCompat:
    """Wraps spotipy.Spotify to handle broken/renamed endpoints."""

    def __init__(self, client: spotipy.Spotify, token: str) -> None:
        self._client = client
        self._token = token
        self._last_request_time: float = 0.0

    def _throttle(self) -> None:
        """Enforce minimum delay between Spotify API requests."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < _MIN_REQUEST_INTERVAL:
            sleep_time = _MIN_REQUEST_INTERVAL - elapsed
            logger.debug(f"Spotify throttle: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)
        self._last_request_time = time.monotonic()

    def __getattr__(self, name: str) -> Any:
        """Delegate all unhandled attributes to the underlying spotipy client.

        Callable attributes (API methods) are wrapped with throttling.
        """
        attr = getattr(self._client, name)
        if callable(attr):
            def throttled_call(*args: Any, **kwargs: Any) -> Any:
                self._throttle()
                return attr(*args, **kwargs)
            return throttled_call
        return attr

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
        Includes retry logic for 429 rate limiting.
        """
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/items"
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if fields:
            params["fields"] = fields
        if market:
            params["market"] = market

        headers = {"Authorization": f"Bearer {self._token}"}

        max_retries = 5
        for attempt in range(max_retries):
            self._throttle()
            try:
                response = httpx.get(url, params=params, headers=headers, timeout=30)
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "5"))
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"Spotify 429 on playlist_items (attempt {attempt + 1}/{max_retries}), "
                            f"waiting {retry_after}s"
                        )
                        time.sleep(retry_after)
                        continue
                    else:
                        raise SpotifyRateLimitError(retry_after=retry_after)
                response.raise_for_status()
                data = response.json()
                return self._normalize_playlist_response(data)
            except httpx.HTTPStatusError as e:
                logger.error(f"Spotify API error for playlist_items: {e.response.status_code}")
                raise
            except httpx.RequestError as e:
                logger.error(f"Request error for playlist_items: {e}")
                raise

        # Should not reach here, but just in case
        raise SpotifyRateLimitError(message="Spotify rate limit: max retries exhausted")

    def current_user_playlists(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Delegate to spotipy but normalize playlist track counts.

        The API renamed 'tracks' to 'items' in playlist objects.
        """
        self._throttle()
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
