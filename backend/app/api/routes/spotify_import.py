"""Spotify data export import routes.

Upload a ZIP from Spotify's "Download your data" page to browse
your Spotify library with match status against local tracks.
"""

import asyncio
import json
import logging
from uuid import uuid4

from fastapi import APIRouter, Form, UploadFile
from pydantic import BaseModel

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import NotFoundError, ValidationError
from app.services.spotify_import import SpotifyImportService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/spotify", tags=["spotify"])

MAX_ZIP_SIZE = 500 * 1024 * 1024  # 500 MB


# ── Response Models ───────────────────────────────────────────────


class SpotifyImportResponse(BaseModel):
    id: str
    profile_id: str
    imported_at: str
    spotify_username: str | None = None
    favorites: dict | None = None
    playlists: dict | None = None
    streaming_stats: dict | None = None
    match_results: dict | None = None
    summary: dict | None = None
    matching_task_id: str | None = None


class SpotifyMatchProgressResponse(BaseModel):
    phase: str | None = None
    progress: float | None = None
    matched: int | None = None
    total: int | None = None
    message: str | None = None


class SpotifyTaskStatusResponse(BaseModel):
    status: str
    error: str | None = None
    matched: int | None = None
    total: int | None = None


class SpotifyDeleteResponse(BaseModel):
    ok: bool


class SpotifyRematchResponse(BaseModel):
    task_id: str
    status: str


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


@router.post("/import", response_model=SpotifyImportResponse)
async def upload_spotify_export(
    db: DbSession,
    profile: RequiredProfile,
    file: UploadFile,
    include_favorites: bool = Form(True),
    include_playlists: bool = Form(True),
    include_streaming: bool = Form(True),
) -> SpotifyImportResponse:
    """Upload a Spotify data export ZIP. Parses immediately, matches in background."""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise ValidationError("File must be a ZIP archive")

    zip_bytes = await file.read()
    if len(zip_bytes) > MAX_ZIP_SIZE:
        raise ValidationError("File too large", detail=f"Max size: {MAX_ZIP_SIZE // 1024 // 1024} MB")

    service = SpotifyImportService(db)
    import_ = await service.parse_and_save(
        profile.id,
        zip_bytes,
        include_favorites=include_favorites,
        include_playlists=include_playlists,
        include_streaming=include_streaming,
    )

    from app.services.background import get_background_manager
    bg = get_background_manager()

    task_id = str(uuid4())
    asyncio.create_task(bg.run_spotify_matching(task_id, profile.id))

    return SpotifyImportResponse(**_serialize_import(import_), matching_task_id=task_id)


@router.get("/import/progress", response_model=SpotifyMatchProgressResponse | None)
async def get_spotify_matching_progress() -> SpotifyMatchProgressResponse | None:
    """Get live matching progress from Redis (null if not running)."""
    try:
        from app.services.background import get_background_manager
        data: bytes | None = get_background_manager().redis.get("familiar:spotify_match:progress")  # type: ignore[assignment]
        return SpotifyMatchProgressResponse(**json.loads(data)) if data else None
    except Exception:
        return None


@router.get("/import/status/{task_id}", response_model=SpotifyTaskStatusResponse)
async def get_spotify_import_status(task_id: str) -> SpotifyTaskStatusResponse:
    """Poll the status of a background Spotify matching task."""
    from app.services.background import get_background_manager
    bg = get_background_manager()

    key = f"familiar:spotify_import:{task_id}"
    data: bytes | None = bg.redis.get(key)  # type: ignore[assignment]
    if not data:
        raise NotFoundError("Task not found")

    return SpotifyTaskStatusResponse(**json.loads(data))


@router.get("/import", response_model=SpotifyImportResponse | None)
async def get_spotify_import(
    db: DbSession,
    profile: RequiredProfile,
) -> SpotifyImportResponse | None:
    """Get the current Spotify import for the profile."""
    service = SpotifyImportService(db)
    import_ = await service.get_import(profile.id)
    if not import_:
        return None
    return SpotifyImportResponse(**_serialize_import(import_))


@router.delete("/import", response_model=SpotifyDeleteResponse)
async def delete_spotify_import(
    db: DbSession,
    profile: RequiredProfile,
) -> SpotifyDeleteResponse:
    """Remove the Spotify import for the profile."""
    service = SpotifyImportService(db)
    deleted = await service.delete_import(profile.id)
    if not deleted:
        raise NotFoundError("No Spotify import found")
    return SpotifyDeleteResponse(ok=True)


@router.post("/rematch", response_model=SpotifyRematchResponse)
async def rematch_spotify_import(
    profile: RequiredProfile,
) -> SpotifyRematchResponse:
    """Re-run matching against current library without re-uploading (runs in background)."""
    from app.services.background import get_background_manager
    bg = get_background_manager()

    task_id = str(uuid4())
    asyncio.create_task(bg.run_spotify_rematch(task_id, profile.id))

    return SpotifyRematchResponse(task_id=task_id, status="processing")
