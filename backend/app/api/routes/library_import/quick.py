"""Quick import endpoints (upload, scan-path, from-path, recent)."""

import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, UploadFile
from pydantic import BaseModel

from app.api.deps import DbSession
from app.api.exceptions import (
    FileOperationError,
    InvalidPathError,
    LibraryImportError,
    NotFoundError,
    ValidationError,
    sanitize_error_for_client,
)
from app.services.import_service import ImportService, MusicImportError, save_upload_to_temp
from app.services.scanner import LibraryScanner

logger = logging.getLogger(__name__)

router = APIRouter()


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


class ScanPathEntry(BaseModel):
    """A directory entry from scan-path."""
    name: str
    file_count: int
    total_size_bytes: int


class ImportFromPathRequest(BaseModel):
    """Request body for importing from a local path."""
    source_path: str


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
        raise ValidationError("No filename provided")

    # Read uploaded file
    content = await file.read()
    if len(content) == 0:
        raise ValidationError("Empty file")

    # Save to temp file
    try:
        temp_path = save_upload_to_temp(content, file.filename)
    except Exception as e:
        raise FileOperationError("Failed to save upload", detail=str(e))

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
        raise ValidationError(sanitize_error_for_client(e, "Import failed"))
    except Exception:
        raise LibraryImportError()
    finally:
        # Clean up temp file
        temp_path.unlink(missing_ok=True)


@router.get("/import/scan-path", response_model=list[ScanPathEntry])
async def scan_path(path: str) -> list[ScanPathEntry]:
    """List subdirectories at a local path with audio file counts.

    Useful for discovering what's available for import at a given path
    (e.g. a mounted volume of downloaded music).

    Args:
        path: Absolute path inside the container to scan.
    """
    from app.config import AUDIO_EXTENSIONS

    scan_dir = Path(path)
    if not scan_dir.exists():
        raise NotFoundError(f"Path does not exist: {path}")
    if not scan_dir.is_dir():
        raise InvalidPathError(f"Path is not a directory: {path}")

    entries = []
    for child in sorted(scan_dir.iterdir()):
        if not child.is_dir():
            continue
        audio_files = [
            f for f in child.rglob("*")
            if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
        ]
        if audio_files:
            entries.append(ScanPathEntry(
                name=child.name,
                file_count=len(audio_files),
                total_size_bytes=sum(f.stat().st_size for f in audio_files),
            ))

    return entries


@router.post("/import/from-path", response_model=ImportResult)
async def import_from_path(
    request: ImportFromPathRequest,
    background_tasks: BackgroundTasks,
) -> ImportResult:
    """Import audio files from a local filesystem path.

    Copies audio files from the given directory into the library's _imports/
    folder and triggers a background metadata scan.
    """
    source = Path(request.source_path)

    try:
        import_service = ImportService()
        result = import_service.process_local_directory(source)

        # Schedule scan of the import directory (same pattern as POST /import)
        import_dir = Path(result["import_path"])

        async def scan_import():
            from app.db.session import async_session_maker
            async with async_session_maker() as bg_db:
                try:
                    scanner = LibraryScanner(bg_db)
                    await scanner.scan(import_dir, full_scan=True)
                    await bg_db.commit()
                except Exception as e:
                    await bg_db.rollback()
                    logger.error(f"Background scan failed: {e}")

        background_tasks.add_task(scan_import)

        return ImportResult(
            status="processing",
            message=f"Imported {result['files_found']} files from {source.name}, scanning for metadata...",
            import_path=result["import_path"],
            files_found=result["files_found"],
            files=result.get("files", []),
        )

    except MusicImportError as e:
        raise ValidationError(sanitize_error_for_client(e, "Import failed"))
    except Exception:
        raise LibraryImportError()


@router.get("/imports/recent", response_model=list[RecentImport])
async def get_recent_imports(limit: int = 10) -> list[RecentImport]:
    """Get list of recent import directories."""
    import_service = ImportService()
    imports = import_service.get_recent_imports(limit)
    return [RecentImport(**i) for i in imports]
