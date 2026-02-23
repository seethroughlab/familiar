"""External track management endpoints.

External tracks are tracks the user wants but doesn't have locally.
They appear in playlists alongside local tracks with visual distinction.
"""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import sanitize_error_for_client
from app.db.models import ExternalTrack, ExternalTrackSource
from app.services.external_track_matcher import ExternalTrackMatcher

router = APIRouter(prefix="/external-tracks", tags=["external-tracks"])


class ExternalTrackCreate(BaseModel):
    """Request to create an external track."""

    title: str = Field(..., min_length=1, max_length=500)
    artist: str = Field(..., min_length=1, max_length=500)
    album: str | None = Field(None, max_length=500)
    duration_seconds: float | None = None
    year: int | None = None
    isrc: str | None = Field(None, max_length=12)
    spotify_id: str | None = Field(None, max_length=50)
    external_data: dict | None = None


class ExternalTrackResponse(BaseModel):
    """External track response."""

    id: str
    title: str
    artist: str
    album: str | None
    duration_seconds: float | None
    track_number: int | None
    year: int | None
    source: str
    external_data: dict

    # Matching status
    is_matched: bool
    matched_track_id: str | None
    matched_at: str | None
    match_confidence: float | None
    match_method: str | None

    # External IDs
    spotify_id: str | None
    isrc: str | None

    created_at: str


class ManualMatchRequest(BaseModel):
    """Request to manually match an external track."""

    track_id: str = Field(..., description="ID of local track to match to")


class RematchResponse(BaseModel):
    """Response from rematch operation."""

    processed: int
    matched: int
    task_id: str | None = None


