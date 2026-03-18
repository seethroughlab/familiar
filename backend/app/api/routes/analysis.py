"""API routes for track analysis."""

import json
import logging
from uuid import UUID, uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.exceptions import ConflictError, NotFoundError, TrackNotFoundError, ValidationError
from app.db.models import Track, TrackAnalysis
from app.services.background import get_background_manager
from app.services.track_analysis import (
    generate_comparative_report,
    generate_report,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tracks", tags=["analysis"])


class BulkAnalysisRequest(BaseModel):
    track_ids: list[str]


# ─── Bulk endpoints (must be declared before {track_id} parameterized routes) ──


@router.post("/analysis/bulk")
async def trigger_bulk_analysis(body: BulkAnalysisRequest, db: DbSession):
    """Trigger analysis for multiple tracks. Returns task_id for polling."""
    if not body.track_ids:
        raise ValidationError("No track IDs provided")

    if len(body.track_ids) > 50:
        raise ValidationError("Maximum 50 tracks per bulk request")

    bg = get_background_manager()

    # Reject if analysis queue is already saturated
    queued = bg.get_analysis_task_count()
    if queued >= 500:
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Analysis queue is full",
                "queue_depth": queued,
            },
        )

    task_id = str(uuid4())[:8]

    import asyncio
    asyncio.create_task(bg.run_bulk_analysis(task_id, body.track_ids))

    return {"status": "processing", "task_id": task_id, "total": len(body.track_ids)}


@router.get("/analysis/bulk/{task_id}")
async def get_bulk_analysis_progress(task_id: str):
    """Poll progress of a bulk analysis task."""
    bg = get_background_manager()
    data = bg.redis.get(f"familiar:analysis:{task_id}")

    if not data:
        raise NotFoundError("Task not found")

    return json.loads(data)


@router.get("/analysis/bulk/{task_id}/report")
async def get_bulk_analysis_report(task_id: str, db: DbSession):
    """Download combined markdown report for a bulk analysis task."""
    bg = get_background_manager()
    data = bg.redis.get(f"familiar:analysis:{task_id}")

    if not data:
        raise NotFoundError("Task not found")

    progress = json.loads(data)
    if progress["status"] != "completed":
        raise ConflictError("Task not complete", detail=f"Status: {progress['status']}")

    # Batch-fetch all analyses and tracks in two queries instead of 2N
    track_uuids = [UUID(tid) for tid in progress["track_ids"]]

    analyses_result = await db.execute(
        select(TrackAnalysis).where(TrackAnalysis.track_id.in_(track_uuids))
    )
    analyses_by_id = {
        str(a.track_id): a for a in analyses_result.scalars().all()
    }

    tracks_result = await db.execute(
        select(Track).where(Track.id.in_(track_uuids))
    )
    tracks_by_id = {
        str(t.id): t for t in tracks_result.scalars().all()
    }

    analyses = []
    track_metas = []

    for tid in progress["track_ids"]:
        analysis = analyses_by_id.get(tid)
        track = tracks_by_id.get(tid)

        if analysis and analysis.analysis_detail and track:
            analyses.append(analysis.analysis_detail)
            track_metas.append({
                "artist": track.artist,
                "title": track.title,
                "album": track.album,
                "duration_seconds": track.duration_seconds,
                "track_id": tid,
            })

    if not analyses:
        raise NotFoundError("No completed analyses found")

    report = generate_comparative_report(analyses, track_metas)

    return StreamingResponse(
        iter([report]),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="track-analysis.md"'},
    )


# ─── Single track endpoints ────────────────────────────────────────────────


@router.post("/{track_id}/analysis")
async def trigger_analysis(track_id: UUID, db: DbSession):
    """Trigger full analysis pipeline for a single track.

    Runs all missing phases (features, embedding, deep analysis/melodic)
    using a dedicated on-demand executor. Caching is handled internally.
    """
    track = (await db.execute(select(Track).where(Track.id == track_id))).scalar_one_or_none()
    if not track:
        raise TrackNotFoundError()

    bg = get_background_manager()
    await bg.run_track_analysis_full(str(track_id))

    return {"status": "processing", "track_id": str(track_id)}


