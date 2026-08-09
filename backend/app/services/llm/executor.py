"""Tool executor for LLM service."""

import logging
import random
import re
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Track

from .handlers import (
    AnalysisHandlersMixin,
    DiscoveryHandlersMixin,
    LibraryInfoHandlersMixin,
    MetadataHandlersMixin,
    PlaybackHandlersMixin,
    PlaylistHandlersMixin,
    SearchHandlersMixin,
)

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
            "list_playlists": self._list_playlists,
            "get_playlist": self._get_playlist,
            "add_tracks_to_playlist": self._add_tracks_to_playlist,
            "set_favorite": self._set_favorite,
            "get_recently_played": self._get_recently_played,
            "get_radio_suggestions": self._get_radio_suggestions,
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

    def _playlist_name_from_request(self) -> str:
        """Derive a playlist name from the user's request by stripping filler words."""
        from datetime import datetime

        msg = self.user_message.strip()
        if not msg:
            return f"AI Playlist — {datetime.now().strftime('%b %d')}"

        # If the user put a name in quotes, use that directly
        quoted = re.search(r'"([^"]{2,40})"', msg)
        if quoted:
            return quoted.group(1).strip()

        # Strip leading filler phrases (order matters — longer patterns first)
        leading = [
            r"^please\s+(can you\s+)?",
            r"^can you\s+",
            r"^i('d| would) like\s+(you to\s+)?",
            r"^i want\s+(you to\s+)?",
            r"^(make|build|create|put together|generate|give me|get me)\s+(me\s+)?an?\s+",
            r"^(make|build|create|put together|generate|give me|get me)\s+(me\s+)?",
            r"^(play|queue|put on)\s+(me\s+|up\s+)?some\s+",
            r"^(play|queue|put on)\s+(me\s+|up\s+)?",
            r"^find\s+(me\s+)?some\s+",
            r"^find\s+(me\s+)?",
            r"^(show|suggest)\s+(me\s+)?",
        ]
        text = msg
        for pattern in leading:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()

        # Strip trailing filler
        trailing = [
            r"\s+for\s+me$",
            r"\s+please$",
            r",?\s+please$",
        ]
        for pattern in trailing:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()

        # Title-case and truncate at a word boundary
        text = text[:1].upper() + text[1:] if text else text
        if len(text) > 50:
            text = text[:47].rsplit(" ", 1)[0] + "…"

        return text or msg[:50]

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
