"""Library scanner service for discovering and tracking audio files."""

import asyncio
import hashlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AUDIO_EXTENSIONS
from app.db.models import Track, TrackStatus


class LibraryValidationError(Exception):
    """Raised when library path validation fails."""

    pass


class EmptyLibraryError(LibraryValidationError):
    """Raised when library path is empty or has no audio files."""

    pass


@dataclass
class LibraryValidation:
    """Result of library path validation before scan."""

    path: Path
    exists: bool
    is_directory: bool
    is_readable: bool
    is_empty: bool
    file_count: int  # Quick count of immediate files (not recursive)
    dir_count: int  # Quick count of immediate subdirs
    error: str | None = None


def validate_library_path(library_path: Path) -> LibraryValidation:
    """Validate library path before scanning.

    Performs quick checks to catch misconfigured or unmounted volumes
    BEFORE attempting a full scan that could delete all tracks.

    Checks:
    1. Path exists
    2. Path is a directory
    3. Path is readable
    4. Path has content (files or subdirectories)
    5. For /Volumes/* paths on macOS, warns about potential unmount
    """
    if not library_path.exists():
        return LibraryValidation(
            path=library_path,
            exists=False,
            is_directory=False,
            is_readable=False,
            is_empty=True,
            file_count=0,
            dir_count=0,
            error=f"Path does not exist: {library_path}",
        )

    if not library_path.is_dir():
        return LibraryValidation(
            path=library_path,
            exists=True,
            is_directory=False,
            is_readable=False,
            is_empty=True,
            file_count=0,
            dir_count=0,
            error=f"Path is not a directory: {library_path}",
        )

    # Check readability
    try:
        contents = list(library_path.iterdir())
    except PermissionError:
        return LibraryValidation(
            path=library_path,
            exists=True,
            is_directory=True,
            is_readable=False,
            is_empty=True,
            file_count=0,
            dir_count=0,
            error=f"Permission denied: cannot read {library_path}",
        )

    file_count = sum(1 for c in contents if c.is_file())
    dir_count = sum(1 for c in contents if c.is_dir())
    is_empty = file_count == 0 and dir_count == 0

    # Check for unmounted volume on macOS
    error = None
    path_str = str(library_path)
    if path_str.startswith("/Volumes/") and is_empty:
        error = f"Volume appears unmounted or empty: {library_path}"

    return LibraryValidation(
        path=library_path,
        exists=True,
        is_directory=True,
        is_readable=True,
        is_empty=is_empty,
        file_count=file_count,
        dir_count=dir_count,
        error=error,
    )

logger = logging.getLogger(__name__)

# Thread pool for blocking file I/O operations
_file_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="scanner-io")

# Lowercase extensions for fast lookup
_AUDIO_EXT_LOWER = {ext.lower() for ext in AUDIO_EXTENSIONS}


def compute_file_hash(path: Path, chunk_size: int = 8192) -> str:
    """Compute SHA-256 hash of file for change detection.

    Uses first and last chunks plus file size for speed on large files.
    """
    file_size = path.stat().st_size
    hasher = hashlib.sha256()

    with open(path, "rb") as f:
        # Hash first chunk
        hasher.update(f.read(chunk_size))

        # Hash last chunk if file is large enough
        if file_size > chunk_size * 2:
            f.seek(-chunk_size, 2)  # Seek to last chunk
            hasher.update(f.read(chunk_size))

        # Include file size in hash
        hasher.update(str(file_size).encode())

    return hasher.hexdigest()


def _discover_files_sync(library_path: Path, progress_callback=None) -> list[Path]:
    """Synchronous file discovery using single-pass os.walk (runs in thread pool).

    Much faster than multiple rglob calls, especially on network volumes.
    Logs progress every 500 directories scanned.

    Args:
        library_path: Root directory to scan
        progress_callback: Optional callable(dirs_scanned, files_found) for progress updates
    """
    files: list[Path] = []
    dirs_scanned = 0

    logger.info(f"Starting single-pass directory walk of {library_path}")

    for root, dirs, filenames in os.walk(library_path):
        dirs_scanned += 1

        # Log and report progress every 25 directories (more frequent for slow network mounts)
        if dirs_scanned % 25 == 0:
            logger.info(f"Discovery progress: scanned {dirs_scanned} directories, found {len(files)} audio files so far...")
            if progress_callback:
                progress_callback(dirs_scanned, len(files))

        # Check each file in this directory
        for filename in filenames:
            # Fast extension check (case-insensitive)
            ext = os.path.splitext(filename)[1].lower()
            if ext in _AUDIO_EXT_LOWER:
                files.append(Path(root) / filename)

    logger.info(f"Discovery complete: scanned {dirs_scanned} directories, found {len(files)} audio files")
    # Final progress update
    if progress_callback:
        progress_callback(dirs_scanned, len(files))
    return sorted(files)


