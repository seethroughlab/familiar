"""Spotify data export import routes.

Upload a ZIP from Spotify's "Download your data" page to browse
your Spotify library with match status against local tracks.
"""

import asyncio
import json
import logging
from uuid import uuid4

from fastapi import APIRouter, Form, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import NotFoundError, ValidationError
from app.db.models import SpotifyImport
from app.services.spotify_import import SpotifyImportService
from app.utils.time import to_rfc3339

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/spotify", tags=["spotify"])

MAX_ZIP_SIZE = 500 * 1024 * 1024  # 500 MB


# ── Response Models ───────────────────────────────────────────────


class SpotifyImportResponse(BaseModel):
    id: str
    profile_id: str
    imported_at: str
    spotify_username: str | None = None
    favorites: list | dict | None = None
    playlists: list | dict | None = None
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


class SpotifyUnmatchedTrack(BaseModel):
    artist: str
    track: str
    album: str
    sources: list[str]


class SpotifyUnmatchedResponse(BaseModel):
    tracks: list[SpotifyUnmatchedTrack]
    total: int
    limit: int
    offset: int
    warning: str | None = None


class SpotifyStatsResponse(BaseModel):
    total_favorites: int
    matched_favorites: int
    total_playlist_tracks: int
    matched_playlist_tracks: int
    total_unique_tracks: int | None = None
    total_matched: int
    total_unmatched: int | None = None
    match_rate: float | None = None
    matching_status: str
    imported_at: str


def _serialize_import(import_) -> dict:
    """Serialize a SpotifyImport to a JSON-safe dict."""
    return {
        "id": str(import_.id),
        "profile_id": str(import_.profile_id),
        "imported_at": to_rfc3339(import_.imported_at),
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


@router.get("/unmatched", response_model=SpotifyUnmatchedResponse)
async def get_spotify_unmatched(
    db: DbSession,
    profile: RequiredProfile,
    search: str | None = Query(None, description="Free-text search across artist, track, album"),
    artist: str | None = Query(None, description="Filter by artist (case-insensitive contains)"),
    album: str | None = Query(None, description="Filter by album (case-insensitive contains)"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> SpotifyUnmatchedResponse:
    """Search unmatched Spotify tracks with filtering and pagination."""
    service = SpotifyImportService(db)
    import_ = await service.get_import(profile.id)
    if not import_:
        raise NotFoundError("No Spotify import found")

    unique = SpotifyImportService._iter_unique_tracks(import_.favorites, import_.playlists)
    match_results = import_.match_results or {}

    # Filter to unmatched only
    unmatched = [v for k, v in unique.items() if k not in match_results]

    # Apply filters (case-insensitive substring on original values)
    if search:
        s = search.lower()
        unmatched = [
            t for t in unmatched
            if s in t["artist"].lower() or s in t["track"].lower() or s in t["album"].lower()
        ]
    if artist:
        a = artist.lower()
        unmatched = [t for t in unmatched if a in t["artist"].lower()]
    if album:
        al = album.lower()
        unmatched = [t for t in unmatched if al in t["album"].lower()]

    # Sort for deterministic pagination
    unmatched.sort(key=lambda t: (t["artist"].lower(), t["track"].lower()))

    total = len(unmatched)
    page = unmatched[offset : offset + limit]

    warning = None
    summary = import_.summary or {}
    if summary.get("matching_status") == "pending":
        warning = "Matching has not run yet — all tracks appear unmatched"

    return SpotifyUnmatchedResponse(
        tracks=[SpotifyUnmatchedTrack(**t) for t in page],
        total=total,
        limit=limit,
        offset=offset,
        warning=warning,
    )


@router.get("/stats", response_model=SpotifyStatsResponse)
async def get_spotify_stats(
    db: DbSession,
    profile: RequiredProfile,
) -> SpotifyStatsResponse:
    """Lightweight match statistics without loading heavy JSONB fields."""
    result = await db.execute(
        select(SpotifyImport.summary, SpotifyImport.imported_at).where(
            SpotifyImport.profile_id == profile.id
        )
    )
    row = result.one_or_none()
    if not row:
        raise NotFoundError("No Spotify import found")

    summary, imported_at = row
    return SpotifyStatsResponse(
        total_favorites=summary.get("total_favorites", 0),
        matched_favorites=summary.get("matched_favorites", 0),
        total_playlist_tracks=summary.get("total_playlist_tracks", 0),
        matched_playlist_tracks=summary.get("matched_playlist_tracks", 0),
        total_unique_tracks=summary.get("total_unique_tracks"),
        total_matched=summary.get("total_matched", 0),
        total_unmatched=summary.get("total_unmatched"),
        match_rate=summary.get("match_rate"),
        matching_status=summary.get("matching_status", "unknown"),
        imported_at=to_rfc3339(imported_at),
    )
