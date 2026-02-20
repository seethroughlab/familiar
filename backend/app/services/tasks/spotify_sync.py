"""Spotify sync task: fetch favorites, match to local library, rate limiting.

Contains SpotifySyncProgressReporter, run_spotify_sync, and helpers.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from app.services.redis_client import get_redis

logger = logging.getLogger(__name__)

SPOTIFY_SYNC_PROGRESS_KEY = "familiar:spotify:sync:progress"
SPOTIFY_RATE_LIMIT_KEY = "familiar:spotify:rate_limit_until"


class SpotifySyncProgressReporter:
    """Reports Spotify sync progress to Redis for API consumption."""

    def __init__(self, profile_id: str):
        self.redis = get_redis()
        self.profile_id = profile_id
        self.started_at = datetime.now().isoformat()
        self._update_progress({
            "status": "running",
            "phase": "connecting",
            "message": "Connecting to Spotify...",
            "profile_id": profile_id,
            "tracks_fetched": 0,
            "tracks_processed": 0,
            "tracks_total": 0,
            "new_favorites": 0,
            "matched": 0,
            "unmatched": 0,
            "current_track": None,
            "started_at": self.started_at,
            "last_heartbeat": datetime.now().isoformat(),
            "errors": [],
        })

    def _update_progress(self, data: dict[str, Any]) -> None:
        """Update progress in Redis with heartbeat."""
        data["last_heartbeat"] = datetime.now().isoformat()
        self.redis.set(SPOTIFY_SYNC_PROGRESS_KEY, json.dumps(data), ex=3600)

    def _get_current(self) -> dict[str, Any]:
        """Get current progress from Redis."""
        data: bytes | None = self.redis.get(SPOTIFY_SYNC_PROGRESS_KEY)  # type: ignore[assignment]
        if data:
            return json.loads(data)
        return {}

    def set_fetching(self, fetched: int, message: str | None = None) -> None:
        """Update fetching progress."""
        self._update_progress({
            "status": "running",
            "phase": "fetching",
            "message": message or f"Fetching saved tracks from Spotify... ({fetched} tracks)",
            "profile_id": self.profile_id,
            "tracks_fetched": fetched,
            "tracks_processed": 0,
            "tracks_total": 0,
            "new_favorites": 0,
            "matched": 0,
            "unmatched": 0,
            "current_track": None,
            "started_at": self.started_at,
            "errors": [],
        })

    def set_matching(
        self,
        processed: int,
        total: int,
        new: int,
        matched: int,
        unmatched: int,
        current: str | None = None,
    ) -> None:
        """Update matching progress."""
        pct = int(processed / total * 100) if total > 0 else 0
        self._update_progress({
            "status": "running",
            "phase": "matching",
            "message": f"Matching to local library... {processed}/{total} ({pct}%)",
            "profile_id": self.profile_id,
            "tracks_fetched": total,
            "tracks_processed": processed,
            "tracks_total": total,
            "new_favorites": new,
            "matched": matched,
            "unmatched": unmatched,
            "current_track": current,
            "started_at": self.started_at,
            "errors": [],
        })

    def complete(self, fetched: int, new: int, matched: int, unmatched: int) -> None:
        """Mark sync as complete."""
        self._update_progress({
            "status": "completed",
            "phase": "complete",
            "message": f"Complete: {fetched} tracks synced, {matched} matched to local library",
            "profile_id": self.profile_id,
            "tracks_fetched": fetched,
            "tracks_processed": fetched,
            "tracks_total": fetched,
            "new_favorites": new,
            "matched": matched,
            "unmatched": unmatched,
            "current_track": None,
            "started_at": self.started_at,
            "errors": [],
        })

    def error(self, msg: str) -> None:
        """Mark sync as failed."""
        current = self._get_current()
        current["status"] = "error"
        current["message"] = msg
        if "errors" not in current:
            current["errors"] = []
        current["errors"].append(msg)
        self._update_progress(current)


def get_spotify_sync_progress() -> dict[str, Any] | None:
    """Get current Spotify sync progress from Redis."""
    try:
        r = get_redis()
        data: bytes | None = r.get(SPOTIFY_SYNC_PROGRESS_KEY)  # type: ignore[assignment]
        if data:
            return json.loads(data)
    except Exception as e:
        logger.error(f"Failed to get Spotify sync progress: {e}")
    return None


def clear_spotify_sync_progress() -> None:
    """Clear Spotify sync progress from Redis."""
    try:
        r = get_redis()
        r.delete(SPOTIFY_SYNC_PROGRESS_KEY)
    except Exception as e:
        logger.error(f"Failed to clear Spotify sync progress: {e}")


def set_spotify_rate_limit(seconds: int) -> None:
    """Store Spotify rate limit expiry in Redis with auto-expiring TTL."""
    try:
        r = get_redis()
        until = (datetime.now() + timedelta(seconds=seconds)).isoformat()
        r.set(SPOTIFY_RATE_LIMIT_KEY, until, ex=seconds)
        logger.warning(f"Spotify rate limited for {seconds}s, until {until}")
    except Exception as e:
        logger.error(f"Failed to set Spotify rate limit: {e}")


def get_spotify_rate_limit() -> str | None:
    """Get Spotify rate limit expiry ISO timestamp, or None if not rate limited."""
    try:
        r = get_redis()
        data: bytes | None = r.get(SPOTIFY_RATE_LIMIT_KEY)  # type: ignore[assignment]
        if data:
            return data.decode() if isinstance(data, bytes) else str(data)
    except Exception as e:
        logger.error(f"Failed to get Spotify rate limit: {e}")
    return None


async def run_spotify_sync(
    profile_id: str,
    include_top_tracks: bool = True,
    favorite_matched: bool = False,
) -> dict[str, Any]:
    """Sync Spotify favorites for a profile."""
    from datetime import datetime as dt

    from spotipy.exceptions import SpotifyException
    from sqlalchemy import delete, func, select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.db.models import (
        ExternalTrack,
        ExternalTrackSource,
        ProfileExternalFavorite,
        ProfileFavorite,
        SpotifyFavorite,
        SpotifyProfile,
    )
    from app.db.session import create_task_engine_session
    from app.services.spotify import SpotifyService
    from app.services.spotify_compat import SpotifyRateLimitError

    progress = SpotifySyncProgressReporter(profile_id)
    profile_uuid = UUID(profile_id)

    stats = {
        "fetched": 0,
        "new": 0,
        "matched": 0,
        "unmatched": 0,
        "top_tracks_fetched": 0,
        "top_tracks_new": 0,
        "favorited": 0,
    }

    local_engine, local_session_maker = create_task_engine_session()

    try:
        async with local_session_maker() as db:
            spotify_service = SpotifyService()
            client = await spotify_service.get_client(db, profile_uuid)

            if not client:
                raise ValueError("Spotify not connected - please reconnect your account")

            # Fetch saved tracks
            all_tracks: list[dict[str, Any]] = []
            offset = 0
            limit = 50

            progress.set_fetching(0, "Fetching saved tracks from Spotify...")

            while True:
                max_page_retries = 3
                for page_attempt in range(max_page_retries):
                    try:
                        results = await asyncio.to_thread(
                            client.current_user_saved_tracks, limit=limit, offset=offset
                        )
                        break  # Success
                    except SpotifyRateLimitError as e:
                        wait = e.retry_after or 30
                        if wait > 300:
                            set_spotify_rate_limit(wait)
                            raise ValueError(
                                f"Spotify rate limit too long ({wait}s), aborting sync"
                            )
                        if page_attempt < max_page_retries - 1:
                            logger.warning(
                                f"Spotify rate limited during favorites sync, "
                                f"waiting {wait}s (attempt {page_attempt + 1})"
                            )
                            await asyncio.sleep(wait)
                        else:
                            raise ValueError(
                                f"Spotify rate limit exceeded after {max_page_retries} retries"
                            )
                    except SpotifyException as e:
                        if e.http_status == 429:
                            retry_after = int(e.headers.get("Retry-After", "30")) if e.headers else 30
                            if retry_after > 300:
                                set_spotify_rate_limit(retry_after)
                                raise ValueError(
                                    f"Spotify rate limit too long ({retry_after}s), aborting sync"
                                )
                            if page_attempt < max_page_retries - 1:
                                logger.warning(
                                    f"Spotify 429 during favorites sync, "
                                    f"waiting {retry_after}s (attempt {page_attempt + 1})"
                                )
                                await asyncio.sleep(retry_after)
                            else:
                                raise ValueError(
                                    f"Spotify rate limit exceeded after {max_page_retries} retries"
                                )
                        else:
                            raise ValueError(f"Spotify API error: {e.msg if hasattr(e, 'msg') else str(e)}")

                tracks = results.get("items", [])
                if not tracks:
                    break

                all_tracks.extend(tracks)
                stats["fetched"] = len(all_tracks)
                progress.set_fetching(len(all_tracks))

                offset += limit
                if offset > 2000:
                    break

                await asyncio.sleep(1.0)  # Throttle between pages

            added_track_ids: set[str] = set()
            matched_local_track_ids: set[UUID] = set()

            # Process tracks
            for i, item in enumerate(all_tracks):
                spotify_track = item.get("track")
                if not spotify_track:
                    continue

                track_id = spotify_track["id"]
                if track_id in added_track_ids:
                    continue

                added_at = item.get("added_at")
                track_name = spotify_track.get("name", "Unknown")
                artists = spotify_track.get("artists", [])
                artist_name = artists[0]["name"] if artists else "Unknown"

                if i % 10 == 0:
                    progress.set_matching(
                        processed=i,
                        total=len(all_tracks),
                        new=stats["new"],
                        matched=stats["matched"],
                        unmatched=stats["unmatched"],
                        current=f"{artist_name} - {track_name}",
                    )

                # Try to match to local library
                local_match = await _match_to_local(db, spotify_track)

                parsed_added_at = None
                if added_at:
                    parsed_dt = dt.fromisoformat(added_at.replace("Z", "+00:00"))
                    parsed_added_at = parsed_dt.replace(tzinfo=None)

                values = {
                    "profile_id": profile_uuid,
                    "spotify_track_id": track_id,
                    "matched_track_id": local_match.id if local_match else None,
                    "track_data": _extract_track_data(spotify_track),
                    "added_at": parsed_added_at,
                }
                insert_stmt = pg_insert(SpotifyFavorite).values(**values)
                upsert_stmt = insert_stmt.on_conflict_do_update(
                    constraint="uq_spotify_favorite_profile",
                    set_={
                        "matched_track_id": insert_stmt.excluded.matched_track_id,
                        "track_data": insert_stmt.excluded.track_data,
                        "added_at": insert_stmt.excluded.added_at,
                        "synced_at": func.now(),
                    },
                )
                await db.execute(upsert_stmt)
                added_track_ids.add(track_id)
                stats["new"] += 1

                if local_match:
                    stats["matched"] += 1
                    if favorite_matched:
                        matched_local_track_ids.add(local_match.id)
                else:
                    stats["unmatched"] += 1

            # Remove favorites no longer in Spotify saved tracks
            if added_track_ids:
                await db.execute(
                    delete(SpotifyFavorite).where(
                        SpotifyFavorite.profile_id == profile_uuid,
                        SpotifyFavorite.spotify_track_id.notin_(added_track_ids),
                    )
                )

            # Batch process ProfileFavorites
            if favorite_matched and matched_local_track_ids:
                existing_result = await db.execute(
                    select(ProfileFavorite.track_id).where(
                        ProfileFavorite.profile_id == profile_uuid,
                        ProfileFavorite.track_id.in_(matched_local_track_ids),
                    )
                )
                existing_favs = {row[0] for row in existing_result.fetchall()}

                new_favs = [
                    ProfileFavorite(profile_id=profile_uuid, track_id=tid)
                    for tid in matched_local_track_ids
                    if tid not in existing_favs
                ]
                if new_favs:
                    db.add_all(new_favs)
                    stats["favorited"] = len(new_favs)

            # Promote unmatched favorites to external favorites
            unmatched_result = await db.execute(
                select(SpotifyFavorite).where(
                    SpotifyFavorite.profile_id == profile_uuid,
                    SpotifyFavorite.matched_track_id.is_(None),
                )
            )
            unmatched_favs = unmatched_result.scalars().all()
            promoted = 0

            for fav in unmatched_favs:
                track_data = fav.track_data or {}

                # Find or create ExternalTrack by spotify_id
                ext_result = await db.execute(
                    select(ExternalTrack).where(
                        ExternalTrack.spotify_id == fav.spotify_track_id
                    )
                )
                external_track = ext_result.scalar_one_or_none()

                if not external_track:
                    external_track = ExternalTrack(
                        title=track_data.get("name") or "Unknown",
                        artist=track_data.get("artist") or "Unknown",
                        album=track_data.get("album") if isinstance(track_data.get("album"), str) else None,
                        duration_seconds=(track_data.get("duration_ms") or 0) / 1000.0,
                        spotify_id=fav.spotify_track_id,
                        source=ExternalTrackSource.SPOTIFY_FAVORITE,
                        external_data={
                            "spotify_url": track_data.get("external_url"),
                            "album_id": track_data.get("album_id"),
                            "artist_id": track_data.get("artist_id"),
                        },
                    )
                    db.add(external_track)
                    await db.flush()

                # Check if ProfileExternalFavorite already exists
                pef_result = await db.execute(
                    select(ProfileExternalFavorite).where(
                        ProfileExternalFavorite.profile_id == profile_uuid,
                        ProfileExternalFavorite.external_track_id == external_track.id,
                    )
                )
                if not pef_result.scalar_one_or_none():
                    db.add(ProfileExternalFavorite(
                        profile_id=profile_uuid,
                        external_track_id=external_track.id,
                        favorited_at=fav.added_at or dt.utcnow(),
                    ))
                    promoted += 1

            stats["external_favorites"] = promoted
            logger.info(
                f"Promoted {promoted} unmatched Spotify favorites to external favorites"
            )

            # Remove external favorites for tracks that now have local matches
            if matched_local_track_ids:
                matched_spotify_ids_result = await db.execute(
                    select(SpotifyFavorite.spotify_track_id).where(
                        SpotifyFavorite.profile_id == profile_uuid,
                        SpotifyFavorite.matched_track_id.isnot(None),
                    )
                )
                matched_spotify_ids = [
                    row[0] for row in matched_spotify_ids_result.fetchall()
                ]
                if matched_spotify_ids:
                    matched_ext_result = await db.execute(
                        select(ExternalTrack.id).where(
                            ExternalTrack.spotify_id.in_(matched_spotify_ids)
                        )
                    )
                    matched_ext_ids = [row[0] for row in matched_ext_result.fetchall()]
                    if matched_ext_ids:
                        await db.execute(
                            delete(ProfileExternalFavorite).where(
                                ProfileExternalFavorite.profile_id == profile_uuid,
                                ProfileExternalFavorite.external_track_id.in_(matched_ext_ids),
                            )
                        )

            # Update last sync time
            profile_result = await db.execute(
                select(SpotifyProfile).where(SpotifyProfile.profile_id == profile_uuid)
            )
            spotify_profile = profile_result.scalar_one_or_none()
            if spotify_profile:
                spotify_profile.last_sync_at = dt.utcnow()

            await db.commit()

        progress.complete(
            fetched=stats["fetched"],
            new=stats["new"],
            matched=stats["matched"],
            unmatched=stats["unmatched"],
        )

        return {"status": "success", **stats}

    except ValueError as e:
        logger.error(f"Spotify sync failed: {e}")
        progress.error(str(e))
        return {"status": "error", "error": str(e)}
    except Exception as e:
        logger.error(f"Spotify sync failed unexpectedly: {e}", exc_info=True)
        progress.error(f"Unexpected error: {str(e)}")
        return {"status": "error", "error": str(e)}
    finally:
        await local_engine.dispose()


async def _match_to_local(db, spotify_track: dict[str, Any]):
    """Try to match a Spotify track to local library."""
    from sqlalchemy import func, select

    from app.db.models import Track

    isrc = spotify_track.get("external_ids", {}).get("isrc")
    track_name = spotify_track.get("name", "").lower().strip()
    artists = spotify_track.get("artists", [])
    artist_name = artists[0]["name"].lower().strip() if artists else ""

    if isrc:
        result = await db.execute(select(Track).where(Track.isrc == isrc))
        match = result.scalar_one_or_none()
        if match:
            return match

    if track_name and artist_name:
        result = await db.execute(
            select(Track).where(
                func.lower(Track.title) == track_name,
                func.lower(Track.artist) == artist_name,
            ).limit(1)
        )
        match = result.scalars().first()
        if match:
            return match

    return None


def _extract_track_data(spotify_track: dict[str, Any]) -> dict[str, Any]:
    """Extract relevant data from Spotify track object."""
    artists = spotify_track.get("artists", [])
    album = spotify_track.get("album", {})

    return {
        "name": spotify_track.get("name"),
        "artist": artists[0]["name"] if artists else None,
        "artist_id": artists[0]["id"] if artists else None,
        "album": album.get("name"),
        "album_id": album.get("id"),
        "duration_ms": spotify_track.get("duration_ms"),
        "external_url": spotify_track.get("external_urls", {}).get("spotify"),
    }
