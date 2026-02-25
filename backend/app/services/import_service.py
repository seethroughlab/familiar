"""Music import service for handling zip files and folder imports."""

import logging
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import AUDIO_EXTENSIONS, MUSIC_LIBRARY_PATH
from app.services.artwork import extract_artwork
from app.services.metadata import extract_metadata

logger = logging.getLogger(__name__)

# Formats that need conversion (lossless uncompressed)
CONVERTIBLE_FORMATS = {".aiff", ".aif", ".wav"}

# Import session storage (in-memory for simplicity, could use Redis for persistence)
_import_sessions: dict[str, dict[str, Any]] = {}


class MusicImportError(Exception):
    """Import operation failed."""
    pass


class ImportService:
    """Handles importing music files from zip archives or folders."""

    def __init__(self, library_path: Path | None = None):
        self.library_path = library_path or MUSIC_LIBRARY_PATH
        self.imports_dir = self.library_path / "_imports"

    def create_import_dir(self) -> Path:
        """Create a timestamped import directory."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        import_dir = self.imports_dir / timestamp
        import_dir.mkdir(parents=True, exist_ok=True)
        return import_dir

    def extract_zip(self, zip_path: Path, dest_dir: Path) -> list[Path]:
        """Extract a zip file and return list of extracted audio files.

        Args:
            zip_path: Path to the zip file
            dest_dir: Directory to extract to

        Returns:
            List of extracted audio file paths
        """
        logger.info(f"Extracting zip: {zip_path}")

        if not zipfile.is_zipfile(zip_path):
            raise MusicImportError(f"Not a valid zip file: {zip_path}")

        extracted_audio = []

        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Check for malicious paths (zip slip vulnerability)
            for member in zf.namelist():
                member_path = Path(member)
                if member_path.is_absolute() or '..' in member_path.parts:
                    raise MusicImportError(f"Unsafe path in zip: {member}")

            # Extract all files
            zf.extractall(dest_dir)

            # Find audio files
            for member in zf.namelist():
                member_path = dest_dir / member
                if member_path.is_file():
                    ext = member_path.suffix.lower()
                    if ext in AUDIO_EXTENSIONS:
                        extracted_audio.append(member_path)
                        logger.info(f"  Found audio: {member_path.name}")

        logger.info(f"Extracted {len(extracted_audio)} audio files from zip")
        return extracted_audio

    def process_upload(self, file_path: Path, original_filename: str) -> dict[str, Any]:
        """Process an uploaded file (zip or audio).

        Args:
            file_path: Path to the uploaded file (in temp location)
            original_filename: Original filename from upload

        Returns:
            Dict with import results
        """
        import_dir = self.create_import_dir()

        try:
            if original_filename.lower().endswith('.zip'):
                # Extract zip file
                audio_files = self.extract_zip(file_path, import_dir)
            else:
                # Single audio file
                ext = Path(original_filename).suffix.lower()
                if ext not in AUDIO_EXTENSIONS:
                    raise MusicImportError(f"Unsupported file type: {ext}")

                # Move to import directory
                dest = import_dir / original_filename
                shutil.move(str(file_path), str(dest))
                audio_files = [dest]
                logger.info(f"Imported single file: {original_filename}")

            return {
                "status": "success",
                "import_path": str(import_dir),
                "files_found": len(audio_files),
                "files": [str(f.relative_to(import_dir)) for f in audio_files],
            }

        except Exception as e:
            # Clean up on failure
            if import_dir.exists():
                shutil.rmtree(import_dir, ignore_errors=True)
            raise MusicImportError(f"Import failed: {str(e)}") from e

    def process_local_directory(self, source_dir: Path) -> dict[str, Any]:
        """Import audio files from a local directory on the filesystem.

        Copies audio files (preserving subdirectory structure) into a
        timestamped import directory under _imports/.

        Args:
            source_dir: Path to the source directory containing audio files.

        Returns:
            Dict with import results (same format as process_upload).
        """
        if not source_dir.exists():
            raise MusicImportError(f"Source directory does not exist: {source_dir}")
        if not source_dir.is_dir():
            raise MusicImportError(f"Source path is not a directory: {source_dir}")

        import_dir = self.create_import_dir()

        try:
            # Copy the directory tree, filtering to only audio files
            def audio_filter(entry: str, entries: list[str]) -> set[str]:
                """Return entries to IGNORE (shutil.copytree ignore pattern)."""
                ignored = set()
                base = Path(entry)
                for name in entries:
                    full = base / name
                    if full.is_file() and full.suffix.lower() not in AUDIO_EXTENSIONS:
                        ignored.add(name)
                return ignored

            shutil.copytree(source_dir, import_dir, dirs_exist_ok=True, ignore=audio_filter)

            # Find all copied audio files
            audio_files = [
                f for f in import_dir.rglob("*")
                if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
            ]

            # Remove any empty directories left by filtering
            for dirpath in sorted(import_dir.rglob("*"), reverse=True):
                if dirpath.is_dir() and not any(dirpath.iterdir()):
                    dirpath.rmdir()

            if not audio_files:
                shutil.rmtree(import_dir, ignore_errors=True)
                raise MusicImportError(f"No audio files found in {source_dir}")

            return {
                "status": "success",
                "import_path": str(import_dir),
                "files_found": len(audio_files),
                "files": [str(f.relative_to(import_dir)) for f in audio_files],
            }

        except MusicImportError:
            raise
        except Exception as e:
            if import_dir.exists():
                shutil.rmtree(import_dir, ignore_errors=True)
            raise MusicImportError(f"Import failed: {str(e)}") from e

    def get_recent_imports(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get list of recent import directories."""
        if not self.imports_dir.exists():
            return []

        imports = []
        for import_dir in sorted(self.imports_dir.iterdir(), reverse=True)[:limit]:
            if import_dir.is_dir():
                # Count audio files
                audio_count = sum(
                    1 for f in import_dir.rglob("*")
                    if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
                )

                imports.append({
                    "name": import_dir.name,
                    "path": str(import_dir),
                    "file_count": audio_count,
                    "created_at": datetime.strptime(
                        import_dir.name, "%Y%m%d_%H%M%S"
                    ).isoformat() if import_dir.name[0].isdigit() else None,
                })

        return imports


