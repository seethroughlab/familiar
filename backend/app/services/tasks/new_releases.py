"""New releases check task: discover new albums from library artists.

Phase 1 (revival): MusicBrainz only. Spotify integration was removed when
that feature was shelved separately; can be reintroduced when/if Spotify
discovery support is revived.
"""

import asyncio
import json
import logging
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any
from uuid import UUID as UUIDType

from app.services.redis_client import get_redis

logger = logging.getLogger(__name__)


def _artist_names_match(searched: str, found: str) -> bool:
    """Check if a found artist name is a close match to the searched name."""
    from app.services.new_releases import normalize_artist_name

    a = normalize_artist_name(searched)
    b = normalize_artist_name(found)
    if a == b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.85


NEW_RELEASES_PROGRESS_KEY = "familiar:new_releases:progress"

#: How long any one MusicBrainz call may take before the artist is skipped.
#:
#: Inherited from the request path that ADR-0099 Phase 1 deleted, where it existed to
#: stop a person waiting. Here the reason is different and better: `musicbrainzngs`
#: answers a 503 by retrying with backoff, silently, so one throttled artist could
#: otherwise absorb an entire batch's wall-clock and starve the nine behind it. A
#: stalled artist now costs one slot out of ten.
#:
#: `asyncio.wait_for` cannot cancel the thread — the call finishes in the background
#: pool regardless. That is accepted: it is one bounded HTTP request, and the artist is
#: left unrecorded so the next batch retries it.
MUSICBRAINZ_CALL_TIMEOUT_SECONDS = 6.0


async def _check_one_artist_isolated(
    db: Any,
    service: Any,
    artist_name: str,
    normalized: str,
    mb_artist_id: str | None,
    days_back: int,
    stats: dict[str, Any],
) -> bool:
    """Check one artist, containing any failure to that artist. Returns success.

    **One artist's failure must cost one artist.** Before this existed, the only
    ``try`` in the path was inside ``_check_artist_against_musicbrainz``, around the
    MusicBrainz call and nothing else — so a database error raised while saving a
    release escaped to the caller's outer handler and ended the whole run. That is
    how a single duplicated release row stopped nineteen consecutive nights of
    discovery (ADR-0099).

    The ``rollback()`` is the part that actually does the work. Catching without it
    leaves the ``AsyncSession`` in a failed transaction, so every subsequent artist
    raises ``PendingRollbackError`` and the batch is just as dead — a fix that looks
    right and changes nothing.
    """
    from app.services.tasks.common import _record_task_failure

    try:
        await _check_artist_against_musicbrainz(
            service=service,
            artist_name=artist_name,
            normalized=normalized,
            mb_artist_id=mb_artist_id,
            days_back=days_back,
            stats=stats,
        )
        # Commit per artist rather than every 25: a rollback must not discard up to
        # twenty-four artists' worth of successful work alongside the one that failed.
        await db.commit()
        return True
    except Exception as e:
        await db.rollback()
        stats["artists_failed"] = stats.get("artists_failed", 0) + 1
        _record_task_failure("new_releases", str(e), track_info=artist_name)
        logger.warning(
            "discovery_artist_failed",
            extra={"artist": artist_name, "error": str(e)},
            exc_info=True,
        )
        return False


class NewReleasesProgressReporter:
    """Reports new releases check progress to Redis for API consumption."""

    def __init__(self, profile_id: str | None = None):
        self.redis = get_redis()
        self.profile_id = profile_id
        self.started_at = datetime.now().isoformat()
        self._update_progress(
            {
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
            }
        )

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
        self._update_progress(
            {
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
            }
        )

    def complete(self, checked: int, found: int, new: int) -> None:
        self._update_progress(
            {
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
            }
        )

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


