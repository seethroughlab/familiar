"""Favorites management endpoints for profile-based track favorites."""

import logging
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import TrackNotFoundError
from app.api.schemas.common import UTCDateTime
from app.api.schemas.suggestions import (
    SuggestedTrackResponse,
    SuggestedTracksResponse,
    SuggestionReasonResponse,
)
from app.api.schemas.tracks import TrackResponse
from app.db.models import ProfileFavorite, ProfilePlayHistory, Track
from app.services.collection_suggestions import SEED_SAMPLE_CAP, suggest_for_collection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/favorites", tags=["favorites"])


class FavoriteTrackResponse(TrackResponse):
    """Track in favorites list — full track data plus favorited_at."""

    favorited_at: UTCDateTime | None = None


class FavoritesListResponse(BaseModel):
    """Response for favorites list."""

    favorites: list[FavoriteTrackResponse]
    total: int


class FavoriteStatusResponse(BaseModel):
    """Response for favorite status check."""

    track_id: UUID
    is_favorite: bool


async def _toggle_local_favorite(
    db: DbSession, profile_id: UUID, track_id: UUID
) -> bool:
    """Toggle a local track's favorite status. Returns new is_favorite state."""
    result = await db.execute(
        select(ProfileFavorite).where(
            ProfileFavorite.profile_id == profile_id,
            ProfileFavorite.track_id == track_id,
        )
    )
    favorite = result.scalar_one_or_none()

    if favorite:
        await db.delete(favorite)
        await db.commit()
        return False
    else:
        favorite = ProfileFavorite(profile_id=profile_id, track_id=track_id)
        db.add(favorite)
        await db.commit()
        return True


