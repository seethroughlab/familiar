"""Send earned scrobbles to Last.fm, out of band (ADR-0030).

**Nothing here may fail, delay or alter a listening event.** The play or skip is already written by
the time any of this runs; the listening record is what matters, and an expired Last.fm session must
not turn `/played` into an error. Every function swallows its failures into the log.

It runs as a `BackgroundTasks` job for a second reason worth stating: it opens its own short-lived
database session rather than borrowing the request's. A request dependency is held until the response
has finished *sending* — the property that exhausted the connection pool from the streaming endpoints
on 2026-08-02 — so work that outlives the handler takes its own connection or none at all.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from app.db.models import Track
from app.db.session import async_session_maker
from app.services.lastfm import get_lastfm_service
from app.services.scrobble_policy import should_scrobble

logger = logging.getLogger(__name__)


async def scrobble_if_earned(
    profile_id: UUID,
    track_id: UUID,
    played_seconds: float | None,
    track_duration: float | None,
    started_at: datetime,
) -> None:
    """Scrobble this listening event, if Last.fm's rule says it counts.

    Called for both plays and skips: the two are different questions about the same event, and a
    track abandoned past halfway is a skip to Familiar and a scrobble to Last.fm.
    """
    if not should_scrobble(played_seconds, track_duration):
        return

    try:
        async with async_session_maker() as db:
            lastfm = get_lastfm_service()
            session = await lastfm.get_stored_session(db, profile_id)
            if not session:
                # Not connected. The overwhelmingly common case, and not a problem.
                return

            track = (
                await db.execute(select(Track).where(Track.id == track_id, Track.active_filter()))
            ).scalar_one_or_none()
            if track is None or not track.title or not track.artist:
                # Last.fm rejects a scrobble without both, and there is nothing to be done about a
                # track whose tags are missing.
                return

            await lastfm.scrobble(
                session_key=session.session_key,
                artist=track.artist,
                track=track.title,
                # The moment the listening happened, not the moment it reached us. An event replayed
                # from an offline queue days later scrobbles at its original time because of this
                # one argument.
                timestamp=int(started_at.timestamp()),
                album=track.album,
                duration=int(track.duration_seconds) if track.duration_seconds else None,
            )
    except Exception:
        logger.warning("Scrobble failed for track %s", track_id, exc_info=True)


async def remember_now_playing(profile_id: UUID, track_id: UUID) -> None:
    """Remember what just started, so the server can be asked what is playing.

    Separate from `send_now_playing` because the two have different failure modes and different
    reasons to exist: that one talks to Last.fm and needs a stored session, this one needs nothing
    and must work for a listener who has never connected an account.
    """
    from app.services.now_playing import StartedTrack, get_registry

    try:
        async with async_session_maker() as db:
            track = (
                await db.execute(select(Track).where(Track.id == track_id, Track.active_filter()))
            ).scalar_one_or_none()
            if track is None:
                return
            get_registry().record(
                profile_id,
                StartedTrack(
                    track_id=track.id,
                    title=track.title,
                    artist=track.artist,
                    album=track.album,
                    duration_seconds=(
                        float(track.duration_seconds) if track.duration_seconds else None
                    ),
                    started_at=time.monotonic(),
                ),
            )
    except Exception:
        logger.warning("Could not remember now-playing for track %s", track_id, exc_info=True)


async def send_now_playing(profile_id: UUID, track_id: UUID) -> None:
    """Tell Last.fm what is playing right now.

    Never queued and never retried (ADR-0030 point 7): this is a claim about the present, and one
    replayed later is a lie. Last.fm expires it in minutes regardless.
    """
    try:
        async with async_session_maker() as db:
            lastfm = get_lastfm_service()
            session = await lastfm.get_stored_session(db, profile_id)
            if not session:
                return

            track = (
                await db.execute(select(Track).where(Track.id == track_id, Track.active_filter()))
            ).scalar_one_or_none()
            if track is None or not track.title or not track.artist:
                return

            await lastfm.update_now_playing(
                session_key=session.session_key,
                artist=track.artist,
                track=track.title,
                album=track.album,
                duration=int(track.duration_seconds) if track.duration_seconds else None,
            )
    except Exception:
        logger.warning("Now-playing failed for track %s", track_id, exc_info=True)