async def _check_artist_against_musicbrainz(
    service: Any,
    artist_name: str,
    normalized: str,
    mb_artist_id: str | None,
    days_back: int,
    stats: dict[str, Any],
) -> None:
    """Resolve an artist's MB id, fetch recent releases, and persist them.

    Mutates ``stats`` in place. Records the check whenever MusicBrainz *answered* —
    matched or not — so an artist with no MusicBrainz entry leaves the never-checked
    backlog instead of being re-selected on every batch. Only a call that genuinely
    failed leaves no record, and is retried next batch. See the comment at the write.
    """
    from app.services.metadata.musicbrainz import (
        get_artist_releases_recent,
        search_artist,
    )
    from app.services.new_releases import plausible_release_date

    mb_id_to_use = mb_artist_id
    releases_for_artist: list[dict[str, Any]] = []
    # Whether MusicBrainz was actually reached and answered. Distinct from whether it
    # *matched*: "asked, no such artist" and "could not ask" have to be told apart, or
    # the artist either churns forever or is written off on a network blip.
    upstream_answered = False

    try:
        if not mb_id_to_use:
            mb_result = await asyncio.wait_for(
                asyncio.to_thread(search_artist, artist_name),
                timeout=MUSICBRAINZ_CALL_TIMEOUT_SECONDS,
            )
            if mb_result and mb_result.get("score", 0) >= 80:
                if _artist_names_match(artist_name, mb_result.get("name", "")):
                    mb_id_to_use = mb_result["musicbrainz_artist_id"]
                else:
                    logger.debug(
                        f"MusicBrainz match rejected: '{artist_name}' != "
                        f"'{mb_result.get('name')}'"
                    )

        if mb_id_to_use:
            recent = await asyncio.wait_for(
                asyncio.to_thread(
                    get_artist_releases_recent, mb_id_to_use, days_back=days_back
                ),
                timeout=MUSICBRAINZ_CALL_TIMEOUT_SECONDS,
            )
            stats["musicbrainz_queries"] += 1

            for release in recent:
                releases_for_artist.append(
                    {
                        "release_id": release["musicbrainz_release_group_id"],
                        "release_name": release["title"],
                        "release_type": release.get("release_type"),
                        "release_date": release.get("release_date_parsed")
                        or release.get("release_date"),
                        "artwork_url": release.get("artwork_url"),
                        "musicbrainz_artist_id": mb_id_to_use,
                    }
                )

        upstream_answered = True

    except TimeoutError:
        # Logged apart from other failures because this is the *rate-limit signature*:
        # `musicbrainzngs` retries a 503 with backoff and reports nothing, so a call
        # that runs past the bound has almost certainly been throttled rather than
        # having failed outright. `upstream_answered` stays False, so nothing is
        # recorded and the next batch retries the artist.
        stats["artists_timed_out"] = stats.get("artists_timed_out", 0) + 1
        stats["_source_failure"] = ("rate_limited", f"no answer in {MUSICBRAINZ_CALL_TIMEOUT_SECONDS}s")
        logger.warning(
            "discovery_musicbrainz_timeout",
            extra={"artist": artist_name, "timeout_s": MUSICBRAINZ_CALL_TIMEOUT_SECONDS},
        )

    except Exception as e:
        stats["_source_failure"] = ("http_error", str(e))
        logger.warning(f"MusicBrainz lookup failed for {artist_name}: {e}")

    for release in releases_for_artist:
        stats["releases_found"] += 1

        release_date: datetime | None = None
        raw_date = release.get("release_date")
        if isinstance(raw_date, datetime):
            release_date = raw_date
        elif isinstance(raw_date, str) and raw_date:
            try:
                release_date = datetime.fromisoformat(raw_date)
            except Exception:
                release_date = None

        # A date that cannot be true is worse than no date here, because this list is ordered by
        # date descending — a release claiming 2913 sorts above everything real. See
        # `plausible_release_date`; two rows in the live cache did exactly that.
        release_date = plausible_release_date(release_date)

        saved = await service.save_discovered_release(
            artist_name=artist_name,
            release_id=release["release_id"],
            release_name=release["release_name"],
            release_type=release.get("release_type"),
            release_date=release_date,
            artwork_url=release.get("artwork_url"),
            musicbrainz_artist_id=release.get("musicbrainz_artist_id"),
        )
        if saved:
            stats["releases_new"] += 1

    # **Record the check whenever MusicBrainz answered, matched or not.**
    #
    # This used to write only when an id resolved, so that an unmatched artist would be
    # retried rather than cached-out. That reasoning optimised for a rare transient at
    # the cost of the common structural case, and once ADR-0101 admitted unplayed
    # artists to the rotation the cost stopped being bounded: an artist MusicBrainz has
    # no entry for would be re-selected by the never-checked reserve on *every* batch,
    # forever, displacing artists that have never been looked at even once. Measured on
    # the live library — a 20-artist batch touched six cache rows and inserted none,
    # while 2,937 artists had no row at all.
    #
    # A row without a `musicbrainz_artist_id` is the honest record of "asked, nothing
    # matched": the artist leaves the backlog and rejoins the normal staleness rotation
    # rather than churning. If the call *failed*, nothing is written and it is retried
    # next batch.
    #
    # The imperfection worth naming: `search_artist` swallows a 503 and returns `None`,
    # so a rate-limited window is indistinguishable here from a genuine no-match and
    # costs one rotation. ADR-0099 point 6 is where that becomes visible; it is not
    # fixable from this side today.
    if mb_id_to_use or upstream_answered:
        await service.update_artist_cache(
            artist_normalized=normalized,
            musicbrainz_id=mb_id_to_use,
        )
        if not mb_id_to_use:
            stats["artists_unmatched"] = stats.get("artists_unmatched", 0) + 1