@router.get("", response_model=FavoritesListResponse)
async def list_favorites(
    db: DbSession,
    profile: RequiredProfile,
    limit: int = 100,
    offset: int = 0,
) -> FavoritesListResponse:
    """List all favorite tracks for the current profile."""
    # Get local favorites with track data
    result = await db.execute(
        select(ProfileFavorite, Track)
        .join(Track, ProfileFavorite.track_id == Track.id)
        .where(ProfileFavorite.profile_id == profile.id)
        .where(Track.active_filter())
        .order_by(ProfileFavorite.favorited_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.all()

    local_count = await db.scalar(
        select(func.count())
        .select_from(ProfileFavorite)
        .join(Track, ProfileFavorite.track_id == Track.id)
        .where(ProfileFavorite.profile_id == profile.id)
        .where(Track.active_filter())
    ) or 0

    # Fetch play history for all favorite tracks
    track_ids = [track.id for _, track in rows]
    play_history_map = {}
    if track_ids:
        ph_result = await db.execute(
            select(ProfilePlayHistory).where(
                ProfilePlayHistory.profile_id == profile.id,
                ProfilePlayHistory.track_id.in_(track_ids),
            )
        )
        play_history_map = {ph.track_id: ph for ph in ph_result.scalars().all()}

    favorites = []
    for favorite, track in rows:
        resp = FavoriteTrackResponse.model_validate(
            track, from_attributes=True
        )
        resp.favorited_at = favorite.favorited_at
        if track.id in play_history_map:
            ph = play_history_map[track.id]
            resp.last_played_at = ph.last_played_at
            resp.play_count = ph.play_count
        favorites.append(resp)

    return FavoritesListResponse(
        favorites=favorites,
        total=local_count,
    )


class AutoDownloadResponse(BaseModel):
    """Response for favorites auto-download setting."""

    enabled: bool


class AutoDownloadUpdate(BaseModel):
    """Request to update favorites auto-download setting."""

    enabled: bool


@router.get("/auto-download", response_model=AutoDownloadResponse, deprecated=True)
async def get_favorites_auto_download(
    db: DbSession,
    profile: RequiredProfile,
) -> AutoDownloadResponse:
    """Get the auto-download setting for favorites. **Deprecated** (ADR-0029 point 4).

    The setting moved to the client. Whether to keep 1,700 tracks offline depends on the device's
    disk, and one boolean per profile meant a phone and a desktop could not disagree. This was the
    only listener preference the server held; after the move it holds none.

    Still served, and still reads the stored value, because both clients call it exactly once per
    profile to carry the old value across. Removing it would make that seed impossible and silently
    turn the feature off for anyone who had it on. It can go once every client has seeded — and
    note that `familiar-apple` commits `openapi.json` verbatim, so removal there means regenerating
    the Swift client in the same change.
    """
    enabled = (profile.settings or {}).get("favorites_auto_download", False)
    return AutoDownloadResponse(enabled=enabled)


@router.put("/auto-download", response_model=AutoDownloadResponse, deprecated=True)
async def set_favorites_auto_download(
    request: AutoDownloadUpdate,
    db: DbSession,
    profile: RequiredProfile,
) -> AutoDownloadResponse:
    """Set the auto-download setting for favorites. **Deprecated** (ADR-0029 point 4).

    No shipping client writes here any more — the setting is device-local. Kept so an older build
    that still writes is not met with a 404, and so the stored value stays a usable seed for a
    device that has not been updated yet.
    """
    settings = dict(profile.settings or {})
    settings["favorites_auto_download"] = request.enabled
    profile.settings = settings
    await db.commit()
    return AutoDownloadResponse(enabled=request.enabled)


@router.get("/suggested-tracks", response_model=SuggestedTracksResponse)
async def get_favorites_suggested_tracks(
    db: DbSession,
    profile: RequiredProfile,
    limit: int = Query(10, ge=1, le=50),
) -> SuggestedTracksResponse:
    """Tracks from your library that fit your favorites and are not already among them.

    Each carries the favourite that reached it, so the list explains itself rather than needing a
    heading nobody can write truthfully (ADR-0093 point 7).

    **Registered above `GET /{track_id}`, and it has to stay there.** FastAPI matches in registration
    order, so behind the parameterised route this path is read as a track id and 422s on the UUID
    parse — the same trap `routes/playlists/__init__.py` documents for `/generate`.
    """
    favorite_ids = list(
        (
            await db.execute(
                select(ProfileFavorite.track_id)
                .join(Track, ProfileFavorite.track_id == Track.id)
                .where(ProfileFavorite.profile_id == profile.id)
                .where(Track.active_filter())
                .order_by(ProfileFavorite.favorited_at.desc())
            )
        )
        .scalars()
        .all()
    )

    suggestions = await suggest_for_collection(
        db,
        seed_track_ids=favorite_ids[:SEED_SAMPLE_CAP],
        # Everything favourited, not the capped seed — ADR-0093 point 4. This is the difference
        # between a panel that suggests new music and one that suggests what you already loved.
        exclude_track_ids=set(favorite_ids),
        profile_id=profile.id,
        limit=limit,
    )

    return SuggestedTracksResponse(
        suggestions=[
            SuggestedTrackResponse(
                track=TrackResponse.model_validate(s.track, from_attributes=True),
                because_of=SuggestionReasonResponse(
                    track_id=s.because_of.id,
                    title=s.because_of.title,
                    artist=s.because_of.artist,
                ),
                similarity=s.similarity,
                votes=s.votes,
            )
            for s in suggestions
        ],
        seed_track_count=len(favorite_ids),
    )


@router.post("/{track_id}", status_code=status.HTTP_201_CREATED)
async def add_favorite(
    track_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> FavoriteStatusResponse:
    """Add a track to favorites."""
    # Verify track exists
    track = await db.get(Track, track_id)
    if not track:
        raise TrackNotFoundError()

    # Check if already favorited
    result = await db.execute(
        select(ProfileFavorite).where(
            ProfileFavorite.profile_id == profile.id,
            ProfileFavorite.track_id == track_id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Already favorited, just return success
        return FavoriteStatusResponse(track_id=track_id, is_favorite=True)

    # Add favorite
    favorite = ProfileFavorite(
        profile_id=profile.id,
        track_id=track_id,
    )
    db.add(favorite)
    await db.commit()

    return FavoriteStatusResponse(track_id=track_id, is_favorite=True)


@router.delete("/{track_id}", status_code=status.HTTP_200_OK)
async def remove_favorite(
    track_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> FavoriteStatusResponse:
    """Remove a track from favorites."""
    result = await db.execute(
        select(ProfileFavorite).where(
            ProfileFavorite.profile_id == profile.id,
            ProfileFavorite.track_id == track_id,
        )
    )
    favorite = result.scalar_one_or_none()

    if favorite:
        await db.delete(favorite)
        await db.commit()

    return FavoriteStatusResponse(track_id=track_id, is_favorite=False)


@router.get("/{track_id}", response_model=FavoriteStatusResponse)
async def check_favorite(
    track_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> FavoriteStatusResponse:
    """Check if a track is in favorites."""
    result = await db.execute(
        select(ProfileFavorite).where(
            ProfileFavorite.profile_id == profile.id,
            ProfileFavorite.track_id == track_id,
        )
    )
    favorite = result.scalar_one_or_none()

    return FavoriteStatusResponse(track_id=track_id, is_favorite=favorite is not None)


@router.post("/{track_id}/toggle", response_model=FavoriteStatusResponse)
async def toggle_favorite(
    track_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> FavoriteStatusResponse:
    """Toggle a track's favorite status."""
    # Verify track exists
    track = await db.get(Track, track_id)
    if not track:
        raise TrackNotFoundError()

    is_fav = await _toggle_local_favorite(db, profile.id, track_id)
    return FavoriteStatusResponse(track_id=track_id, is_favorite=is_fav)
