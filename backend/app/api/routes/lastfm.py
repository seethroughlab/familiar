"""Last.fm endpoints for authentication and scrobbling."""

import time
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentProfile, DbSession
from app.api.exceptions import (
    AuthenticationError,
    ServiceUnavailableError,
    TrackNotFoundError,
    ValidationError,
)
from app.db.models import Track, TrackStatus
from app.services.lastfm import get_lastfm_service

router = APIRouter(prefix="/lastfm", tags=["lastfm"])


class LastfmStatusResponse(BaseModel):
    """Last.fm connection status."""
    configured: bool
    connected: bool
    username: str | None = None


class LastfmAuthResponse(BaseModel):
    """Last.fm auth URL response."""
    auth_url: str


class LastfmCallbackResponse(BaseModel):
    """Last.fm callback response."""
    status: str
    username: str


class ScrobbleRequest(BaseModel):
    """Request to scrobble a track."""
    track_id: str
    timestamp: int | None = None


class ScrobbleResponse(BaseModel):
    """Scrobble response."""
    status: str
    message: str


@router.get("/status", response_model=LastfmStatusResponse)
async def get_lastfm_status(
    db: DbSession,
    profile: CurrentProfile,
) -> LastfmStatusResponse:
    """Get Last.fm connection status.

    Requires X-Profile-ID header.
    """
    lastfm = get_lastfm_service()

    if not lastfm.is_configured():
        return LastfmStatusResponse(
            configured=False,
            connected=False
        )

    if not profile:
        return LastfmStatusResponse(
            configured=True,
            connected=False
        )

    # Check for stored session in database
    session = await lastfm.get_stored_session(db, profile.id)

    return LastfmStatusResponse(
        configured=True,
        connected=session is not None,
        username=session.username if session else None
    )


@router.get("/auth", response_model=LastfmAuthResponse)
async def get_auth_url(profile: CurrentProfile) -> LastfmAuthResponse:
    """Get the Last.fm authorization URL.

    Requires X-Profile-ID header.
    """
    if not profile:
        raise AuthenticationError("Profile ID required - register at POST /profiles/register")

    lastfm = get_lastfm_service()

    if not lastfm.is_configured():
        raise ServiceUnavailableError("Last.fm API not configured. Add credentials in Settings.")

    # Get frontend URL from settings
    from app.config import settings
    base_url = settings.frontend_url or "http://localhost:4400"
    callback_url = f"{base_url.rstrip('/')}/settings?lastfm_callback=true"
    auth_url = lastfm.get_auth_url(callback_url)

    return LastfmAuthResponse(auth_url=auth_url)


@router.post("/callback", response_model=LastfmCallbackResponse)
async def handle_callback(
    db: DbSession,
    profile: CurrentProfile,
    token: str = Query(...),
) -> LastfmCallbackResponse:
    """
    Handle the Last.fm auth callback.
    Exchange the token for a session key.

    Requires X-Profile-ID header.
    """
    if not profile:
        raise AuthenticationError("Profile ID required")

    lastfm = get_lastfm_service()

    if not lastfm.is_configured():
        raise ServiceUnavailableError("Last.fm API not configured")

    try:
        # Exchange token for session
        session = await lastfm.exchange_token(token)

        # Persist to database
        await lastfm.save_session(db, profile.id, session)

        return LastfmCallbackResponse(
            status="connected",
            username=session.username
        )
    except Exception as e:
        raise ValidationError("Failed to authenticate with Last.fm", detail=str(e))


class LastfmDisconnectResponse(BaseModel):
    """Last.fm disconnect response."""
    status: str


@router.post("/disconnect", response_model=LastfmDisconnectResponse)
async def disconnect(
    db: DbSession,
    profile: CurrentProfile,
) -> LastfmDisconnectResponse:
    """Disconnect from Last.fm.

    Requires X-Profile-ID header.
    """
    if not profile:
        raise AuthenticationError("Profile ID required")

    lastfm = get_lastfm_service()
    await lastfm.delete_session(db, profile.id)

    return LastfmDisconnectResponse(status="disconnected")


@router.post("/now-playing", response_model=ScrobbleResponse)
async def update_now_playing(
    db: DbSession,
    profile: CurrentProfile,
    request: ScrobbleRequest,
) -> ScrobbleResponse:
    """Update the "now playing" status on Last.fm.

    Requires X-Profile-ID header.
    """
    if not profile:
        raise AuthenticationError("Profile ID required")

    lastfm = get_lastfm_service()
    session = await lastfm.get_stored_session(db, profile.id)

    if not session:
        raise ValidationError("Not connected to Last.fm")

    # Get track from database
    query = select(Track).where(Track.id == UUID(request.track_id), Track.active_filter())
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise TrackNotFoundError()

    if not track.title or not track.artist:
        raise ValidationError("Track must have title and artist for scrobbling")

    success = await lastfm.update_now_playing(
        session_key=session.session_key,
        artist=track.artist,
        track=track.title,
        album=track.album,
        duration=int(track.duration_seconds) if track.duration_seconds else None
    )

    if success:
        return ScrobbleResponse(
            status="success",
            message=f"Now playing: {track.artist} - {track.title}"
        )
    else:
        return ScrobbleResponse(
            status="error",
            message="Failed to update now playing"
        )


@router.post("/scrobble", response_model=ScrobbleResponse)
async def scrobble_track(
    db: DbSession,
    profile: CurrentProfile,
    request: ScrobbleRequest,
) -> ScrobbleResponse:
    """
    Scrobble a track to Last.fm.
    Should be called after 50% of the track has been played.

    Requires X-Profile-ID header.
    """
    if not profile:
        raise AuthenticationError("Profile ID required")

    lastfm = get_lastfm_service()
    session = await lastfm.get_stored_session(db, profile.id)

    if not session:
        raise ValidationError("Not connected to Last.fm")

    # Get track from database
    query = select(Track).where(Track.id == UUID(request.track_id), Track.active_filter())
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise TrackNotFoundError()

    if not track.title or not track.artist:
        raise ValidationError("Track must have title and artist for scrobbling")

    timestamp = request.timestamp or int(time.time())

    success = await lastfm.scrobble(
        session_key=session.session_key,
        artist=track.artist,
        track=track.title,
        timestamp=timestamp,
        album=track.album,
        duration=int(track.duration_seconds) if track.duration_seconds else None
    )

    if success:
        return ScrobbleResponse(
            status="success",
            message=f"Scrobbled: {track.artist} - {track.title}"
        )
    else:
        return ScrobbleResponse(
            status="error",
            message="Failed to scrobble track"
        )
