"""Metadata writing service using mutagen.

Writes metadata to audio files in various formats (MP3, FLAC, M4A, OGG, AIFF).
Mirrors the structure of metadata.py for consistency.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mutagen.aiff import AIFF
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    APIC,
    COMM,
    ID3,
    TALB,
    TCOM,
    TCON,
    TDRC,
    TEXT,
    TIT1,
    TIT2,
    TPE1,
    TPE2,
    TPE3,
    TPOS,
    TRCK,
    TSOA,
    TSOP,
    TSOT,
    USLT,
    ID3NoHeaderError,
)
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis

logger = logging.getLogger(__name__)


@dataclass
class WriteResult:
    """Result of a metadata write operation."""

    success: bool
    file_path: str
    error: str | None = None
    fields_written: list[str] = field(default_factory=list)
    unsupported_fields: list[str] = field(default_factory=list)


# ID3 frame mappings for MP3/AIFF
ID3_FIELD_MAP = {
    "title": "TIT2",
    "artist": "TPE1",
    "album": "TALB",
    "album_artist": "TPE2",
    "track_number": "TRCK",
    "disc_number": "TPOS",
    "year": "TDRC",
    "genre": "TCON",
    "composer": "TCOM",
    "conductor": "TPE3",
    "lyricist": "TEXT",
    "grouping": "TIT1",
    "comment": "COMM",
    "sort_artist": "TSOP",
    "sort_album": "TSOA",
    "sort_title": "TSOT",
}

# MP4 atom mappings for M4A/AAC
MP4_FIELD_MAP = {
    "title": "\xa9nam",
    "artist": "\xa9ART",
    "album": "\xa9alb",
    "album_artist": "aART",
    "track_number": "trkn",
    "disc_number": "disk",
    "year": "\xa9day",
    "genre": "\xa9gen",
    "composer": "\xa9wrt",
    "comment": "\xa9cmt",
    "grouping": "\xa9grp",
    "sort_artist": "soar",
    "sort_album": "soal",
    "sort_title": "sonm",
    # Note: MP4 doesn't have standard tags for conductor, lyricist
}

# Vorbis comment mappings for FLAC/OGG
VORBIS_FIELD_MAP = {
    "title": "TITLE",
    "artist": "ARTIST",
    "album": "ALBUM",
    "album_artist": "ALBUMARTIST",
    "track_number": "TRACKNUMBER",
    "disc_number": "DISCNUMBER",
    "year": "DATE",
    "genre": "GENRE",
    "composer": "COMPOSER",
    "conductor": "CONDUCTOR",
    "lyricist": "LYRICIST",
    "grouping": "GROUPING",
    "comment": "COMMENT",
    # Note: Vorbis doesn't have standard sort fields, but we can use them anyway
    "sort_artist": "ARTISTSORT",
    "sort_album": "ALBUMSORT",
    "sort_title": "TITLESORT",
}


def write_metadata(file_path: Path, metadata: dict[str, Any]) -> WriteResult:
    """Write metadata to audio file.

    Dispatches to format-specific writer based on file extension.

    Args:
        file_path: Path to the audio file
        metadata: Dict of field names to values. Only non-None values are written.

    Returns:
        WriteResult with success status and details
    """
    if not file_path.exists():
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=f"File not found: {file_path}",
        )

    # Filter out None values - we only write fields that are explicitly set
    metadata = {k: v for k, v in metadata.items() if v is not None}

    if not metadata:
        return WriteResult(
            success=True,
            file_path=str(file_path),
            fields_written=[],
        )

    suffix = file_path.suffix.lower()

    try:
        if suffix == ".mp3":
            return _write_id3_tags(file_path, metadata)
        elif suffix == ".flac":
            return _write_flac_tags(file_path, metadata)
        elif suffix in {".m4a", ".aac", ".mp4"}:
            return _write_mp4_tags(file_path, metadata)
        elif suffix == ".ogg":
            return _write_ogg_tags(file_path, metadata)
        elif suffix in {".aiff", ".aif"}:
            return _write_aiff_tags(file_path, metadata)
        else:
            return WriteResult(
                success=False,
                file_path=str(file_path),
                error=f"Unsupported format: {suffix}",
            )
    except PermissionError:
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error="Permission denied: cannot write to file",
        )
    except Exception as e:
        logger.error(f"Error writing metadata to {file_path}: {e}")
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=str(e),
        )


def _write_id3_tags(file_path: Path, metadata: dict[str, Any]) -> WriteResult:
    """Write ID3 tags to MP3 file."""
    fields_written = []
    unsupported = []

    try:
        try:
            tags = ID3(file_path)
        except ID3NoHeaderError:
            # Create new ID3 header
            tags = ID3()

        for field_name, value in metadata.items():
            frame_name = ID3_FIELD_MAP.get(field_name)
            if not frame_name:
                unsupported.append(field_name)
                continue

            # Handle special cases
            if field_name == "track_number":
                tags.delall("TRCK")
                tags.add(TRCK(encoding=3, text=str(value)))
            elif field_name == "disc_number":
                tags.delall("TPOS")
                tags.add(TPOS(encoding=3, text=str(value)))
            elif field_name == "year":
                tags.delall("TDRC")
                tags.add(TDRC(encoding=3, text=str(value)))
            elif field_name == "comment":
                # Remove existing comments and add new one
                tags.delall("COMM")
                tags.add(COMM(encoding=3, lang="eng", desc="", text=str(value)))
            elif field_name == "title":
                tags.delall("TIT2")
                tags.add(TIT2(encoding=3, text=str(value)))
            elif field_name == "artist":
                tags.delall("TPE1")
                tags.add(TPE1(encoding=3, text=str(value)))
            elif field_name == "album":
                tags.delall("TALB")
                tags.add(TALB(encoding=3, text=str(value)))
            elif field_name == "album_artist":
                tags.delall("TPE2")
                tags.add(TPE2(encoding=3, text=str(value)))
            elif field_name == "genre":
                tags.delall("TCON")
                tags.add(TCON(encoding=3, text=str(value)))
            elif field_name == "composer":
                tags.delall("TCOM")
                tags.add(TCOM(encoding=3, text=str(value)))
            elif field_name == "conductor":
                tags.delall("TPE3")
                tags.add(TPE3(encoding=3, text=str(value)))
            elif field_name == "lyricist":
                tags.delall("TEXT")
                tags.add(TEXT(encoding=3, text=str(value)))
            elif field_name == "grouping":
                tags.delall("TIT1")
                tags.add(TIT1(encoding=3, text=str(value)))
            elif field_name == "sort_artist":
                tags.delall("TSOP")
                tags.add(TSOP(encoding=3, text=str(value)))
            elif field_name == "sort_album":
                tags.delall("TSOA")
                tags.add(TSOA(encoding=3, text=str(value)))
            elif field_name == "sort_title":
                tags.delall("TSOT")
                tags.add(TSOT(encoding=3, text=str(value)))
            else:
                continue

            fields_written.append(field_name)

        tags.save(file_path)

        return WriteResult(
            success=True,
            file_path=str(file_path),
            fields_written=fields_written,
            unsupported_fields=unsupported,
        )

    except Exception as e:
        logger.error(f"Error writing ID3 tags to {file_path}: {e}")
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=str(e),
        )


def _write_flac_tags(file_path: Path, metadata: dict[str, Any]) -> WriteResult:
    """Write Vorbis comments to FLAC file."""
    fields_written = []
    unsupported = []

    try:
        audio = FLAC(file_path)

        for field_name, value in metadata.items():
            tag_name = VORBIS_FIELD_MAP.get(field_name)
            if not tag_name:
                unsupported.append(field_name)
                continue

            # Vorbis comments are simple key=value
            audio[tag_name] = str(value)
            fields_written.append(field_name)

        audio.save()

        return WriteResult(
            success=True,
            file_path=str(file_path),
            fields_written=fields_written,
            unsupported_fields=unsupported,
        )

    except Exception as e:
        logger.error(f"Error writing FLAC tags to {file_path}: {e}")
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=str(e),
        )


def _write_mp4_tags(file_path: Path, metadata: dict[str, Any]) -> WriteResult:
    """Write MP4 atoms to M4A/AAC file."""
    fields_written: list[str] = []
    unsupported: list[str] = []

    try:
        audio = MP4(file_path)
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        assert tags is not None

        for field_name, value in metadata.items():
            atom_name = MP4_FIELD_MAP.get(field_name)
            if not atom_name:
                unsupported.append(field_name)
                continue

            # Handle special cases for track/disc numbers (stored as tuples)
            if field_name == "track_number":
                # Get existing total if present
                existing = tags.get("trkn", [(0, 0)])
                total = existing[0][1] if existing else 0
                tags["trkn"] = [(int(value), total)]
            elif field_name == "disc_number":
                existing = tags.get("disk", [(0, 0)])
                total = existing[0][1] if existing else 0
                tags["disk"] = [(int(value), total)]
            else:
                tags[atom_name] = [str(value)]

            fields_written.append(field_name)

        audio.save()

        return WriteResult(
            success=True,
            file_path=str(file_path),
            fields_written=fields_written,
            unsupported_fields=unsupported,
        )

    except Exception as e:
        logger.error(f"Error writing MP4 tags to {file_path}: {e}")
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=str(e),
        )


def _write_ogg_tags(file_path: Path, metadata: dict[str, Any]) -> WriteResult:
    """Write Vorbis comments to OGG file."""
    fields_written = []
    unsupported = []

    try:
        audio = OggVorbis(file_path)

        for field_name, value in metadata.items():
            tag_name = VORBIS_FIELD_MAP.get(field_name)
            if not tag_name:
                unsupported.append(field_name)
                continue

            audio[tag_name] = str(value)
            fields_written.append(field_name)

        audio.save()

        return WriteResult(
            success=True,
            file_path=str(file_path),
            fields_written=fields_written,
            unsupported_fields=unsupported,
        )

    except Exception as e:
        logger.error(f"Error writing OGG tags to {file_path}: {e}")
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=str(e),
        )


def _write_aiff_tags(file_path: Path, metadata: dict[str, Any]) -> WriteResult:
    """Write ID3 tags to AIFF file."""
    fields_written: list[str] = []
    unsupported: list[str] = []

    try:
        audio = AIFF(file_path)

        # AIFF uses ID3 tags, but through the AIFF wrapper
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        assert tags is not None

        for field_name, value in metadata.items():
            frame_name = ID3_FIELD_MAP.get(field_name)
            if not frame_name:
                unsupported.append(field_name)
                continue

            # Similar to MP3 ID3 handling
            if field_name == "track_number":
                tags.delall("TRCK")
                tags.add(TRCK(encoding=3, text=str(value)))
            elif field_name == "disc_number":
                tags.delall("TPOS")
                tags.add(TPOS(encoding=3, text=str(value)))
            elif field_name == "year":
                tags.delall("TDRC")
                tags.add(TDRC(encoding=3, text=str(value)))
            elif field_name == "comment":
                tags.delall("COMM")
                tags.add(COMM(encoding=3, lang="eng", desc="", text=str(value)))
            elif field_name == "title":
                tags.delall("TIT2")
                tags.add(TIT2(encoding=3, text=str(value)))
            elif field_name == "artist":
                tags.delall("TPE1")
                tags.add(TPE1(encoding=3, text=str(value)))
            elif field_name == "album":
                tags.delall("TALB")
                tags.add(TALB(encoding=3, text=str(value)))
            elif field_name == "album_artist":
                tags.delall("TPE2")
                tags.add(TPE2(encoding=3, text=str(value)))
            elif field_name == "genre":
                tags.delall("TCON")
                tags.add(TCON(encoding=3, text=str(value)))
            elif field_name == "composer":
                tags.delall("TCOM")
                tags.add(TCOM(encoding=3, text=str(value)))
            elif field_name == "conductor":
                tags.delall("TPE3")
                tags.add(TPE3(encoding=3, text=str(value)))
            elif field_name == "lyricist":
                tags.delall("TEXT")
                tags.add(TEXT(encoding=3, text=str(value)))
            elif field_name == "grouping":
                tags.delall("TIT1")
                tags.add(TIT1(encoding=3, text=str(value)))
            elif field_name == "sort_artist":
                tags.delall("TSOP")
                tags.add(TSOP(encoding=3, text=str(value)))
            elif field_name == "sort_album":
                tags.delall("TSOA")
                tags.add(TSOA(encoding=3, text=str(value)))
            elif field_name == "sort_title":
                tags.delall("TSOT")
                tags.add(TSOT(encoding=3, text=str(value)))
            else:
                continue

            fields_written.append(field_name)

        audio.save()

        return WriteResult(
            success=True,
            file_path=str(file_path),
            fields_written=fields_written,
            unsupported_fields=unsupported,
        )

    except Exception as e:
        logger.error(f"Error writing AIFF tags to {file_path}: {e}")
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=str(e),
        )


def write_artwork(
    file_path: Path,
    image_data: bytes,
    mime_type: str = "image/jpeg",
) -> WriteResult:
    """Embed cover art in audio file.

    Args:
        file_path: Path to the audio file
        image_data: Raw image bytes
        mime_type: MIME type of the image (image/jpeg or image/png)

    Returns:
        WriteResult with success status
    """
    if not file_path.exists():
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=f"File not found: {file_path}",
        )

    suffix = file_path.suffix.lower()

    try:
        if suffix == ".mp3":
            return _write_id3_artwork(file_path, image_data, mime_type)
        elif suffix == ".flac":
            return _write_flac_artwork(file_path, image_data, mime_type)
        elif suffix in {".m4a", ".aac", ".mp4"}:
            return _write_mp4_artwork(file_path, image_data, mime_type)
        elif suffix == ".ogg":
            # OGG Vorbis doesn't support embedded artwork in the same way
            return WriteResult(
                success=False,
                file_path=str(file_path),
                error="OGG format does not support embedded artwork",
            )
        elif suffix in {".aiff", ".aif"}:
            return _write_aiff_artwork(file_path, image_data, mime_type)
        else:
            return WriteResult(
                success=False,
                file_path=str(file_path),
                error=f"Unsupported format for artwork: {suffix}",
            )
    except PermissionError:
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error="Permission denied: cannot write to file",
        )
    except Exception as e:
        logger.error(f"Error writing artwork to {file_path}: {e}")
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=str(e),
        )


def _write_id3_artwork(
    file_path: Path, image_data: bytes, mime_type: str
) -> WriteResult:
    """Write artwork to MP3 file as APIC frame."""
    try:
        try:
            tags = ID3(file_path)
        except ID3NoHeaderError:
            tags = ID3()

        # Remove existing artwork
        tags.delall("APIC")

        # Add new artwork (type 3 = front cover)
        tags.add(
            APIC(
                encoding=3,
                mime=mime_type,
                type=3,  # Front cover
                desc="Cover",
                data=image_data,
            )
        )

        tags.save(file_path)

        return WriteResult(
            success=True,
            file_path=str(file_path),
            fields_written=["artwork"],
        )

    except Exception as e:
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=str(e),
        )


def _write_flac_artwork(
    file_path: Path, image_data: bytes, mime_type: str
) -> WriteResult:
    """Write artwork to FLAC file as picture block."""
    try:
        audio = FLAC(file_path)

        # Remove existing pictures
        audio.clear_pictures()

        # Create new picture
        picture = Picture()
        picture.type = 3  # Front cover
        picture.mime = mime_type
        picture.desc = "Cover"
        picture.data = image_data

        audio.add_picture(picture)
        audio.save()

        return WriteResult(
            success=True,
            file_path=str(file_path),
            fields_written=["artwork"],
        )

    except Exception as e:
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=str(e),
        )


def _write_mp4_artwork(
    file_path: Path, image_data: bytes, mime_type: str
) -> WriteResult:
    """Write artwork to MP4/M4A file."""
    try:
        audio = MP4(file_path)
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        assert tags is not None

        # Determine image format
        if mime_type == "image/png":
            image_format = MP4Cover.FORMAT_PNG
        else:
            image_format = MP4Cover.FORMAT_JPEG

        # Set cover art
        tags["covr"] = [MP4Cover(image_data, imageformat=image_format)]
        audio.save()

        return WriteResult(
            success=True,
            file_path=str(file_path),
            fields_written=["artwork"],
        )

    except Exception as e:
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=str(e),
        )


def _write_aiff_artwork(
    file_path: Path, image_data: bytes, mime_type: str
) -> WriteResult:
    """Write artwork to AIFF file as APIC frame."""
    try:
        audio = AIFF(file_path)
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        assert tags is not None

        # Remove existing artwork
        tags.delall("APIC")

        # Add new artwork
        tags.add(
            APIC(
                encoding=3,
                mime=mime_type,
                type=3,
                desc="Cover",
                data=image_data,
            )
        )

        audio.save()

        return WriteResult(
            success=True,
            file_path=str(file_path),
            fields_written=["artwork"],
        )

    except Exception as e:
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=str(e),
        )


def remove_artwork(file_path: Path) -> WriteResult:
    """Remove embedded artwork from audio file.

    Args:
        file_path: Path to the audio file

    Returns:
        WriteResult with success status
    """
    if not file_path.exists():
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=f"File not found: {file_path}",
        )

    suffix = file_path.suffix.lower()

    try:
        if suffix == ".mp3":
            mp3_tags = ID3(file_path)
            mp3_tags.delall("APIC")
            mp3_tags.save(file_path)
        elif suffix == ".flac":
            flac_audio = FLAC(file_path)
            flac_audio.clear_pictures()
            flac_audio.save()
        elif suffix in {".m4a", ".aac", ".mp4"}:
            mp4_audio = MP4(file_path)
            if mp4_audio.tags and "covr" in mp4_audio.tags:
                del mp4_audio.tags["covr"]
                mp4_audio.save()
        elif suffix in {".aiff", ".aif"}:
            aiff_audio = AIFF(file_path)
            if aiff_audio.tags:
                aiff_audio.tags.delall("APIC")
                aiff_audio.save()
        else:
            return WriteResult(
                success=False,
                file_path=str(file_path),
                error=f"Unsupported format: {suffix}",
            )

        return WriteResult(
            success=True,
            file_path=str(file_path),
            fields_written=["artwork_removed"],
        )

    except Exception as e:
        logger.error(f"Error removing artwork from {file_path}: {e}")
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=str(e),
        )


def write_lyrics(file_path: Path, lyrics: str) -> WriteResult:
    """Write lyrics to audio file.

    Args:
        file_path: Path to the audio file
        lyrics: Lyrics text (plain text or synced LRC format)

    Returns:
        WriteResult with success status
    """
    if not file_path.exists():
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=f"File not found: {file_path}",
        )

    suffix = file_path.suffix.lower()

    try:
        if suffix == ".mp3":
            return _write_id3_lyrics(file_path, lyrics)
        elif suffix == ".flac":
            return _write_flac_lyrics(file_path, lyrics)
        elif suffix in {".m4a", ".aac", ".mp4"}:
            return _write_mp4_lyrics(file_path, lyrics)
        elif suffix == ".ogg":
            return _write_ogg_lyrics(file_path, lyrics)
        elif suffix in {".aiff", ".aif"}:
            return _write_aiff_lyrics(file_path, lyrics)
        else:
            return WriteResult(
                success=False,
                file_path=str(file_path),
                error=f"Unsupported format for lyrics: {suffix}",
            )
    except Exception as e:
        logger.error(f"Error writing lyrics to {file_path}: {e}")
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=str(e),
        )


def _write_id3_lyrics(file_path: Path, lyrics: str) -> WriteResult:
    """Write lyrics to MP3 file as USLT frame."""
    try:
        try:
            tags = ID3(file_path)
        except ID3NoHeaderError:
            tags = ID3()

        # Remove existing lyrics
        tags.delall("USLT")

        # Add new lyrics
        tags.add(
            USLT(
                encoding=3,
                lang="eng",
                desc="",
                text=lyrics,
            )
        )

        tags.save(file_path)

        return WriteResult(
            success=True,
            file_path=str(file_path),
            fields_written=["lyrics"],
        )

    except Exception as e:
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=str(e),
        )


def _write_flac_lyrics(file_path: Path, lyrics: str) -> WriteResult:
    """Write lyrics to FLAC file as LYRICS tag."""
    try:
        audio = FLAC(file_path)
        audio["LYRICS"] = lyrics
        audio.save()

        return WriteResult(
            success=True,
            file_path=str(file_path),
            fields_written=["lyrics"],
        )

    except Exception as e:
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=str(e),
        )


def _write_mp4_lyrics(file_path: Path, lyrics: str) -> WriteResult:
    """Write lyrics to MP4/M4A file."""
    try:
        audio = MP4(file_path)
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        assert tags is not None

        # MP4 lyrics atom
        tags["\xa9lyr"] = [lyrics]
        audio.save()

        return WriteResult(
            success=True,
            file_path=str(file_path),
            fields_written=["lyrics"],
        )

    except Exception as e:
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=str(e),
        )


def _write_ogg_lyrics(file_path: Path, lyrics: str) -> WriteResult:
    """Write lyrics to OGG file as LYRICS tag."""
    try:
        audio = OggVorbis(file_path)
        audio["LYRICS"] = lyrics
        audio.save()

        return WriteResult(
            success=True,
            file_path=str(file_path),
            fields_written=["lyrics"],
        )

    except Exception as e:
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=str(e),
        )


def _write_aiff_lyrics(file_path: Path, lyrics: str) -> WriteResult:
    """Write lyrics to AIFF file as USLT frame."""
    try:
        audio = AIFF(file_path)
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        assert tags is not None

        tags.delall("USLT")
        tags.add(
            USLT(
                encoding=3,
                lang="eng",
                desc="",
                text=lyrics,
            )
        )

        audio.save()

        return WriteResult(
            success=True,
            file_path=str(file_path),
            fields_written=["lyrics"],
        )

    except Exception as e:
        return WriteResult(
            success=False,
            file_path=str(file_path),
            error=str(e),
        )
