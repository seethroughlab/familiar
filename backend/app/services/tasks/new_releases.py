"""New releases check task: discover new albums from library artists.

Contains NewReleasesProgressReporter, run_new_releases_check, and
run_prioritized_new_releases_check.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from app.services.redis_client import get_redis

logger = logging.getLogger(__name__)

NEW_RELEASES_PROGRESS_KEY = "familiar:new_releases:progress"


class NewReleasesProgressReporter:
    """Reports new releases check progress to Redis for API consumption."""

    def __init__(self, profile_id: str | None = None):
        self.redis = get_redis()
        self.profile_id = profile_id
        self.started_at = datetime.now().isoformat()
        self._update_progress({
            "status": "running",
            "phase": "starting",
            "message": "Starting new releases check...",
            "profile_id": profile_id,
            "artists_total": 0,
            "artists_checked": 0,
            "releases_found": 0,
            "releases_new": 0,
            "current_artist": None,
            "started_at": self.started_at,
            "last_heartbeat": datetime.now().isoformat(),
            "errors": [],
        })

    def _update_progress(self, data: dict[str, Any]) -> None:
        data["last_heartbeat"] = datetime.now().isoformat()
        self.redis.set(NEW_RELEASES_PROGRESS_KEY, json.dumps(data), ex=3600)

    def _get_current(self) -> dict[str, Any]:
        data: bytes | None = self.redis.get(NEW_RELEASES_PROGRESS_KEY)  # type: ignore[assignment]
        if data:
            return json.loads(data)
        return {}

    def set_checking(
        self,
        checked: int,
        total: int,
        found: int,
        new: int,
        current_artist: str | None = None,
    ) -> None:
        pct = int(checked / total * 100) if total > 0 else 0
        self._update_progress({
            "status": "running",
            "phase": "checking",
            "message": f"Checking artists... {checked}/{total} ({pct}%)",
            "profile_id": self.profile_id,
            "artists_total": total,
            "artists_checked": checked,
            "releases_found": found,
            "releases_new": new,
            "current_artist": current_artist,
            "started_at": self.started_at,
            "errors": [],
        })

    def complete(self, checked: int, found: int, new: int) -> None:
        self._update_progress({
            "status": "completed",
            "phase": "complete",
            "message": f"Complete: {checked} artists checked, {new} new releases found",
            "profile_id": self.profile_id,
            "artists_total": checked,
            "artists_checked": checked,
            "releases_found": found,
            "releases_new": new,
            "current_artist": None,
            "started_at": self.started_at,
            "errors": [],
        })

    def error(self, msg: str) -> None:
        current = self._get_current()
        current["status"] = "error"
        current["message"] = msg
        if "errors" not in current:
            current["errors"] = []
        current["errors"].append(msg)
        self._update_progress(current)


def get_new_releases_progress() -> dict[str, Any] | None:
    """Get current new releases check progress from Redis."""
    try:
        r = get_redis()
        data: bytes | None = r.get(NEW_RELEASES_PROGRESS_KEY)  # type: ignore[assignment]
        if data:
            return json.loads(data)
    except Exception as e:
        logger.error(f"Failed to get new releases progress: {e}")
    return None


def clear_new_releases_progress() -> None:
    """Clear new releases check progress from Redis."""
    try:
        r = get_redis()
        r.delete(NEW_RELEASES_PROGRESS_KEY)
    except Exception as e:
        logger.error(f"Failed to clear new releases progress: {e}")


async def run_new_releases_check(
    profile_id: str | None = None,
    days_back: int = 90,
    force: bool = False,
) -> dict[str, Any]:
    """Check for new releases from artists in the library."""

    from app.db.session import create_task_engine_session
    from app.services.musicbrainz import get_artist_releases_recent, search_artist
    from app.services.new_releases import NewReleasesService
    from app.services.spotify import SpotifyArtistService
    from app.services.spotify_compat import SpotifyRateLimitError

    progress = NewReleasesProgressReporter(profile_id)

    stats = {
        "artists_total": 0,
        "artists_checked": 0,
        "artists_skipped_cache": 0,
        "releases_found": 0,
        "releases_new": 0,
        "spotify_queries": 0,
        "musicbrainz_queries": 0,
    }

    local_engine, local_session_maker = create_task_engine_session()

    try:
        async with local_session_maker() as db:
            service = NewReleasesService(db)
            spotify_service = None

            if profile_id:
                spotify_service = SpotifyArtistService(db)

            artists = await service.get_library_artists()
            stats["artists_total"] = len(artists)

            if not artists:
                progress.complete(0, 0, 0)
                return {"status": "success", **stats}

            for i, artist_info in enumerate(artists):
                artist_name = artist_info["name"]
                normalized = artist_info["normalized_name"]
                mb_artist_id = artist_info.get("musicbrainz_artist_id")

                if i % 5 == 0:
                    progress.set_checking(
                        checked=i,
                        total=len(artists),
                        found=stats["releases_found"],
                        new=stats["releases_new"],
                        current_artist=artist_name,
                    )

                if not force:
                    should_check = await service.should_check_artist(normalized)
                    if not should_check:
                        stats["artists_skipped_cache"] += 1
                        continue

                stats["artists_checked"] += 1
                spotify_artist_id = None
                mb_id_to_use = mb_artist_id
                releases_for_artist: list[dict[str, Any]] = []

                # Try Spotify first
                if spotify_service and profile_id:
                    try:
                        spotify_artist = await spotify_service.search_artist(
                            UUID(profile_id), artist_name
                        )
                        if spotify_artist:
                            spotify_artist_id = spotify_artist["id"]
                            recent = await spotify_service.get_artist_albums_recent(
                                UUID(profile_id),
                                spotify_artist_id,
                                days_back=days_back,
                            )
                            stats["spotify_queries"] += 1

                            for album in recent:
                                releases_for_artist.append({
                                    "release_id": album["id"],
                                    "source": "spotify",
                                    "release_name": album["name"],
                                    "release_type": album.get("album_type"),
                                    "release_date_str": album.get("release_date"),
                                    "release_date": album.get("release_date_parsed"),
                                    "artwork_url": album["images"][0]["url"] if album.get("images") else None,
                                    "external_url": album.get("external_url"),
                                    "track_count": album.get("total_tracks"),
                                    "spotify_artist_id": spotify_artist_id,
                                })

                        if spotify_artist:
                            await asyncio.sleep(2.0)  # Rate limiting: ~4s per artist with throttled API calls

                    except SpotifyRateLimitError as e:
                        logger.warning(
                            f"Spotify rate limited during new releases check "
                            f"(retry_after={e.retry_after}s), disabling Spotify for remainder"
                        )
                        spotify_service = None  # Fall back to MusicBrainz for remaining artists
                    except Exception as e:
                        logger.warning(f"Spotify lookup failed for {artist_name}: {e}")
                        spotify_service = None  # Don't keep retrying broken Spotify

                # Fall back to MusicBrainz
                if not releases_for_artist:
                    try:
                        mb_id_to_use = mb_artist_id
                        if not mb_id_to_use:
                            mb_result = await asyncio.to_thread(search_artist, artist_name)
                            if mb_result and mb_result.get("score", 0) >= 80:
                                mb_id_to_use = mb_result["musicbrainz_artist_id"]

                        if mb_id_to_use:
                            recent = await asyncio.to_thread(get_artist_releases_recent, mb_id_to_use, days_back=days_back)
                            stats["musicbrainz_queries"] += 1

                            for release in recent:
                                releases_for_artist.append({
                                    "release_id": release["musicbrainz_release_group_id"],
                                    "source": "musicbrainz",
                                    "release_name": release["title"],
                                    "release_type": release.get("release_type"),
                                    "release_date_str": release.get("release_date"),
                                    "release_date": release.get("release_date_parsed"),
                                    "musicbrainz_artist_id": mb_id_to_use,
                                })

                    except Exception as e:
                        logger.warning(f"MusicBrainz lookup failed for {artist_name}: {e}")

                # Save discovered releases
                for release in releases_for_artist:
                    stats["releases_found"] += 1

                    release_date = None
                    if release.get("release_date"):
                        try:
                            from datetime import datetime as dt
                            release_date = dt.fromisoformat(release["release_date"])
                        except Exception:
                            pass

                    saved = await service.save_discovered_release(
                        artist_name=artist_name,
                        release_id=release["release_id"],
                        source=release["source"],
                        release_name=release["release_name"],
                        release_type=release.get("release_type"),
                        release_date=release_date,
                        artwork_url=release.get("artwork_url"),
                        external_url=release.get("external_url"),
                        track_count=release.get("track_count"),
                        musicbrainz_artist_id=release.get("musicbrainz_artist_id"),
                        spotify_artist_id=release.get("spotify_artist_id"),
                    )
                    if saved:
                        stats["releases_new"] += 1

                # Only cache if lookup resolved to an actual artist
                if spotify_artist_id or mb_id_to_use:
                    await service.update_artist_cache(
                        artist_normalized=normalized,
                        musicbrainz_id=mb_id_to_use or mb_artist_id,
                        spotify_id=spotify_artist_id,
                    )

                if (i + 1) % 25 == 0:
                    await db.commit()

            await db.commit()

        progress.complete(
            checked=stats["artists_checked"],
            found=stats["releases_found"],
            new=stats["releases_new"],
        )

        return {"status": "success", **stats}

    except Exception as e:
        logger.error(f"New releases check failed: {e}", exc_info=True)
        progress.error(str(e))
        return {"status": "error", "error": str(e)}
    finally:
        await local_engine.dispose()


async def run_prioritized_new_releases_check(
    profile_id: str,
    batch_size: int = 75,
    days_back: int = 90,
) -> dict[str, Any]:
    """Check for new releases using priority-based batching.

    Checks a limited batch of artists prioritized by recent listening activity.
    Only checks artists the user has actually listened to.
    Designed to run daily and eventually cover all listened artists.

    Args:
        profile_id: Profile ID to use for play history prioritization
        batch_size: Number of artists to check per run (default 75)
        days_back: How far back to look for releases (default 90 days)

    Returns:
        Dict with status and statistics
    """
    from uuid import UUID as UUIDType

    from app.db.session import create_task_engine_session
    from app.services.musicbrainz import get_artist_releases_recent, search_artist
    from app.services.new_releases import NewReleasesService

    progress = NewReleasesProgressReporter(profile_id)
    profile_uuid = UUIDType(profile_id)

    stats = {
        "artists_in_batch": 0,
        "artists_checked": 0,
        "releases_found": 0,
        "releases_new": 0,
        "musicbrainz_queries": 0,
    }

    local_engine, local_session_maker = create_task_engine_session()

    try:
        async with local_session_maker() as db:
            service = NewReleasesService(db)

            # Get prioritized batch of artists based on listening activity
            artists = await service.get_prioritized_artists_batch(
                profile_id=profile_uuid,
                batch_size=batch_size,
                min_days_since_check=7,  # Don't re-check artists checked within 7 days
            )
            stats["artists_in_batch"] = len(artists)

            if not artists:
                logger.info("No artists need checking in this batch")
                progress.complete(0, 0, 0)
                return {"status": "success", **stats}

            logger.info(
                f"Checking {len(artists)} prioritized artists for new releases "
                f"(top priority: {artists[0]['name'] if artists else 'N/A'})"
            )

            for i, artist_info in enumerate(artists):
                artist_name = artist_info["name"]
                normalized = artist_info["normalized_name"]
                mb_artist_id = artist_info.get("musicbrainz_artist_id")

                if i % 5 == 0:
                    progress.set_checking(
                        checked=i,
                        total=len(artists),
                        found=stats["releases_found"],
                        new=stats["releases_new"],
                        current_artist=artist_name,
                    )

                stats["artists_checked"] += 1
                releases_for_artist: list[dict[str, Any]] = []
                mb_id_to_use = mb_artist_id

                # Query MusicBrainz for releases
                try:
                    if not mb_id_to_use:
                        mb_result = await asyncio.to_thread(search_artist, artist_name)
                        if mb_result and mb_result.get("score", 0) >= 80:
                            mb_id_to_use = mb_result["musicbrainz_artist_id"]

                    if mb_id_to_use:
                        recent = await asyncio.to_thread(get_artist_releases_recent, mb_id_to_use, days_back=days_back)
                        stats["musicbrainz_queries"] += 1

                        for release in recent:
                            releases_for_artist.append({
                                "release_id": release["musicbrainz_release_group_id"],
                                "source": "musicbrainz",
                                "release_name": release["title"],
                                "release_type": release.get("release_type"),
                                "release_date_str": release.get("release_date"),
                                "release_date": release.get("release_date_parsed"),
                                "musicbrainz_artist_id": mb_id_to_use,
                            })

                except Exception as e:
                    logger.warning(f"MusicBrainz lookup failed for {artist_name}: {e}")

                # Save discovered releases
                for release in releases_for_artist:
                    stats["releases_found"] += 1

                    release_date = None
                    if release.get("release_date"):
                        try:
                            from datetime import datetime as dt
                            release_date = dt.fromisoformat(release["release_date"])
                        except Exception:
                            pass

                    saved = await service.save_discovered_release(
                        artist_name=artist_name,
                        release_id=release["release_id"],
                        source=release["source"],
                        release_name=release["release_name"],
                        release_type=release.get("release_type"),
                        release_date=release_date,
                        musicbrainz_artist_id=release.get("musicbrainz_artist_id"),
                    )
                    if saved:
                        stats["releases_new"] += 1

                # Only cache if lookup resolved to an actual artist
                if mb_id_to_use:
                    await service.update_artist_cache(
                        artist_normalized=normalized,
                        musicbrainz_id=mb_id_to_use,
                    )

                if (i + 1) % 25 == 0:
                    await db.commit()

            await db.commit()

        progress.complete(
            checked=stats["artists_checked"],
            found=stats["releases_found"],
            new=stats["releases_new"],
        )

        logger.info(
            f"Priority-based new releases check complete: "
            f"{stats['artists_checked']} artists, {stats['releases_new']} new releases"
        )

        return {"status": "success", **stats}

    except Exception as e:
        logger.error(f"Priority-based new releases check failed: {e}", exc_info=True)
        progress.error(str(e))
        return {"status": "error", "error": str(e)}
    finally:
        await local_engine.dispose()
