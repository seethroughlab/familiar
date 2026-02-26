"""External track matching service.

Matches external/missing tracks to local library tracks and vice versa.
Used for Spotify imports, LLM recommendations, and wishlist functionality.
"""

import logging
import re
from datetime import datetime
from typing import Any
from uuid import UUID

from rapidfuzz import fuzz
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExternalTrack, ExternalTrackSource, PlaylistTrack, Track

logger = logging.getLogger(__name__)


def normalize_for_matching(s: str) -> str:
    """Normalize string for matching comparisons.

    Removes common variations like featuring credits, remaster annotations,
    and normalizes punctuation/whitespace.
    """
    # Remove featuring/feat variations
    s = re.sub(
        r'\s*[\(\[](feat\.?|ft\.?|featuring)[^\)\]]*[\)\]]',
        '',
        s,
        flags=re.IGNORECASE
    )
    # Remove remaster/remix annotations in parentheses/brackets
    s = re.sub(
        r'\s*[\(\[][^\)\]]*(?:remaster(?:ed)?|remix|version|edit|deluxe|bonus)[^\)\]]*[\)\]]',
        '',
        s,
        flags=re.IGNORECASE
    )
    # Remove dash-prefixed remaster/remix/edit annotations (Spotify style)
    # e.g. "Song - 2011 Remaster", "Track - Remastered", "Song - Radio Edit"
    s = re.sub(
        r'\s+-\s+(?:\d{4}\s+)?(?:remaster(?:ed)?|remix|version|edit|deluxe|bonus|radio\s+edit)\b.*$',
        '',
        s,
        flags=re.IGNORECASE
    )
    # Normalize apostrophes
    s = s.replace("'", "'").replace("'", "'").replace("`", "'")
    # Remove extra whitespace
    s = ' '.join(s.split())
    return s.strip().lower()


