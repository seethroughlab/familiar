"""Metadata extraction service using mutagen."""

import logging
from pathlib import Path
from typing import Any

import mutagen
from mutagen.aiff import AIFF
from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis

logger = logging.getLogger(__name__)


def extract_metadata(file_path: Path) -> dict[str, Any]:
    """Extract audio metadata from file tags.

    Supports MP3 (ID3), FLAC, M4A/AAC (MP4), and OGG.

    Returns:
        Dict with extracted metadata fields.
    """
    metadata: dict[str, Any] = {
        "title": None,
        "artist": None,
        "album": None,
        "album_artist": None,
        "track_number": None,
        "disc_number": None,
        "year": None,
        "genre": None,
        "duration_seconds": None,
        "sample_rate": None,
        "bit_depth": None,
        "bitrate": None,
        "bitrate_mode": None,  # "CBR", "VBR", or None
        "format": None,
        # Extended metadata
        "composer": None,
        "conductor": None,
        "lyricist": None,
        "grouping": None,
        "comment": None,
        # Sort fields
        "sort_artist": None,
        "sort_album": None,
        "sort_title": None,
        # Lyrics
        "lyrics": None,
    }

    try:
        audio = mutagen.File(file_path, easy=True)  # type: ignore[attr-defined]
        if audio is None:
            return metadata

        # Determine format
        suffix = file_path.suffix.lower()
        metadata["format"] = suffix.lstrip(".")

        # Get duration from audio info
        if hasattr(audio, "info") and audio.info:
            metadata["duration_seconds"] = audio.info.length
            if hasattr(audio.info, "sample_rate"):
                metadata["sample_rate"] = audio.info.sample_rate
            if hasattr(audio.info, "bits_per_sample"):
                metadata["bit_depth"] = audio.info.bits_per_sample
            if hasattr(audio.info, "bitrate"):
                metadata["bitrate"] = audio.info.bitrate

        # Extract tags based on format
        if suffix == ".mp3":
            metadata.update(_extract_id3_tags(file_path))
            # Extract bitrate mode for MP3
            metadata.update(_extract_mp3_bitrate_mode(file_path))
        elif suffix == ".flac":
            metadata.update(_extract_flac_tags(file_path))
        elif suffix in {".m4a", ".aac", ".mp4"}:
            metadata.update(_extract_mp4_tags(file_path))
        elif suffix == ".ogg":
            metadata.update(_extract_ogg_tags(file_path))
        elif suffix in {".aiff", ".aif"}:
            metadata.update(_extract_aiff_tags(file_path))
        else:
            # Try easy interface as fallback
            metadata.update(_extract_easy_tags(audio))

    except Exception as e:
        # Log error but return partial metadata
        logger.warning(f"Error extracting metadata from {file_path}: {e}")

    return metadata


def _extract_easy_tags(audio: Any) -> dict[str, Any]:
    """Extract tags using mutagen's easy interface."""
    tags: dict[str, Any] = {}

    def get_first(key: str) -> str | None:
        val = audio.get(key)
        if val and len(val) > 0:
            return str(val[0])
        return None

    tags["title"] = get_first("title")
    tags["artist"] = get_first("artist")
    tags["album"] = get_first("album")
    tags["album_artist"] = get_first("albumartist") or get_first("album artist")
    tags["genre"] = get_first("genre")

    # Parse track number (may be "3/12" format)
    track_str = get_first("tracknumber")
    if track_str:
        tags["track_number"] = _parse_number(track_str)

    disc_str = get_first("discnumber")
    if disc_str:
        tags["disc_number"] = _parse_number(disc_str)

    # Parse year
    date_str = get_first("date") or get_first("year")
    if date_str:
        tags["year"] = _parse_year(date_str)

    # Extended metadata
    tags["composer"] = get_first("composer")
    tags["conductor"] = get_first("conductor")
    tags["lyricist"] = get_first("lyricist")
    tags["grouping"] = get_first("grouping")
    tags["comment"] = get_first("comment")

    # Sort fields
    tags["sort_artist"] = get_first("artistsort") or get_first("sortartist")
    tags["sort_album"] = get_first("albumsort") or get_first("sortalbum")
    tags["sort_title"] = get_first("titlesort") or get_first("sorttitle")

    return tags