@router.get("/{track_id}/analysis")
async def get_analysis(track_id: UUID, db: DbSession):
    """Get cached analysis JSON for a track."""
    analysis = (
        await db.execute(
            select(TrackAnalysis)
            .where(TrackAnalysis.track_id == track_id)
        )
    ).scalar_one_or_none()

    if not analysis or not analysis.analysis_detail:
        return JSONResponse(
            status_code=202,
            content={"status": "processing", "track_id": str(track_id)},
        )

    return {
        "track_id": str(track_id),
        "features_version": analysis.features_version,
        "results": analysis.analysis_detail,
        "midi_path": analysis.midi_path,
        "has_melodic": analysis.has_melodic,
        "melodic_version": analysis.melodic_version,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
    }


@router.get("/{track_id}/analysis/report")
async def get_analysis_report(track_id: UUID, db: DbSession, format: str = "md"):
    """Download the analysis report as markdown or JSON."""
    analysis = (
        await db.execute(
            select(TrackAnalysis)
            .where(TrackAnalysis.track_id == track_id)
        )
    ).scalar_one_or_none()

    if not analysis or not analysis.analysis_detail:
        raise NotFoundError("Analysis not found")

    track = (await db.execute(select(Track).where(Track.id == track_id))).scalar_one_or_none()
    if not track:
        raise TrackNotFoundError()

    # If melodic analysis hasn't run yet, is stale, or outdated version, run on-demand
    from app.config import MELODIC_VERSION
    if (not analysis.has_melodic
            or "melodic" not in (analysis.analysis_detail or {})
            or (analysis.melodic_version or 0) < MELODIC_VERSION):
        from app.services.track_analysis import run_analysis

        bg = get_background_manager()
        await bg.run_cpu_bound_ondemand(run_analysis, str(track_id))

        # Re-fetch with updated melodic data (expire to bypass identity map cache)
        db.expire_all()
        analysis = (
            await db.execute(
                select(TrackAnalysis)
                .where(TrackAnalysis.track_id == track_id)
            )
        ).scalar_one_or_none()

    track_meta = {
        "artist": track.artist,
        "title": track.title,
        "album": track.album,
        "duration_seconds": track.duration_seconds,
    }

    if format == "json":
        return analysis.analysis_detail

    report = generate_report(analysis.analysis_detail, track_meta, track_id=str(track_id))
    filename = f"{track.artist or 'Unknown'} - {track.title or 'Unknown'} - analysis.md"
    filename = "".join(c for c in filename if c.isalnum() or c in " -_.").strip()

    return StreamingResponse(
        iter([report]),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{track_id}/analysis/similarity.png")
async def get_similarity_image(track_id: UUID, db: DbSession):
    """Serve the self-similarity matrix PNG for a track."""
    from pathlib import Path

    analysis = (
        await db.execute(
            select(TrackAnalysis)
            .where(TrackAnalysis.track_id == track_id)
        )
    ).scalar_one_or_none()

    if not analysis or not analysis.analysis_detail:
        raise NotFoundError("Analysis not found")

    ssm_path = analysis.analysis_detail.get("structural", {}).get("self_similarity_png_path")
    if not ssm_path:
        raise NotFoundError("Similarity image not available")

    ssm_file = Path(ssm_path)
    if not ssm_file.exists():
        raise NotFoundError("Similarity image not found on disk")

    def file_iter():
        with open(ssm_file, "rb") as f:
            yield f.read()

    return StreamingResponse(
        file_iter(),
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="{track_id}_similarity.png"'},
    )


@router.get("/{track_id}/analysis/midi")
async def get_analysis_midi(track_id: UUID, db: DbSession):
    """Download the MIDI transcription file if available."""
    from pathlib import Path

    analysis = (
        await db.execute(
            select(TrackAnalysis)
            .where(TrackAnalysis.track_id == track_id)
        )
    ).scalar_one_or_none()

    if not analysis or not analysis.midi_path:
        raise NotFoundError("MIDI file not available")

    midi_file = Path(analysis.midi_path)
    if not midi_file.exists():
        raise NotFoundError("MIDI file not found on disk")

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