def _get_file_info_sync(file_path: Path) -> tuple[str, datetime, int]:
    """Get file hash, mtime, and size (runs in thread pool)."""
    stat = file_path.stat()
    file_hash = compute_file_hash(file_path)
    file_mtime = datetime.fromtimestamp(stat.st_mtime)
    return file_hash, file_mtime, stat.st_size


def _extract_metadata_sync(file_path: Path) -> dict[str, Any]:
    """Extract metadata from file (runs in thread pool)."""
    from app.services.metadata import extract_metadata
    return extract_metadata(file_path)


class LibraryScanner:
    """Scans music library directories for audio files."""

    def __init__(self, db: AsyncSession, scan_state=None):
        self.db = db
        self.scan_state = scan_state  # Optional ScanState for progress updates

    async def scan(
        self,
        library_path: Path,
        reread_unchanged: bool = False,
        reanalyze_changed: bool = True,
        # Legacy parameter
        full_scan: bool | None = None,
    ) -> dict[str, Any]:
        """Scan library for new, changed, or deleted files.

        Args:
            library_path: Root directory to scan
            reread_unchanged: Re-read metadata for files even if unchanged
            reanalyze_changed: Queue changed files for audio analysis
            full_scan: Deprecated. Use reread_unchanged instead.

        Returns:
            Dict with scan results: total, new, updated, deleted, queued
        """
        # Handle legacy parameter
        if full_scan is not None:
            reread_unchanged = full_scan
        # Validate library path before scanning
        validation = validate_library_path(library_path)
        if not validation.exists:
            raise LibraryValidationError(f"Library path does not exist: {library_path}")
        if not validation.is_directory:
            raise LibraryValidationError(f"Library path is not a directory: {library_path}")
        if not validation.is_readable:
            raise LibraryValidationError(f"Library path is not readable: {library_path}")
        if validation.is_empty:
            raise EmptyLibraryError(
                f"Library path is empty or has no content: {library_path}. "
                "This may indicate an unmounted volume or misconfigured path. "
                "Scan aborted to prevent accidental track deletion."
            )

        loop = asyncio.get_event_loop()

        # Get all existing tracks from database
        logger.info("Loading existing tracks from database...")
        existing_tracks = await self._get_existing_tracks()
        existing_paths = {t.file_path: t for t in existing_tracks}

        # Build hash lookup for detecting relocated files (same content, different path)
        # First track wins in case of hash collisions (shouldn't happen normally)
        existing_hashes: dict[str, Track] = {}
        for t in existing_tracks:
            if t.file_hash and t.file_hash not in existing_hashes:
                existing_hashes[t.file_hash] = t

        logger.info(f"Found {len(existing_tracks)} existing tracks in database ({len(existing_hashes)} unique hashes)")

        # Find all audio files (in thread pool to not block)
        logger.info(f"Discovering audio files in {library_path}...")

        # Create progress callback that updates scan_state
        def discovery_progress(dirs_scanned: int, files_found: int):
            if self.scan_state:
                self.scan_state.set_discovery(dirs_scanned, files_found)

        found_files = await loop.run_in_executor(
            _file_executor, _discover_files_sync, library_path, discovery_progress
        )
        found_paths = {str(p) for p in found_files}
        logger.info(f"Discovered {len(found_files)} audio files")

        results = {
            "total": len(found_files),
            "new": 0,
            "updated": 0,
            "unchanged": 0,
            "queued": 0,
            "marked_missing": 0,  # Newly marked as missing this scan
            "still_missing": 0,   # Already missing, still not found
            "recovered": 0,       # Previously missing, now found
            "relocated": 0,       # Found at different path
        }

        # Track IDs to queue for analysis after commit
        pending_analysis_ids: list[str] = []

        # Track newly created tracks for external track matching
        new_tracks: list[Track] = []

        # Process found files
        processed = 0
        for file_path in found_files:
            path_str = str(file_path)
            processed += 1

            # Update progress state
            if self.scan_state and processed % 10 == 0:
                self.scan_state.set_processing(
                    processed=processed,
                    total=len(found_files),
                    new=results["new"],
                    updated=results["updated"],
                    unchanged=results["unchanged"],
                    current=file_path.name,
                    recovered=results["recovered"],
                )

            # Log progress every 100 files
            if processed % 100 == 0:
                logger.info(f"Progress: {processed}/{len(found_files)} files ({results['new']} new, {results['updated']} updated, {results['unchanged']} unchanged)")

            # Get file info in thread pool
            file_hash, file_mtime, file_size = await loop.run_in_executor(
                _file_executor, _get_file_info_sync, file_path
            )

            if path_str not in existing_paths:
                # Path not found - check if same file exists at different path (by hash)
                if file_hash in existing_hashes:
                    # Found by hash - this is a relocated file, update its path
                    existing = existing_hashes[file_hash]
                    old_path = existing.file_path
                    logger.info(f"RELOCATED (by hash): {Path(old_path).name} -> {path_str}")
                    existing.file_path = path_str
                    existing.status = TrackStatus.ACTIVE
                    existing.missing_since = None
                    results["relocated"] += 1
                    # Update path lookup so we don't process old path as missing
                    existing_paths[path_str] = existing
                    if old_path in existing_paths:
                        del existing_paths[old_path]
                else:
                    # Truly new file
                    logger.info(f"NEW: {file_path.name}")
                    track = await self._create_track(file_path, file_hash, file_mtime, file_size)
                    pending_analysis_ids.append(str(track.id))
                    new_tracks.append(track)
                    results["new"] += 1
                    results["queued"] += 1
                    # Add to hash lookup so subsequent files with same hash are detected
                    existing_hashes[file_hash] = track
            else:
                existing = existing_paths[path_str]

                # Check if track was previously missing and is now recovered
                if existing.status in (TrackStatus.MISSING, TrackStatus.PENDING_DELETION):
                    logger.info(f"RECOVERED: {file_path.name}")
                    existing.status = TrackStatus.ACTIVE
                    existing.missing_since = None
                    results["recovered"] += 1

                file_changed = existing.file_hash != file_hash
                if reread_unchanged or file_changed:
                    # Re-read metadata (reread_unchanged=True or file changed)
                    logger.info(f"UPDATED: {file_path.name}")
                    # Only reset analysis if file content actually changed AND reanalyze_changed is True
                    reset_analysis = file_changed and reanalyze_changed
                    track = await self._update_track(
                        existing, file_hash, file_mtime, file_size, reset_analysis=reset_analysis
                    )
                    if reset_analysis:
                        pending_analysis_ids.append(str(track.id))
                        results["queued"] += 1
                    results["updated"] += 1
                else:
                    # Backfill file_size if missing (for tracks added before this column existed)
                    if existing.file_size is None:
                        existing.file_size = file_size
                    results["unchanged"] += 1

            # Commit periodically to make tracks visible and free memory
            if processed % 50 == 0:
                await self.db.commit()
                # Note: Analysis is now queued after scan completes via queue_unanalyzed_tracks
                pending_analysis_ids = []
                await asyncio.sleep(0)

        # Commit any remaining tracks from the last batch
        if pending_analysis_ids:
            await self.db.commit()
            # Note: Analysis is now queued after scan completes via queue_unanalyzed_tracks
            pending_analysis_ids = []

        # Handle missing files - only check files that were under this library_path
        library_prefix = str(library_path)
        missing_paths = set(
            p for p in existing_paths.keys()
            if p.startswith(library_prefix)
        ) - found_paths

        if missing_paths:
            logger.info(f"Found {len(missing_paths)} missing files, searching for relocated files...")

        # Build filename -> path map for relocated file search
        filename_to_path: dict[str, str] = {}
        for path_str in found_paths:
            filename = Path(path_str).name.lower()
            # Only use first occurrence to avoid ambiguity
            if filename not in filename_to_path:
                filename_to_path[filename] = path_str

        now = datetime.now()
        for path_str in missing_paths:
            track = existing_paths[path_str]
            filename = Path(path_str).name.lower()

            # Check if file exists at a new location
            if filename in filename_to_path:
                new_path = filename_to_path[filename]
                # Verify it's not already tracked by another record
                if new_path not in existing_paths:
                    logger.info(f"RELOCATED: {Path(path_str).name} -> {new_path}")
                    track.file_path = new_path
                    # If it was missing, recover it
                    if track.status in (TrackStatus.MISSING, TrackStatus.PENDING_DELETION):
                        track.status = TrackStatus.ACTIVE
                        track.missing_since = None
                        results["recovered"] += 1
                    results["relocated"] += 1
                    continue

            # File not found - mark as missing instead of deleting
            if track.status == TrackStatus.ACTIVE:
                # First time this track is missing
                logger.info(f"MISSING: {Path(path_str).name}")
                track.status = TrackStatus.MISSING
                track.missing_since = now
                results["marked_missing"] += 1
            elif track.status == TrackStatus.MISSING:
                # Already missing, check if >30 days
                if track.missing_since and (now - track.missing_since).days >= 30:
                    logger.info(f"PENDING_DELETION: {Path(path_str).name} (missing >30 days)")
                    track.status = TrackStatus.PENDING_DELETION
                results["still_missing"] += 1
            else:
                # PENDING_DELETION - stays in that state until user confirms
                results["still_missing"] += 1

        # Update cleanup progress with final counts
        if self.scan_state and (results["marked_missing"] > 0 or results["still_missing"] > 0):
            self.scan_state.set_cleanup(results["marked_missing"], results["still_missing"])

        await self.db.commit()

        logger.info(
            f"Scan complete: {results['new']} new, {results['updated']} updated, "
            f"{results['relocated']} relocated, {results['recovered']} recovered, "
            f"{results['marked_missing']} marked missing, {results['still_missing']} still missing, "
            f"{results['unchanged']} unchanged"
        )

        # Match new tracks to external tracks (and replace in playlists)
        if new_tracks:
            try:
                from app.services.external_track_matcher import ExternalTrackMatcher

                matcher = ExternalTrackMatcher(self.db)
                total_matched = 0
                for track in new_tracks:
                    matched_externals = await matcher.match_new_local_track(track, commit=False)
                    total_matched += len(matched_externals)
                await self.db.commit()

                if total_matched > 0:
                    logger.info(
                        f"Matched {total_matched} external tracks to {len(new_tracks)} new library additions"
                    )
                    results["external_matched"] = total_matched
            except Exception as e:
                logger.warning(f"External track matching failed (non-fatal): {e}")

        return results

    async def cleanup_orphaned_tracks(self, configured_paths: list[Path]) -> dict[str, int]:
        """Mark tracks as missing if they're not under any configured library path.

        This handles the case where a library path is removed from config -
        tracks from that path should be marked as missing.
        """
        from datetime import datetime

        results = {"orphaned": 0}
        now = datetime.now()

        # Get all active tracks
        result = await self.db.execute(
            select(Track).where(Track.status == TrackStatus.ACTIVE)
        )
        active_tracks = list(result.scalars().all())

        # Convert configured paths to strings for prefix matching
        path_prefixes = [str(p) for p in configured_paths]

        for track in active_tracks:
            # Check if track is under any configured path
            is_under_configured_path = any(
                track.file_path.startswith(prefix) for prefix in path_prefixes
            )

            if not is_under_configured_path:
                logger.info(f"ORPHANED: {track.file_path} (not under any configured library path)")
                track.status = TrackStatus.MISSING
                track.missing_since = now
                results["orphaned"] += 1

        if results["orphaned"] > 0:
            await self.db.commit()
            logger.info(f"Marked {results['orphaned']} orphaned tracks as missing")

        return results

    async def _get_existing_tracks(self) -> list[Track]:
        """Get all tracks currently in database."""
        result = await self.db.execute(select(Track))
        return list(result.scalars().all())

    async def _create_track(
        self, file_path: Path, file_hash: str, file_mtime: datetime, file_size: int | None = None
    ) -> Track:
        """Create a new track record, or update if it already exists (upsert)."""
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        loop = asyncio.get_event_loop()

        # Extract metadata from file (in thread pool)
        metadata = await loop.run_in_executor(
            _file_executor, _extract_metadata_sync, file_path
        )

        values = {
            "file_path": str(file_path),
            "file_hash": file_hash,
            "file_size": file_size,
            "file_modified_at": file_mtime,
            "title": metadata.get("title"),
            "artist": metadata.get("artist"),
            "album": metadata.get("album"),
            "album_artist": metadata.get("album_artist"),
            "track_number": metadata.get("track_number"),
            "disc_number": metadata.get("disc_number"),
            "year": metadata.get("year"),
            "genre": metadata.get("genre"),
            "duration_seconds": metadata.get("duration_seconds"),
            "sample_rate": metadata.get("sample_rate"),
            "bit_depth": metadata.get("bit_depth"),
            "bitrate": metadata.get("bitrate"),
            "bitrate_mode": metadata.get("bitrate_mode"),
            "format": metadata.get("format"),
        }

        # Use upsert to handle race conditions (another process may have inserted this track)
        insert_stmt = pg_insert(Track).values(**values)
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=["file_path"],
            set_={
                "file_hash": insert_stmt.excluded.file_hash,
                "file_size": insert_stmt.excluded.file_size,
                "file_modified_at": insert_stmt.excluded.file_modified_at,
                "title": insert_stmt.excluded.title,
                "artist": insert_stmt.excluded.artist,
                "album": insert_stmt.excluded.album,
                "album_artist": insert_stmt.excluded.album_artist,
                "track_number": insert_stmt.excluded.track_number,
                "disc_number": insert_stmt.excluded.disc_number,
                "year": insert_stmt.excluded.year,
                "genre": insert_stmt.excluded.genre,
                "duration_seconds": insert_stmt.excluded.duration_seconds,
                "sample_rate": insert_stmt.excluded.sample_rate,
                "bit_depth": insert_stmt.excluded.bit_depth,
                "bitrate": insert_stmt.excluded.bitrate,
                "bitrate_mode": insert_stmt.excluded.bitrate_mode,
                "format": insert_stmt.excluded.format,
            },
        ).returning(Track)

        result = await self.db.execute(upsert_stmt)
        track = result.scalar_one()

        # Note: Analysis is queued by the caller after commit
        return track

    async def detect_compilation_albums(self) -> dict[str, int]:
        """Detect compilation albums and set album_artist for tracks.

        Finds albums where:
        - album_artist is not already set
        - Multiple different artists exist for the same album

        Sets album_artist = "Various Artists" for all tracks in those albums.
        Returns dict with albums_detected and tracks_updated counts.

        Uses case-insensitive album matching to handle variations like
        "Alice In Ultraland" vs "Alice in Ultraland".
        """
        from sqlalchemy import func, update

        # Find albums with multiple artists (compilation candidates)
        # Only consider tracks where album_artist is not already set
        # Use lower(album) for case-insensitive grouping
        compilation_query = (
            select(func.lower(Track.album).label("album_lower"))
            .where(
                Track.album.isnot(None),
                Track.album != "",
                Track.status == TrackStatus.ACTIVE,
                (Track.album_artist.is_(None) | (Track.album_artist == "")),
            )
            .group_by(func.lower(Track.album))
            .having(func.count(func.distinct(func.lower(Track.artist))) > 1)
        )

        result = await self.db.execute(compilation_query)
        compilation_albums_lower = [row[0] for row in result.fetchall()]

        if not compilation_albums_lower:
            logger.info("No compilation albums detected")
            return {"albums_detected": 0, "tracks_updated": 0}

        logger.info(f"Detected {len(compilation_albums_lower)} compilation albums: {compilation_albums_lower[:5]}...")

        # Update all tracks in those albums to have album_artist = "Various Artists"
        # Use case-insensitive matching
        update_stmt = (
            update(Track)
            .where(
                func.lower(Track.album).in_(compilation_albums_lower),
                (Track.album_artist.is_(None) | (Track.album_artist == "")),
            )
            .values(album_artist="Various Artists")
        )

        result = await self.db.execute(update_stmt)
        tracks_updated = result.rowcount  # type: ignore[attr-defined]

        await self.db.commit()

        logger.info(
            f"Compilation detection complete: {len(compilation_albums_lower)} albums, "
            f"{tracks_updated} tracks updated"
        )

        return {"albums_detected": len(compilation_albums_lower), "tracks_updated": tracks_updated}

    async def _update_track(
        self,
        track: Track,
        file_hash: str,
        file_mtime: datetime,
        file_size: int | None = None,
        reset_analysis: bool = True,
    ) -> Track:
        """Update an existing track record.

        Args:
            track: Existing track to update
            file_hash: New file hash
            file_mtime: New file modification time
            reset_analysis: If True, reset analysis status to trigger re-analysis
        """
        loop = asyncio.get_event_loop()

        # Re-extract metadata (in thread pool)
        metadata = await loop.run_in_executor(
            _file_executor, _extract_metadata_sync, Path(track.file_path)
        )

        track.file_hash = file_hash
        track.file_size = file_size
        track.file_modified_at = file_mtime
        track.title = metadata.get("title")
        track.artist = metadata.get("artist")
        track.album = metadata.get("album")
        track.album_artist = metadata.get("album_artist")
        track.track_number = metadata.get("track_number")
        track.disc_number = metadata.get("disc_number")
        track.year = metadata.get("year")
        track.genre = metadata.get("genre")
        track.duration_seconds = metadata.get("duration_seconds")
        track.sample_rate = metadata.get("sample_rate")
        track.bit_depth = metadata.get("bit_depth")
        track.bitrate = metadata.get("bitrate")
        track.bitrate_mode = metadata.get("bitrate_mode")
        track.format = metadata.get("format")

        # Only reset analysis status if requested (when file content changed)
        if reset_analysis:
            track.analysis_version = 0
            track.analyzed_at = None

        # Note: Analysis is queued by the caller after commit
        return track
