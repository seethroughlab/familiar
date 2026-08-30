"""ZIP download endpoints for playlists and track collections."""

import asyncio
import json
import logging
import os
import re
import zipfile
from io import BytesIO
from uuid import UUID, uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import (
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    PlaylistNotFoundError,
    ValidationError,
)
from app.db.models import Playlist, PlaylistTrack, Track, TrackAnalysis
from app.services.smart_playlists import SmartPlaylistService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/download", tags=["exports"])

MAX_TRACKS = 500
MAX_SIZE_BYTES = 2 * 1024 * 1024 * 1024  # 2GB


def _sanitize_filename(name: str) -> str:
    """Remove characters that are problematic in filenames."""
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip('. ')


def _build_zip_bytes(tracks: list[Track], folder_name: str) -> tuple[bytes, int]:
    """Build a ZIP file in memory from a list of tracks.

    Returns (zip_bytes, skipped_count).
    """
    buf = BytesIO()
    skipped = 0
    safe_folder = _sanitize_filename(folder_name)

    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as zf:
        for track in tracks:
            if not track.file_path or not os.path.isfile(track.file_path):
                skipped += 1
                continue

            # Build a clean filename: "01 Artist - Title.ext"
            ext = os.path.splitext(track.file_path)[1]
            num = f"{track.track_number:02d}" if track.track_number else "00"
            artist = _sanitize_filename(track.artist or "Unknown")
            title = _sanitize_filename(track.title or "Unknown")
            filename = f"{num} {artist} - {title}{ext}"

            arcname = f"{safe_folder}/{filename}"
            zf.write(track.file_path, arcname)

    return buf.getvalue(), skipped


async def _get_playlist_tracks(db: DbSession, playlist_id: UUID, profile_id: UUID) -> tuple[list[Track], str]:
    """Get tracks and name for a playlist."""
    playlist = await db.get(Playlist, playlist_id)
    if not playlist or playlist.profile_id != profile_id:
        raise PlaylistNotFoundError()

    result = await db.execute(
        select(PlaylistTrack)
        .where(PlaylistTrack.playlist_id == playlist_id)
        .order_by(PlaylistTrack.position)
        .options(selectinload(PlaylistTrack.track))
    )
    playlist_tracks = result.scalars().all()
    tracks = [pt.track for pt in playlist_tracks if pt.track_id and pt.track]
    return tracks, playlist.name


def _check_limits(tracks: list[Track]) -> None:
    """Raise 413 if track list exceeds limits."""
    if len(tracks) > MAX_TRACKS:
        raise PayloadTooLargeError(f"Too many tracks ({len(tracks)}). Maximum is {MAX_TRACKS}.")

    estimated_size = sum(t.file_size or 0 for t in tracks)
    if estimated_size > MAX_SIZE_BYTES:
        size_gb = estimated_size / (1024 * 1024 * 1024)
        raise PayloadTooLargeError(f"Estimated size ({size_gb:.1f} GB) exceeds 2 GB limit.")


@router.get("/playlist/{playlist_id}")
async def download_playlist_zip(
    playlist_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> StreamingResponse:
    """Download all tracks in a playlist as a ZIP file."""
    tracks, name = await _get_playlist_tracks(db, playlist_id, profile.id)

    if not tracks:
        raise NotFoundError("No downloadable tracks in playlist")

    _check_limits(tracks)

    zip_bytes, skipped = await asyncio.to_thread(_build_zip_bytes, tracks, name)

    safe_name = _sanitize_filename(name)
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_name}.zip"',
    }
    if skipped > 0:
        headers["X-Skipped-Tracks"] = str(skipped)

    return StreamingResponse(
        iter([zip_bytes]),
        media_type="application/zip",
        headers=headers,
    )