def save_upload_to_temp(content: bytes, filename: str) -> Path:
    """Save uploaded file content to a temporary file.

    Args:
        content: File content as bytes
        filename: Original filename (for extension)

    Returns:
        Path to temporary file
    """
    suffix = Path(filename).suffix
    fd, temp_path = tempfile.mkstemp(suffix=suffix)

    try:
        with open(fd, 'wb') as f:
            f.write(content)
    except Exception:
        Path(temp_path).unlink(missing_ok=True)
        raise

    return Path(temp_path)


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


def embed_artwork(file_path: Path, artwork_data: bytes) -> bool:
    """Embed artwork into an audio file using mutagen.

    Args:
        file_path: Path to the audio file
        artwork_data: Raw image bytes (JPEG or PNG)

    Returns:
        True if successful
    """
    from io import BytesIO

    import mutagen
    from mutagen.flac import FLAC, Picture
    from mutagen.id3 import APIC, ID3
    from PIL import Image

    suffix = file_path.suffix.lower()

    try:
        # Get image dimensions for proper metadata
        img = Image.open(BytesIO(artwork_data))
        width, height = img.size
        # Determine color depth (bits per pixel)
        if img.mode == "RGB":
            color_depth = 24
        elif img.mode == "RGBA":
            color_depth = 32
        elif img.mode == "L":
            color_depth = 8
        else:
            color_depth = 24  # Default

        if suffix == ".flac":
            audio = FLAC(file_path)
            pic = Picture()
            pic.type = 3  # Front cover
            pic.mime = "image/jpeg"
            pic.desc = "Cover"
            pic.width = width
            pic.height = height
            pic.depth = color_depth
            pic.data = artwork_data
            audio.clear_pictures()
            audio.add_picture(pic)
            audio.save()
            return True

        elif suffix == ".mp3":
            try:
                tags = ID3(file_path)
            except mutagen.id3.ID3NoHeaderError:
                tags = ID3()

            # Remove existing artwork
            tags.delall("APIC")

            # Add new artwork
            tags.add(APIC(
                encoding=3,  # UTF-8
                mime="image/jpeg",
                type=3,  # Front cover
                desc="Cover",
                data=artwork_data,
            ))
            tags.save(file_path)
            return True

    except Exception as e:
        logger.error(f"Failed to embed artwork in {file_path}: {e}")

    return False


