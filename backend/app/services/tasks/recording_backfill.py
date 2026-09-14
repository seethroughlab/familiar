"""Name the library's recordings through AcoustID, and tell the corpus (ADR-0115).

Two bounded phases per tick, under ADR-0099's discipline: **resolve** sends stored
fingerprints to AcoustID and writes back an id when the four tiers name one;
**claim** sends every id the library holds and has not yet claimed to the corpus.
Each phase has its own health row, its own gate, and its own resumption state in
``TrackAnalysis.acoustid_lookup`` — so a rate-limited window costs one batch, a
restart costs nothing, and one bad track costs one track.

No file is opened anywhere in this module. The fingerprint and the duration are
already in the database, which is the entire reason the backfill is affordable.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.orm import aliased

from app.utils.time import utcnow

logger = logging.getLogger(__name__)

#: Health rows. One per upstream, because they fail and cost differently: AcoustID
#: is 3 requests a second and answers at once; the corpus is 30 writes a minute.
SOURCE_ACOUSTID = "acoustid"
SOURCE_CLAIMS = "community_cache_claims"

#: Per tick. At the paces below a resolve phase is about a minute and a claim
#: phase six, on a ten-minute interval (ADR-0115 point 1).
RESOLVE_BATCH = 150
CLAIM_BATCH = 150

#: AcoustID's documented ceiling is 3/s; 0.34 s between requests stays under it,
#: and measured 200 lookups in 116–120 s on 2026-09-14.
ACOUSTID_PACE_SECONDS = 0.34

#: A claim is a write against the corpus's 30/minute limit. Pacing *at* the limit
#: lost 9% of the 2026-09-13 run to exhausted retries; 25 leaves room for them.
CLAIM_PACE_SECONDS = 60.0 / 25

#: A track AcoustID could not name, or the corpus did not hold, is asked about
#: again after this long (ADR-0115 point 5). Both grow.
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
#: fits inside its interval whatever the upstreams do. Resolve is sized to about
#: a minute and claim to six; together they must finish under ten.
PHASE_DEADLINE_SECONDS = 240

#: Which phase a tick is in, so a tick that overruns can be recorded against the
#: upstream that was actually being waited on.
_active_phase: str | None = None

#: Indirection so a test can move this module's clock without moving asyncio's.
_clock = time.monotonic


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
    from app.services.app_settings import get_app_settings_service
    from app.services.community_cache import CommunityCacheService
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

    global _active_phase
    _active_phase = SOURCE_ACOUSTID
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
                fingerprint = CommunityCacheService.canonical_fingerprint(analysis.acoustid).decode()
                try:
                    data = await asyncio.to_thread(
                        _lookup, api_key, fingerprint, int(track.duration_seconds)
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
        _active_phase = None

    if stats["status"] in ("ok", "deadline") and stats["considered"] and not dry_run:
        await health.record_success(SOURCE_ACOUSTID, items=stats["resolved"])
    stats["seconds"] = round(_clock() - started, 1)
    logger.info("recording_backfill_resolve", extra=stats)
    return stats


# --- claim ----------------------------------------------------------------


async def _claim_candidates(db: Any, limit: int) -> list[tuple[Any, Any]]:
    """Tracks with a fingerprint and an id that no analysis row says is claimed,
    or was found not held within the recheck window."""
    from app.db.models import Track, TrackAnalysis, TrackStatus

    other = aliased(TrackAnalysis)
    settled = exists().where(
        other.track_id == Track.id,
        (other.acoustid_lookup["claimed_at"].astext.is_not(None))
        | (other.acoustid_lookup["claim_checked_at"].astext > _cutoff_iso()),
    )
    stmt = (
        select(Track, TrackAnalysis)
        .join(TrackAnalysis, TrackAnalysis.track_id == Track.id)
        .where(
            Track.status == TrackStatus.ACTIVE,
            Track.musicbrainz_track_id.is_not(None),
            TrackAnalysis.acoustid.is_not(None),
            ~settled,
        )
        .distinct(Track.id)
        .order_by(Track.id, TrackAnalysis.features_version.desc())
        .limit(limit)
    )
    return [(row.Track, row.TrackAnalysis) for row in (await db.execute(stmt)).all()]


async def run_claim_phase(*, limit: int = CLAIM_BATCH, dry_run: bool = False) -> dict[str, Any]:
    """Send up to ``limit`` unclaimed ids to the corpus, paced under its write limit."""
    from app.db.session import create_task_engine_session
    from app.services.app_settings import get_app_settings_service
    from app.services.community_cache import get_community_cache_service
    from app.services.discovery import get_recorder

    stats: dict[str, Any] = {
        "phase": "claim",
        "status": "ok",
        "considered": 0,
        "claimed": 0,
        "not_held": 0,
        "errors": 0,
    }
    app_settings = get_app_settings_service()
    current = app_settings.get()
    # A claim discloses which recording this installation holds — the same consent
    # `community_cache_contribute` asks for, so it is the same gate (ADR-0115 §7).
    if not current.community_cache_contribute:
        stats["status"] = "disabled"
        return stats

    health = get_recorder()
    if await health.should_skip(SOURCE_CLAIMS):
        stats["status"] = "backing_off"
        return stats

    cache = get_community_cache_service(
        cache_url=current.community_cache_url,
        client_id=app_settings.ensure_community_cache_client_id() if not dry_run else None,
    )
    global _active_phase
    _active_phase = SOURCE_CLAIMS
    engine, session_maker = create_task_engine_session()
    started = _clock()
    upstream_failures = 0
    try:
        async with session_maker() as db:
            rows = await _claim_candidates(db, limit)
            for track, analysis in rows:
                if _clock() - started > PHASE_DEADLINE_SECONDS * 2:
                    stats["status"] = "deadline"
                    break
                stats["considered"] += 1
                if dry_run:
                    stats["claimed"] += 1
                    continue
                outcome = await cache.claim_recording_outcome(
                    analysis.acoustid, track.musicbrainz_track_id
                )
                try:
                    if outcome == "claimed":
                        stats["claimed"] += 1
                        upstream_failures = 0
                        analysis.acoustid_lookup = _merged(
                            analysis.acoustid_lookup, claimed_at=_now_iso()
                        )
                        await db.commit()
                    elif outcome == "not_held":
                        stats["not_held"] += 1
                        upstream_failures = 0
                        analysis.acoustid_lookup = _merged(
                            analysis.acoustid_lookup,
                            claim_checked_at=_now_iso(),
                            claim_outcome="not_held",
                        )
                        await db.commit()
                    else:
                        stats["errors"] += 1
                        upstream_failures += 1
                        await health.record_failure(
                            SOURCE_CLAIMS,
                            kind="http_error",
                            detail=f"claim failed for {track.musicbrainz_track_id}",
                        )
                        if upstream_failures >= UPSTREAM_FAILURE_LIMIT:
                            stats["status"] = "upstream_failed"
                            break
                except Exception:
                    await db.rollback()
                    stats["errors"] += 1
                    logger.warning(
                        "recording_backfill_claim_write_failed",
                        extra={"track_id": str(track.id)},
                        exc_info=True,
                    )
                await asyncio.sleep(CLAIM_PACE_SECONDS)
    finally:
        await engine.dispose()
        _active_phase = None

    if stats["status"] in ("ok", "deadline") and stats["considered"] and not dry_run:
        await health.record_success(SOURCE_CLAIMS, items=stats["claimed"])
    stats["seconds"] = round(_clock() - started, 1)
    logger.info("recording_backfill_claim", extra=stats)
    return stats


async def run_recording_backfill(
    *,
    resolve_limit: int = RESOLVE_BATCH,
    claim_limit: int = CLAIM_BATCH,
    dry_run: bool = False,
    deadline_seconds: float | None = None,
) -> dict[str, Any]:
    """One tick: resolve, then claim. Each phase decides for itself whether to run.

    `deadline_seconds` bounds the whole tick. A tick that overruns is recorded as
    a `timeout` failure against the phase that was active — the state the health
    surface could not see on 2026-09-14 — and the next tick is free to run.
    """

    async def tick():
        resolved = await run_resolve_phase(limit=resolve_limit, dry_run=dry_run)
        claimed = await run_claim_phase(limit=claim_limit, dry_run=dry_run)
        return {"resolve": resolved, "claim": claimed}

    if deadline_seconds is None:
        return await tick()
    try:
        return await asyncio.wait_for(tick(), timeout=deadline_seconds)
    except TimeoutError:
        from app.services.discovery import get_recorder

        phase = _active_phase or SOURCE_ACOUSTID
        logger.warning("recording_backfill_tick_overran", extra={"phase": phase, "seconds": deadline_seconds})
        await get_recorder().record_failure(
            phase, kind="timeout", detail=f"tick exceeded {deadline_seconds:.0f}s"
        )
        return {"status": "overran", "phase": phase}
