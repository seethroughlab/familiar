"""Automatic metadata enrichment service.

Fetches missing metadata from MusicBrainz/AcoustID and writes to ID3 tags.
Triggered when a track is played that has incomplete metadata.
"""

import logging
from pathlib import Path
from typing import Any

import httpx
from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC
from mutagen.mp4 import MP4

from app.db.models import Track

logger = logging.getLogger(__name__)

# Cover Art Archive base URL
CAA_BASE_URL = "https://coverartarchive.org"

# Fields to check for completeness
ENRICHABLE_FIELDS = ["title", "artist", "album", "genre", "year"]

# Patterns that indicate placeholder/missing values
PLACEHOLDER_PATTERNS = ["unknown", "track ", "untitled", "various artists"]


def is_field_missing(value: Any) -> bool:
    """Check if a field value is missing or a placeholder."""
    if value is None:
        return True
    if isinstance(value, str):
        lower_val = value.lower().strip()
        if not lower_val:
            return True
        if any(pattern in lower_val for pattern in PLACEHOLDER_PATTERNS):
            return True
    return False


def needs_enrichment(track: Track, check_artwork: bool = True) -> bool:
    """Check if a track has missing or incomplete metadata.

    Args:
        track: Track to check
        check_artwork: Also check if artwork is missing

    Returns:
        True if track needs enrichment
    """
    # Check core metadata fields
    for field in ENRICHABLE_FIELDS:
        value = getattr(track, field, None)
        if is_field_missing(value):
            return True

    # Check artwork
    if check_artwork:
        from app.services.artwork import compute_album_hash, get_artwork_path

        album_hash = compute_album_hash(track.artist, track.album)
        artwork_path = get_artwork_path(album_hash, "full")
        if not artwork_path.exists():
            return True

    return False


def get_missing_fields(track: Track) -> list[str]:
    """Return list of fields that are missing or contain placeholders."""
    missing = []
    for field in ENRICHABLE_FIELDS:
        value = getattr(track, field, None)
        if is_field_missing(value):
            missing.append(field)
    return missing


async def fetch_cover_art(release_id: str) -> bytes | None:
    """Fetch album art from Cover Art Archive.

    Args:
        release_id: MusicBrainz release ID

    Returns:
        Image bytes or None if not found
    """
    url = f"{CAA_BASE_URL}/release/{release_id}/front-500"

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            response = await client.get(url)
            if response.status_code == 200:
                return response.content
            logger.debug(f"Cover Art Archive returned {response.status_code} for {release_id}")
        except httpx.TimeoutException:
            logger.warning(f"Timeout fetching cover art for {release_id}")
        except Exception as e:
            logger.warning(f"Error fetching cover art: {e}")

    return None


def write_metadata_to_file(
    file_path: Path,
    metadata: dict[str, Any],
    overwrite_existing: bool = False,
) -> bool:
    """Write metadata to audio file ID3/Vorbis tags.

    Supports MP3, FLAC, M4A formats.

    Args:
        file_path: Path to audio file
        metadata: Dict with fields: title, artist, album, genre, year, track_number
        overwrite_existing: If True, overwrite existing values. If False, only fill blank fields.

    Returns:
        True if successful
    """
    suffix = file_path.suffix.lower()

    try:
        if suffix == ".mp3":
            return _write_id3_tags(file_path, metadata, overwrite_existing)
        elif suffix == ".flac":
            return _write_flac_tags(file_path, metadata, overwrite_existing)
        elif suffix in {".m4a", ".aac", ".mp4"}:
            return _write_mp4_tags(file_path, metadata, overwrite_existing)
        else:
            logger.warning(f"Unsupported format for tag writing: {suffix}")
            return False
    except Exception as e:
        logger.error(f"Failed to write tags to {file_path}: {e}")
        return False


def _write_id3_tags(file_path: Path, metadata: dict[str, Any], overwrite: bool) -> bool:
    """Write ID3 tags to MP3 file."""
    try:
        try:
            tags = EasyID3(file_path)
        except Exception:
            tags = EasyID3()
            tags.save(file_path)
            tags = EasyID3(file_path)

        def should_update(key: str) -> bool:
            if overwrite:
                return True
            existing = tags.get(key)
            return not existing or not existing[0].strip()

        if metadata.get("title") and should_update("title"):
            tags["title"] = metadata["title"]
        if metadata.get("artist") and should_update("artist"):
            tags["artist"] = metadata["artist"]
        if metadata.get("album") and should_update("album"):
            tags["album"] = metadata["album"]
        if metadata.get("genre") and should_update("genre"):
            tags["genre"] = metadata["genre"]
        if metadata.get("year") and should_update("date"):
            tags["date"] = str(metadata["year"])
        if metadata.get("track_number") and should_update("tracknumber"):
            tags["tracknumber"] = str(metadata["track_number"])

        tags.save()
        return True
    except Exception as e:
        logger.error(f"Error writing ID3 tags: {e}")
        return False


def _write_flac_tags(file_path: Path, metadata: dict[str, Any], overwrite: bool) -> bool:
    """Write Vorbis comments to FLAC file."""
    try:
        audio = FLAC(file_path)

        def should_update(key: str) -> bool:
            if overwrite:
                return True
            existing = audio.get(key)
            return not existing or not existing[0].strip()

        if metadata.get("title") and should_update("title"):
            audio["title"] = metadata["title"]
        if metadata.get("artist") and should_update("artist"):
            audio["artist"] = metadata["artist"]
        if metadata.get("album") and should_update("album"):
            audio["album"] = metadata["album"]
        if metadata.get("genre") and should_update("genre"):
            audio["genre"] = metadata["genre"]
        if metadata.get("year") and should_update("date"):
            audio["date"] = str(metadata["year"])
        if metadata.get("track_number") and should_update("tracknumber"):
            audio["tracknumber"] = str(metadata["track_number"])

        audio.save()
        return True
    except Exception as e:
        logger.error(f"Error writing FLAC tags: {e}")
        return False


def _write_mp4_tags(file_path: Path, metadata: dict[str, Any], overwrite: bool) -> bool:
    """Write MP4 atoms to M4A/AAC file."""
    try:
        audio = MP4(file_path)

        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        assert tags is not None

        def should_update(key: str) -> bool:
            if overwrite:
                return True
            existing = tags.get(key)
            return not existing or (isinstance(existing, list) and not existing[0])

        if metadata.get("title") and should_update("\xa9nam"):
            tags["\xa9nam"] = [metadata["title"]]
        if metadata.get("artist") and should_update("\xa9ART"):
            tags["\xa9ART"] = [metadata["artist"]]
        if metadata.get("album") and should_update("\xa9alb"):
            tags["\xa9alb"] = [metadata["album"]]
        if metadata.get("genre") and should_update("\xa9gen"):
            tags["\xa9gen"] = [metadata["genre"]]
        if metadata.get("year") and should_update("\xa9day"):
            tags["\xa9day"] = [str(metadata["year"])]
        if metadata.get("track_number") and should_update("trkn"):
            tags["trkn"] = [(metadata["track_number"], 0)]

        audio.save()
        return True
    except Exception as e:
        logger.error(f"Error writing MP4 tags: {e}")
        return False