def convert_audio(
    input_path: Path,
    output_path: Path,
    target_format: str,
    mp3_bitrate: int = 320,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Convert audio file using ffmpeg.

    Args:
        input_path: Source audio file
        output_path: Destination path
        target_format: "flac" or "mp3"
        mp3_bitrate: Bitrate for MP3 (128, 192, 320)
        metadata: Optional metadata to override (copies source metadata first)

    Returns:
        True if successful
    """
    # Extract artwork from source file BEFORE conversion
    # (ffmpeg doesn't reliably copy artwork from AIFF/WAV)
    artwork_data = extract_artwork(input_path)

    cmd = ["ffmpeg", "-y", "-i", str(input_path)]

    # Copy metadata from source
    cmd.extend(["-map_metadata", "0"])

    # Override specific metadata if provided (only non-empty values)
    if metadata:
        if metadata.get("title"):
            cmd.extend(["-metadata", f"title={metadata['title']}"])
        if metadata.get("artist"):
            cmd.extend(["-metadata", f"artist={metadata['artist']}"])
        if metadata.get("album"):
            cmd.extend(["-metadata", f"album={metadata['album']}"])
        if metadata.get("track_num"):
            cmd.extend(["-metadata", f"track={metadata['track_num']}"])
        if metadata.get("year"):
            cmd.extend(["-metadata", f"date={metadata['year']}"])

    if target_format == "flac":
        cmd.extend(["-c:a", "flac", "-compression_level", "8"])
    elif target_format == "mp3":
        cmd.extend(["-c:a", "libmp3lame", "-b:a", f"{mp3_bitrate}k"])
        # Ensure ID3v2 tags are written
        cmd.extend(["-id3v2_version", "3"])

    cmd.append(str(output_path))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout per file
        )
        if result.returncode != 0:
            logger.error(f"ffmpeg conversion failed: {result.stderr}")
            return False

        # Re-embed artwork into the converted file using mutagen
        if artwork_data:
            embed_artwork(output_path, artwork_data)

        return True
    except subprocess.TimeoutExpired:
        logger.error(f"ffmpeg conversion timed out for {input_path}")
        return False
    except Exception as e:
        logger.error(f"ffmpeg conversion error: {e}")
        return False


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


class ImportExecuteService:
    """Handles executing an import with user-specified options."""

    def __init__(self, library_path: Path | None = None):
        self.library_path = library_path or MUSIC_LIBRARY_PATH

    def execute_import(
        self,
        session_id: str,
        tracks: list[dict[str, Any]],
        options: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute import with user-specified metadata and options.

        Args:
            session_id: Preview session ID
            tracks: List of tracks with user-edited metadata
            options: Import options (format, organization, etc.)

        Returns:
            Import result with status and imported file list
        """
        session = _import_sessions.get(session_id)
        if not session:
            raise MusicImportError(f"Import session not found: {session_id}")

        temp_dir = Path(session["temp_dir"])
        if not temp_dir.exists():
            raise MusicImportError("Import session expired - files no longer available")

        target_format = options.get("format", "original")
        mp3_quality = options.get("mp3_quality", 320)
        organization = options.get("organization", "imports")
        queue_analysis = options.get("queue_analysis", True)

        # Determine destination directory
        if organization == "organized":
            # Will create Artist/Album structure
            base_dest = self.library_path
        else:
            # Create timestamped _imports folder
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_dest = self.library_path / "_imports" / timestamp
            base_dest.mkdir(parents=True, exist_ok=True)

        imported_files = []
        errors = []
        imported_dirs: set[Path] = set()  # Track unique album directories for scanning
        replaced_tracks: list[dict[str, Any]] = []  # Tracks that replaced existing ones

        # Create lookup from original session tracks
        session_tracks = {t["relative_path"]: t for t in session["tracks"]}

        for track in tracks:
            try:
                # Check action - skip tracks with action="skip"
                action = track.get("action", "import")
                if action == "skip":
                    continue

                relative_path = track.get("relative_path") or track.get("filename")
                source_path = temp_dir / relative_path

                if not source_path.exists():
                    errors.append(f"Source file not found: {relative_path}")
                    continue

                # Get original track info for format
                orig_info = session_tracks.get(relative_path, {})
                orig_format = orig_info.get("format", source_path.suffix.lower().lstrip("."))

                # Determine output format and extension
                needs_conversion = False
                output_ext = f".{orig_format}"

                if target_format == "flac" and orig_format.lower() in ["aiff", "aif", "wav"]:
                    needs_conversion = True
                    output_ext = ".flac"
                elif target_format == "mp3" and orig_format.lower() in ["aiff", "aif", "wav", "flac"]:
                    needs_conversion = True
                    output_ext = ".mp3"

                # Get actual metadata values (may be None if not provided)
                meta_artist = track.get("artist") or track.get("detected_artist")
                meta_album = track.get("album") or track.get("detected_album")
                meta_title = track.get("title") or track.get("detected_title")
                meta_track_num = track.get("track_num") or track.get("detected_track_num")
                meta_year = track.get("year") or track.get("detected_year")

                # For file organization, use fallbacks
                file_artist = meta_artist or "Unknown Artist"
                file_album = meta_album or "Unknown Album"
                file_title = meta_title or source_path.stem

                # Sanitize for filesystem
                def sanitize(s: str) -> str:
                    return re.sub(r'[<>:"/\\|?*]', "_", s)[:200]

                if organization == "organized":
                    # Artist/Album/## - Title.ext
                    dest_dir = base_dest / sanitize(file_artist) / sanitize(file_album)
                    if meta_track_num:
                        filename = f"{meta_track_num:02d} - {sanitize(file_title)}{output_ext}"
                    else:
                        filename = f"{sanitize(file_title)}{output_ext}"
                else:
                    # Flat in _imports folder
                    dest_dir = base_dest
                    filename = f"{sanitize(file_artist)} - {sanitize(file_title)}{output_ext}"

                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_path = dest_dir / filename

                # Handle duplicates
                counter = 1
                while dest_path.exists():
                    stem = dest_path.stem
                    dest_path = dest_dir / f"{stem} ({counter}){output_ext}"
                    counter += 1

                # Convert or copy
                if needs_conversion:
                    # Only pass metadata values that are actually set (not fallbacks)
                    # ffmpeg will copy source metadata first, we only override specifics
                    metadata = {
                        "title": meta_title,
                        "artist": meta_artist,
                        "album": meta_album,
                        "track_num": meta_track_num,
                        "year": meta_year,
                    }
                    success = convert_audio(
                        source_path,
                        dest_path,
                        "flac" if target_format == "flac" else "mp3",
                        mp3_bitrate=mp3_quality,
                        metadata=metadata,
                    )
                    if not success:
                        errors.append(f"Conversion failed: {relative_path}")
                        continue
                else:
                    shutil.copy2(source_path, dest_path)

                imported_files.append(str(dest_path.relative_to(self.library_path)))
                imported_dirs.add(dest_dir)

                # Track replacement info if this is replacing an existing track
                if action == "replace" and track.get("replace_track_id"):
                    replaced_tracks.append({
                        "track_id": track["replace_track_id"],
                        "new_file_path": str(dest_path),
                    })

            except Exception as e:
                errors.append(f"Failed to import {track.get('filename', 'unknown')}: {str(e)}")
                logger.error(f"Import error: {e}")

        # Clean up session (skip rmtree for local-path sessions)
        try:
            if not session.get("is_local_path"):
                shutil.rmtree(temp_dir, ignore_errors=True)
            del _import_sessions[session_id]
        except Exception:
            pass

        # Return specific imported directories for targeted scanning
        # This prevents full library scan when using "organized" structure
        scan_paths = [
            str(d.relative_to(self.library_path)) for d in imported_dirs
        ] if imported_dirs else []

        return {
            "status": "completed" if not errors else "completed_with_errors",
            "imported_count": len(imported_files),
            "imported_files": imported_files,
            "errors": errors,
            "base_path": str(base_dest.relative_to(self.library_path)),
            "scan_paths": scan_paths,  # Specific directories to scan
            "queue_analysis": queue_analysis,
            "replaced_tracks": replaced_tracks,  # Tracks that replaced existing ones
        }


def cleanup_expired_sessions(max_age_hours: int = 24) -> int:
    """Clean up expired import sessions.

    Returns number of sessions cleaned up.
    """
    now = datetime.now()
    expired = []

    for session_id, session in _import_sessions.items():
        created = datetime.fromisoformat(session["created_at"])
        if (now - created).total_seconds() > max_age_hours * 3600:
            expired.append(session_id)

    for session_id in expired:
        session = _import_sessions.pop(session_id, None)
        if session:
            temp_dir = Path(session["temp_dir"])
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    return len(expired)
