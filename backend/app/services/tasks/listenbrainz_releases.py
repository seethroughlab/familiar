"""Pull ListenBrainz fresh releases into the discovery cache (ADR-0099 §11).

Runs on its own cadence rather than inside the per-artist batch, because it is a
different shape of request: one large call covering every artist at once, instead
of one small call per artist. Folding it into the twenty-minute batch would fetch
a megabyte of releases to look at ten artists.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import select

logger = logging.getLogger(__name__)

SOURCE = "listenbrainz"


async def run_listenbrainz_fresh_releases(days: int | None = None) -> dict[str, Any]:
    """Fetch fresh releases, keep the ones this library's artists made, cache them.

    Writes through ``NewReleasesService.save_discovered_release``, so rows land in
    the same ``artist_new_release`` context the MusicBrainz path uses and dedupe
    against it on ``release_group_mbid`` through the existing partial unique index.
    A release both sources know about becomes one row, not two.
    """
    from app.db.models import Artist, Track, TrackStatus
    from app.db.session import create_task_engine_session
    from app.services.discovery import get_recorder, source_enabled
    from app.services.discovery.listenbrainz import (
        DEFAULT_DAYS,
        fetch_fresh_releases,
        select_for_library,
    )
    from app.services.new_releases import NewReleasesService

    health = get_recorder()
    stats: dict[str, Any] = {
        "releases_seen": 0,
        "matched_library": 0,
        "releases_new": 0,
        "artists_with_mbid": 0,
    }

    # Checked before backoff: being switched off is not a fault, so it records
    # nothing and reports a state of its own (ADR-0099 point 12).
    if not source_enabled(SOURCE):
        logger.info("listenbrainz_skipped", extra={"reason": "disabled"})
        return {"status": "disabled", **stats}

    if await health.should_skip(SOURCE):
        logger.info("listenbrainz_skipped", extra={"reason": "backing off"})
        return {"status": "skipped", **stats}

    try:
        releases, rate = await fetch_fresh_releases(days=days or DEFAULT_DAYS)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        # 429 is the one failure this source reports honestly, and it tells us how
        # long to wait — so the backoff comes from the header rather than a guess.
        retry_after = None
        if status == 429:
            raw = exc.response.headers.get("X-RateLimit-Reset-In")
            retry_after = float(raw) if raw and raw.isdigit() else None
        await health.record_failure(
            SOURCE,
            kind="rate_limited" if status == 429 else "http_error",
            detail=f"HTTP {status}",
            retry_after_seconds=retry_after,
        )
        return {"status": "error", "error": f"HTTP {status}", **stats}
    except Exception as exc:
        await health.record_failure(
            SOURCE,
            kind="bad_response" if isinstance(exc, ValueError) else "timeout",
            detail=str(exc)[:500],
        )
        return {"status": "error", "error": str(exc), **stats}

    stats["releases_seen"] = len(releases)
    remaining = rate.get("X-RateLimit-Remaining")

    engine, session_maker = create_task_engine_session()
    try:
        async with session_maker() as db:
            rows = (
                await db.execute(
                    select(Artist.musicbrainz_id, Artist.name)
                    .join(Track, Track.canonical_artist_id == Artist.id)
                    .where(
                        Artist.musicbrainz_id.isnot(None),
                        Track.status == TrackStatus.ACTIVE,
                    )
                    .distinct()
                )
            ).all()
            library = {mbid: name for mbid, name in rows}
            stats["artists_with_mbid"] = len(library)

            wanted = select_for_library(releases, library)
            stats["matched_library"] = len(wanted)

            service = NewReleasesService(db)
            for item in wanted:
                try:
                    saved = await service.save_discovered_release(**item)
                    if saved:
                        stats["releases_new"] += 1
                    # Committed per release for the same reason the artist batch is:
                    # one bad row must cost one row (ADR-0099 point 9).
                    await db.commit()
                except Exception:
                    await db.rollback()
                    logger.warning(
                        "listenbrainz_release_failed",
                        extra={"release": item.get("release_name")},
                        exc_info=True,
                    )
    finally:
        await engine.dispose()

    await health.record_success(SOURCE, items=stats["releases_new"])
    logger.info(
        "listenbrainz_fresh_releases_complete: "
        f"{stats['releases_seen']} seen, {stats['matched_library']} match the library, "
        f"{stats['releases_new']} new (rate limit remaining: {remaining})"
    )
    return {"status": "success", **stats}