async def run_new_releases_check(
    profile_id: str | None = None,
    days_back: int = 90,
    force: bool = False,
) -> dict[str, Any]:
    """Check for new releases from every artist in the library (MB only)."""

    from app.db.session import create_task_engine_session
    from app.services.new_releases import NewReleasesService

    progress = NewReleasesProgressReporter(profile_id)

    stats: dict[str, Any] = {
        "artists_total": 0,
        "artists_checked": 0,
        "artists_skipped_cache": 0,
        "releases_found": 0,
        "releases_new": 0,
        "musicbrainz_queries": 0,
        "artists_failed": 0,
        "artists_unmatched": 0,
        "artists_timed_out": 0,
    }

    local_engine, local_session_maker = create_task_engine_session()

    try:
        async with local_session_maker() as db:
            service = NewReleasesService(db)
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
                    if not await service.should_check_artist(normalized):
                        stats["artists_skipped_cache"] += 1
                        continue

                stats["artists_checked"] += 1

                await _check_one_artist_isolated(
                    db=db,
                    service=service,
                    artist_name=artist_name,
                    normalized=normalized,
                    mb_artist_id=mb_artist_id,
                    days_back=days_back,
                    stats=stats,
                )

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
    """Check a prioritized batch of artists by listening recency + frequency."""

    from app.db.session import create_task_engine_session
    from app.services.new_releases import NewReleasesService

    progress = NewReleasesProgressReporter(profile_id)
    profile_uuid = UUIDType(profile_id)

    stats: dict[str, Any] = {
        "artists_in_batch": 0,
        "artists_checked": 0,
        "releases_found": 0,
        "releases_new": 0,
        "musicbrainz_queries": 0,
        "artists_failed": 0,
        "artists_unmatched": 0,
        "artists_timed_out": 0,
    }

    from app.services.discovery import get_recorder, source_enabled

    # ADR-0099 point 12. Checked before anything else, including backoff: when
    # discovery is off, no request leaves the machine and nothing is recorded as a
    # failure either — being switched off is not a fault.
    if not source_enabled("musicbrainz"):
        logger.info("discovery_batch_skipped", extra={"reason": "disabled"})
        return {"status": "disabled", **stats}

    health = get_recorder()

    # **Backoff is consulted before the work, not just reported after it** (ADR-0099
    # point 4). A source in backoff is skipped and the batch ends immediately rather
    # than spending ten slots re-confirming an outage. With one source this looks like
    # a guard; the shape is what makes a second source able to keep running while this
    # one is down.
    if await health.should_skip("musicbrainz"):
        logger.info("discovery_batch_skipped", extra={"reason": "musicbrainz backing off"})
        await health.record_success("discovery_batch", items=0)
        return {"status": "skipped", "reason": "musicbrainz backing off", **stats}

    local_engine, local_session_maker = create_task_engine_session()

    try:
        async with local_session_maker() as db:
            service = NewReleasesService(db)

            artists = await service.get_prioritized_artists_batch(
                profile_id=profile_uuid,
                batch_size=batch_size,
                min_days_since_check=7,
            )
            stats["artists_in_batch"] = len(artists)

            if not artists:
                logger.info("No artists need checking in this batch")
                progress.complete(0, 0, 0)
                return {"status": "success", **stats}

            logger.info(
                f"Checking {len(artists)} prioritized artists for new releases "
                f"(top priority: {artists[0]['name']})"
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

                await _check_one_artist_isolated(
                    db=db,
                    service=service,
                    artist_name=artist_name,
                    normalized=normalized,
                    mb_artist_id=mb_artist_id,
                    days_back=days_back,
                    stats=stats,
                )

        progress.complete(
            checked=stats["artists_checked"],
            found=stats["releases_found"],
            new=stats["releases_new"],
        )

        # One health write per source per batch rather than per artist: ten writes to
        # say the same thing costs ten transactions and tells nobody anything more.
        #
        # **"Answered" is the success condition, not "found something".** A source that
        # replies correctly and has no new releases is working; conflating the two is
        # how a healthy upstream would start reading as broken every quiet week.
        answered = stats["musicbrainz_queries"] > 0 or stats.get("artists_unmatched", 0) > 0
        if answered:
            await health.record_success("musicbrainz", items=stats["releases_new"])
        elif stats.get("_source_failure"):
            kind, detail = stats["_source_failure"]
            await health.record_failure("musicbrainz", kind=kind, detail=detail)

        logger.info(
            f"Priority-based new releases check complete: "
            f"{stats['artists_checked']} artists, {stats['releases_new']} new releases, "
            f"{stats.get('artists_unmatched', 0)} unmatched, "
            f"{stats.get('artists_timed_out', 0)} timed out, "
            f"{stats.get('artists_failed', 0)} failed"
        )

        # ADR-0099 point 10: the job's own outcome, separately from its upstreams'.
        # The nineteen-night outage had a perfectly healthy MusicBrainz and a dead
        # writer — a source-only view would have shown all green throughout.
        await health.record_success("discovery_batch", items=stats["releases_new"])

        stats.pop("_source_failure", None)
        return {"status": "success", **stats}

    except Exception as e:
        logger.error(f"Priority-based new releases check failed: {e}", exc_info=True)
        progress.error(str(e))
        await health.record_failure("discovery_batch", kind="crashed", detail=str(e))
        return {"status": "error", "error": str(e)}
    finally:
        await local_engine.dispose()
