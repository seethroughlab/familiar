"""Name the library's recordings through AcoustID (ADR-0115).

One bounded phase per tick, under ADR-0099's discipline: **resolve** sends stored
fingerprints to AcoustID and writes back an id when the four tiers name one. It has
its own health row and its own resumption state in ``TrackAnalysis.acoustid_lookup``,
so a rate-limited window costs one batch, a restart costs nothing, and one bad track
costs one track.

There used to be a second phase, **claim**, which told the Clapback commons which
recordings the library held. ADR-0159 removed it with the commons. The ``claimed_at``
and ``claim_*`` keys it wrote stay in ``acoustid_lookup`` as history.

No file is opened anywhere in this module. The fingerprint and the duration are
already in the database, which is the entire reason the backfill is affordable.
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.orm import aliased

from app.utils.time import utcnow

logger = logging.getLogger(__name__)

#: Health row.
SOURCE_ACOUSTID = "acoustid"

#: Per tick. At the pace below a resolve phase is about a minute, on a ten-minute
#: interval (ADR-0115 point 1).
RESOLVE_BATCH = 150

#: AcoustID's documented ceiling is 3/s; 0.34 s between requests stays under it,
#: and measured 200 lookups in 116–120 s on 2026-09-14.
ACOUSTID_PACE_SECONDS = 0.34

#: A track AcoustID could not name is asked about again after this long
#: (ADR-0115 point 5). The library grows, and so does AcoustID.
RECHECK_DAYS = 180

#: Consecutive upstream failures within one phase before the phase stops and
#: backs off, rather than burning the rest of a batch against a wall.
UPSTREAM_FAILURE_LIMIT = 3

#: pyacoustid's `lookup` defaults to **no timeout**. On 2026-09-14 at 12:05 UTC one
#: request never answered, the worker thread held it for 45 minutes, and every
#: tick after was skipped by `max_instances=1` — with both health rows reading
#: `working`, because a hang is not a failure. A request that takes longer than
#: this is a failure now.
ACOUSTID_TIMEOUT_SECONDS = 30

#: A phase stops taking new tracks once it has run this long, so a tick always
#: fits inside its interval whatever the upstream does. It is sized to about a
#: minute and must finish under ten.
PHASE_DEADLINE_SECONDS = 240

#: Indirection so a test can move this module's clock without moving asyncio's.
_clock = time.monotonic

#: AcoustID requests run on their own thread, not the loop's default executor.
#: On 2026-09-14 from 14:30 a burst of MusicBrainz work — hundreds of 503s, each
#: retried with a blocking backoff sleep — filled the shared pool, and every
#: `to_thread` lookup waited ~45 s for a thread while the request itself took
#: 0.3 s. Resolve phases hit their deadline after four tracks with zero errors.
#: One thread is the right size: the pace is sequential by design.
_acoustid_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="acoustid-lookup")


def _now_iso() -> str:
    return utcnow().replace(tzinfo=None).isoformat(timespec="seconds")


def _cutoff_iso() -> str:
    return (utcnow().replace(tzinfo=None) - timedelta(days=RECHECK_DAYS)).isoformat(
        timespec="seconds"
    )


def _merged(existing: dict[str, Any] | None, **updates: Any) -> dict[str, Any]:
    """A new dict, because SQLAlchemy does not see in-place mutation of JSONB."""
    out = dict(existing or {})
    out.update(updates)
    return out


def _acoustid_kind(exc: Exception) -> str:
    """Map pyacoustid's one exception type onto a health kind by its message."""
    text = str(exc).lower()
    if "429" in text or "rate" in text or "too many" in text:
        return "rate_limited"
    if "timed out" in text or "timeout" in text:
        return "timeout"
    return "http_error"


def _is_per_track(exc: Exception) -> bool:
    """AcoustID reporting a bad *request* — an invalid fingerprint, say — is about
    this track, not the upstream, and must not put AcoustID into backoff."""
    text = str(exc).lower()
    return "invalid" in text or "status:" in text


# --- resolve --------------------------------------------------------------


async def _resolve_candidates(db: Any, limit: int) -> list[tuple[Any, Any]]:
    """Tracks with a fingerprint and a duration, no id, and no recent check.

    One analysis row per track — the newest that carries a fingerprint — so the
    resumption marker is written to the row the next tick will read. The
    ``NOT EXISTS`` is against *any* of the track's analysis rows for the same
    reason: a marker on one row must exclude the track, whichever row the join
    would otherwise pick.
    """
    from app.db.models import Track, TrackAnalysis, TrackStatus

    other = aliased(TrackAnalysis)
    recently_checked = exists().where(
        other.track_id == Track.id,
        other.acoustid_lookup["checked_at"].astext > _cutoff_iso(),
    )
    stmt = (
        select(Track, TrackAnalysis)
        .join(TrackAnalysis, TrackAnalysis.track_id == Track.id)
        .where(
            Track.status == TrackStatus.ACTIVE,
            Track.musicbrainz_track_id.is_(None),
            Track.duration_seconds.is_not(None),
            TrackAnalysis.acoustid.is_not(None),
            ~recently_checked,
        )
        .distinct(Track.id)
        .order_by(Track.id, TrackAnalysis.features_version.desc())
        .limit(limit)
    )
    return [(row.Track, row.TrackAnalysis) for row in (await db.execute(stmt)).all()]


def _lookup(api_key: str, fingerprint: str, duration: int) -> dict[str, Any]:
    """One AcoustID request. Blocking; called through ``to_thread``."""
    import acoustid

    return acoustid.lookup(
        api_key,
        fingerprint,
        duration,
        meta="recordings releasegroups sources",
        timeout=ACOUSTID_TIMEOUT_SECONDS,
    )


