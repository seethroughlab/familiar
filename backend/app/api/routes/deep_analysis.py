"""API routes for deep track analysis."""

import json
import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DbSession
from app.db.models import Track, TrackDeepAnalysis
from app.services.background import get_background_manager
from app.services.deep_analysis import (
    DEEP_ANALYSIS_VERSION,
    generate_comparative_report,
    generate_report,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tracks", tags=["deep-analysis"])


class BulkAnalysisRequest(BaseModel):
    track_ids: list[str]


# ─── Bulk endpoints (must be declared before {track_id} parameterized routes) ──


@router.post("/deep-analysis/bulk")
async def trigger_bulk_deep_analysis(body: BulkAnalysisRequest, db: DbSession):
    """Trigger deep analysis for multiple tracks. Returns task_id for polling."""
    if not body.track_ids:
        raise HTTPException(status_code=400, detail="No track IDs provided")

    if len(body.track_ids) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 tracks per bulk request")

    task_id = str(uuid4())[:8]
    bg = get_background_manager()

    import asyncio
    asyncio.create_task(bg.run_bulk_deep_analysis(task_id, body.track_ids))

    return {"status": "processing", "task_id": task_id, "total": len(body.track_ids)}


@router.get("/deep-analysis/bulk/{task_id}")
async def get_bulk_analysis_progress(task_id: str):
    """Poll progress of a bulk deep analysis task."""
    bg = get_background_manager()
    data = bg.redis.get(f"familiar:deep_analysis:{task_id}")

    if not data:
        raise HTTPException(status_code=404, detail="Task not found")

    return json.loads(data)


@router.get("/deep-analysis/bulk/{task_id}/report")
async def get_bulk_analysis_report(task_id: str, db: DbSession):
    """Download combined markdown report for a bulk analysis task."""
    bg = get_background_manager()
    data = bg.redis.get(f"familiar:deep_analysis:{task_id}")

    if not data:
        raise HTTPException(status_code=404, detail="Task not found")

    progress = json.loads(data)
    if progress["status"] != "completed":
        raise HTTPException(status_code=409, detail=f"Task not complete (status: {progress['status']})")

    analyses = []
    track_metas = []

    for tid in progress["track_ids"]:
        cached = (
            await db.execute(
                select(TrackDeepAnalysis).where(
                    TrackDeepAnalysis.track_id == UUID(tid),
                    TrackDeepAnalysis.version == DEEP_ANALYSIS_VERSION,
                )
            )
        ).scalar_one_or_none()

        track = (await db.execute(select(Track).where(Track.id == UUID(tid)))).scalar_one_or_none()

        if cached and track:
            analyses.append(cached.results)
            track_metas.append({
                "artist": track.artist,
                "title": track.title,
                "album": track.album,
                "duration_seconds": track.duration_seconds,
            })

    if not analyses:
        raise HTTPException(status_code=404, detail="No completed analyses found")

    report = generate_comparative_report(analyses, track_metas)

    return StreamingResponse(
        iter([report]),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="track-analysis.md"'},
    )


# ─── Single track endpoints ────────────────────────────────────────────────


@router.post("/{track_id}/deep-analysis")
async def trigger_deep_analysis(track_id: UUID, db: DbSession):
    """Trigger deep analysis for a single track.

    Returns immediately if cached at current version.
    Otherwise queues background processing and returns 202.
    """
    track = (await db.execute(select(Track).where(Track.id == track_id))).scalar_one_or_none()
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    cached = (
        await db.execute(
            select(TrackDeepAnalysis).where(
                TrackDeepAnalysis.track_id == track_id,
                TrackDeepAnalysis.version == DEEP_ANALYSIS_VERSION,
            )
        )
    ).scalar_one_or_none()

    if cached:
        return {"status": "ready", "track_id": str(track_id)}

    bg = get_background_manager()
    await bg.run_deep_analysis(str(track_id))

    return {"status": "processing", "track_id": str(track_id)}


@router.get("/{track_id}/deep-analysis")
async def get_deep_analysis(track_id: UUID, db: DbSession):
    """Get cached deep analysis JSON for a track."""
    cached = (
        await db.execute(
            select(TrackDeepAnalysis).where(
                TrackDeepAnalysis.track_id == track_id,
                TrackDeepAnalysis.version == DEEP_ANALYSIS_VERSION,
            )
        )
    ).scalar_one_or_none()

    if not cached:
        return JSONResponse(
            status_code=202,
            content={"status": "processing", "track_id": str(track_id)},
        )

    return {
        "track_id": str(track_id),
        "version": cached.version,
        "results": cached.results,
        "midi_path": cached.midi_path,
        "section_errors": cached.section_errors,
        "analysis_duration_seconds": cached.analysis_duration_seconds,
        "created_at": cached.created_at.isoformat() if cached.created_at else None,
    }


@router.get("/{track_id}/deep-analysis/report")
async def get_deep_analysis_report(track_id: UUID, db: DbSession, format: str = "md"):
    """Download the deep analysis report as markdown or JSON."""
    cached = (
        await db.execute(
            select(TrackDeepAnalysis).where(
                TrackDeepAnalysis.track_id == track_id,
                TrackDeepAnalysis.version == DEEP_ANALYSIS_VERSION,
            )
        )
    ).scalar_one_or_none()

    if not cached:
        raise HTTPException(status_code=404, detail="Deep analysis not found")

    track = (await db.execute(select(Track).where(Track.id == track_id))).scalar_one_or_none()
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    track_meta = {
        "artist": track.artist,
        "title": track.title,
        "album": track.album,
        "duration_seconds": track.duration_seconds,
    }

    if format == "json":
        return cached.results

    report = generate_report(cached.results, track_meta)
    filename = f"{track.artist or 'Unknown'} - {track.title or 'Unknown'} - analysis.md"
    filename = "".join(c for c in filename if c.isalnum() or c in " -_.").strip()

    return StreamingResponse(
        iter([report]),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{track_id}/deep-analysis/midi")
async def get_deep_analysis_midi(track_id: UUID, db: DbSession):
    """Download the MIDI transcription file if available."""
    from pathlib import Path

    cached = (
        await db.execute(
            select(TrackDeepAnalysis).where(
                TrackDeepAnalysis.track_id == track_id,
                TrackDeepAnalysis.version == DEEP_ANALYSIS_VERSION,
            )
        )
    ).scalar_one_or_none()

    if not cached or not cached.midi_path:
        raise HTTPException(status_code=404, detail="MIDI file not available")

    midi_file = Path(cached.midi_path)
    if not midi_file.exists():
        raise HTTPException(status_code=404, detail="MIDI file not found on disk")

    track = (await db.execute(select(Track).where(Track.id == track_id))).scalar_one_or_none()
    filename = f"{track.artist or 'Unknown'} - {track.title or 'Unknown'}.mid" if track else f"{track_id}.mid"
    filename = "".join(c for c in filename if c.isalnum() or c in " -_.").strip()

    def file_iter():
        with open(midi_file, "rb") as f:
            yield f.read()

    return StreamingResponse(
        file_iter(),
        media_type="audio/midi",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