class ExternalTrackMatcher:
    """Service for matching external tracks to local library and vice versa."""

    # Fuzzy matching threshold (0-100)
    FUZZY_THRESHOLD = 85

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _replace_in_playlists(self, external_track_id: UUID, local_track_id: UUID) -> int:
        """Replace external track with local track in all playlists.

        When an external track is matched to a local track, this updates all
        PlaylistTrack entries that reference the external track to instead
        reference the local track directly.

        Args:
            external_track_id: ID of the external track being replaced
            local_track_id: ID of the local track to replace with

        Returns:
            Number of playlist entries updated
        """
        result = await self.db.execute(
            select(PlaylistTrack).where(PlaylistTrack.external_track_id == external_track_id)
        )
        playlist_tracks = result.scalars().all()

        count = 0
        for pt in playlist_tracks:
            pt.external_track_id = None
            pt.track_id = local_track_id
            count += 1

        if count > 0:
            logger.info(
                f"Replaced external track {external_track_id} with local track {local_track_id} "
                f"in {count} playlist entries"
            )

        return count

    async def match_external_track(
        self,
        external_track: ExternalTrack,
        commit: bool = True,
    ) -> Track | None:
        """Try to match an external track to a local library track.

        Matching priority:
        1. ISRC (International Standard Recording Code) - most reliable
        2. Exact artist + title match
        3. Contains match (substring)
        4. Fuzzy matching with rapidfuzz (threshold 85%)

        Args:
            external_track: The external track to match
            commit: Whether to commit the match to database

        Returns:
            The matched Track or None
        """
        match, method, confidence = await self._find_match(
            title=external_track.title,
            artist=external_track.artist,
            album=external_track.album,
            isrc=external_track.isrc,
        )

        if match:
            external_track.matched_track_id = match.id
            external_track.matched_at = datetime.utcnow()
            external_track.match_method = method
            external_track.match_confidence = confidence

            # Replace external track with local track in all playlists
            await self._replace_in_playlists(external_track.id, match.id)

            if commit:
                await self.db.commit()

            logger.info(
                f"Matched external track '{external_track.title}' by {external_track.artist} "
                f"to local track {match.id} via {method} (confidence: {confidence:.2f})"
            )

        return match

    async def match_spotify_track(
        self,
        spotify_track: dict[str, Any],
    ) -> Track | None:
        """Match a Spotify track dict to local library (for import preview).

        Does not create any database records.

        Args:
            spotify_track: Spotify track data dict

        Returns:
            The matched Track or None
        """
        isrc = spotify_track.get("external_ids", {}).get("isrc")
        title = spotify_track.get("name", "")
        artists = spotify_track.get("artists", [])
        artist = artists[0]["name"] if artists else ""
        album_data = spotify_track.get("album", {})
        album = album_data.get("name") if album_data else None

        match, _, _ = await self._find_match(
            title=title,
            artist=artist,
            album=album,
            isrc=isrc,
        )

        return match

    async def match_new_local_track(
        self,
        track: Track,
        commit: bool = True,
    ) -> list[ExternalTrack]:
        """Match a newly added local track to unmatched external tracks.

        Called when a new track is added to the library. Finds and updates
        any external tracks that match this local track.

        Args:
            track: The newly added local track
            commit: Whether to commit matches to database

        Returns:
            List of external tracks that were matched
        """
        matched_external: list[ExternalTrack] = []

        # Build query for potential matches
        query = select(ExternalTrack).where(
            ExternalTrack.matched_track_id.is_(None),
        )

        # If we have ISRC, prioritize that
        if track.isrc:
            isrc_result = await self.db.execute(
                query.where(ExternalTrack.isrc == track.isrc)
            )
            isrc_matches = isrc_result.scalars().all()

            for ext in isrc_matches:
                ext.matched_track_id = track.id
                ext.matched_at = datetime.utcnow()
                ext.match_method = "isrc"
                ext.match_confidence = 1.0
                # Replace external track with local track in all playlists
                await self._replace_in_playlists(ext.id, track.id)
                matched_external.append(ext)

            if matched_external:
                if commit:
                    await self.db.commit()
                logger.info(
                    f"Matched {len(matched_external)} external tracks to new local track "
                    f"'{track.title}' via ISRC"
                )
                return matched_external

        # Try title/artist matching
        if track.title and track.artist:
            normalized_title = normalize_for_matching(track.title)
            normalized_artist = normalize_for_matching(track.artist)

            # Get candidate external tracks (with similar artist)
            result = await self.db.execute(
                query.where(
                    or_(
                        func.lower(ExternalTrack.artist).contains(normalized_artist),
                        func.lower(ExternalTrack.artist).op('%')(normalized_artist),  # trigram similarity
                    )
                ).limit(500)
            )
            candidates = result.scalars().all()

            for ext in candidates:
                ext_title = normalize_for_matching(ext.title)
                ext_artist = normalize_for_matching(ext.artist)

                # Try exact match
                if ext_title == normalized_title and ext_artist == normalized_artist:
                    ext.matched_track_id = track.id
                    ext.matched_at = datetime.utcnow()
                    ext.match_method = "exact"
                    ext.match_confidence = 1.0
                    # Replace external track with local track in all playlists
                    await self._replace_in_playlists(ext.id, track.id)
                    matched_external.append(ext)
                    continue

                # Try fuzzy match
                title_score = fuzz.ratio(ext_title, normalized_title)
                artist_score = fuzz.ratio(ext_artist, normalized_artist)
                combined = (title_score * 0.6) + (artist_score * 0.4)

                if combined >= self.FUZZY_THRESHOLD:
                    ext.matched_track_id = track.id
                    ext.matched_at = datetime.utcnow()
                    ext.match_method = "fuzzy"
                    ext.match_confidence = combined / 100.0
                    # Replace external track with local track in all playlists
                    await self._replace_in_playlists(ext.id, track.id)
                    matched_external.append(ext)

        if matched_external and commit:
            await self.db.commit()
            logger.info(
                f"Matched {len(matched_external)} external tracks to new local track "
                f"'{track.title}' by {track.artist}"
            )

        return matched_external

    async def rematch_all_unmatched(self) -> dict[str, int]:
        """Re-run matching for all unmatched external tracks.

        Used as a background job after bulk imports or library changes.

        Returns:
            Stats dict with counts
        """
        stats = {"processed": 0, "matched": 0}

        # Get all unmatched external tracks
        result = await self.db.execute(
            select(ExternalTrack).where(ExternalTrack.matched_track_id.is_(None))
        )
        unmatched = result.scalars().all()

        for ext in unmatched:
            stats["processed"] += 1
            match = await self.match_external_track(ext, commit=False)
            if match:
                stats["matched"] += 1

        await self.db.commit()
        logger.info(f"Rematch completed: {stats}")
        return stats

    async def manual_match(
        self,
        external_track_id: UUID,
        track_id: UUID,
    ) -> ExternalTrack | None:
        """Manually match an external track to a local track.

        Args:
            external_track_id: ID of external track to match
            track_id: ID of local track to match to

        Returns:
            Updated ExternalTrack or None if not found
        """
        result = await self.db.execute(
            select(ExternalTrack).where(ExternalTrack.id == external_track_id)
        )
        external_track = result.scalar_one_or_none()

        if not external_track:
            return None

        # Verify track exists
        track_result = await self.db.execute(
            select(Track).where(Track.id == track_id)
        )
        track = track_result.scalar_one_or_none()

        if not track:
            raise ValueError(f"Track {track_id} not found")

        external_track.matched_track_id = track.id
        external_track.matched_at = datetime.utcnow()
        external_track.match_method = "manual"
        external_track.match_confidence = 1.0

        # Replace external track with local track in all playlists
        await self._replace_in_playlists(external_track_id, track.id)

        await self.db.commit()
        await self.db.refresh(external_track)

        logger.info(
            f"Manually matched external track '{external_track.title}' "
            f"to local track '{track.title}'"
        )

        return external_track

    async def remove_match(self, external_track_id: UUID) -> ExternalTrack | None:
        """Remove a match from an external track.

        Args:
            external_track_id: ID of external track

        Returns:
            Updated ExternalTrack or None if not found
        """
        result = await self.db.execute(
            select(ExternalTrack).where(ExternalTrack.id == external_track_id)
        )
        external_track = result.scalar_one_or_none()

        if not external_track:
            return None

        external_track.matched_track_id = None
        external_track.matched_at = None
        external_track.match_method = None
        external_track.match_confidence = None

        await self.db.commit()
        await self.db.refresh(external_track)

        return external_track

    async def replace_all_matched_in_playlists(self) -> dict[str, int]:
        """One-time migration: replace all matched external tracks in playlists.

        Finds all external tracks that have been matched to local tracks and
        replaces their references in playlists with the local track.

        Returns:
            Stats dict with external_tracks_processed and playlist_entries_replaced
        """
        result = await self.db.execute(
            select(ExternalTrack).where(ExternalTrack.matched_track_id.isnot(None))
        )
        matched_externals = result.scalars().all()

        total_replaced = 0
        for ext in matched_externals:
            count = await self._replace_in_playlists(ext.id, ext.matched_track_id)
            total_replaced += count

        await self.db.commit()

        logger.info(
            f"Migration completed: processed {len(matched_externals)} matched external tracks, "
            f"replaced {total_replaced} playlist entries"
        )

        return {
            "external_tracks_processed": len(matched_externals),
            "playlist_entries_replaced": total_replaced,
        }

    async def match_by_album(
        self,
        source_album: str,
        target_album: str,
        target_artist: str | None = None,
    ) -> dict[str, Any]:
        """Match unmatched external tracks by album name.

        Finds all unmatched external tracks from source_album and tries to
        fuzzy-match their titles against local tracks from target_album.
        Uses a lower threshold (70) since album context confirms same content.

        Args:
            source_album: Album name on external tracks
            target_album: Album name on local tracks
            target_artist: Optional artist filter for local tracks

        Returns:
            Dict with matched, failed counts and details
        """
        # Get unmatched external tracks from source album
        result = await self.db.execute(
            select(ExternalTrack).where(
                ExternalTrack.matched_track_id.is_(None),
                func.lower(ExternalTrack.album) == source_album.lower(),
            )
        )
        unmatched = result.scalars().all()

        if not unmatched:
            return {"matched": 0, "failed": 0, "details": []}

        # Get local tracks from target album
        local_query = select(Track).where(
            func.lower(Track.album) == target_album.lower(),
        )
        if target_artist:
            local_query = local_query.where(
                func.lower(Track.artist) == target_artist.lower(),
            )
        local_result = await self.db.execute(local_query)
        local_tracks = local_result.scalars().all()

        if not local_tracks:
            return {
                "matched": 0,
                "failed": len(unmatched),
                "details": [
                    {
                        "external_track_id": str(ext.id),
                        "title": ext.title,
                        "matched_track_id": None,
                        "status": "no_local_tracks",
                    }
                    for ext in unmatched
                ],
            }

        matched_count = 0
        failed_count = 0
        details: list[dict[str, Any]] = []

        for ext in unmatched:
            normalized_ext_title = normalize_for_matching(ext.title)
            best_match: Track | None = None
            best_score: float = 0.0

            for local in local_tracks:
                if not local.title:
                    continue
                local_title = normalize_for_matching(local.title)
                score = fuzz.ratio(normalized_ext_title, local_title)
                if score > best_score:
                    best_score = score
                    best_match = local

            # Lower threshold since album context confirms same content
            if best_match and best_score >= 70:
                ext.matched_track_id = best_match.id
                ext.matched_at = datetime.utcnow()
                ext.match_method = "album_batch"
                ext.match_confidence = best_score / 100.0
                await self._replace_in_playlists(ext.id, best_match.id)
                matched_count += 1
                details.append({
                    "external_track_id": str(ext.id),
                    "title": ext.title,
                    "matched_track_id": str(best_match.id),
                    "status": "matched",
                })
            else:
                failed_count += 1
                details.append({
                    "external_track_id": str(ext.id),
                    "title": ext.title,
                    "matched_track_id": None,
                    "status": "no_match",
                })

        await self.db.commit()
        logger.info(
            f"Album batch match '{source_album}' -> '{target_album}': "
            f"{matched_count} matched, {failed_count} failed"
        )

        return {
            "matched": matched_count,
            "failed": failed_count,
            "details": details,
        }

    async def _find_match(
        self,
        title: str,
        artist: str,
        album: str | None = None,
        isrc: str | None = None,
    ) -> tuple[Track | None, str | None, float | None]:
        """Find a matching local track.

        Returns:
            Tuple of (matched_track, match_method, confidence)
        """
        # 1. Try ISRC match
        if isrc:
            result = await self.db.execute(
                select(Track).where(Track.isrc == isrc)
            )
            match = result.scalar_one_or_none()
            if match:
                return match, "isrc", 1.0

        if not title or not artist:
            return None, None, None

        title_lower = title.lower().strip()
        artist_lower = artist.lower().strip()
        normalized_title = normalize_for_matching(title)
        normalized_artist = normalize_for_matching(artist)

        # 2. Try exact artist + title match (raw)
        result = await self.db.execute(
            select(Track).where(
                func.lower(Track.title) == title_lower,
                func.lower(Track.artist) == artist_lower,
            ).limit(1)
        )
        match = result.scalars().first()
        if match:
            return match, "exact", 1.0

        # 2b. Try exact match with normalized title/artist
        # Catches "Suedehead - 2011 Remaster" matching library's "Suedehead"
        if normalized_title != title_lower or normalized_artist != artist_lower:
            result = await self.db.execute(
                select(Track).where(
                    func.lower(Track.title) == normalized_title,
                    func.lower(Track.artist) == normalized_artist,
                ).limit(1)
            )
            match = result.scalars().first()
            if match:
                return match, "exact_normalized", 0.95

        # 3. Try partial match (title contains, artist contains)
        result = await self.db.execute(
            select(Track).where(
                func.lower(Track.title).contains(title_lower),
                func.lower(Track.artist).contains(artist_lower),
            ).limit(1)
        )
        match = result.scalars().first()
        if match:
            return match, "partial", 0.9

        # 4. Fuzzy match with rapidfuzz
        # Get candidate tracks - limit to reasonable set for performance
        result = await self.db.execute(
            select(Track)
            .where(Track.title.isnot(None), Track.artist.isnot(None))
            .limit(5000)
        )
        candidates = result.scalars().all()

        best_match: Track | None = None
        best_score: float = 0.0

        for track in candidates:
            if not track.title or not track.artist:
                continue

            local_title = normalize_for_matching(track.title)
            local_artist = normalize_for_matching(track.artist)

            # Calculate fuzzy scores
            title_score = fuzz.ratio(normalized_title, local_title)
            artist_score = fuzz.ratio(normalized_artist, local_artist)

            # Combined score with weights (title matters more)
            combined = (title_score * 0.6) + (artist_score * 0.4)

            if combined >= self.FUZZY_THRESHOLD and combined > best_score:
                best_score = combined
                best_match = track

        if best_match:
            return best_match, "fuzzy", best_score / 100.0

        return None, None, None

    async def find_match_candidates(
        self,
        title: str,
        artist: str,
        album: str | None = None,
        isrc: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Find candidate local tracks for manual matching.

        Uses the same matching pipeline as _find_match() but returns multiple
        candidates with a lower fuzzy threshold (50 instead of 85), since the
        user will visually confirm the match.

        Args:
            title: Track title
            artist: Artist name
            album: Album name (optional)
            isrc: ISRC code (optional)
            limit: Maximum number of candidates to return

        Returns:
            List of candidate dicts with track info, match_method, and confidence
        """
        candidates: list[dict[str, Any]] = []
        seen_ids: set = set()

        def _track_to_candidate(track: Track, method: str, confidence: float) -> dict[str, Any]:
            return {
                "track_id": str(track.id),
                "title": track.title,
                "artist": track.artist,
                "album": track.album,
                "duration_seconds": track.duration_seconds,
                "format": track.format,
                "year": track.year,
                "match_method": method,
                "confidence": round(confidence, 3),
            }

        def _add_candidate(track: Track, method: str, confidence: float) -> None:
            if track.id not in seen_ids:
                seen_ids.add(track.id)
                candidates.append(_track_to_candidate(track, method, confidence))

        # 1. ISRC match
        if isrc:
            result = await self.db.execute(
                select(Track).where(Track.isrc == isrc)
            )
            match = result.scalar_one_or_none()
            if match:
                _add_candidate(match, "isrc", 1.0)

        if not title and not artist:
            return candidates[:limit]

        title_lower = title.lower().strip() if title else ""
        artist_lower = artist.lower().strip() if artist else ""
        normalized_title = normalize_for_matching(title) if title else ""
        normalized_artist = normalize_for_matching(artist) if artist else ""

        # 2. Exact match
        if title_lower and artist_lower:
            result = await self.db.execute(
                select(Track).where(
                    func.lower(Track.title) == title_lower,
                    func.lower(Track.artist) == artist_lower,
                ).limit(1)
            )
            match = result.scalars().first()
            if match:
                _add_candidate(match, "exact", 1.0)

        # 3. Partial match (contains)
        if title_lower and artist_lower:
            result = await self.db.execute(
                select(Track).where(
                    func.lower(Track.title).contains(title_lower),
                    func.lower(Track.artist).contains(artist_lower),
                ).limit(5)
            )
            for match in result.scalars().all():
                _add_candidate(match, "partial", 0.9)

        # 4. Fuzzy match with lower threshold for manual confirmation
        CANDIDATE_THRESHOLD = 50
        result = await self.db.execute(
            select(Track)
            .where(Track.title.isnot(None), Track.artist.isnot(None))
            .limit(5000)
        )
        all_tracks = result.scalars().all()

        fuzzy_scored: list[tuple[Track, float]] = []
        for track in all_tracks:
            if not track.title or not track.artist:
                continue
            if track.id in seen_ids:
                continue

            local_title = normalize_for_matching(track.title)
            local_artist = normalize_for_matching(track.artist)

            title_score = fuzz.ratio(normalized_title, local_title) if normalized_title else 0
            artist_score = fuzz.ratio(normalized_artist, local_artist) if normalized_artist else 0
            combined = (title_score * 0.6) + (artist_score * 0.4)

            if combined >= CANDIDATE_THRESHOLD:
                fuzzy_scored.append((track, combined))

        # Sort by score descending
        fuzzy_scored.sort(key=lambda x: x[1], reverse=True)

        for track, score in fuzzy_scored:
            _add_candidate(track, "fuzzy", score / 100.0)
            if len(candidates) >= limit:
                break

        return candidates[:limit]

    async def create_external_track(
        self,
        title: str,
        artist: str,
        album: str | None = None,
        source: ExternalTrackSource = ExternalTrackSource.MANUAL,
        spotify_id: str | None = None,
        isrc: str | None = None,
        duration_seconds: float | None = None,
        external_data: dict | None = None,
        source_playlist_id: UUID | None = None,
        source_spotify_playlist_id: str | None = None,
        try_match: bool = True,
    ) -> ExternalTrack:
        """Create a new external track, optionally trying to match immediately.

        If spotify_id is provided and already exists, returns existing track.

        Args:
            title: Track title
            artist: Artist name
            album: Album name (optional)
            source: How this track was discovered
            spotify_id: Spotify track ID (optional)
            isrc: ISRC code (optional)
            duration_seconds: Track duration (optional)
            external_data: Additional metadata (optional)
            source_playlist_id: Local playlist that originated this track
            source_spotify_playlist_id: Original Spotify playlist ID
            try_match: Whether to attempt matching to local library

        Returns:
            Created or existing ExternalTrack
        """
        # Check if already exists by spotify_id
        if spotify_id:
            result = await self.db.execute(
                select(ExternalTrack).where(ExternalTrack.spotify_id == spotify_id)
            )
            existing = result.scalar_one_or_none()
            if existing:
                return existing

        # Create new external track
        external_track = ExternalTrack(
            title=title,
            artist=artist,
            album=album,
            source=source,
            spotify_id=spotify_id,
            isrc=isrc,
            duration_seconds=duration_seconds,
            external_data=external_data or {},
            source_playlist_id=source_playlist_id,
            source_spotify_playlist_id=source_spotify_playlist_id,
        )
        self.db.add(external_track)

        if try_match:
            await self.match_external_track(external_track, commit=False)

        await self.db.commit()
        await self.db.refresh(external_track)

        return external_track
