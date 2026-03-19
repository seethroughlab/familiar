"""Library deduplication endpoints — find and remove duplicate tracks."""

import logging
from collections import defaultdict
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DbSession
from app.db.models import Track, TrackStatus
from app.services.normalize import normalize_for_duplicate_matching
from app.services.quality import QualityScore, calculate_quality_score

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/deduplicate", tags=["deduplicate"])


# ── Response models ────────────────────────────────────────────


class TrackInfo(BaseModel):
    id: UUID
    title: str | None
    artist: str | None
    album: str | None
    file_path: str
    format: str | None
    quality: str
    format_tier: int
    metadata_completeness: int
    created_at: str


class DuplicateGroup(BaseModel):
    normalized_key: str
    keep: TrackInfo
    remove: list[TrackInfo]


class DeduplicatePreviewResponse(BaseModel):
    total_groups: int
    total_duplicates: int
    groups: list[DuplicateGroup]


# ── Helpers ────────────────────────────────────────────────────


_METADATA_FIELDS = ("year", "genre", "track_number", "disc_number", "album_artist", "composer")


def _metadata_completeness(track: Track) -> int:
    """Count non-null metadata fields for tiebreaking."""
    return sum(1 for f in _METADATA_FIELDS if getattr(track, f, None) is not None)


def _quality_score(track: Track) -> QualityScore:
    return calculate_quality_score(
        format=track.format,
        bitrate=track.bitrate,
        sample_rate=track.sample_rate,
        bit_depth=track.bit_depth,
        bitrate_mode=track.bitrate_mode,
    )


def _sort_key(track: Track) -> tuple:
    """Sort key for choosing the best track: higher is better for first two, earlier is better for third."""
    qs = _quality_score(track)
    return (
        qs.format_tier.value,
        _metadata_completeness(track),
        -(track.created_at.timestamp() if track.created_at else 0),
    )


def _track_info(track: Track) -> TrackInfo:
    qs = _quality_score(track)
    return TrackInfo(
        id=track.id,
        title=track.title,
        artist=track.artist,
        album=track.album,
        file_path=track.file_path,
        format=track.format,
        quality=qs.format_string(),
        format_tier=qs.format_tier.value,
        metadata_completeness=_metadata_completeness(track),
        created_at=track.created_at.isoformat() if track.created_at else "",
    )


# ── Endpoints ──────────────────────────────────────────────────


@router.post("/preview", response_model=DeduplicatePreviewResponse)
async def deduplicate_preview(
    db: DbSession,
    search: str | None = Query(None),
    artist: str | None = Query(None),
    album: str | None = Query(None),
) -> DeduplicatePreviewResponse:
    """Find duplicate tracks and show what would be kept/removed."""
    stmt = select(Track).where(Track.active_filter())
    if artist:
        stmt = stmt.where(Track.artist.ilike(f"%{artist}%"))
    if album:
        stmt = stmt.where(Track.album.ilike(f"%{album}%"))
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            Track.title.ilike(pattern)
            | Track.artist.ilike(pattern)
            | Track.album.ilike(pattern)
        )

    result = await db.execute(stmt)
    tracks = list(result.scalars().all())

    # Group by normalized (artist, album, title)
    groups: dict[str, list[Track]] = defaultdict(list)
    for track in tracks:
        key = (
            normalize_for_duplicate_matching(track.artist, strip_articles=True),
            normalize_for_duplicate_matching(track.album),
            normalize_for_duplicate_matching(track.title),
        )
        groups["|".join(key)].append(track)

    # Build response for groups with duplicates
    duplicate_groups: list[DuplicateGroup] = []
    total_dupes = 0

    for norm_key, group_tracks in sorted(groups.items()):
        if len(group_tracks) < 2:
            continue

        # Sort: best first
        group_tracks.sort(key=_sort_key, reverse=True)
        keep = group_tracks[0]
        remove = group_tracks[1:]
        total_dupes += len(remove)

        duplicate_groups.append(
            DuplicateGroup(
                normalized_key=norm_key,
                keep=_track_info(keep),
                remove=[_track_info(t) for t in remove],
            )
        )

    return DeduplicatePreviewResponse(
        total_groups=len(duplicate_groups),
        total_duplicates=total_dupes,
        groups=duplicate_groups,
    )
