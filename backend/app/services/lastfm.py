"""Last.fm scrobbling service."""

import hashlib
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.app_settings import get_app_settings_service


@dataclass
class LastfmSession:
    """Last.fm session data."""
    session_key: str
    username: str


class LastfmService:
    """Service for Last.fm API integration and scrobbling."""

    API_URL = "https://ws.audioscrobbler.com/2.0/"
    AUTH_URL = "https://www.last.fm/api/auth/"

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=10.0)

    def _get_credentials(self) -> tuple[str | None, str | None]:
        """Get Last.fm credentials with proper precedence."""
        settings_service = get_app_settings_service()
        api_key = settings_service.get_effective("lastfm_api_key")
        api_secret = settings_service.get_effective("lastfm_api_secret")
        return api_key, api_secret

    def is_configured(self) -> bool:
        """Check if Last.fm API is configured."""
        api_key, api_secret = self._get_credentials()
        return bool(api_key and api_secret)

    def get_auth_url(self, callback_url: str) -> str:
        """Get the Last.fm authorization URL."""
        if not self.is_configured():
            raise ValueError("Last.fm API key not configured")

        api_key, _ = self._get_credentials()
        assert api_key is not None  # mypy narrowing
        return f"{self.AUTH_URL}?api_key={api_key}&cb={quote(callback_url, safe='')}"

    def _sign_params(self, params: dict[str, Any]) -> str:
        """Generate API signature for authenticated requests."""
        _, api_secret = self._get_credentials()
        # Sort params alphabetically and concatenate key+value
        sorted_params = sorted(params.items())
        sig_string = "".join(f"{k}{v}" for k, v in sorted_params)
        sig_string += api_secret or ""

        return hashlib.md5(sig_string.encode()).hexdigest()

    async def exchange_token(self, token: str) -> LastfmSession:
        """
        Exchange an auth token for a session key.
        Called after user authorizes via Last.fm web auth.

        Note: This does NOT persist to database - caller must save via save_session().
        """
        if not self.is_configured():
            raise ValueError("Last.fm API key not configured")

        api_key, _ = self._get_credentials()
        params = {
            "method": "auth.getSession",
            "api_key": api_key,
            "token": token,
        }
        params["api_sig"] = self._sign_params(params)
        params["format"] = "json"

        response = await self.client.get(self.API_URL, params=params)  # type: ignore[arg-type]
        response.raise_for_status()

        data: dict[str, Any] = response.json()
        if "error" in data:
            raise ValueError(f"Last.fm error: {data.get('message', 'Unknown error')}")

        session_data = data.get("session", {})
        return LastfmSession(
            session_key=session_data.get("key", ""),
            username=session_data.get("name", "")
        )

    async def save_session(
        self,
        db: AsyncSession,
        profile_id: UUID,
        session: LastfmSession,
    ) -> None:
        """Persist Last.fm session to database."""
        from app.db.models import LastfmProfile

        existing = await db.get(LastfmProfile, profile_id)
        if existing:
            existing.username = session.username
            existing.session_key = session.session_key
        else:
            db.add(LastfmProfile(
                profile_id=profile_id,
                username=session.username,
                session_key=session.session_key,
            ))
        await db.commit()

    async def get_stored_session(
        self,
        db: AsyncSession,
        profile_id: UUID,
    ) -> LastfmSession | None:
        """Get stored session for a profile from database."""
        from app.db.models import LastfmProfile

        lastfm_profile = await db.get(LastfmProfile, profile_id)
        if lastfm_profile and lastfm_profile.session_key:
            return LastfmSession(
                session_key=lastfm_profile.session_key,
                username=lastfm_profile.username or "",
            )
        return None

    async def delete_session(self, db: AsyncSession, profile_id: UUID) -> None:
        """Delete stored Last.fm session for a profile."""
        from app.db.models import LastfmProfile

        lastfm_profile = await db.get(LastfmProfile, profile_id)
        if lastfm_profile:
            await db.delete(lastfm_profile)
            await db.commit()

    async def update_now_playing(
        self,
        session_key: str,
        artist: str,
        track: str,
        album: str | None = None,
        duration: int | None = None,
    ) -> bool:
        """
        Update the "now playing" status on Last.fm.
        Called when a track starts playing.
        """
        if not self.is_configured():
            return False

        api_key, _ = self._get_credentials()
        params = {
            "method": "track.updateNowPlaying",
            "api_key": api_key,
            "sk": session_key,
            "artist": artist,
            "track": track,
        }

        if album:
            params["album"] = album
        if duration:
            params["duration"] = str(duration)

        params["api_sig"] = self._sign_params(params)
        params["format"] = "json"

        try:
            response = await self.client.post(self.API_URL, data=params)  # type: ignore[arg-type]
            data: dict[str, Any] = response.json()
            return "error" not in data
        except Exception:
            return False

    async def scrobble(
        self,
        session_key: str,
        artist: str,
        track: str,
        timestamp: int | None = None,
        album: str | None = None,
        duration: int | None = None,
    ) -> bool:
        """
        Scrobble a track to Last.fm.
        Called after at least 50% of the track has been played (or 4 minutes).
        """
        if not self.is_configured():
            return False

        if timestamp is None:
            timestamp = int(time.time())

        api_key, _ = self._get_credentials()
        params = {
            "method": "track.scrobble",
            "api_key": api_key,
            "sk": session_key,
            "artist": artist,
            "track": track,
            "timestamp": str(timestamp),
        }

        if album:
            params["album"] = album
        if duration:
            params["duration"] = str(duration)

        params["api_sig"] = self._sign_params(params)
        params["format"] = "json"

        try:
            response = await self.client.post(self.API_URL, data=params)  # type: ignore[arg-type]
            data: dict[str, Any] = response.json()
            return "error" not in data
        except Exception:
            return False

    async def get_user_info(self, session_key: str) -> dict[str, Any] | None:
        """Get user info for a session."""
        if not self.is_configured():
            return None

        api_key, _ = self._get_credentials()
        params: dict[str, Any] = {
            "method": "user.getInfo",
            "api_key": api_key,
            "sk": session_key,
        }
        params["api_sig"] = self._sign_params(params)
        params["format"] = "json"

        try:
            response = await self.client.get(self.API_URL, params=params)  # type: ignore[arg-type]
            data: dict[str, Any] = response.json()
            if "error" not in data:
                user_data: dict[str, Any] | None = data.get("user")
                return user_data
            return None
        except Exception:
            return None

    async def get_similar_artists(
        self,
        artist: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get similar artists from Last.fm.

        Returns list of artists with: name, mbid, match (0-1 similarity), url, image
        This method does not require authentication (no session key needed).
        """
        if not self.is_configured():
            return []

        api_key, _ = self._get_credentials()
        params = {
            "method": "artist.getSimilar",
            "artist": artist,
            "api_key": api_key,
            "limit": str(limit),
            "autocorrect": "1",
            "format": "json",
        }

        try:
            response = await self.client.get(self.API_URL, params=params)
            data: dict[str, Any] = response.json()
            similar_artists = data.get("similarartists", {})
            if isinstance(similar_artists, dict):
                return similar_artists.get("artist", [])
            return []
        except Exception:
            return []

    async def get_similar_tracks(
        self,
        artist: str,
        track: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get similar tracks from Last.fm.

        Returns list of tracks with: name, artist, match, url, image
        This method does not require authentication (no session key needed).
        """
        if not self.is_configured():
            return []

        api_key, _ = self._get_credentials()
        params = {
            "method": "track.getSimilar",
            "artist": artist,
            "track": track,
            "api_key": api_key,
            "limit": str(limit),
            "autocorrect": "1",
            "format": "json",
        }

        try:
            response = await self.client.get(self.API_URL, params=params)
            data: dict[str, Any] = response.json()
            similar_tracks = data.get("similartracks", {})
            if isinstance(similar_tracks, dict):
                return similar_tracks.get("track", [])
            return []
        except Exception:
            return []

    async def get_artist_info(
        self,
        artist: str,
        lang: str = "en",
    ) -> dict[str, Any] | None:
        """Get detailed artist info from Last.fm.

        Returns artist data with: name, mbid, url, image, bio, stats, similar, tags.
        This method does not require authentication (no session key needed).

        Args:
            artist: Artist name to look up
            lang: ISO 639 alpha-2 language code for biography (default: en)

        Returns:
            Artist info dict or None if not found/error
        """
        if not self.is_configured():
            return None

        api_key, _ = self._get_credentials()
        params = {
            "method": "artist.getInfo",
            "artist": artist,
            "api_key": api_key,
            "autocorrect": "1",
            "lang": lang,
            "format": "json",
        }

        try:
            response = await self.client.get(self.API_URL, params=params)
            data: dict[str, Any] = response.json()

            if "error" in data:
                return None

            return data.get("artist")
        except Exception:
            return None

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()


# Singleton instance
_lastfm_service: LastfmService | None = None


def get_lastfm_service() -> LastfmService:  # type: ignore[return]
    """Get or create the Last.fm service singleton."""
    global _lastfm_service
    if _lastfm_service is None:
        _lastfm_service = LastfmService()
    return _lastfm_service
