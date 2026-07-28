"""Pending review queue API — manage newly discovered tracks awaiting user approval."""

import logging
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import TrackNotFoundError, ValidationError
from app.db.models import Track, TrackStatus
from app.utils.time import to_rfc3339

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pending-tracks", tags=["pending-review"])
group_router = APIRouter(prefix="/pending-tracks/group", tags=["pending-review"])
bulk_router = APIRouter(prefix="/pending-tracks/bulk", tags=["pending-review"])

# Review statuses the listing/un-skip endpoints can target.
_REVIEW_STATUSES = {
    "pending_review": TrackStatus.PENDING_REVIEW,
    "skipped": TrackStatus.SKIPPED,
}


# ============================================================================
# Request/Response Models
# ============================================================================


class PendingTrackResponse(BaseModel):
    """A pending track with review_info."""
    id: str
    file_path: str
    title: str | None
    artist: str | None
    album: str | None
    album_artist: str | None
    track_number: int | None
    disc_number: int | None
    year: int | None
    genre: str | None
    duration_seconds: float | None
    format: str | None
    sample_rate: int | None
    bit_depth: int | None
    bitrate: int | None
    bitrate_mode: str | None
    codec: str | None
    created_at: str
    review_info: dict[str, Any] | None


class PendingGroupResponse(BaseModel):
    """A group of pending tracks from the same folder."""
    folder_path: str
    folder_name: str
    track_count: int
    duplicate_count: int
    upgrade_count: int
    downgrade_count: int
    earliest_scan: str
    tracks: list[PendingTrackResponse]


class PendingGroupsListResponse(BaseModel):
    """Paginated list of groups."""
    groups: list[PendingGroupResponse]
    total_groups: int
    total_tracks: int


class PendingStatsResponse(BaseModel):
    """Counts for sidebar badge."""
    total_tracks: int
    total_groups: int
    with_duplicates: int
    upgrades: int
    downgrades: int


class ApproveRequest(BaseModel):
    metadata_overrides: dict[str, Any] | None = None
    queue_analysis: bool = True


class ReplaceRequest(BaseModel):
    replace_track_id: str
    metadata_overrides: dict[str, Any] | None = None
    queue_analysis: bool = True
    transfer_user_data: bool = True


class GroupApproveRequest(BaseModel):
    folder_path: str
    queue_analysis: bool = True
    metadata_overrides: dict[str, Any] | None = None


class GroupSkipRequest(BaseModel):
    folder_path: str


class GroupReplaceUpgradesRequest(BaseModel):
    folder_path: str
    queue_analysis: bool = True


class GroupSkipDowngradesRequest(BaseModel):
    folder_path: str


class GroupMetadataRequest(BaseModel):
    folder_path: str
    metadata: dict[str, Any]


class BulkRequest(BaseModel):
    queue_analysis: bool = True


class MetadataUpdateRequest(BaseModel):
    artist: str | None = None
    album: str | None = None
    title: str | None = None
    track_number: int | None = None
    year: int | None = None


# ============================================================================
# Helpers
# ============================================================================


def _folder_path(file_path: str) -> str:
    """Extract the immediate parent directory from a file path."""
    return str(PurePosixPath(file_path).parent)


def _folder_name(folder_path: str) -> str:
    """Extract the folder name from a path."""
    return PurePosixPath(folder_path).name


def _track_to_response(track: Track) -> PendingTrackResponse:
    return PendingTrackResponse(
        id=str(track.id),
        file_path=track.file_path,
        title=track.title,
        artist=track.artist,
        album=track.album,
        album_artist=track.album_artist,
        track_number=track.track_number,
        disc_number=track.disc_number,
        year=track.year,
        genre=track.genre,
        duration_seconds=track.duration_seconds,
        format=track.format,
        sample_rate=track.sample_rate,
        bit_depth=track.bit_depth,
        bitrate=track.bitrate,
        bitrate_mode=track.bitrate_mode,
        codec=track.codec,
        created_at=to_rfc3339(track.created_at),
        review_info=track.review_info,
    )