@router.get("", response_model=list[ExternalTrackResponse])
async def list_external_tracks(
    db: DbSession,
    profile: RequiredProfile,
    matched: bool | None = Query(None, description="Filter by matched status"),
    source: str | None = Query(None, description="Filter by source"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[ExternalTrackResponse]:
    """List external tracks with optional filtering."""
    query = select(ExternalTrack)

    if matched is not None:
        if matched:
            query = query.where(ExternalTrack.matched_track_id.isnot(None))
        else:
            query = query.where(ExternalTrack.matched_track_id.is_(None))

    if source:
        try:
            source_enum = ExternalTrackSource(source)
            query = query.where(ExternalTrack.source == source_enum)
        except ValueError:
            pass  # Invalid source, ignore filter

    query = query.order_by(ExternalTrack.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    tracks = result.scalars().all()

    return [_external_track_to_response(t) for t in tracks]


@router.get("/stats")
async def get_external_track_stats(
    db: DbSession,
    profile: RequiredProfile,
) -> dict:
    """Get statistics about external tracks."""
    # Total count
    total = await db.scalar(select(func.count(ExternalTrack.id))) or 0

    # Matched count
    matched = await db.scalar(
        select(func.count(ExternalTrack.id)).where(
            ExternalTrack.matched_track_id.isnot(None)
        )
    ) or 0

    # Count by source
    source_counts = {}
    for source in ExternalTrackSource:
        count = await db.scalar(
            select(func.count(ExternalTrack.id)).where(
                ExternalTrack.source == source
            )
        ) or 0
        source_counts[source.value] = count

    return {
        "total": total,
        "matched": matched,
        "unmatched": total - matched,
        "match_rate": round(matched / total * 100, 1) if total > 0 else 0,
        "by_source": source_counts,
    }


@router.post("", response_model=ExternalTrackResponse, status_code=status.HTTP_201_CREATED)
async def create_external_track(
    request: ExternalTrackCreate,
    db: DbSession,
    profile: RequiredProfile,
) -> ExternalTrackResponse:
    """Create a new external track (manually added)."""
    matcher = ExternalTrackMatcher(db)

    external_track = await matcher.create_external_track(
        title=request.title,
        artist=request.artist,
        album=request.album,
        source=ExternalTrackSource.MANUAL,
        spotify_id=request.spotify_id,
        isrc=request.isrc,
        duration_seconds=request.duration_seconds,
        external_data=request.external_data,
        try_match=True,
    )

    return _external_track_to_response(external_track)


@router.get("/{external_track_id}", response_model=ExternalTrackResponse)
async def get_external_track(
    external_track_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> ExternalTrackResponse:
    """Get an external track by ID."""
    external_track = await db.get(ExternalTrack, external_track_id)

    if not external_track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="External track not found",
        )

    return _external_track_to_response(external_track)


class MatchCandidate(BaseModel):
    """A candidate local track for manual matching."""

    track_id: str
    title: str | None
    artist: str | None
    album: str | None
    duration_seconds: float | None
    format: str | None
    year: int | None
    match_method: str
    confidence: float


class MatchCandidatesResponse(BaseModel):
    """Response with candidate matches for an external track."""

    candidates: list[MatchCandidate]


@router.get("/{external_track_id}/match-candidates", response_model=MatchCandidatesResponse)
async def get_match_candidates(
    external_track_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
    limit: int = Query(10, ge=1, le=50),
) -> MatchCandidatesResponse:
    """Get smart-matched candidate local tracks for manual matching.

    Uses the same matching algorithm as automatic matching (ISRC, exact,
    partial, fuzzy) but with a lower threshold, returning multiple candidates
    for the user to choose from.
    """
    external_track = await db.get(ExternalTrack, external_track_id)

    if not external_track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="External track not found",
        )

    matcher = ExternalTrackMatcher(db)
    candidates = await matcher.find_match_candidates(
        title=external_track.title,
        artist=external_track.artist,
        album=external_track.album,
        isrc=external_track.isrc,
        limit=limit,
    )

    return MatchCandidatesResponse(candidates=[MatchCandidate(**c) for c in candidates])


@router.delete("/{external_track_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_external_track(
    external_track_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> None:
    """Delete an external track."""
    external_track = await db.get(ExternalTrack, external_track_id)

    if not external_track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="External track not found",
        )

    await db.delete(external_track)
    await db.commit()


@router.post("/{external_track_id}/match", response_model=ExternalTrackResponse)
async def manual_match(
    external_track_id: UUID,
    request: ManualMatchRequest,
    db: DbSession,
    profile: RequiredProfile,
) -> ExternalTrackResponse:
    """Manually match an external track to a local track."""
    matcher = ExternalTrackMatcher(db)

    try:
        track_id = UUID(request.track_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid track_id format",
        )

    try:
        external_track = await matcher.manual_match(external_track_id, track_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=sanitize_error_for_client(e, "Track not found"),
        )

    if not external_track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="External track not found",
        )

    return _external_track_to_response(external_track)


@router.delete("/{external_track_id}/match", response_model=ExternalTrackResponse)
async def remove_match(
    external_track_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> ExternalTrackResponse:
    """Remove the match from an external track."""
    matcher = ExternalTrackMatcher(db)
    external_track = await matcher.remove_match(external_track_id)

    if not external_track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="External track not found",
        )

    return _external_track_to_response(external_track)


@router.post("/rematch", response_model=RematchResponse)
async def rematch_all(
    db: DbSession,
    profile: RequiredProfile,
    background_tasks: BackgroundTasks,
    run_in_background: bool = Query(False, description="Run in background"),
) -> RematchResponse:
    """Re-run matching for all unmatched external tracks.

    If run_in_background=True, returns immediately with task_id.
    Otherwise, runs synchronously and returns results.
    """
    matcher = ExternalTrackMatcher(db)

    if run_in_background:
        # For now, just run synchronously but return task structure
        # TODO: Implement proper background task tracking
        stats = await matcher.rematch_all_unmatched()
        return RematchResponse(
            processed=stats["processed"],
            matched=stats["matched"],
            task_id=None,
        )
    else:
        stats = await matcher.rematch_all_unmatched()
        return RematchResponse(
            processed=stats["processed"],
            matched=stats["matched"],
        )


class AlbumMatchRequest(BaseModel):
    """Request to batch-match external tracks by album."""

    source_album: str = Field(..., description="Album name on external tracks")
    target_album: str = Field(..., description="Album name on local tracks")
    target_artist: str | None = Field(None, description="Optional artist filter for local tracks")


class AlbumMatchDetail(BaseModel):
    external_track_id: str
    title: str
    matched_track_id: str | None
    status: str


class AlbumMatchResponse(BaseModel):
    matched: int
    failed: int
    details: list[AlbumMatchDetail]


@router.post("/match-by-album", response_model=AlbumMatchResponse)
async def match_by_album(
    request: AlbumMatchRequest,
    db: DbSession,
    profile: RequiredProfile,
) -> AlbumMatchResponse:
    """Batch-match unmatched external tracks by album name.

    Finds all unmatched external tracks from source_album and fuzzy-matches
    their titles against local tracks from target_album. Uses a lower threshold
    since album context confirms they're the same content.
    """
    matcher = ExternalTrackMatcher(db)
    result = await matcher.match_by_album(
        source_album=request.source_album,
        target_album=request.target_album,
        target_artist=request.target_artist,
    )
    return AlbumMatchResponse(**result)


class MigrateMatchedResponse(BaseModel):
    """Response from migrate-matched operation."""

    external_tracks_processed: int
    playlist_entries_replaced: int


@router.post("/migrate-matched", response_model=MigrateMatchedResponse)
async def migrate_matched_to_local(
    db: DbSession,
    profile: RequiredProfile,
) -> MigrateMatchedResponse:
    """One-time migration to replace matched external tracks with local tracks in playlists.

    This finds all external tracks that have been matched to local tracks and updates
    all playlist entries that reference them to instead reference the local track directly.

    This is useful for cleaning up playlists that were created before the automatic
    replacement feature was added.
    """
    matcher = ExternalTrackMatcher(db)
    stats = await matcher.replace_all_matched_in_playlists()
    return MigrateMatchedResponse(
        external_tracks_processed=stats["external_tracks_processed"],
        playlist_entries_replaced=stats["playlist_entries_replaced"],
    )


def _external_track_to_response(track: ExternalTrack) -> ExternalTrackResponse:
    """Convert ExternalTrack model to response."""
    return ExternalTrackResponse(
        id=str(track.id),
        title=track.title,
        artist=track.artist,
        album=track.album,
        duration_seconds=track.duration_seconds,
        track_number=track.track_number,
        year=track.year,
        source=track.source.value,
        external_data=track.external_data or {},
        is_matched=track.matched_track_id is not None,
        matched_track_id=str(track.matched_track_id) if track.matched_track_id else None,
        matched_at=track.matched_at.isoformat() if track.matched_at else None,
        match_confidence=track.match_confidence,
        match_method=track.match_method,
        spotify_id=track.spotify_id,
        isrc=track.isrc,
        created_at=track.created_at.isoformat(),
    )
