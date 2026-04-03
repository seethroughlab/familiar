"""Tool executor for LLM service."""

import logging
import random
import re
from typing import Any
from uuid import UUID

import anthropic
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Track
from app.services.app_settings import get_app_settings_service

from .models import get_anthropic_model
from .handlers import (
    AnalysisHandlersMixin,
    DiscoveryHandlersMixin,
    LibraryInfoHandlersMixin,
    MetadataHandlersMixin,
    PlaybackHandlersMixin,
    PlaylistHandlersMixin,
    SearchHandlersMixin,
)

# Timeout for LLM calls (shorter for playlist name generation)
_PLAYLIST_NAME_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)

logger = logging.getLogger(__name__)


class ToolExecutor(
    SearchHandlersMixin,
    LibraryInfoHandlersMixin,
    PlaybackHandlersMixin,
    AnalysisHandlersMixin,
    DiscoveryHandlersMixin,
    MetadataHandlersMixin,
    PlaylistHandlersMixin,
):
    """Executes tools called by the LLM."""

    def __init__(
        self,
        db: AsyncSession,
        profile_id: UUID | None = None,
        user_message: str = "",
        visible_track_ids: list[str] | None = None,
    ) -> None:
        self.db = db
        self.profile_id = profile_id
        self.user_message = user_message
        self.visible_track_ids = visible_track_ids or []
        self._queued_tracks: list[dict[str, Any]] = []
        self._clear_queue: bool = True  # Default to clearing queue for new requests
        self._playback_action: str | None = None
        self._auto_saved_playlist: dict[str, Any] | None = None

    async def execute(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool and return the result."""
        logger.info(f"Executing tool: {tool_name}")
        handlers = {
            "search_library": self._search_library,
            "find_similar_tracks": self._find_similar_tracks,
            "semantic_search": self._semantic_search,
            "filter_tracks": self._filter_tracks,
            "filter_tracks_by_features": self._filter_tracks,  # backwards compat alias
            "get_library_stats": self._get_library_stats,
            "get_library_genres": self._get_library_genres,
            "get_feature_distribution": self._get_feature_distribution,
            "get_available_mood_tags": self._get_available_mood_tags,
            "queue_tracks": self._queue_tracks,
            "control_playback": self._control_playback,
            "get_track_details": self._get_track_details,
            "search_bandcamp": self._search_bandcamp,
            "recommend_bandcamp_purchases": self._recommend_bandcamp_purchases,
            "select_diverse_tracks": self._select_diverse_tracks,
            # Metadata correction tools
            "lookup_correct_metadata": self._lookup_correct_metadata,
            "propose_metadata_change": self._propose_metadata_change,
            "get_album_tracks": self._get_album_tracks,
            "mark_album_as_compilation": self._mark_album_as_compilation,
            "propose_album_artwork": self._propose_album_artwork,
            # Duplicate detection tools
            "find_duplicate_artists": self._find_duplicate_artists,
            "merge_duplicate_artists": self._merge_duplicate_artists,
            # View context tools
            "get_visible_tracks": self._get_visible_tracks,
            # Discovery tools
            "get_similar_artists_in_library": self._get_similar_artists_in_library,
            "get_new_releases": self._get_new_releases,
            "get_discovery_recommendations": self._get_discovery_recommendations,
            "get_spotify_unmatched": self._get_spotify_unmatched,
            # Web page reading tools
            "fetch_webpage": self._fetch_webpage,
            "create_playlist_from_items": self._create_playlist_from_items,
            # Track identification tools
            "identify_track": self._identify_track,
            # Analysis tools
            "get_track_analysis": self._get_track_analysis,
        }

        handler = handlers.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            # Handle methods that take no args vs those that do
            if tool_name in ("get_library_stats", "get_visible_tracks"):
                return await handler()  # type: ignore[operator]
            return await handler(**tool_input)  # type: ignore[operator]
        except Exception as e:
            logger.exception(f"Tool {tool_name} failed")
            try:
                await self.db.rollback()
            except Exception:
                pass
            error_detail = str(e)[:200] if str(e) else "no details"
            return {"error": f"Tool '{tool_name}' failed ({type(e).__name__}): {error_detail}"}

    def get_queued_tracks(self) -> tuple[list[dict[str, Any]], bool]:
        """Get tracks that were queued during this conversation turn.

        Returns (tracks, should_clear_queue).
        """
        return self._queued_tracks, self._clear_queue

    def get_playback_action(self) -> str | None:
        """Get playback action requested during this conversation turn."""
        return self._playback_action

    def get_auto_saved_playlist(self) -> dict[str, Any] | None:
        """Get the auto-saved playlist created during this conversation turn."""
        return self._auto_saved_playlist

    # --- Shared helper methods (used by multiple handler groups) ---

    def _safe_parse_uuids(self, ids: list[str]) -> list[UUID]:
        """Parse a list of string IDs to UUIDs, skipping invalid ones."""
        valid = []
        for id_str in ids:
            try:
                valid.append(UUID(id_str))
            except (ValueError, AttributeError):
                logger.warning(f"Skipping invalid UUID: {id_str!r}")
        return valid

    async def _generate_playlist_name_llm(self, tracks: list[dict[str, Any]]) -> str:
        """Generate a creative playlist name using the LLM."""
        from datetime import datetime

        logger.info(f"Generating playlist name for {len(tracks)} tracks, user_message='{self.user_message}'")

        if not tracks:
            return f"AI Playlist - {datetime.now().strftime('%b %d %H:%M')}"

        artists = list(set(t.get("artist", "") for t in tracks[:10] if t.get("artist")))
        genres = list(set(t.get("genre", "") for t in tracks[:10] if t.get("genre")))

        prompt = f"""Generate a short, creative playlist name (2-5 words max).

User's request: "{self.user_message or 'curated selection'}"
Artists included: {', '.join(artists[:5]) or 'Various'}
Genres: {', '.join(genres[:3]) or 'Mixed'}
Track count: {len(tracks)}

Rules:
- Be creative and evocative, not literal
- Don't just repeat the user's words
- Avoid generic names like "Chill Vibes" or "Good Music"
- No quotes, colons, or special characters
- Examples of good names: "Midnight Drive", "Sunday Morning Coffee", "Electric Dreams"

Respond with ONLY the playlist name, nothing else."""

        try:
            api_key = get_app_settings_service().get_effective("anthropic_api_key")
            if not api_key:
                raise ValueError("No API key")

            anthropic_client = anthropic.Anthropic(api_key=api_key, timeout=_PLAYLIST_NAME_TIMEOUT)
            message = anthropic_client.messages.create(
                model=get_anthropic_model("utility"),
                max_tokens=50,
                messages=[{"role": "user", "content": prompt}],
            )
            name = ""
            if message.content:
                first_block = message.content[0]
                if hasattr(first_block, "text"):
                    name = first_block.text.strip()

            name = name.strip('"\'').strip()
            logger.info(f"LLM generated playlist name: '{name}'")
            if name and len(name) <= 50 and not any(c in name for c in [":", "\n", '"']):
                return name
            else:
                logger.warning(f"Generated name rejected (empty, too long, or invalid chars): '{name}'")

        except Exception as e:
            logger.warning(f"LLM playlist name generation failed: {e}")

        return self._generate_playlist_name_fallback()

    def _generate_playlist_name_fallback(self) -> str:
        """Fallback playlist name from user message or timestamp."""
        from datetime import datetime

        if self.user_message:
            name = self.user_message[:50].strip()
            if len(self.user_message) > 50:
                name += "..."
            return name
        return f"AI Playlist - {datetime.now().strftime('%b %d %H:%M')}"

    def _normalize_query_variations(self, query: str) -> list[str]:
        """Generate search variations to handle number padding, etc."""
        variations = [query]

        padded = re.sub(r"(\s)(\d)(\s|$)", r"\g<1>0\2\3", query)
        if padded != query:
            variations.append(padded)

        unpadded = re.sub(r"(\s)0(\d)(\s|$)", r"\g<1>\2\3", query)
        if unpadded != query:
            variations.append(unpadded)

        return variations

    def _apply_diversity(
        self,
        tracks: list[Track],
        max_per_artist: int = 2,
        max_per_album: int = 3,
    ) -> list[Track]:
        """Filter tracks to ensure diversity across artists and albums."""
        shuffled = list(tracks)
        random.shuffle(shuffled)

        artist_counts: dict[str, int] = {}
        album_counts: dict[str, int] = {}
        diverse: list[Track] = []

        for track in shuffled:
            artist_key = (track.artist or "").lower().strip()
            album_key = f"{artist_key}:{(track.album or '').lower().strip()}"

            artist_count = artist_counts.get(artist_key, 0)
            album_count = album_counts.get(album_key, 0)

            if artist_count >= max_per_artist or album_count >= max_per_album:
                continue

            diverse.append(track)
            artist_counts[artist_key] = artist_count + 1
            album_counts[album_key] = album_count + 1

        return diverse

    def _track_to_dict(self, track: Track) -> dict[str, Any]:
        """Convert track to dictionary."""
        return {
            "id": str(track.id),
            "title": track.title,
            "artist": track.artist,
            "album": track.album,
            "genre": track.genre,
            "duration_seconds": track.duration_seconds,
            "year": track.year,
        }