async def run_resolve_phase(
    *, limit: int = RESOLVE_BATCH, dry_run: bool = False
) -> dict[str, Any]:
    """Ask AcoustID about up to ``limit`` unnamed tracks and write what it names."""
    from app.db.session import create_task_engine_session
    from app.services.analysis import canonical_fingerprint
    from app.services.app_settings import get_app_settings_service
    from app.services.discovery import get_recorder
    from app.services.recording_resolution import candidates_as_json, resolve

    stats: dict[str, Any] = {
        "phase": "resolve",
        "status": "ok",
        "considered": 0,
        "resolved": 0,
        "refused": 0,
        "errors": 0,
        "by_tier": {},
        "by_reason": {},
    }
    app_settings = get_app_settings_service()
    if not app_settings.get().recording_backfill_enabled:
        stats["status"] = "disabled"
        return stats

    health = get_recorder()
    api_key = app_settings.get_effective("acoustid_api_key")
    if not api_key:
        # Enabled but unconfigured is an error state, not a silent skip (ADR-0099 §12).
        await health.record_failure(
            SOURCE_ACOUSTID, kind="not_configured", detail="no AcoustID API key"
        )
        stats["status"] = "not_configured"
        return stats
    if await health.should_skip(SOURCE_ACOUSTID):
        stats["status"] = "backing_off"
        return stats

    engine, session_maker = create_task_engine_session()
    started = _clock()
    upstream_failures = 0
    try:
        async with session_maker() as db:
            rows = await _resolve_candidates(db, limit)
            for track, analysis in rows:
                if _clock() - started > PHASE_DEADLINE_SECONDS:
                    stats["status"] = "deadline"
                    break
                stats["considered"] += 1
                fingerprint = canonical_fingerprint(analysis.acoustid).decode()
                try:
                    data = await asyncio.get_running_loop().run_in_executor(
                        _acoustid_executor, _lookup, api_key, fingerprint, int(track.duration_seconds)
                    )
                except Exception as exc:
                    if _is_per_track(exc):
                        # AcoustID answered; it just did not like this fingerprint.
                        stats["errors"] += 1
                        if not dry_run:
                            analysis.acoustid_lookup = _merged(
                                analysis.acoustid_lookup,
                                checked_at=_now_iso(),
                                error=str(exc)[:200],
                            )
                            await db.commit()
                        continue
                    upstream_failures += 1
                    stats["errors"] += 1
                    await health.record_failure(
                        SOURCE_ACOUSTID, kind=_acoustid_kind(exc), detail=str(exc)[:500]
                    )
                    if upstream_failures >= UPSTREAM_FAILURE_LIMIT:
                        stats["status"] = "upstream_failed"
                        break
                    await asyncio.sleep(ACOUSTID_PACE_SECONDS)
                    continue
                upstream_failures = 0

                resolution = resolve(data, title=track.title, album=track.album)
                stats["by_reason"][resolution.reason] = (
                    stats["by_reason"].get(resolution.reason, 0) + 1
                )
                if resolution.resolved:
                    stats["resolved"] += 1
                    stats["by_tier"][resolution.tier] = stats["by_tier"].get(resolution.tier, 0) + 1
                else:
                    stats["refused"] += 1

                if not dry_run:
                    try:
                        # One track's failure costs one track (ADR-0099 §9): the
                        # rollback is what keeps the session usable for the next.
                        analysis.acoustid_lookup = _merged(
                            analysis.acoustid_lookup,
                            candidates=candidates_as_json(resolution),
                            checked_at=_now_iso(),
                            resolved=(
                                {
                                    "recording_mbid": resolution.recording_mbid,
                                    "tier": resolution.tier,
                                    "score": round(resolution.score, 4),
                                    "at": _now_iso(),
                                }
                                if resolution.resolved
                                else None
                            ),
                            reason=resolution.reason,
                        )
                        if resolution.resolved and track.musicbrainz_track_id is None:
                            track.musicbrainz_track_id = resolution.recording_mbid
                        await db.commit()
                    except Exception:
                        await db.rollback()
                        stats["errors"] += 1
                        logger.warning(
                            "recording_backfill_write_failed",
                            extra={"track_id": str(track.id)},
                            exc_info=True,
                        )
                await asyncio.sleep(ACOUSTID_PACE_SECONDS)
    finally:
        await engine.dispose()

    if stats["status"] in ("ok", "deadline") and stats["considered"] and not dry_run:
        await health.record_success(SOURCE_ACOUSTID, items=stats["resolved"])
    stats["seconds"] = round(_clock() - started, 1)
    logger.info("recording_backfill_resolve", extra=stats)
    return stats


async def run_recording_backfill(
    *,
    resolve_limit: int = RESOLVE_BATCH,
    dry_run: bool = False,
    deadline_seconds: float | None = None,
) -> dict[str, Any]:
    """One tick: the resolve phase.

    `deadline_seconds` bounds the whole tick. A tick that overruns is recorded as
    a `timeout` failure against AcoustID — the state the health surface could not
    see on 2026-09-14 — and the next tick is free to run.
    """

    async def tick():
        return {"resolve": await run_resolve_phase(limit=resolve_limit, dry_run=dry_run)}

    if deadline_seconds is None:
        return await tick()
    try:
        return await asyncio.wait_for(tick(), timeout=deadline_seconds)
    except TimeoutError:
        from app.services.discovery import get_recorder

        logger.warning(
            "recording_backfill_tick_overran",
            extra={"phase": SOURCE_ACOUSTID, "seconds": deadline_seconds},
        )
        await get_recorder().record_failure(
            SOURCE_ACOUSTID, kind="timeout", detail=f"tick exceeded {deadline_seconds:.0f}s"
        )
        return {"status": "overran", "phase": SOURCE_ACOUSTID}
