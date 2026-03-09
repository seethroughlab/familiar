"""Spotify data export import routes.

Upload a ZIP from Spotify's "Download your data" page to browse
your Spotify library with match status against local tracks.
"""

import asyncio
import json
import logging
from uuid import uuid4

from fastapi import APIRouter, HTTPException, UploadFile

from app.api.deps import DbSession, RequiredProfile
from app.services.spotify_import import SpotifyImportService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/spotify", tags=["spotify"])

MAX_ZIP_SIZE = 500 * 1024 * 1024  # 500 MB


def _serialize_import(import_) -> dict:
    """Serialize a SpotifyImport to a JSON-safe dict."""
    return {
        "id": str(import_.id),
        "profile_id": str(import_.profile_id),
        "imported_at": import_.imported_at.isoformat(),
        "spotify_username": import_.spotify_username,
        "favorites": import_.favorites,
        "playlists": import_.playlists,
        "streaming_stats": import_.streaming_stats,
        "match_results": import_.match_results,
        "summary": import_.summary,
    }


@router.post("/import")
async def upload_spotify_export(
    file: UploadFile,
    profile: RequiredProfile,
):
    """Upload and process a Spotify data export ZIP (runs in background)."""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "File must be a ZIP archive")

    zip_bytes = await file.read()
    if len(zip_bytes) > MAX_ZIP_SIZE:
        raise HTTPException(400, f"File too large (max {MAX_ZIP_SIZE // 1024 // 1024} MB)")

    from app.services.background import get_background_manager
    bg = get_background_manager()

    task_id = str(uuid4())
    asyncio.create_task(bg.run_spotify_import(task_id, profile.id, zip_bytes))

    return {"task_id": task_id, "status": "processing"}


@router.get("/import/status/{task_id}")
async def get_spotify_import_status(task_id: str):
    """Poll the status of a background Spotify import task."""
    from app.services.background import get_background_manager
    bg = get_background_manager()

    key = f"familiar:spotify_import:{task_id}"
    data: bytes | None = bg.redis.get(key)  # type: ignore[assignment]
    if not data:
        raise HTTPException(404, "Task not found")

    return json.loads(data)


@router.get("/import")
async def get_spotify_import(
    db: DbSession,
    profile: RequiredProfile,
):
    """Get the current Spotify import for the profile."""
    service = SpotifyImportService(db)
    import_ = await service.get_import(profile.id)
    if not import_:
        return None
    return _serialize_import(import_)


@router.delete("/import")
async def delete_spotify_import(
    db: DbSession,
    profile: RequiredProfile,
):
    """Remove the Spotify import for the profile."""
    service = SpotifyImportService(db)
    deleted = await service.delete_import(profile.id)
    if not deleted:
        raise HTTPException(404, "No Spotify import found")
    return {"ok": True}


@router.post("/rematch")
async def rematch_spotify_import(
    profile: RequiredProfile,
):
    """Re-run matching against current library without re-uploading (runs in background)."""
    from app.services.background import get_background_manager
    bg = get_background_manager()

    task_id = str(uuid4())
    asyncio.create_task(bg.run_spotify_rematch(task_id, profile.id))

    return {"task_id": task_id, "status": "processing"}
