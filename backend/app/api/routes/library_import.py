"""Music import endpoints."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, func, select

from app.api.deps import DbSession
from app.api.exceptions import sanitize_error_for_client
from app.config import settings
from app.db.models import Track, TrackAnalysis
from app.services.import_service import ImportService, MusicImportError, save_upload_to_temp
from app.services.scanner import LibraryScanner

logger = logging.getLogger(__name__)

router = APIRouter(tags=["library"])


class ImportResult(BaseModel):
    """Import operation result."""
    status: str
    message: str
    import_path: str | None = None
    files_found: int = 0
    files: list[str] = []


class RecentImport(BaseModel):
    """Recent import directory info."""
    name: str
    path: str
    file_count: int
    created_at: str | None


@router.post("/import", response_model=ImportResult)
async def import_music(
    db: DbSession,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> ImportResult:
    """Import music from a zip file or audio file.

    Accepts:
    - Zip files containing audio (extracts and imports)
    - Individual audio files (mp3, flac, m4a, etc.)

    Files are saved to {MUSIC_LIBRARY_PATH}/_imports/{timestamp}/
    and automatically scanned for metadata.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Read uploaded file
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    # Save to temp file
    try:
        temp_path = save_upload_to_temp(content, file.filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {e}")

    # Process the import
    try:
        import_service = ImportService()
        result = import_service.process_upload(temp_path, file.filename)

        # Schedule scan of the import directory
        import_dir = Path(result["import_path"])

        async def scan_import():
            # Create new db session for background task (request session is closed)
            from app.db.session import async_session_maker
            async with async_session_maker() as bg_db:
                try:
                    scanner = LibraryScanner(bg_db)
                    await scanner.scan(import_dir, full_scan=True)
                    await bg_db.commit()
                except Exception as e:
                    await bg_db.rollback()
                    import logging
                    logging.getLogger(__name__).error(f"Background scan failed: {e}")

        background_tasks.add_task(scan_import)

        return ImportResult(
            status="processing",
            message=f"Imported {result['files_found']} files, scanning for metadata...",
            import_path=result["import_path"],
            files_found=result["files_found"],
            files=result.get("files", []),
        )

    except MusicImportError as e:
        raise HTTPException(status_code=400, detail=sanitize_error_for_client(e, "Import failed"))
    except Exception:
        raise HTTPException(status_code=500, detail="Import failed")
    finally:
        # Clean up temp file
        temp_path.unlink(missing_ok=True)


@router.get("/imports/recent", response_model=list[RecentImport])
async def get_recent_imports(limit: int = 10) -> list[RecentImport]:
    """Get list of recent import directories."""
    import_service = ImportService()
    imports = import_service.get_recent_imports(limit)
    return [RecentImport(**i) for i in imports]


# ============================================================================
# Enhanced Import with Preview
# ============================================================================


class ImportTrackPreview(BaseModel):
    """Preview info for a single track."""
    filename: str
    relative_path: str
    detected_artist: str | None
    detected_album: str | None
    detected_title: str | None
    detected_track_num: int | None
    detected_year: int | None = None
    format: str
    duration_seconds: float | None
    file_size_bytes: int
    sample_rate: int | None = None
    bit_depth: int | None = None
    bitrate: int | None = None
    bitrate_mode: str | None = None  # "CBR", "VBR", or None
    # Duplicate detection
    duplicate_of: str | None = None  # ID of existing track if duplicate found
    duplicate_info: str | None = None  # e.g. "Artist - Album - Title"
    # Quality comparison (for duplicates)
    trump_status: str | None = None  # "trumps", "trumped_by", "equal"
    trump_reason: str | None = None  # Human-readable comparison reason
    incoming_quality: dict | None = None  # Quality info for incoming track
    existing_quality: dict | None = None  # Quality info for existing track
    duplicate_match_type: str | None = None  # "exact", "normalized", "artist_title"


class ImportPreviewResponse(BaseModel):
    """Response from import preview endpoint."""
    session_id: str
    tracks: list[ImportTrackPreview]
    total_size_bytes: int
    estimated_sizes: dict[str, int]
    has_convertible_formats: bool


class ImportTrackInput(BaseModel):
    """User-edited track metadata for import."""
    filename: str | None = None
    relative_path: str | None = None
    artist: str | None = None
    album: str | None = None
    title: str | None = None
    track_num: int | None = None
    year: int | None = None
    # Pass through detected values if not edited
    detected_artist: str | None = None
    detected_album: str | None = None
    detected_title: str | None = None
    detected_track_num: int | None = None
    detected_year: int | None = None
    # Quality-based replacement
    action: str = "import"  # "import", "replace", "skip"
    replace_track_id: str | None = None  # Track ID to replace (for action="replace")


class ImportOptions(BaseModel):
    """Import execution options."""
    format: str = "original"  # "original", "flac", "mp3"
    mp3_quality: int = 320  # 128, 192, 320
    organization: str = "imports"  # "organized" or "imports"
    duplicate_handling: str = "rename"  # "skip", "replace", "rename"
    queue_analysis: bool = True


class ImportExecuteRequest(BaseModel):
    """Request body for import execution."""
    session_id: str
    tracks: list[ImportTrackInput]
    options: ImportOptions


class ImportExecuteResponse(BaseModel):
    """Response from import execute endpoint."""
    status: str
    imported_count: int
    replaced_count: int = 0  # Count of tracks that replaced existing ones
    imported_files: list[str]
    errors: list[str]
    base_path: str
    queue_analysis: bool


async def _find_import_duplicate(
    db: "AsyncSession",
    artist: str,
    album: str,
    title: str,
) -> tuple["Track | None", str]:
    """Multi-phase duplicate detection for import preview.

    Returns (matching_track, match_type) where match_type is one of:
    "exact", "normalized", "artist_title", or "" if no match.
    """

    from app.db.models import Track
    from app.services.normalize import normalize_for_duplicate_matching

    # Phase 1: Exact case-insensitive match (artist + album + title)
    if album:
        stmt = (
            select(Track)
            .where(
                func.lower(Track.artist) == artist.lower(),
                func.lower(Track.album) == album.lower(),
                func.lower(Track.title) == title.lower(),
            )
            .limit(1)
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            return existing, "exact"

    # Phase 2: Fetch candidates by artist variants for fuzzy matching
    artist_lower = artist.lower()
    artist_variants = [artist_lower]

    # Add with/without leading articles
    for article in ("the ", "a ", "an "):
        if artist_lower.startswith(article):
            artist_variants.append(artist_lower[len(article):])
        else:
            artist_variants.append(article + artist_lower)

    stmt = (
        select(Track)
        .where(func.lower(Track.artist).in_(artist_variants))
    )
    candidates = (await db.execute(stmt)).scalars().all()

    if not candidates:
        return None, ""

    # Phase 3: Normalized artist + album + title
    norm_artist = normalize_for_duplicate_matching(artist, strip_articles=True)
    norm_album = normalize_for_duplicate_matching(album)
    norm_title = normalize_for_duplicate_matching(title)

    if norm_album:
        for candidate in candidates:
            if (
                normalize_for_duplicate_matching(candidate.artist, strip_articles=True) == norm_artist
                and normalize_for_duplicate_matching(candidate.album) == norm_album
                and normalize_for_duplicate_matching(candidate.title) == norm_title
            ):
                return candidate, "normalized"

    # Phase 4: Artist + title only (no album requirement)
    for candidate in candidates:
        if (
            normalize_for_duplicate_matching(candidate.artist, strip_articles=True) == norm_artist
            and normalize_for_duplicate_matching(candidate.title) == norm_title
        ):
            return candidate, "artist_title"

    return None, ""


@router.post("/import/preview", response_model=ImportPreviewResponse)
async def import_preview(
    db: DbSession,
    file: UploadFile = File(...),
) -> ImportPreviewResponse:
    """Preview an import - extract and scan files without importing.

    Uploads file to temp location, extracts if zip, scans metadata,
    and returns preview with session_id for later execution.

    Session expires after 24 hours if not executed.
    """
    from app.services.import_service import (
        ImportPreviewService,
        MusicImportError,
        save_upload_to_temp,
    )

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Read uploaded file
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    # Save to temp file
    try:
        temp_path = save_upload_to_temp(content, file.filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {e}")

    try:
        from app.services.quality import calculate_quality_score, compare_quality

        preview_service = ImportPreviewService()
        result = preview_service.create_preview_session(temp_path, file.filename)

        # Check for duplicates in the library and compare quality
        tracks = result["tracks"]
        for track in tracks:
            artist = track.get("detected_artist") or ""
            album = track.get("detected_album") or ""
            title = track.get("detected_title") or ""

            # Only check if we have enough metadata to match
            if artist and title:
                existing, match_type = await _find_import_duplicate(
                    db, artist, album, title
                )

                if existing:
                    track["duplicate_of"] = str(existing.id)
                    track["duplicate_info"] = (
                        f"{existing.artist} - {existing.album} - {existing.title}"
                    )
                    track["duplicate_match_type"] = match_type

                    # Calculate quality scores and compare
                    incoming_score = calculate_quality_score(
                        format=track.get("format"),
                        bitrate=track.get("bitrate"),
                        sample_rate=track.get("sample_rate"),
                        bit_depth=track.get("bit_depth"),
                        bitrate_mode=track.get("bitrate_mode"),
                    )
                    existing_score = calculate_quality_score(
                        format=existing.format,
                        bitrate=existing.bitrate,
                        sample_rate=existing.sample_rate,
                        bit_depth=existing.bit_depth,
                        bitrate_mode=existing.bitrate_mode,
                    )

                    trump_status, trump_reason = compare_quality(
                        incoming_score, existing_score
                    )
                    track["trump_status"] = trump_status
                    track["trump_reason"] = trump_reason
                    track["incoming_quality"] = incoming_score.to_dict()
                    track["existing_quality"] = existing_score.to_dict()

        return ImportPreviewResponse(
            session_id=result["session_id"],
            tracks=[ImportTrackPreview(**t) for t in tracks],
            total_size_bytes=result["total_size_bytes"],
            estimated_sizes=result["estimated_sizes"],
            has_convertible_formats=result["has_convertible_formats"],
        )

    except MusicImportError as e:
        raise HTTPException(status_code=400, detail=sanitize_error_for_client(e, "Preview failed"))
    except Exception:
        raise HTTPException(status_code=500, detail="Preview failed")
    finally:
        # Clean up temp file (session has its own copy)
        temp_path.unlink(missing_ok=True)


@router.post("/import/execute", response_model=ImportExecuteResponse)
async def import_execute(
    db: DbSession,
    background_tasks: BackgroundTasks,
    request: ImportExecuteRequest,
) -> ImportExecuteResponse:
    """Execute an import with user-specified options.

    Uses session_id from preview to access uploaded files.
    Applies user-edited metadata and conversion options.
    """
    from pathlib import Path
    from uuid import UUID

    from app.db.models import Track
    from app.services.import_service import ImportExecuteService, MusicImportError
    from app.services.metadata import extract_metadata
    from app.services.scanner import compute_file_hash

    try:
        execute_service = ImportExecuteService()
        result = execute_service.execute_import(
            session_id=request.session_id,
            tracks=[t.model_dump() for t in request.tracks],
            options=request.options.model_dump(),
        )

        # Handle track replacements - update existing tracks to point to new files
        replaced_tracks = result.get("replaced_tracks", [])
        replaced_count = 0
        for replacement in replaced_tracks:
            try:
                track_id = UUID(replacement["track_id"])
                new_file_path = Path(replacement["new_file_path"])

                # Get the existing track
                existing = await db.get(Track, track_id)
                if not existing:
                    result["errors"].append(f"Track to replace not found: {track_id}")
                    continue

                # Delete the old file if it exists
                old_path = Path(existing.file_path)
                if old_path.exists():
                    old_path.unlink()

                # Update track with new file info
                existing.file_path = str(new_file_path)

                # Calculate new file hash (must match scanner's partial-hash scheme)
                existing.file_hash = compute_file_hash(new_file_path)

                # Extract metadata from new file
                metadata = extract_metadata(new_file_path)
                existing.format = metadata.get("format")
                existing.bitrate = metadata.get("bitrate")
                existing.bitrate_mode = metadata.get("bitrate_mode")
                existing.sample_rate = metadata.get("sample_rate")
                existing.bit_depth = metadata.get("bit_depth")
                existing.duration_seconds = metadata.get("duration_seconds")

                # Reset analysis to trigger re-analysis
                existing.analyzed_at = None
                existing.analysis_error = None
                existing.analysis_failed_at = None
                await db.execute(delete(TrackAnalysis).where(TrackAnalysis.track_id == existing.id))

                replaced_count += 1

            except Exception as e:
                result["errors"].append(f"Failed to replace track: {e}")

        # Commit replacement changes
        if replaced_count > 0:
            await db.commit()
            # Adjust imported count to not double-count replacements
            result["imported_count"] = result["imported_count"] - replaced_count
            result["replaced_count"] = replaced_count

        # Schedule scan of imported files if requested
        # Use specific scan_paths to avoid scanning entire library
        scan_paths = result.get("scan_paths", [])
        if result["queue_analysis"] and scan_paths and settings.music_library_paths:
            from app.db.session import async_session_maker
            from app.services.scanner import LibraryScanner

            library_root = Path(settings.music_library_paths[0])

            async def scan_import():
                # Create new db session for background task (request session is closed)
                async with async_session_maker() as bg_db:
                    try:
                        scanner = LibraryScanner(bg_db)
                        for rel_path in scan_paths:
                            scan_dir = library_root / rel_path
                            if scan_dir.exists():
                                await scanner.scan(scan_dir, full_scan=True)
                        await bg_db.commit()
                    except Exception as e:
                        await bg_db.rollback()
                        import logging
                        logging.getLogger(__name__).error(f"Background scan failed: {e}")

            background_tasks.add_task(scan_import)

        return ImportExecuteResponse(**result)

    except MusicImportError as e:
        raise HTTPException(status_code=400, detail=sanitize_error_for_client(e, "Import failed"))
    except Exception:
        raise HTTPException(status_code=500, detail="Import failed")