def _extract_id3_tags(file_path: Path) -> dict[str, Any]:
    """Extract ID3 tags from MP3 files."""
    tags: dict[str, Any] = {}

    try:
        audio = EasyID3(file_path)  # type: ignore[no-untyped-call]
        tags = _extract_easy_tags(audio)
    except Exception:
        # Fall back to mutagen.File
        audio = mutagen.File(file_path, easy=True)  # type: ignore[attr-defined]
        if audio:
            tags = _extract_easy_tags(audio)

    # Also try to extract lyrics from raw ID3 (not available in EasyID3)
    try:
        from mutagen.id3 import ID3
        id3 = ID3(file_path)
        # Look for USLT (unsynchronized lyrics) frames
        for key in id3.keys():
            if key.startswith("USLT"):
                frame = id3[key]
                if hasattr(frame, "text") and frame.text:
                    tags["lyrics"] = str(frame.text)
                    break
    except Exception:
        pass

    return tags


def _extract_mp3_bitrate_mode(file_path: Path) -> dict[str, Any]:
    """Extract bitrate mode (CBR/VBR) from MP3 files."""
    result: dict[str, Any] = {}

    try:
        from mutagen.mp3 import MP3, BitrateMode

        mp3 = MP3(file_path)
        if mp3.info:
            if mp3.info.bitrate_mode == BitrateMode.CBR:
                result["bitrate_mode"] = "CBR"
            elif mp3.info.bitrate_mode == BitrateMode.VBR:
                result["bitrate_mode"] = "VBR"
            elif mp3.info.bitrate_mode == BitrateMode.ABR:
                result["bitrate_mode"] = "VBR"  # Treat ABR as VBR for quality purposes
            # BitrateMode.UNKNOWN leaves bitrate_mode as None
    except Exception as e:
        logger.warning(f"Error extracting MP3 bitrate mode: {e}")

    return result


def _extract_flac_tags(file_path: Path) -> dict[str, Any]:
    """Extract Vorbis comments from FLAC files."""
    tags: dict[str, Any] = {}

    try:
        audio = FLAC(file_path)

        def get_first(key: str) -> str | None:
            val = audio.get(key)
            if val and len(val) > 0:
                return str(val[0])
            return None

        tags["title"] = get_first("title")
        tags["artist"] = get_first("artist")
        tags["album"] = get_first("album")
        tags["album_artist"] = get_first("albumartist") or get_first("album artist")
        tags["genre"] = get_first("genre")

        track_str = get_first("tracknumber")
        if track_str:
            tags["track_number"] = _parse_number(track_str)

        disc_str = get_first("discnumber")
        if disc_str:
            tags["disc_number"] = _parse_number(disc_str)

        date_str = get_first("date") or get_first("year")
        if date_str:
            tags["year"] = _parse_year(date_str)

        # Extended metadata
        tags["composer"] = get_first("composer")
        tags["conductor"] = get_first("conductor")
        tags["lyricist"] = get_first("lyricist")
        tags["grouping"] = get_first("grouping")
        tags["comment"] = get_first("comment") or get_first("description")

        # Sort fields
        tags["sort_artist"] = get_first("artistsort")
        tags["sort_album"] = get_first("albumsort")
        tags["sort_title"] = get_first("titlesort")

        # Lyrics
        tags["lyrics"] = get_first("lyrics") or get_first("unsyncedlyrics")

        # FLAC-specific: bit depth from audio info
        if audio.info:
            tags["bit_depth"] = audio.info.bits_per_sample
            tags["sample_rate"] = audio.info.sample_rate

    except Exception as e:
        logger.warning(f"Error reading FLAC tags: {e}")

    return tags


