"""Unified metadata lookup service.

Queries multiple sources (MusicBrainz, Spotify) and returns ranked candidates
with confidence scores. Used by the LLM to propose metadata corrections.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import musicbrainzngs

from app.services.metadata.musicbrainz import (
    _normalize_for_comparison,
    search_recording,
)

logger = logging.getLogger(__name__)


@dataclass
class MetadataCandidate:
    """A candidate metadata match from an external source."""

    source: str  # "musicbrainz", "spotify"
    source_id: str  # External ID for reference
    confidence: float  # 0.0-1.0
    metadata: dict[str, Any]  # title, artist, album, year, album_artist, etc.
    artwork_url: str | None = None
    match_details: dict[str, Any] = field(default_factory=dict)  # Debug info about why this matched


@dataclass
class AlbumCandidate:
    """A candidate album match with track listing."""

    source: str
    source_id: str
    confidence: float
    album: str
    artist: str
    year: int | None
    track_count: int
    tracks: list[dict[str, Any]]  # [{track_number, title, duration_ms}, ...]
    artwork_url: str | None = None


def _calculate_string_similarity(s1: str | None, s2: str | None) -> float:
    """Calculate similarity between two strings (0.0-1.0).

    Uses a simple approach: longer common prefix = higher score.
    """
    if not s1 or not s2:
        return 0.0

    s1_norm = _normalize_for_comparison(s1)
    s2_norm = _normalize_for_comparison(s2)

    if s1_norm == s2_norm:
        return 1.0

    # Check if one contains the other
    if s1_norm in s2_norm or s2_norm in s1_norm:
        return 0.8

    # Calculate Jaccard similarity on words
    words1 = set(s1_norm.split())
    words2 = set(s2_norm.split())
    if not words1 or not words2:
        return 0.0

    intersection = words1 & words2
    union = words1 | words2
    return len(intersection) / len(union)


class MetadataLookupService:
    """Unified metadata lookup across multiple sources."""

    async def lookup_track(
        self,
        title: str,
        artist: str,
        album: str | None = None,
        duration_ms: int | None = None,
        limit: int = 5,
    ) -> list[MetadataCandidate]:
        """Look up track metadata from external sources.

        Args:
            title: Track title
            artist: Artist name
            album: Album name (optional, improves matching)
            duration_ms: Track duration in milliseconds (optional, for verification)
            limit: Maximum candidates to return

        Returns:
            List of candidates sorted by confidence (highest first)
        """
        candidates: list[MetadataCandidate] = []

        # Try MusicBrainz
        mb_candidates = await self._lookup_musicbrainz_track(
            title, artist, album, duration_ms
        )
        candidates.extend(mb_candidates)

        # TODO: Add Spotify lookup
        # spotify_candidates = await self._lookup_spotify_track(title, artist, album)
        # candidates.extend(spotify_candidates)

        # Sort by confidence and limit
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates[:limit]

    async def _lookup_musicbrainz_track(
        self,
        title: str,
        artist: str,
        album: str | None = None,
        duration_ms: int | None = None,
    ) -> list[MetadataCandidate]:
        """Search MusicBrainz for track metadata."""
        candidates = []

        try:
            # Search for recordings
            result = search_recording(title, artist, local_album=album)
            if not result:
                return []

            # The search_recording function returns the best match directly
            # We'll create a candidate from it
            confidence = 0.9  # Base confidence for MusicBrainz match

            # Adjust confidence based on how well it matches
            title_sim = _calculate_string_similarity(title, result.get("title"))
            artist_sim = _calculate_string_similarity(artist, result.get("artist"))
            confidence = (confidence * 0.5) + (title_sim * 0.25) + (artist_sim * 0.25)

            # Check duration if available
            if duration_ms and result.get("length_ms"):
                duration_diff = abs(duration_ms - result["length_ms"])
                if duration_diff < 3000:  # Within 3 seconds
                    confidence = min(1.0, confidence + 0.05)
                elif duration_diff > 30000:  # More than 30 seconds off
                    confidence = max(0.0, confidence - 0.2)

            candidate = MetadataCandidate(
                source="musicbrainz",
                source_id=result.get("musicbrainz_recording_id", ""),
                confidence=confidence,
                metadata={
                    "title": result.get("title"),
                    "artist": result.get("artist"),
                    "album": result.get("album"),
                    "year": result.get("year"),
                    "genre": ", ".join(result.get("tags", [])[:3]) if result.get("tags") else None,
                    "musicbrainz_recording_id": result.get("musicbrainz_recording_id"),
                    "musicbrainz_artist_id": result.get("musicbrainz_artist_id"),
                    "musicbrainz_release_id": result.get("musicbrainz_release_id"),
                },
                match_details={
                    "title_similarity": title_sim,
                    "artist_similarity": artist_sim,
                },
            )
            candidates.append(candidate)

        except Exception as e:
            logger.warning(f"MusicBrainz lookup failed for '{title}' by '{artist}': {e}")

        return candidates

    async def lookup_album(
        self,
        album: str,
        artist: str,
        limit: int = 5,
    ) -> list[AlbumCandidate]:
        """Look up album metadata and track listing.

        Args:
            album: Album name
            artist: Artist name
            limit: Maximum candidates to return

        Returns:
            List of album candidates with track listings
        """
        candidates: list[AlbumCandidate] = []

        # Try MusicBrainz
        mb_candidates = await self._lookup_musicbrainz_album(album, artist)
        candidates.extend(mb_candidates)

        # Sort by confidence and limit
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates[:limit]

    async def _lookup_musicbrainz_album(
        self,
        album: str,
        artist: str,
    ) -> list[AlbumCandidate]:
        """Search MusicBrainz for album metadata."""
        candidates = []

        try:
            # Search for releases
            result = musicbrainzngs.search_releases(
                release=album,
                artist=artist,
                limit=5,
            )

            releases = result.get("release-list", [])
            for release in releases:
                release_id = release.get("id")
                release_title = release.get("title", "")
                release_artist = ""

                # Extract artist
                artist_credit = release.get("artist-credit", [])
                if artist_credit:
                    artist_parts = []
                    for credit in artist_credit:
                        if isinstance(credit, dict):
                            artist_parts.append(credit.get("artist", {}).get("name", ""))
                        elif isinstance(credit, str):
                            artist_parts.append(credit)
                    release_artist = "".join(artist_parts)

                # Calculate confidence
                album_sim = _calculate_string_similarity(album, release_title)
                artist_sim = _calculate_string_similarity(artist, release_artist)
                confidence = (album_sim * 0.6) + (artist_sim * 0.4)

                # Extract year from date
                date_str = release.get("date", "")
                year = None
                if date_str and len(date_str) >= 4:
                    try:
                        year = int(date_str[:4])
                    except ValueError:
                        pass

                # Get track count
                medium_list = release.get("medium-list", [])
                track_count = sum(
                    int(m.get("track-count", 0)) for m in medium_list
                )

                # We'd need another API call to get full track listing
                # For now, just include basic info
                candidate = AlbumCandidate(
                    source="musicbrainz",
                    source_id=release_id,
                    confidence=confidence,
                    album=release_title,
                    artist=release_artist,
                    year=year,
                    track_count=track_count,
                    tracks=[],  # Would require additional API call
                    artwork_url=None,  # Cover Art Archive
                )
                candidates.append(candidate)

        except Exception as e:
            logger.warning(f"MusicBrainz album lookup failed for '{album}' by '{artist}': {e}")

        return candidates

    async def search_artwork(
        self,
        artist: str,
        album: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search for album artwork from multiple sources.

        Returns:
            List of artwork options: [{url, source, size, thumbnail_url}, ...]
        """
        artwork_options = []

        # Try Cover Art Archive (MusicBrainz)
        try:
            albums = await self._lookup_musicbrainz_album(album, artist)
            for album_candidate in albums[:3]:
                if album_candidate.source_id:
                    # Cover Art Archive URL pattern
                    caa_url = f"https://coverartarchive.org/release/{album_candidate.source_id}/front"
                    artwork_options.append({
                        "url": caa_url,
                        "source": "coverartarchive",
                        "source_id": album_candidate.source_id,
                        "confidence": album_candidate.confidence,
                        "album": album_candidate.album,
                        "artist": album_candidate.artist,
                    })
        except Exception as e:
            logger.warning(f"Cover Art Archive search failed: {e}")

        # TODO: Add Spotify, Last.fm, Discogs artwork search

        return artwork_options[:limit]


# Module-level instance for convenience
_service: MetadataLookupService | None = None


def get_metadata_lookup_service() -> MetadataLookupService:
    """Get the singleton metadata lookup service."""
    global _service
    if _service is None:
        _service = MetadataLookupService()
    return _service
