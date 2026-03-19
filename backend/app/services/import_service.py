"""Music import service for handling zip files and folder imports."""

import logging
import re
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import AUDIO_EXTENSIONS
from app.services.metadata import extract_metadata

logger = logging.getLogger(__name__)

# Formats that need conversion (lossless uncompressed)
CONVERTIBLE_FORMATS = {".aiff", ".aif", ".wav"}

# Import session storage (in-memory for simplicity, could use Redis for persistence)
_import_sessions: dict[str, dict[str, Any]] = {}


class MusicImportError(Exception):
    """Import operation failed."""
    pass


def parse_filename_metadata(filepath: Path) -> dict[str, Any]:
    """Try to extract metadata from filename patterns.

    Patterns tried:
    - "Artist - Title.ext"
    - "## - Title.ext" or "## Title.ext" (track number)
    - Folder structure: "Artist/Album/## - Title.ext"
    """
    result: dict[str, Any] = {
        "detected_artist": None,
        "detected_album": None,
        "detected_title": None,
        "detected_track_num": None,
    }

    filename = filepath.stem
    parent = filepath.parent.name
    grandparent = filepath.parent.parent.name if filepath.parent.parent != filepath.parent else None

    # Try "Artist - Title" pattern
    if " - " in filename:
        parts = filename.split(" - ", 1)
        # Check if first part is a track number
        if re.match(r"^\d{1,2}$", parts[0].strip()):
            result["detected_track_num"] = int(parts[0].strip())
            result["detected_title"] = parts[1].strip()
        else:
            result["detected_artist"] = parts[0].strip()
            result["detected_title"] = parts[1].strip()

    # Try "## Title" or "##. Title" pattern
    track_match = re.match(r"^(\d{1,2})[\.\s\-_]+(.+)$", filename)
    if track_match and not result["detected_title"]:
        result["detected_track_num"] = int(track_match.group(1))
        result["detected_title"] = track_match.group(2).strip()

    # If no title yet, use filename
    if not result["detected_title"]:
        result["detected_title"] = filename

    # Try folder structure for artist/album
    if parent and parent not in (".", "_imports") and not parent.startswith("20"):
        # Parent could be album
        if grandparent and grandparent not in (".", "_imports") and not grandparent.startswith("20"):
            result["detected_artist"] = grandparent
            result["detected_album"] = parent
        else:
            # Parent might be artist or album
            result["detected_album"] = parent

    return result


def estimate_converted_size(original_size: int, original_format: str, target_format: str) -> int:
    """Estimate file size after conversion.

    These are rough estimates based on typical compression ratios.
    """
    # Compression ratios relative to uncompressed (WAV/AIFF)
    ratios = {
        "aiff": 1.0,
        "aif": 1.0,
        "wav": 1.0,
        "flac": 0.55,  # ~55% of original
        "mp3_320": 0.18,  # ~18% of original
        "mp3_192": 0.11,
        "mp3_128": 0.08,
    }

    orig_fmt = original_format.lower().lstrip(".")

    # If original is already compressed, estimate based on that
    if orig_fmt in ("mp3", "m4a", "aac", "ogg"):
        # Already compressed - keep original for most conversions
        if target_format == "original":
            return original_size
        elif target_format == "flac":
            # MP3 to FLAC doesn't make sense, but estimate larger
            return int(original_size * 3)
        else:
            return original_size

    # For uncompressed formats
    if target_format == "original":
        return original_size
    elif target_format == "flac":
        return int(original_size * ratios["flac"])
    elif target_format.startswith("mp3"):
        quality = target_format.split("_")[1] if "_" in target_format else "320"
        return int(original_size * ratios.get(f"mp3_{quality}", 0.18))

    return original_size


