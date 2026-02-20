"""Track matching for import operations.

Matches track references to local library tracks using ISRC, MusicBrainz ID,
exact match, and fuzzy matching strategies.
"""

import logging
from datetime import datetime
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Track
from app.services.external_track_matcher import normalize_for_matching

logger = logging.getLogger(__name__)


class TrackMatcher:
    """Matches track references to local library tracks.

    Used during import to find local tracks that correspond to exported
    track references based on ISRC, MusicBrainz ID, or fuzzy matching.
    """

    # Fuzzy matching threshold (0-100)
    FUZZY_THRESHOLD = 85

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._track_cache: dict[str, Track] | None = None

    async def _get_all_tracks(self) -> list[Track]:
        """Get all tracks from database (cached for batch matching)."""
        result = await self.db.execute(
            select(Track).where(
                Track.title.isnot(None),
                Track.artist.isnot(None),
            )
        )
        return list(result.scalars().all())

    async def _build_track_cache(self) -> None:
        """Build lookup caches for fast matching."""
        if self._track_cache is not None:
            return

        tracks = await self._get_all_tracks()
        self._track_cache = {}

        for track in tracks:
            # Index by ISRC
            if track.isrc:
                self._track_cache[f"isrc:{track.isrc}"] = track

            # Index by MusicBrainz ID
            if track.musicbrainz_track_id:
                self._track_cache[f"mbid:{track.musicbrainz_track_id}"] = track

            # Index by exact title+artist (lowercase)
            if track.title and track.artist:
                key = f"exact:{track.title.lower().strip()}:{track.artist.lower().strip()}"
                self._track_cache[key] = track

    async def match_track_ref(
        self,
        track_ref: dict[str, Any],
    ) -> tuple[Track | None, str | None, float | None]:
        """Match a track reference to a local track.

        Args:
            track_ref: Track reference dict with isrc, musicbrainz_id, title, artist, album, duration_seconds

        Returns:
            Tuple of (matched_track, match_method, confidence)
        """
        await self._build_track_cache()
        assert self._track_cache is not None

        isrc = track_ref.get("isrc")
        musicbrainz_id = track_ref.get("musicbrainz_id")
        title = track_ref.get("title", "")
        artist = track_ref.get("artist", "")
        album = track_ref.get("album")
        duration = track_ref.get("duration_seconds")

        # 1. Try ISRC match (most reliable)
        if isrc:
            track = self._track_cache.get(f"isrc:{isrc}")
            if track:
                return track, "isrc", 1.0

        # 2. Try MusicBrainz ID match
        if musicbrainz_id:
            track = self._track_cache.get(f"mbid:{musicbrainz_id}")
            if track:
                return track, "musicbrainz", 1.0

        # 3. Try exact title + artist match
        if title and artist:
            key = f"exact:{title.lower().strip()}:{artist.lower().strip()}"
            track = self._track_cache.get(key)
            if track:
                return track, "exact", 1.0

        # 4. Try fuzzy matching
        if title and artist:
            return await self._fuzzy_match(title, artist, album, duration)

        return None, None, None

    async def _fuzzy_match(
        self,
        title: str,
        artist: str,
        album: str | None,
        duration: float | None,
    ) -> tuple[Track | None, str | None, float | None]:
        """Fuzzy match against all tracks."""
        normalized_title = normalize_for_matching(title)
        normalized_artist = normalize_for_matching(artist)

        tracks = await self._get_all_tracks()
        best_match: Track | None = None
        best_score: float = 0.0

        for track in tracks:
            if not track.title or not track.artist:
                continue

            local_title = normalize_for_matching(track.title)
            local_artist = normalize_for_matching(track.artist)

            # Calculate fuzzy scores
            title_score = fuzz.ratio(normalized_title, local_title)
            artist_score = fuzz.ratio(normalized_artist, local_artist)

            # Combined score with weights (title matters more)
            combined = (title_score * 0.6) + (artist_score * 0.4)

            # Duration disambiguation: boost score if durations match closely
            if duration and track.duration_seconds:
                duration_diff = abs(duration - track.duration_seconds)
                if duration_diff < 3:  # Within 3 seconds
                    combined = min(100, combined + 5)
                elif duration_diff > 30:  # Very different duration
                    combined = combined * 0.9

            if combined >= self.FUZZY_THRESHOLD and combined > best_score:
                best_score = combined
                best_match = track

        if best_match:
            return best_match, "fuzzy", best_score / 100.0

        return None, None, None

    async def match_batch(
        self,
        track_refs: list[dict[str, Any]],
    ) -> list[tuple[dict[str, Any], Track | None, str | None, float | None]]:
        """Match a batch of track references.

        Returns list of (track_ref, matched_track, method, confidence) tuples.
        """
        await self._build_track_cache()

        results = []
        for ref in track_refs:
            track, method, confidence = await self.match_track_ref(ref)
            results.append((ref, track, method, confidence))

        return results


# In-memory session storage (in production, use Redis)

class ImportPreviewSession:
    """Stores preview results for an import session."""

    def __init__(
        self,
        session_id: str,
        import_data: dict[str, Any],
        matching_results: dict[str, Any],
        summary: dict[str, Any],
        warnings: list[str],
    ) -> None:
        self.session_id = session_id
        self.import_data = import_data
        self.matching_results = matching_results
        self.summary = summary
        self.warnings = warnings
        self.created_at = datetime.utcnow()


class LibraryImportPreviewSession:
    """Stores preview results for a library import session."""

    def __init__(
        self,
        session_id: str,
        import_data: dict[str, Any],
        matching_results: dict[str, Any],
        summary: dict[str, Any],
        warnings: list[str],
    ) -> None:
        self.session_id = session_id
        self.import_data = import_data
        self.matching_results = matching_results
        self.summary = summary
        self.warnings = warnings
        self.created_at = datetime.utcnow()


class BackupPreviewSession:
    """Stores preview results for a backup import session."""

    def __init__(
        self,
        session_id: str,
        import_data: dict[str, Any],
        profile_matching_results: dict[str, Any] | None,
        library_matching_results: dict[str, Any] | None,
        summary: dict[str, Any],
        warnings: list[str],
    ) -> None:
        self.session_id = session_id
        self.import_data = import_data
        self.profile_matching_results = profile_matching_results
        self.library_matching_results = library_matching_results
        self.summary = summary
        self.warnings = warnings
        self.created_at = datetime.utcnow()


# Module-level session dicts shared across modules
_import_sessions: dict[str, ImportPreviewSession] = {}
_library_import_sessions: dict[str, LibraryImportPreviewSession] = {}
_backup_import_sessions: dict[str, BackupPreviewSession] = {}
