"""Audio identification service using AcoustID fingerprinting.

Provides fingerprint-based track identification with enriched metadata from
MusicBrainz and Cover Art Archive. Used for the "Auto-populate" feature
in the track edit modal.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import musicbrainzngs
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import FEATURES_VERSION
from app.db.models import Track, TrackAnalysis

logger = logging.getLogger(__name__)

# Rate limiting for MusicBrainz API (1 request per second)
MB_RATE_LIMIT = 1.0


@dataclass
class IdentifyCandidate:
    """A candidate match from audio fingerprinting."""

    acoustid_score: float  # 0.0-1.0
    musicbrainz_recording_id: str
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    year: int | None = None
    track_number: int | None = None
    disc_number: int | None = None
    genre: str | None = None
    composer: str | None = None
    artwork_url: str | None = None
    features: dict[str, Any] = field(default_factory=dict)
    musicbrainz_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "acoustid_score": self.acoustid_score,
            "musicbrainz_recording_id": self.musicbrainz_recording_id,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "album_artist": self.album_artist,
            "year": self.year,
            "track_number": self.track_number,
            "disc_number": self.disc_number,
            "genre": self.genre,
            "composer": self.composer,
            "artwork_url": self.artwork_url,
            "features": self.features,
            "musicbrainz_url": self.musicbrainz_url,
        }


@dataclass
class IdentifyResult:
    """Result of track identification."""

    track_id: str
    fingerprint_generated: bool = False
    error: str | None = None
    error_type: str | None = None
    candidates: list[IdentifyCandidate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "track_id": self.track_id,
            "fingerprint_generated": self.fingerprint_generated,
            "error": self.error,
            "error_type": self.error_type,
            "candidates": [c.to_dict() for c in self.candidates],
        }


class AudioIdentificationService:
    """Service for identifying tracks via audio fingerprinting.

    Orchestrates:
    1. AcoustID fingerprint lookup for candidate recordings
    2. MusicBrainz enrichment for full metadata
    3. Cover Art Archive for artwork URLs
    """

    def __init__(self):
        self._last_mb_request = 0.0

    async def identify_track(
        self,
        track_id: UUID,
        db: AsyncSession,
        min_score: float = 0.5,
        limit: int = 5,
        skip_cache: bool = False,
    ) -> IdentifyResult:
        """Identify a track using audio fingerprinting.

        Args:
            track_id: Track UUID
            db: Database session
            min_score: Minimum AcoustID score to include (0.0-1.0)
            limit: Maximum number of candidates to return
            skip_cache: If True, bypass cached results and fetch fresh from API

        Returns:
            IdentifyResult with candidates or error
        """
        result = IdentifyResult(track_id=str(track_id))

        # Get track from database
        query = select(Track).where(Track.id == track_id)
        db_result = await db.execute(query)
        track = db_result.scalar_one_or_none()

        if not track:
            result.error = "Track not found"
            result.error_type = "not_found"
            return result

        file_path = Path(track.file_path)
        if not file_path.exists():
            result.error = f"Audio file not found: {file_path}"
            result.error_type = "file_not_found"
            return result

        # Check for cached AcoustID results in TrackAnalysis
        analysis = await self._get_current_analysis(track_id, db)
        acoustid_candidates = None

        if not skip_cache and analysis and analysis.acoustid_lookup:
            cached = analysis.acoustid_lookup
            # Use cache if it exists and has candidates
            if cached.get("candidates"):
                logger.debug(f"Using cached AcoustID results for track {track_id}")
                acoustid_candidates = cached["candidates"]
                result.fingerprint_generated = True

        # If no cache hit, fetch from AcoustID API
        if acoustid_candidates is None:
            # Lazy import to avoid loading librosa/torch in API process
            from app.services.analysis import AcoustIDError, lookup_acoustid_candidates

            try:
                acoustid_candidates = lookup_acoustid_candidates(
                    file_path,
                    min_score=min_score,
                    limit=limit,
                )
                result.fingerprint_generated = True

                # Cache the results in the database
                await self._cache_acoustid_results(track_id, acoustid_candidates, db)

            except AcoustIDError as e:
                result.error = str(e)
                result.error_type = e.error_type
                return result

        if not acoustid_candidates:
            # No error, just no matches
            return result

        # Enrich each candidate with MusicBrainz data
        for acoustid_data in acoustid_candidates:
            candidate = await self._enrich_candidate(acoustid_data)
            result.candidates.append(candidate)

        return result

    async def _get_current_analysis(
        self,
        track_id: UUID,
        db: AsyncSession,
    ) -> TrackAnalysis | None:
        """Get the current analysis record for a track."""
        query = (
            select(TrackAnalysis)
            .where(TrackAnalysis.track_id == track_id)
            .where(TrackAnalysis.features_version == FEATURES_VERSION)
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def _cache_acoustid_results(
        self,
        track_id: UUID,
        candidates: list[dict],
        db: AsyncSession,
    ) -> None:
        """Cache AcoustID lookup results in the TrackAnalysis record."""
        analysis = await self._get_current_analysis(track_id, db)
        if analysis:
            analysis.acoustid_lookup = {"candidates": candidates}
            await db.commit()
            logger.debug(f"Cached {len(candidates)} AcoustID candidates for track {track_id}")

    async def _enrich_candidate(self, acoustid_data: dict) -> IdentifyCandidate:
        """Enrich an AcoustID candidate with MusicBrainz metadata.

        Args:
            acoustid_data: Dict with acoustid_score, musicbrainz_recording_id, title, artist

        Returns:
            Enriched IdentifyCandidate
        """
        recording_id = acoustid_data.get("musicbrainz_recording_id", "")

        candidate = IdentifyCandidate(
            acoustid_score=acoustid_data.get("acoustid_score", 0.0),
            musicbrainz_recording_id=recording_id,
            title=acoustid_data.get("title"),
            artist=acoustid_data.get("artist"),
            musicbrainz_url=f"https://musicbrainz.org/recording/{recording_id}",
        )

        if not recording_id:
            return candidate

        # Fetch full recording data from MusicBrainz
        try:
            await self._rate_limit_mb()
            recording = musicbrainzngs.get_recording_by_id(
                recording_id,
                includes=["artists", "releases", "tags", "work-rels"],
            )

            if recording and "recording" in recording:
                rec_data = recording["recording"]
                await self._populate_from_musicbrainz(candidate, rec_data)

        except musicbrainzngs.WebServiceError as e:
            logger.warning(f"MusicBrainz lookup failed for {recording_id}: {e}")
        except Exception as e:
            logger.warning(f"Error enriching candidate {recording_id}: {e}")

        return candidate

    async def _populate_from_musicbrainz(
        self,
        candidate: IdentifyCandidate,
        rec_data: dict,
    ) -> None:
        """Populate candidate fields from MusicBrainz recording data."""
        # Title
        candidate.title = rec_data.get("title") or candidate.title

        # Artist
        artist_credit = rec_data.get("artist-credit", [])
        if artist_credit:
            artist_names = []
            for credit in artist_credit:
                if isinstance(credit, dict):
                    artist_names.append(credit.get("artist", {}).get("name", ""))
                elif isinstance(credit, str):
                    artist_names.append(credit)
            candidate.artist = "".join(artist_names) or candidate.artist

        # Get first release for album info
        releases = rec_data.get("release-list", [])
        if releases:
            release = releases[0]
            candidate.album = release.get("title")

            # Album artist (may differ from track artist for compilations)
            release_artist_credit = release.get("artist-credit", [])
            if release_artist_credit:
                album_artist_names = []
                for credit in release_artist_credit:
                    if isinstance(credit, dict):
                        album_artist_names.append(credit.get("artist", {}).get("name", ""))
                    elif isinstance(credit, str):
                        album_artist_names.append(credit)
                album_artist = "".join(album_artist_names)
                if album_artist and album_artist != candidate.artist:
                    candidate.album_artist = album_artist

            # Year from release date
            date_str = release.get("date", "")
            if date_str and len(date_str) >= 4:
                try:
                    candidate.year = int(date_str[:4])
                except ValueError:
                    pass

            # Track and disc number from medium
            medium_list = release.get("medium-list", [])
            for medium in medium_list:
                disc_number = medium.get("position")
                track_list = medium.get("track-list", [])
                for track in track_list:
                    if track.get("recording", {}).get("id") == candidate.musicbrainz_recording_id:
                        try:
                            candidate.track_number = int(track.get("position", 0)) or None
                        except (ValueError, TypeError):
                            pass
                        try:
                            candidate.disc_number = int(disc_number) if disc_number else None
                        except (ValueError, TypeError):
                            pass
                        break

            # Artwork URL from Cover Art Archive
            release_id = release.get("id")
            if release_id:
                candidate.artwork_url = f"https://coverartarchive.org/release/{release_id}/front-250"

        # Genre from tags
        tags = rec_data.get("tag-list", [])
        if tags:
            # Get top 3 tags by count, sorted
            sorted_tags = sorted(tags, key=lambda t: int(t.get("count", 0)), reverse=True)
            genre_tags = [t.get("name") for t in sorted_tags[:3] if t.get("name")]
            if genre_tags:
                candidate.genre = ", ".join(genre_tags)

        # Composer from work relations
        work_rels = rec_data.get("work-relation-list", [])
        for work_rel in work_rels:
            if work_rel.get("type") == "performance":
                work = work_rel.get("work", {})
                # Work might have composer info
                work_id = work.get("id")
                if work_id:
                    try:
                        await self._rate_limit_mb()
                        work_data = musicbrainzngs.get_work_by_id(
                            work_id,
                            includes=["artist-rels"],
                        )
                        if work_data and "work" in work_data:
                            artist_rels = work_data["work"].get("artist-relation-list", [])
                            for rel in artist_rels:
                                if rel.get("type") in ("composer", "writer"):
                                    composer = rel.get("artist", {}).get("name")
                                    if composer:
                                        candidate.composer = composer
                                        break
                    except Exception:
                        pass
                break

    async def _rate_limit_mb(self) -> None:
        """Enforce MusicBrainz rate limiting (1 request/second)."""
        import time

        now = time.time()
        elapsed = now - self._last_mb_request
        if elapsed < MB_RATE_LIMIT:
            await asyncio.sleep(MB_RATE_LIMIT - elapsed)
        self._last_mb_request = time.time()


# Module-level singleton
_service: AudioIdentificationService | None = None


def get_audio_identification_service() -> AudioIdentificationService:
    """Get the singleton audio identification service."""
    global _service
    if _service is None:
        _service = AudioIdentificationService()
    return _service