def _extract_mp4_tags(file_path: Path) -> dict[str, Any]:
    """Extract MP4/M4A atom tags."""
    tags: dict[str, Any] = {}

    try:
        audio = MP4(file_path)

        def get_first(key: str) -> str | None:
            val = audio.tags.get(key) if audio.tags else None
            if val and len(val) > 0:
                return str(val[0])
            return None

        # MP4 uses different tag names
        tags["title"] = get_first("\xa9nam")
        tags["artist"] = get_first("\xa9ART")
        tags["album"] = get_first("\xa9alb")
        tags["album_artist"] = get_first("aART")
        tags["genre"] = get_first("\xa9gen")

        # Track number is stored as tuple (track, total)
        trkn = audio.tags.get("trkn") if audio.tags else None
        if trkn and len(trkn) > 0:
            tags["track_number"] = trkn[0][0]

        disk = audio.tags.get("disk") if audio.tags else None
        if disk and len(disk) > 0:
            tags["disc_number"] = disk[0][0]

        date_str = get_first("\xa9day")
        if date_str:
            tags["year"] = _parse_year(date_str)

        # Extended metadata
        tags["composer"] = get_first("\xa9wrt")
        tags["comment"] = get_first("\xa9cmt")
        tags["grouping"] = get_first("\xa9grp")

        # Sort fields
        tags["sort_artist"] = get_first("soar")
        tags["sort_album"] = get_first("soal")
        tags["sort_title"] = get_first("sonm")

        # Lyrics
        tags["lyrics"] = get_first("\xa9lyr")

    except Exception as e:
        logger.warning(f"Error reading MP4 tags: {e}")

    return tags


def _extract_ogg_tags(file_path: Path) -> dict[str, Any]:
    """Extract Vorbis comments from OGG files."""
    tags: dict[str, Any] = {}

    try:
        audio = OggVorbis(file_path)  # type: ignore[no-untyped-call]
        return _extract_easy_tags(audio)
    except Exception as e:
        logger.warning(f"Error reading OGG tags: {e}")

    return tags


def _extract_aiff_tags(file_path: Path) -> dict[str, Any]:
    """Extract ID3 tags from AIFF files."""
    tags: dict[str, Any] = {}

    try:
        audio = AIFF(file_path)

        # AIFF files can have ID3 tags
        if audio.tags:
            def get_text(key: str) -> str | None:
                """Get text from an ID3 frame."""
                frame = audio.tags.get(key)
                if frame is None:
                    return None
                # ID3 frames have a .text attribute which is a list
                if hasattr(frame, 'text') and frame.text:
                    return str(frame.text[0])
                return None

            # ID3 frame names
            tags["title"] = get_text("TIT2")
            tags["artist"] = get_text("TPE1")
            tags["album"] = get_text("TALB")
            tags["album_artist"] = get_text("TPE2")
            tags["genre"] = get_text("TCON")

            # Track number (TRCK frame)
            track_text = get_text("TRCK")
            if track_text:
                tags["track_number"] = _parse_number(track_text)

            # Disc number (TPOS frame)
            disc_text = get_text("TPOS")
            if disc_text:
                tags["disc_number"] = _parse_number(disc_text)

            # Year (TDRC or TYER)
            date_text = get_text("TDRC") or get_text("TYER")
            if date_text:
                tags["year"] = _parse_year(date_text)

            # Extended metadata
            tags["composer"] = get_text("TCOM")
            tags["conductor"] = get_text("TPE3")
            tags["lyricist"] = get_text("TEXT")
            tags["grouping"] = get_text("TIT1")

            # Comment (COMM frame is special - need to find any COMM frame)
            for key in audio.tags.keys():
                if key.startswith("COMM"):
                    frame = audio.tags[key]
                    if hasattr(frame, 'text') and frame.text:
                        tags["comment"] = str(frame.text[0])
                        break

            # Sort fields
            tags["sort_artist"] = get_text("TSOP")
            tags["sort_album"] = get_text("TSOA")
            tags["sort_title"] = get_text("TSOT")

            # Lyrics (USLT frame)
            for key in audio.tags.keys():
                if key.startswith("USLT"):
                    frame = audio.tags[key]
                    if hasattr(frame, 'text') and frame.text:
                        tags["lyrics"] = str(frame.text)
                        break

        # Audio info
        if audio.info:
            tags["sample_rate"] = audio.info.sample_rate
            tags["bit_depth"] = audio.info.bits_per_sample

    except Exception as e:
        logger.warning(f"Error reading AIFF tags: {e}")

    return tags


def _parse_number(value: str) -> int | None:
    """Parse track/disc number from string like '3' or '3/12'."""
    try:
        # Handle "3/12" format
        if "/" in value:
            value = value.split("/")[0]
        return int(value.strip())
    except (ValueError, AttributeError):
        return None


def _parse_year(value: str) -> int | None:
    """Parse year from string like '2023' or '2023-05-10'."""
    try:
        # Take first 4 characters as year
        return int(value[:4])
    except (ValueError, AttributeError):
        return None
