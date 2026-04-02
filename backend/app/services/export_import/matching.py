"""Track matching for import operations.

Matches track references to local library tracks using ISRC, MusicBrainz ID,
exact match, and fuzzy matching strategies.
"""

import logging
import re
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Track
from app.utils.time import utcnow


def normalize_for_matching(s: str) -> str:
    """Normalize string for matching comparisons."""
    s = re.sub(
        r'\s*[\(\[](feat\.?|ft\.?|featuring)[^\)\]]*[\)\]]',
        '',
        s,
        flags=re.IGNORECASE
    )
    s = re.sub(
        r'\s*[\(\[][^\)\]]*(?:remaster(?:ed)?|remix|version|edit|deluxe|bonus)[^\)\]]*[\)\]]',
        '',
        s,
        flags=re.IGNORECASE
    )
    s = re.sub(
        r'\s+-\s+(?:\d{4}\s+)?(?:remaster(?:ed)?|remix|version|edit|deluxe|bonus|radio\s+edit)\b.*$',
        '',
        s,
        flags=re.IGNORECASE
    )
    s = s.replace("\u2018", "'").replace("\u2019", "'").replace("`", "'")
    # Normalize Unicode whitespace (NBSP, figure space, narrow NBSP, word joiner)
    s = re.sub(r'[\u00A0\u2007\u202F\u2060]', ' ', s)
    s = ' '.join(s.split())
    return s.strip().lower()

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
        self._all_tracks: list[Track] | None = None
        self._artist_index: dict[str, list[tuple[Track, str, str]]] | None = None
        self._artist_keys: list[str] | None = None

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
        self._all_tracks = tracks
        self._track_cache = {}

        artist_idx: dict[str, list[tuple[Track, str, str]]] = defaultdict(list)

        for track in tracks:
            # Index by ISRC
            if track.isrc:
                self._track_cache[f"isrc:{track.isrc}"] = track

            # Index by MusicBrainz ID
            if track.musicbrainz_track_id:
                self._track_cache[f"mbid:{track.musicbrainz_track_id}"] = track

            # Pre-compute normalized strings for exact + fuzzy matching
            if track.title and track.artist:
                norm_title = normalize_for_matching(track.title)
                norm_artist = normalize_for_matching(track.artist)
                self._track_cache[f"exact:{norm_title}:{norm_artist}"] = track
                artist_idx[norm_artist].append((track, norm_title, norm_artist))

        self._artist_index = dict(artist_idx)
        self._artist_keys = list(artist_idx.keys())

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

        # 3. Try exact title + artist match (with normalization)
        if title and artist:
            key = f"exact:{normalize_for_matching(title)}:{normalize_for_matching(artist)}"
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
        """Fuzzy match against all tracks using artist pre-filtering."""
        assert self._artist_keys is not None and self._artist_index is not None

        normalized_title = normalize_for_matching(title)
        normalized_artist = normalize_for_matching(artist)

        # Phase 1: Find candidate artists (cutoff=50 is safe:
        # max title 100*0.6=60 + artist 50*0.4=20 + duration boost 5 = 85)
        artist_matches = process.extract(
            normalized_artist,
            self._artist_keys,
            scorer=fuzz.ratio,
            score_cutoff=50,
            limit=None,
        )

        # Phase 2: Score only tracks from matching artists
        best_match: Track | None = None
        best_score: float = 0.0

        for matched_artist, artist_score, _idx in artist_matches:
            for track, local_title, _local_artist in self._artist_index[matched_artist]:
                title_score = fuzz.ratio(normalized_title, local_title)
                combined = (title_score * 0.6) + (artist_score * 0.4)

                if duration and track.duration_seconds:
                    duration_diff = abs(duration - track.duration_seconds)
                    if duration_diff < 3:
                        combined = min(100, combined + 5)
                    elif duration_diff > 30:
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
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[tuple[dict[str, Any], Track | None, str | None, float | None]]:
        """Match a batch of track references.

        Returns list of (track_ref, matched_track, method, confidence) tuples.
        Calls on_progress(processed, total) every 25 tracks if provided.
        """
        await self._build_track_cache()

        results = []
        total = len(track_refs)
        for i, ref in enumerate(track_refs):
            track, method, confidence = await self.match_track_ref(ref)
            results.append((ref, track, method, confidence))
            if on_progress and (i + 1) % 25 == 0:
                on_progress(i + 1, total)
        if on_progress and total > 0:
            on_progress(total, total)

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
        self.created_at = utcnow()


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
        self.created_at = utcnow()


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
        self.created_at = utcnow()


# Module-level session dicts shared across modules
_import_sessions: dict[str, ImportPreviewSession] = {}
_library_import_sessions: dict[str, LibraryImportPreviewSession] = {}
_backup_import_sessions: dict[str, BackupPreviewSession] = {}