async def _get_pending_track(
    db: AsyncSession, track_id: UUID, status: TrackStatus = TrackStatus.PENDING_REVIEW
) -> Track:
    """Fetch a track in the given review status (default PENDING_REVIEW) or raise 404."""
    result = await db.execute(
        select(Track).where(Track.id == track_id, Track.status == status)
    )
    track = result.scalar_one_or_none()
    if not track:
        raise TrackNotFoundError()
    return track


def _escape_like(s: str) -> str:
    """Escape SQL LIKE wildcards in a string."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _get_pending_tracks_in_folder(
    db: AsyncSession, folder_path: str, status: TrackStatus = TrackStatus.PENDING_REVIEW
) -> list[Track]:
    """Get all tracks in the given review status whose file_path starts with folder_path/."""
    escaped_prefix = _escape_like(folder_path.rstrip("/")) + "/"
    result = await db.execute(
        select(Track).where(
            Track.status == status,
            Track.file_path.like(escaped_prefix + "%", escape="\\"),
            # Ensure we only get files directly in this folder (not subfolders)
            ~Track.file_path.like(escaped_prefix + "%/%", escape="\\"),
        )
    )
    return list(result.scalars().all())


def _apply_metadata_overrides(track: Track, overrides: dict[str, Any] | None) -> None:
    """Apply metadata overrides to a track."""
    if not overrides:
        return
    allowed = {"artist", "album", "title", "track_number", "year", "album_artist", "genre"}
    for key, value in overrides.items():
        if key in allowed:
            setattr(track, key, value)


async def _activate_track(db: AsyncSession, track: Track, queue_analysis: bool = True) -> None:
    """Set track to ACTIVE and clear review_info."""
    track.status = TrackStatus.ACTIVE
    track.review_info = None
    if queue_analysis:
        await _queue_for_analysis(track)


async def _queue_for_analysis(track: Track) -> None:
    """Queue a track for analysis.

    Analysis pipeline auto-discovers unanalyzed ACTIVE tracks on its next run.
    No explicit queueing needed — setting the track to ACTIVE is sufficient.
    """


async def _transfer_user_data(db: AsyncSession, old_track_id: UUID, new_track_id: UUID) -> None:
    """Transfer favorites, playlist entries, play history from old track to new.

    Uses DELETE-before-UPDATE to avoid unique constraint violations on composite
    primary keys (profile_id, track_id) when the user already has data for both tracks.
    """
    from sqlalchemy import delete

    from app.db.models import PlaylistTrack, ProfileFavorite, ProfilePlayHistory

    # Delete any existing favorites/history for new_track_id to avoid PK conflicts
    await db.execute(
        delete(ProfileFavorite).where(ProfileFavorite.track_id == new_track_id)
    )
    await db.execute(
        delete(ProfilePlayHistory).where(ProfilePlayHistory.track_id == new_track_id)
    )

    # Now safe to transfer from old to new
    await db.execute(
        update(ProfileFavorite)
        .where(ProfileFavorite.track_id == old_track_id)
        .values(track_id=new_track_id)
    )

    # Update playlist entries (PlaylistTrack has its own UUID PK, no conflict)
    await db.execute(
        update(PlaylistTrack)
        .where(PlaylistTrack.track_id == old_track_id)
        .values(track_id=new_track_id)
    )

    # Update play history
    await db.execute(
        update(ProfilePlayHistory)
        .where(ProfilePlayHistory.track_id == old_track_id)
        .values(track_id=new_track_id)
    )


# ============================================================================
# Group endpoints
# ============================================================================


@router.get("/groups", response_model=PendingGroupsListResponse)
async def list_groups(
    db: DbSession,
    sort_by: str = Query("created_at", pattern="^(folder_name|track_count|created_at)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    search: str | None = None,
    status: str = Query("pending_review", pattern="^(pending_review|skipped)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> PendingGroupsListResponse:
    """List import groups of tracks awaiting review (default) or previously skipped."""
    review_status = _REVIEW_STATUSES[status]
    query = select(Track).where(Track.status == review_status)

    if search:
        search_filter = f"%{search}%"
        query = query.where(
            Track.title.ilike(search_filter)
            | Track.artist.ilike(search_filter)
            | Track.album.ilike(search_filter)
            | Track.file_path.ilike(search_filter)
        )

    query = query.order_by(Track.created_at.asc())
    result = await db.execute(query)
    tracks = list(result.scalars().all())

    # Group by folder
    groups_dict: dict[str, list[Track]] = {}
    for track in tracks:
        fp = _folder_path(track.file_path)
        groups_dict.setdefault(fp, []).append(track)

    # Build group responses
    group_responses: list[PendingGroupResponse] = []
    for fp, group_tracks in groups_dict.items():
        duplicate_count = sum(1 for t in group_tracks if t.review_info and t.review_info.get("duplicate_of"))
        upgrade_count = sum(1 for t in group_tracks if t.review_info and t.review_info.get("trump_status") == "trumps")
        downgrade_count = sum(1 for t in group_tracks if t.review_info and t.review_info.get("trump_status") == "trumped_by")
        earliest = min(t.created_at for t in group_tracks)

        group_responses.append(PendingGroupResponse(
            folder_path=fp,
            folder_name=_folder_name(fp),
            track_count=len(group_tracks),
            duplicate_count=duplicate_count,
            upgrade_count=upgrade_count,
            downgrade_count=downgrade_count,
            earliest_scan=to_rfc3339(earliest),
            tracks=[_track_to_response(t) for t in group_tracks],
        ))

    # Sort groups
    if sort_by == "folder_name":
        group_responses.sort(key=lambda g: g.folder_name.lower(), reverse=(sort_order == "desc"))
    elif sort_by == "track_count":
        group_responses.sort(key=lambda g: g.track_count, reverse=(sort_order == "desc"))
    else:  # created_at
        group_responses.sort(key=lambda g: g.earliest_scan, reverse=(sort_order == "desc"))

    total_groups = len(group_responses)
    total_tracks = len(tracks)
    group_responses = group_responses[offset:offset + limit]

    return PendingGroupsListResponse(
        groups=group_responses,
        total_groups=total_groups,
        total_tracks=total_tracks,
    )


@router.get("/stats", response_model=PendingStatsResponse)
async def get_stats(db: DbSession) -> PendingStatsResponse:
    """Get counts for sidebar badge."""
    result = await db.execute(
        select(Track).where(Track.status == TrackStatus.PENDING_REVIEW)
    )
    tracks = list(result.scalars().all())

    folders = set()
    with_duplicates = 0
    upgrades = 0
    downgrades = 0

    for t in tracks:
        folders.add(_folder_path(t.file_path))
        if t.review_info and t.review_info.get("duplicate_of"):
            with_duplicates += 1
            if t.review_info.get("trump_status") == "trumps":
                upgrades += 1
            elif t.review_info.get("trump_status") == "trumped_by":
                downgrades += 1

    return PendingStatsResponse(
        total_tracks=len(tracks),
        total_groups=len(folders),
        with_duplicates=with_duplicates,
        upgrades=upgrades,
        downgrades=downgrades,
    )


# ============================================================================
# Group actions (on group_router to avoid /{track_id} path conflict)
# ============================================================================


@group_router.post("/approve")
async def group_approve(
    db: DbSession,
    _profile: RequiredProfile,
    request: GroupApproveRequest,
) -> dict[str, Any]:
    """Approve all pending tracks in a folder."""
    tracks = await _get_pending_tracks_in_folder(db, request.folder_path)
    if not tracks:
        raise ValidationError("No pending tracks found in folder")

    for track in tracks:
        _apply_metadata_overrides(track, request.metadata_overrides)
        await _activate_track(db, track, request.queue_analysis)

    await db.commit()
    return {"status": "approved", "count": len(tracks)}


@group_router.post("/skip")
async def group_skip(
    db: DbSession,
    _profile: RequiredProfile,
    request: GroupSkipRequest,
) -> dict[str, Any]:
    """Skip all pending tracks in a folder."""
    tracks = await _get_pending_tracks_in_folder(db, request.folder_path)
    if not tracks:
        raise ValidationError("No pending tracks found in folder")

    for track in tracks:
        track.status = TrackStatus.SKIPPED
        track.review_info = None

    await db.commit()
    return {"status": "skipped", "count": len(tracks)}


@group_router.post("/unskip")
async def group_unskip(
    db: DbSession,
    _profile: RequiredProfile,
    request: GroupSkipRequest,
) -> dict[str, Any]:
    """Return all skipped tracks in a folder to the review queue."""
    tracks = await _get_pending_tracks_in_folder(
        db, request.folder_path, status=TrackStatus.SKIPPED
    )
    if not tracks:
        raise ValidationError("No skipped tracks found in folder")

    for track in tracks:
        track.status = TrackStatus.PENDING_REVIEW

    await db.commit()
    return {"status": "pending_review", "count": len(tracks)}


@group_router.post("/replace-upgrades")
async def group_replace_upgrades(
    db: DbSession,
    _profile: RequiredProfile,
    request: GroupReplaceUpgradesRequest,
) -> dict[str, Any]:
    """Replace all upgrades within a group."""
    tracks = await _get_pending_tracks_in_folder(db, request.folder_path)
    replaced = 0

    for track in tracks:
        if not (track.review_info and track.review_info.get("trump_status") == "trumps"):
            continue
        old_track_id_str = track.review_info.get("duplicate_of")
        if not old_track_id_str:
            continue

        old_track_id = UUID(old_track_id_str)
        old_result = await db.execute(select(Track).where(Track.id == old_track_id))
        old_track = old_result.scalar_one_or_none()
        if not old_track:
            continue

        await _transfer_user_data(db, old_track_id, track.id)
        await _activate_track(db, track, request.queue_analysis)
        old_track.status = TrackStatus.SKIPPED
        replaced += 1

    await db.commit()
    return {"status": "replaced", "count": replaced}


@group_router.post("/skip-downgrades")
async def group_skip_downgrades(
    db: DbSession,
    _profile: RequiredProfile,
    request: GroupSkipDowngradesRequest,
) -> dict[str, Any]:
    """Skip all downgrades within a group."""
    tracks = await _get_pending_tracks_in_folder(db, request.folder_path)
    skipped = 0

    for track in tracks:
        if track.review_info and track.review_info.get("trump_status") == "trumped_by":
            track.status = TrackStatus.SKIPPED
            track.review_info = None
            skipped += 1

    await db.commit()
    return {"status": "skipped", "count": skipped}


@group_router.post("/metadata")
async def group_metadata(
    db: DbSession,
    _profile: RequiredProfile,
    request: GroupMetadataRequest,
) -> dict[str, Any]:
    """Edit shared metadata for all pending tracks in a group."""
    tracks = await _get_pending_tracks_in_folder(db, request.folder_path)
    if not tracks:
        raise ValidationError("No pending tracks found in folder")

    _allowed = {"artist", "album", "year", "album_artist", "genre"}
    for track in tracks:
        for key, value in request.metadata.items():
            if key in _allowed:
                setattr(track, key, value)

    await db.commit()
    return {"status": "updated", "count": len(tracks)}


# ============================================================================
# Bulk actions (on bulk_router to avoid /{track_id} path conflict)
# ============================================================================


@bulk_router.post("/approve-all")
async def bulk_approve_all(
    db: DbSession,
    _profile: RequiredProfile,
    request: BulkRequest,
) -> dict[str, Any]:
    """Approve all pending tracks globally."""
    result = await db.execute(
        select(Track).where(Track.status == TrackStatus.PENDING_REVIEW)
    )
    tracks = list(result.scalars().all())

    for track in tracks:
        await _activate_track(db, track, request.queue_analysis)

    await db.commit()
    return {"status": "approved", "count": len(tracks)}


@bulk_router.post("/skip-all")
async def bulk_skip_all(db: DbSession, _profile: RequiredProfile) -> dict[str, Any]:
    """Skip all pending tracks globally."""
    result = await db.execute(
        update(Track)
        .where(Track.status == TrackStatus.PENDING_REVIEW)
        .values(status=TrackStatus.SKIPPED, review_info=None)
    )
    await db.commit()
    return {"status": "skipped", "count": result.rowcount}  # type: ignore[attr-defined]


@bulk_router.post("/unskip-all")
async def bulk_unskip_all(db: DbSession, _profile: RequiredProfile) -> dict[str, Any]:
    """Return all skipped tracks to the review queue globally."""
    result = await db.execute(
        update(Track)
        .where(Track.status == TrackStatus.SKIPPED)
        .values(status=TrackStatus.PENDING_REVIEW)
    )
    await db.commit()
    return {"status": "pending_review", "count": result.rowcount}  # type: ignore[attr-defined]


# ============================================================================
# Single track actions
# ============================================================================


@router.post("/{track_id}/approve")
async def approve_track(
    db: DbSession,
    _profile: RequiredProfile,
    track_id: UUID,
    request: ApproveRequest,
) -> dict[str, str]:
    """Approve a single pending track."""
    track = await _get_pending_track(db, track_id)
    _apply_metadata_overrides(track, request.metadata_overrides)
    await _activate_track(db, track, request.queue_analysis)
    await db.commit()
    return {"status": "approved", "track_id": str(track_id)}


@router.post("/{track_id}/replace")
async def replace_track(
    db: DbSession,
    _profile: RequiredProfile,
    track_id: UUID,
    request: ReplaceRequest,
) -> dict[str, str]:
    """Replace an existing duplicate with the pending track."""
    track = await _get_pending_track(db, track_id)

    # Get the existing track to replace
    try:
        old_track_id = UUID(request.replace_track_id)
    except ValueError:
        raise ValidationError("Invalid replace_track_id format")

    old_result = await db.execute(select(Track).where(Track.id == old_track_id))
    old_track = old_result.scalar_one_or_none()
    if not old_track:
        raise TrackNotFoundError()

    # Transfer user data before changing statuses
    if request.transfer_user_data:
        await _transfer_user_data(db, old_track_id, track_id)

    # New track → ACTIVE
    _apply_metadata_overrides(track, request.metadata_overrides)
    await _activate_track(db, track, request.queue_analysis)

    # Old track → SKIPPED
    old_track.status = TrackStatus.SKIPPED

    await db.commit()
    return {"status": "replaced", "track_id": str(track_id), "replaced_track_id": str(old_track_id)}


@router.post("/{track_id}/skip")
async def skip_track(
    db: DbSession,
    _profile: RequiredProfile,
    track_id: UUID,
) -> dict[str, str]:
    """Permanently ignore a pending track."""
    track = await _get_pending_track(db, track_id)
    track.status = TrackStatus.SKIPPED
    track.review_info = None
    await db.commit()
    return {"status": "skipped", "track_id": str(track_id)}


@router.post("/{track_id}/unskip")
async def unskip_track(
    db: DbSession,
    _profile: RequiredProfile,
    track_id: UUID,
) -> dict[str, str]:
    """Return a skipped track to the review queue (SKIPPED -> PENDING_REVIEW).

    review_info stays None — the track re-enters review as a clean pending item; duplicate
    detection is not re-run.
    """
    track = await _get_pending_track(db, track_id, status=TrackStatus.SKIPPED)
    track.status = TrackStatus.PENDING_REVIEW
    await db.commit()
    return {"status": "pending_review", "track_id": str(track_id)}


@router.patch("/{track_id}/metadata")
async def update_track_metadata(
    db: DbSession,
    _profile: RequiredProfile,
    track_id: UUID,
    request: MetadataUpdateRequest,
) -> dict[str, str]:
    """Edit metadata on a pending track before approving."""
    track = await _get_pending_track(db, track_id)
    updates = request.model_dump(exclude_none=True)
    for key, value in updates.items():
        setattr(track, key, value)
    await db.commit()
    return {"status": "updated", "track_id": str(track_id)}