class ImportPreviewService:
    """Handles import preview - extracting metadata without actually importing."""

    def __init__(self):
        self.temp_dir: Path | None = None
        self.session_id: str | None = None

    def create_preview_session(self, file_path: Path, original_filename: str) -> dict[str, Any]:
        """Create a preview session from uploaded file.

        Extracts files (if zip) to temp location and scans metadata.
        Returns preview data with session_id for later execution.
        """
        self.session_id = str(uuid.uuid4())
        self.temp_dir = Path(tempfile.mkdtemp(prefix=f"familiar_import_{self.session_id}_"))

        tracks = []
        total_size = 0

        try:
            if original_filename.lower().endswith('.zip'):
                # Extract zip to temp dir
                if not zipfile.is_zipfile(file_path):
                    raise MusicImportError("Not a valid zip file")

                with zipfile.ZipFile(file_path, 'r') as zf:
                    # Security check
                    for member in zf.namelist():
                        member_path = Path(member)
                        if member_path.is_absolute() or '..' in member_path.parts:
                            raise MusicImportError(f"Unsafe path in zip: {member}")

                    zf.extractall(self.temp_dir)

                # Find all audio files
                for audio_file in self.temp_dir.rglob("*"):
                    if audio_file.is_file() and audio_file.suffix.lower() in AUDIO_EXTENSIONS:
                        track_info = self._extract_track_info(audio_file)
                        tracks.append(track_info)
                        total_size += track_info["file_size_bytes"]
            else:
                # Single file - copy to temp dir
                ext = Path(original_filename).suffix.lower()
                if ext not in AUDIO_EXTENSIONS:
                    raise MusicImportError(f"Unsupported file type: {ext}")

                dest = self.temp_dir / original_filename
                shutil.copy2(file_path, dest)

                track_info = self._extract_track_info(dest)
                tracks.append(track_info)
                total_size = track_info["file_size_bytes"]

            # Sort tracks by detected track number, then filename
            tracks.sort(key=lambda t: (t["detected_track_num"] or 999, t["filename"]))

            # Estimate sizes for different formats
            has_convertible = any(
                t["format"].lower() in [f.lstrip(".") for f in CONVERTIBLE_FORMATS]
                for t in tracks
            )

            estimated_sizes = {
                "original": total_size,
                "flac": sum(
                    estimate_converted_size(t["file_size_bytes"], t["format"], "flac")
                    for t in tracks
                ),
                "mp3_320": sum(
                    estimate_converted_size(t["file_size_bytes"], t["format"], "mp3_320")
                    for t in tracks
                ),
            }

            # Store session for later execution
            _import_sessions[self.session_id] = {
                "temp_dir": str(self.temp_dir),
                "tracks": tracks,
                "created_at": datetime.now().isoformat(),
            }

            return {
                "session_id": self.session_id,
                "tracks": tracks,
                "total_size_bytes": total_size,
                "estimated_sizes": estimated_sizes,
                "has_convertible_formats": has_convertible,
            }

        except Exception as e:
            # Clean up on error
            if self.temp_dir and self.temp_dir.exists():
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            raise MusicImportError(f"Preview failed: {str(e)}") from e

    def create_preview_from_path(self, source_path: Path) -> dict[str, Any]:
        """Create a preview session from a local directory path.

        Unlike create_preview_session, this does NOT copy files - it reads
        them in-place and marks the session as is_local_path so execute
        won't delete the source.
        """
        if not source_path.exists():
            raise MusicImportError(f"Source directory does not exist: {source_path}")
        if not source_path.is_dir():
            raise MusicImportError(f"Source path is not a directory: {source_path}")

        self.session_id = str(uuid.uuid4())
        self.temp_dir = source_path  # Point directly at source

        tracks = []
        total_size = 0

        try:
            for audio_file in source_path.rglob("*"):
                if audio_file.is_file() and audio_file.suffix.lower() in AUDIO_EXTENSIONS:
                    track_info = self._extract_track_info(audio_file)
                    tracks.append(track_info)
                    total_size += track_info["file_size_bytes"]

            if not tracks:
                raise MusicImportError(f"No audio files found in {source_path}")

            tracks.sort(key=lambda t: (t["detected_track_num"] or 999, t["filename"]))

            has_convertible = any(
                t["format"].lower() in [f.lstrip(".") for f in CONVERTIBLE_FORMATS]
                for t in tracks
            )

            estimated_sizes = {
                "original": total_size,
                "flac": sum(
                    estimate_converted_size(t["file_size_bytes"], t["format"], "flac")
                    for t in tracks
                ),
                "mp3_320": sum(
                    estimate_converted_size(t["file_size_bytes"], t["format"], "mp3_320")
                    for t in tracks
                ),
            }

            _import_sessions[self.session_id] = {
                "temp_dir": str(self.temp_dir),
                "tracks": tracks,
                "created_at": datetime.now().isoformat(),
                "is_local_path": True,
            }

            return {
                "session_id": self.session_id,
                "tracks": tracks,
                "total_size_bytes": total_size,
                "estimated_sizes": estimated_sizes,
                "has_convertible_formats": has_convertible,
            }

        except MusicImportError:
            raise
        except Exception as e:
            raise MusicImportError(f"Preview failed: {str(e)}") from e

    def _extract_track_info(self, audio_path: Path) -> dict[str, Any]:
        """Extract full track info including metadata."""
        # Get file metadata using existing service
        file_metadata = extract_metadata(audio_path)

        # Get filename-based metadata
        filename_metadata = parse_filename_metadata(audio_path)

        # Merge - prefer embedded tags, fall back to filename
        return {
            "filename": audio_path.name,
            "relative_path": str(audio_path.relative_to(self.temp_dir)) if self.temp_dir else audio_path.name,
            "detected_artist": file_metadata.get("artist") or filename_metadata["detected_artist"],
            "detected_album": file_metadata.get("album") or filename_metadata["detected_album"],
            "detected_title": file_metadata.get("title") or filename_metadata["detected_title"],
            "detected_track_num": file_metadata.get("track_number") or filename_metadata["detected_track_num"],
            "detected_year": file_metadata.get("year"),
            "format": file_metadata.get("format") or audio_path.suffix.lower().lstrip("."),
            "duration_seconds": file_metadata.get("duration_seconds"),
            "file_size_bytes": audio_path.stat().st_size,
            "sample_rate": file_metadata.get("sample_rate"),
            "bit_depth": file_metadata.get("bit_depth"),
            "bitrate": file_metadata.get("bitrate"),
            "bitrate_mode": file_metadata.get("bitrate_mode"),
        }
