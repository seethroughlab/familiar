"""API routes for new releases discovery."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import DbSession, RequiredProfile
from app.services.new_releases import NewReleasesService
from app.services.tasks import (
    clear_new_releases_progress,
    get_new_releases_progress,
)

router = APIRouter(prefix="/new-releases", tags=["new-releases"])


class NewReleaseItem(BaseModel):
    """A discovered release by an artist in the library.

    Deliberately *not* ``ExternalAlbumResponse``, which the recommendation surfaces
    use: that model requires ``match_score`` and ``seed_artist``, and this surface has
    no notion of either — a release by an artist you already listen to was not matched
    against a seed. Sharing the model would mean inventing two values to satisfy it.
    """

    id: str
    artist_name: str
    release_name: str
    release_type: str | None
    release_date: str | None
    artwork_url: str
    external_url: str | None
    track_count: int | None
    local_album_match: bool
    dismissed: bool
    discovered_at: str
    # {store_name: {"url": ..., "label": ...}} from generate_release_search_urls()
    purchase_links: dict[str, dict[str, str]]


class NewReleasesListResponse(BaseModel):
    """A page of discovered releases, with the age of the data behind it."""

    releases: list[NewReleaseItem]
    total: int
    limit: int
    offset: int
    #: When discovery last wrote a release, and how long ago that was. ``None`` means
    #: it has never written one — which is not the same as "there is nothing new",
    #: and a client showing an empty list must be able to tell the two apart
    #: (ADR-0099 points 7 and 8).
    as_of: str | None = None
    age_hours: float | None = None


@router.get("", response_model=NewReleasesListResponse)
async def list_new_releases(
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    include_dismissed: bool = Query(default=False),
    include_owned: bool = Query(default=False),
) -> dict[str, Any]:
    """List cached new releases (MusicBrainz-discovered) for artists in the library.

    Query params:
    - limit: Max releases to return (1-100)
    - offset: Pagination offset
    - include_dismissed: Include releases the user dismissed
    - include_owned: Include releases the user already owns locally
    """
    service = NewReleasesService(db)

    releases = await service.get_cached_releases(
        limit=limit,
        offset=offset,
        include_dismissed=include_dismissed,
        include_owned=include_owned,
    )

    total = await service.get_releases_count(
        include_dismissed=include_dismissed,
        include_owned=include_owned,
    )

    as_of, age_hours = await service.get_discovery_freshness()

    return {
        "releases": releases,
        "total": total,
        "limit": limit,
        "offset": offset,
        "as_of": as_of.isoformat() if as_of else None,
        "age_hours": round(age_hours, 1) if age_hours is not None else None,
    }


@router.get("/status")
async def get_status(
    db: DbSession,
    profile: RequiredProfile,
) -> dict[str, Any]:
    """Get new releases check status: DB stats, in-flight progress, rotation."""
    service = NewReleasesService(db)

    db_stats = await service.get_check_status()
    progress = get_new_releases_progress()
    rotation = await service.get_rotation_status(profile.id)

    return {
        **db_stats,
        "progress": progress,
        "rotation": rotation,
    }


@router.post("/check")
async def trigger_check(
    profile: RequiredProfile,
    days_back: int = Query(default=90, ge=1, le=365),
    force: bool = Query(default=False),
) -> dict[str, Any]:
    """Trigger a full background check of every library artist via MusicBrainz.

    Query params:
    - days_back: Number of days to look back (1-365)
    - force: If true, check all artists regardless of cache age
    """
    import asyncio

    from app.services.background import get_background_manager

    clear_new_releases_progress()

    bg = get_background_manager()
    asyncio.create_task(
        bg.run_new_releases_check(
            profile_id=str(profile.id),
            days_back=days_back,
            force=force,
        )
    )

    return {
        "status": "started",
        "message": "New releases check started",
    }


@router.post("/check/batch")
async def trigger_batch_check(
    profile: RequiredProfile,
    batch_size: int = Query(default=75, ge=10, le=200),
    days_back: int = Query(default=90, ge=1, le=365),
) -> dict[str, Any]:
    """Trigger a priority-based batch check (only artists the user has listened to)."""
    import asyncio

    from app.services.background import get_background_manager

    clear_new_releases_progress()

    bg = get_background_manager()
    asyncio.create_task(
        bg.run_prioritized_new_releases_check(
            profile_id=str(profile.id),
            batch_size=batch_size,
            days_back=days_back,
        )
    )

    return {
        "status": "started",
        "message": f"Priority-based new releases check started (batch size: {batch_size})",
    }


@router.post("/{release_id}/dismiss")
async def dismiss_release(
    release_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> dict[str, Any]:
    """Dismiss a release (hide from default list; visible with include_dismissed=true)."""
    service = NewReleasesService(db)

    success = await service.dismiss_release(release_id, profile.id)
    if not success:
        raise HTTPException(status_code=404, detail="Release not found")

    await db.commit()

    return {"status": "ok", "message": "Release dismissed"}