@router.get("/smart-playlist/{playlist_id}")
async def download_smart_playlist_zip(
    playlist_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> StreamingResponse:
    """Download all tracks matching a smart playlist as a ZIP file."""
    service = SmartPlaylistService(db)
    playlist = await service.get_by_id(playlist_id, profile.id)

    if not playlist:
        raise PlaylistNotFoundError("Smart playlist not found")

    tracks = await service.get_tracks(playlist, limit=MAX_TRACKS + 1, offset=0)

    if not tracks:
        raise NotFoundError("No downloadable tracks in smart playlist")

    _check_limits(tracks)

    zip_bytes, skipped = await asyncio.to_thread(_build_zip_bytes, tracks, playlist.name)

    safe_name = _sanitize_filename(playlist.name)
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_name}.zip"',
    }
    if skipped > 0:
        headers["X-Skipped-Tracks"] = str(skipped)

    return StreamingResponse(
        iter([zip_bytes]),
        media_type="application/zip",
        headers=headers,
    )


class TrackDownloadRequest(BaseModel):
    """Request to download arbitrary tracks as ZIP."""

    track_ids: list[str] = Field(..., min_length=1)
    name: str = Field(default="Tracks", max_length=255)


@router.post("/tracks")
async def download_tracks_zip(
    request: TrackDownloadRequest,
    db: DbSession,
    profile: RequiredProfile,
) -> StreamingResponse:
    """Download a set of tracks as a ZIP file."""
    track_uuids = []
    for tid in request.track_ids:
        try:
            track_uuids.append(UUID(tid))
        except ValueError:
            continue

    if not track_uuids:
        raise ValidationError("No valid track IDs provided")

    result = await db.execute(
        select(Track).where(Track.id.in_(track_uuids))
    )
    tracks = list(result.scalars().all())

    if not tracks:
        raise NotFoundError("No tracks found")

    _check_limits(tracks)

    zip_bytes, skipped = await asyncio.to_thread(_build_zip_bytes, tracks, request.name)

    safe_name = _sanitize_filename(request.name)
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_name}.zip"',
    }
    if skipped > 0:
        headers["X-Skipped-Tracks"] = str(skipped)

    return StreamingResponse(
        iter([zip_bytes]),
        media_type="application/zip",
        headers=headers,
    )


# ── Analysis ZIP downloads ─────────────────────────────────────────────────


class AnalysisDownloadRequest(BaseModel):
    """Request to download track analyses as ZIP."""

    track_ids: list[str] = Field(..., min_length=1)
    name: str = Field(default="Track Analyses", max_length=255)


def _build_analysis_zip(
    tracks: list[Track],
    analyses: dict[UUID, TrackAnalysis],
    folder_name: str,
) -> bytes:
    """Build a ZIP of markdown analysis reports."""
    from app.services.track_analysis import generate_report

    buf = BytesIO()
    safe_folder = _sanitize_filename(folder_name)

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for track in tracks:
            analysis = analyses.get(track.id)
            if not analysis or not analysis.analysis_detail:
                continue

            meta = {
                "artist": track.artist,
                "title": track.title,
                "album": track.album,
                "duration_seconds": track.duration_seconds,
                "track_id": str(track.id),
            }
            report = generate_report(analysis.analysis_detail, meta)

            artist = _sanitize_filename(track.artist or "Unknown")
            title = _sanitize_filename(track.title or "Unknown")
            filename = f"{artist} - {title}.md"
            zf.writestr(f"{safe_folder}/{filename}", report)

    return buf.getvalue()


@router.post("/analyses", response_model=None)
async def download_analyses_zip(
    request: AnalysisDownloadRequest,
    db: DbSession,
    profile: RequiredProfile,
) -> StreamingResponse | JSONResponse:
    """Download track analyses as a ZIP of markdown reports.

    Fast path: all tracks already analyzed -> returns ZIP immediately (200).
    Slow path: some need analysis -> kicks off background task -> returns 202 with task_id.
    """
    track_uuids = []
    for tid in request.track_ids:
        try:
            track_uuids.append(UUID(tid))
        except ValueError:
            continue

    if not track_uuids:
        raise ValidationError("No valid track IDs provided")

    if len(track_uuids) > MAX_TRACKS:
        raise PayloadTooLargeError(f"Too many tracks ({len(track_uuids)}). Maximum is {MAX_TRACKS}.")

    # Fetch tracks
    result = await db.execute(select(Track).where(Track.id.in_(track_uuids)))
    tracks = list(result.scalars().all())
    if not tracks:
        raise NotFoundError("No tracks found")

    # Fetch existing analyses
    analysis_result = await db.execute(
        select(TrackAnalysis).where(TrackAnalysis.track_id.in_(track_uuids))
    )
    analyses = {a.track_id: a for a in analysis_result.scalars().all()}

    # Check which tracks need analysis
    from app.config import MELODIC_VERSION
    needs_analysis = [
        str(t.id) for t in tracks
        if t.id not in analyses
        or not analyses[t.id].analysis_detail
        or not analyses[t.id].has_melodic
        or "melodic" not in (analyses[t.id].analysis_detail or {})
        or (analyses[t.id].melodic_version or 0) < MELODIC_VERSION
    ]

    if not needs_analysis:
        # Fast path: all analyzed, build ZIP immediately
        zip_bytes = await asyncio.to_thread(
            _build_analysis_zip, tracks, analyses, request.name
        )
        safe_name = _sanitize_filename(request.name)
        return StreamingResponse(
            iter([zip_bytes]),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_name}.zip"',
            },
        )

    # Slow path: kick off background analysis, store all track IDs for later
    from app.services.background import get_background_manager

    task_id = str(uuid4())[:8]
    bg = get_background_manager()

    # Store full track ID list so download endpoint can build complete ZIP
    bg.redis.set(
        f"familiar:download_analysis:{task_id}:track_ids",
        json.dumps([str(u) for u in track_uuids]),
        ex=3600,
    )
    bg.redis.set(
        f"familiar:download_analysis:{task_id}:name",
        request.name,
        ex=3600,
    )

    asyncio.create_task(bg.run_analyses_for_download(task_id, needs_analysis))

    return JSONResponse(
        status_code=202,
        content={
            "task_id": task_id,
            "total": len(tracks),
            "needs_analysis": len(needs_analysis),
            "already_done": len(tracks) - len(needs_analysis),
        },
    )


@router.get("/analyses/{task_id}/status")
async def get_analysis_download_status(task_id: str) -> dict:
    """Poll progress of analysis-for-download task."""
    from app.services.background import get_background_manager

    bg = get_background_manager()
    data = bg.redis.get(f"familiar:download_analysis:{task_id}")
    if not data:
        raise NotFoundError("Task not found")
    return json.loads(data)


@router.get("/analyses/{task_id}/download")
async def download_analysis_zip_result(
    task_id: str,
    db: DbSession,
    profile: RequiredProfile,
) -> StreamingResponse:
    """Download the analysis ZIP once background processing is ready."""
    from app.services.background import get_background_manager

    bg = get_background_manager()
    data = bg.redis.get(f"familiar:download_analysis:{task_id}")
    if not data:
        raise NotFoundError("Task not found")

    progress = json.loads(data)
    if progress["status"] != "ready":
        raise ConflictError(f"Task not ready (status: {progress['status']})")

    # Get full track ID list and name stored at initiation
    track_ids_data = bg.redis.get(f"familiar:download_analysis:{task_id}:track_ids")
    name = bg.redis.get(f"familiar:download_analysis:{task_id}:name")
    folder_name = name.decode() if isinstance(name, bytes) else (name or "Track Analyses")

    if not track_ids_data:
        raise NotFoundError("Task track data expired")

    raw = track_ids_data.decode() if isinstance(track_ids_data, bytes) else track_ids_data
    all_track_ids = json.loads(raw)
    track_uuids = [UUID(tid) for tid in all_track_ids]

    result = await db.execute(select(Track).where(Track.id.in_(track_uuids)))
    tracks = list(result.scalars().all())

    analysis_result = await db.execute(
        select(TrackAnalysis).where(TrackAnalysis.track_id.in_(track_uuids))
    )
    analyses = {a.track_id: a for a in analysis_result.scalars().all()}

    zip_bytes = await asyncio.to_thread(
        _build_analysis_zip, tracks, analyses, folder_name
    )

    safe_name = _sanitize_filename(folder_name)
    return StreamingResponse(
        iter([zip_bytes]),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}.zip"',
        },
    )
