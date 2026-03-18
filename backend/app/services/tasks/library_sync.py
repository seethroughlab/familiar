"""Library sync task: file discovery, metadata reading, and analysis orchestration.

Contains scan subprocess infrastructure and run_library_sync.
Progress reporting is in library_sync_progress.py.
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from concurrent.futures import ProcessPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.config import EMBEDDING_VERSION, FEATURES_VERSION, MELODIC_VERSION, settings
from app.services.background.events import record_background_event
from app.services.redis_client import get_redis
from app.services.tasks.library_sync_progress import (
    SYNC_GUARDRAIL_PHASES,
    SYNC_MAX_REQUEUE_ATTEMPTS_PER_WINDOW,
    SYNC_QUEUE_CHURN_WINDOW_SECONDS,
    SyncProgressReporter,
    _register_phase_requeue_attempt,
)
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


async def _mark_crashed_tracks_as_skipped(phase: str) -> int:
    """Mark OOM-crashed tracks as skipped so they don't re-queue forever.

    When stall recovery fires, the pending tracks are ones whose worker
    subprocess was killed (OOM). Mark them as done with a skip marker so
    the queue filter excludes them on the next pass.

    Returns the number of tracks marked.
    """
    from sqlalchemy import and_, select, update

    from app.db.models import Track, TrackAnalysis
    from app.db.session import async_session_maker

    marked = 0
    async with async_session_maker() as db:
        if phase == "backfill":
            # Find tracks stuck without analysis_detail — mark with skip sentinel
            result = await db.execute(
                select(TrackAnalysis.track_id)
                .join(Track, Track.id == TrackAnalysis.track_id)
                .where(
                    and_(
                        TrackAnalysis.features_version >= FEATURES_VERSION,
                        TrackAnalysis.analysis_detail.is_(None),
                    )
                )
                # Target the longest tracks first (most likely OOM culprits)
                .order_by(Track.duration_seconds.desc().nullslast())
                .limit(20)
            )
            stuck_ids = [row[0] for row in result.fetchall()]
            if stuck_ids:
                await db.execute(
                    update(TrackAnalysis)
                    .where(TrackAnalysis.track_id.in_(stuck_ids))
                    .values(analysis_detail={"_skipped": True, "reason": "oom_crash"})
                )
                await db.commit()
                marked = len(stuck_ids)
                logger.warning(
                    f"Marked {marked} likely OOM-crashed tracks as skipped (backfill)"
                )

        elif phase == "melodic":
            # Find tracks stuck without melodic_version — mark as done (no melodic)
            result = await db.execute(
                select(TrackAnalysis.track_id)
                .join(Track, Track.id == TrackAnalysis.track_id)
                .where(
                    and_(
                        TrackAnalysis.features_version >= FEATURES_VERSION,
                        TrackAnalysis.analysis_detail.is_not(None),
                        TrackAnalysis.melodic_version < MELODIC_VERSION,
                    )
                )
                .order_by(Track.duration_seconds.desc().nullslast())
                .limit(20)
            )
            stuck_ids = [row[0] for row in result.fetchall()]
            if stuck_ids:
                await db.execute(
                    update(TrackAnalysis)
                    .where(TrackAnalysis.track_id.in_(stuck_ids))
                    .values(melodic_version=MELODIC_VERSION, has_melodic=False)
                )
                await db.commit()
                marked = len(stuck_ids)
                logger.warning(
                    f"Marked {marked} likely OOM-crashed tracks as skipped (melodic)"
                )

    return marked


# ---- Scan subprocess executor ----

_scan_executor: ProcessPoolExecutor | None = None
_scan_atexit_registered: bool = False


def _cleanup_scan_executor() -> None:
    """atexit handler: terminate scan worker if the process exits uncleanly."""
    if _scan_executor is not None:
        try:
            _scan_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass


def _get_scan_executor() -> ProcessPoolExecutor:
    """Lazy singleton ProcessPoolExecutor for library scanning.

    Separate from the analysis executor — different failure mode, no circuit breaker.
    """
    global _scan_executor, _scan_atexit_registered
    if _scan_executor is None or _scan_executor._broken:
        import atexit
        import multiprocessing as mp

        _scan_executor = ProcessPoolExecutor(
            max_workers=1,
            mp_context=mp.get_context("spawn"),
        )

        if not _scan_atexit_registered:
            atexit.register(_cleanup_scan_executor)
            _scan_atexit_registered = True
    return _scan_executor


def _run_scan_in_process(
    library_paths_str: list[str],
    reread_unchanged: bool,
    started_at: str,
) -> dict[str, Any]:
    """Run library scan in a subprocess — keeps main event loop free for HTTP.

    This is a sync top-level function (must be picklable for ProcessPoolExecutor).
    Pattern follows run_track_features().
    """
    import logging

    logging.basicConfig(level=logging.INFO, format="%(message)s", force=True)

    return asyncio.run(_async_scan_worker(library_paths_str, reread_unchanged, started_at))


async def _async_scan_worker(
    library_paths_str: list[str],
    reread_unchanged: bool,
    started_at: str,
) -> dict[str, Any]:
    """Async scan logic that runs inside the subprocess's own event loop.

    Creates its own async engine + session and SyncProgressReporter.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.services.scanner import LibraryScanner

    results = {
        "new": 0,
        "updated": 0,
        "unchanged": 0,
        "deleted": 0,
        "marked_missing": 0,
        "still_missing": 0,
        "relocated": 0,
        "recovered": 0,
        "compilation_albums": 0,
        "compilation_tracks": 0,
    }

    # Build a SyncProgressReporter with the parent's started_at timestamp
    progress = SyncProgressReporter.__new__(SyncProgressReporter)
    progress.redis = get_redis()
    progress.started_at = started_at
    progress.errors = []

    library_paths = [Path(p) for p in library_paths_str]

    local_engine = create_async_engine(
        settings.database_url,
        echo=False,
        future=True,
    )
    local_session_maker = async_sessionmaker(
        local_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        async with local_session_maker() as db:
            scanner = LibraryScanner(
                db,
                scan_state=_SyncProgressAdapter(progress),
            )

            for library_path in library_paths:
                scan_results = await scanner.scan(
                    library_path,
                    reread_unchanged=reread_unchanged,
                    reanalyze_changed=True,
                )
                results["new"] += scan_results.get("new", 0)
                results["updated"] += scan_results.get("updated", 0)
                results["unchanged"] += scan_results.get("unchanged", 0)
                results["deleted"] += scan_results.get("deleted", 0)
                results["marked_missing"] += scan_results.get("marked_missing", 0)
                results["still_missing"] += scan_results.get("still_missing", 0)
                results["relocated"] += scan_results.get("relocated", 0)
                results["recovered"] += scan_results.get("recovered", 0)

            orphan_results = await scanner.cleanup_orphaned_tracks(library_paths)
            results["marked_missing"] += orphan_results.get("orphaned", 0)

            compilation_results = await scanner.detect_compilation_albums()
            results["compilation_albums"] = compilation_results.get("albums_detected", 0)
            results["compilation_tracks"] = compilation_results.get("tracks_updated", 0)

        return {"status": "success", **results}

    except Exception as e:
        logger.error(f"Scan worker failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        await local_engine.dispose()


async def run_library_sync(
    reread_unchanged: bool = False,
) -> dict[str, Any]:
    """Run a complete library sync: scan + analysis.

    This is the main entry point for unified sync operations.
    Orchestrates the scan and analysis phases with unified progress.

    Args:
        reread_unchanged: Re-read metadata for files even if unchanged.

    Returns:
        Dict with status and statistics.
    """

    from sqlalchemy import and_, func, select

    from app.db.models import Track, TrackAnalysis
    from app.db.session import create_task_engine_session
    from app.services.tasks.analysis_queue import (
        queue_tracks_for_backfill,
        queue_tracks_for_embeddings,
        queue_tracks_for_features,
        queue_tracks_for_melodic,
    )

    progress = SyncProgressReporter()
    phase_requeue_windows: dict[str, deque[float]] = {
        phase: deque() for phase in SYNC_GUARDRAIL_PHASES
    }

    async def _guarded_queue(
        phase: str,
        queue_fn: Callable[..., Awaitable[int]],
        *,
        limit: int,
        stall_recovery: bool = False,
    ) -> tuple[int, bool]:
        """Queue tracks while enforcing per-phase churn guardrails."""
        now = time.monotonic()
        attempts = phase_requeue_windows.setdefault(phase, deque())
        if _register_phase_requeue_attempt(attempts, now):
            reason = (
                f"queue_churn_limit_exceeded:{len(attempts)}/"
                f"{SYNC_MAX_REQUEUE_ATTEMPTS_PER_WINDOW}:{int(SYNC_QUEUE_CHURN_WINDOW_SECONDS)}s"
            )
            progress.set_forced_exit_reason(phase, reason)
            logger.warning("Sync %s phase forced exit: %s", phase, reason)
            return 0, True

        progress.record_requeue_attempt(phase)
        if stall_recovery:
            progress.record_stall_recovery(phase)

        queued = await queue_fn(limit=limit)
        return queued, False

    try:
        # Phase 1 & 2: Run the scan in a separate process so it doesn't
        # block the main event loop (which serves HTTP/streaming requests).
        library_paths = settings.music_library_paths
        if not library_paths:
            progress.error("No music library paths configured.")
            return {"status": "error", "error": "No music library paths configured."}

        valid_paths: list[Path] = []
        for path in library_paths:
            if path.exists() and path.is_dir():
                try:
                    if any(path.iterdir()):
                        valid_paths.append(path)
                except PermissionError:
                    continue

        if not valid_paths:
            error_msg = f"No valid library paths found: {[str(p) for p in library_paths]}"
            progress.error(error_msg)
            return {"status": "error", "error": error_msg}

        loop = asyncio.get_event_loop()
        scan_result = await loop.run_in_executor(
            _get_scan_executor(),
            _run_scan_in_process,
            [str(p) for p in valid_paths],
            reread_unchanged,
            progress.started_at,
        )

        if scan_result.get("status") == "error":
            progress.error(scan_result.get("error", "Scan failed"))
            return scan_result

        # Phase 3: Analysis - wait for all pending analysis to complete
        scan_stats = {
            "files_total": scan_result.get("new", 0) + scan_result.get("updated", 0) + scan_result.get("unchanged", 0),
            "new_tracks": scan_result.get("new", 0),
            "updated_tracks": scan_result.get("updated", 0),
            "unchanged_tracks": scan_result.get("unchanged", 0),
            "relocated_tracks": scan_result.get("relocated", 0),
            "marked_missing": scan_result.get("marked_missing", 0),
            "recovered": scan_result.get("recovered", 0),
        }

        # Create engine for analysis tracking
        local_engine, local_session_maker = create_task_engine_session()

        try:
            # Phase 3a: Feature extraction
            # Wait for all tracks to have features extracted
            features_start_time = time.time()
            max_features_duration = 8 * 60 * 60  # 8 hours max for entire features phase
            features_stall_threshold = 5 * 60  # 5 minutes without progress = stalled
            last_features_progress_time = time.time()
            last_features_done = 0

            while True:
                async with local_session_maker() as db:
                    total_result = await db.execute(select(func.count(Track.id)))
                    total_tracks = total_result.scalar() or 0

                    analyzed_result = await db.execute(
                        select(func.count(TrackAnalysis.id)).where(
                            TrackAnalysis.features_version >= FEATURES_VERSION
                        )
                    )
                    features_done = analyzed_result.scalar() or 0
                    pending_features = total_tracks - features_done

                if pending_features == 0:
                    break

                # Check for timeout
                features_elapsed = time.time() - features_start_time
                if features_elapsed > max_features_duration:
                    logger.warning(
                        f"Features phase timed out after {features_elapsed/3600:.1f}h "
                        f"({features_done} done, {pending_features} still pending)"
                    )
                    progress.set_forced_exit_reason("features", "timeout")
                    break

                # Check for stall (no progress in stall_threshold seconds)
                if features_done > last_features_done:
                    last_features_progress_time = time.time()
                    last_features_done = features_done
                elif time.time() - last_features_progress_time > features_stall_threshold:
                    logger.warning(
                        f"Features progress stalled for {features_stall_threshold}s "
                        f"({pending_features} still pending)"
                    )
                    record_background_event(
                        "queue_stall",
                        {"phase": "features", "pending": pending_features},
                    )
                    queued, forced_exit = await _guarded_queue(
                        "features",
                        queue_tracks_for_features,
                        limit=200,
                        stall_recovery=True,
                    )
                    if forced_exit:
                        break
                    if queued == 0 and pending_features > 0:
                        progress.set_forced_exit_reason("features", "stalled_no_queueable_tracks")
                        logger.warning(
                            f"Cannot queue more features but {pending_features} "
                            f"still pending - exiting to avoid infinite loop"
                        )
                        break
                    last_features_progress_time = time.time()

                # Queue more tracks for feature extraction when queue might be low
                # (the queue_tracks_for_features function handles deduplication)
                if pending_features > 0:
                    _, forced_exit = await _guarded_queue(
                        "features",
                        queue_tracks_for_features,
                        limit=100,
                    )
                    if forced_exit:
                        break

                progress.set_features(
                    analyzed=features_done,
                    pending=pending_features,
                    total=total_tracks,
                    scan_stats=scan_stats,
                )

                await asyncio.sleep(2)

            # Phase 3b: Embedding generation (if enabled)
            from app.services.analysis import get_analysis_capabilities
            caps = get_analysis_capabilities()
            embeddings_enabled = caps["embeddings_enabled"]

            analyzed_count = features_done

            if embeddings_enabled:
                # Timeout and stall detection for embedding loop
                embedding_start_time = time.time()
                max_embedding_duration = 4 * 60 * 60  # 4 hours max for entire embedding phase
                stall_threshold = 5 * 60  # 5 minutes without progress = stalled
                last_progress_time = time.time()
                last_embeddings_done = 0
                failure_cutoff = utcnow() - timedelta(hours=24)

                while True:
                    async with local_session_maker() as db:
                        from app.db.models import TrackAnalysis

                        # Count tracks with current embeddings
                        embeddings_success_result = await db.execute(
                            select(func.count(TrackAnalysis.id)).where(
                                and_(
                                    TrackAnalysis.features_version >= FEATURES_VERSION,
                                    TrackAnalysis.embedding_version >= EMBEDDING_VERSION,
                                )
                            )
                        )
                        embeddings_success = embeddings_success_result.scalar() or 0

                        # Count tracks with recent embedding failures (within 24h)
                        # These count as "done" for progress purposes
                        embeddings_failed_result = await db.execute(
                            select(func.count(TrackAnalysis.id)).where(
                                and_(
                                    TrackAnalysis.features_version >= FEATURES_VERSION,
                                    TrackAnalysis.embedding_version < EMBEDDING_VERSION,
                                    TrackAnalysis.embedding_failed_at.is_not(None),
                                    TrackAnalysis.embedding_failed_at >= failure_cutoff,
                                )
                            )
                        )
                        embeddings_failed = embeddings_failed_result.scalar() or 0

                        # Total "done" = successful + recently failed
                        embeddings_done = embeddings_success + embeddings_failed

                        # Total tracks that need embeddings = all TrackAnalysis records
                        # (NOT total Track count - those without features shouldn't count yet)
                        total_result = await db.execute(
                            select(func.count(TrackAnalysis.id)).where(
                                TrackAnalysis.features_version >= FEATURES_VERSION
                            )
                        )
                        total_with_features = total_result.scalar() or 0

                        pending_embeddings = total_with_features - embeddings_done

                    # Check for timeout
                    elapsed = time.time() - embedding_start_time
                    if elapsed > max_embedding_duration:
                        logger.warning(
                            f"Embedding phase timed out after {elapsed/3600:.1f}h "
                            f"({embeddings_success} success, {embeddings_failed} failed, "
                            f"{pending_embeddings} still pending)"
                        )
                        progress.set_forced_exit_reason("embeddings", "timeout")
                        analyzed_count = embeddings_success
                        break

                    # Check for stall (no progress in stall_threshold seconds)
                    if embeddings_done > last_embeddings_done:
                        last_progress_time = time.time()
                        last_embeddings_done = embeddings_done
                    elif time.time() - last_progress_time > stall_threshold:
                        # Stalled - try queueing more aggressively
                        logger.warning(
                            f"Embedding progress stalled for {stall_threshold}s "
                            f"({pending_embeddings} still pending)"
                        )
                        record_background_event(
                            "queue_stall",
                            {"phase": "embeddings", "pending": pending_embeddings},
                        )
                        # If still no queueable tracks, exit gracefully
                        queued, forced_exit = await _guarded_queue(
                            "embeddings",
                            queue_tracks_for_embeddings,
                            limit=200,
                            stall_recovery=True,
                        )
                        if forced_exit:
                            analyzed_count = embeddings_success
                            break
                        if queued == 0 and pending_embeddings > 0:
                            progress.set_forced_exit_reason("embeddings", "stalled_no_queueable_tracks")
                            logger.warning(
                                f"Cannot queue more embeddings but {pending_embeddings} "
                                f"still pending - exiting to avoid infinite loop"
                            )
                            analyzed_count = embeddings_success
                            break
                        last_progress_time = time.time()

                    if pending_embeddings == 0:
                        analyzed_count = embeddings_success
                        break

                    # Queue more tracks for embedding generation when queue might be low
                    if pending_embeddings > 0:
                        _, forced_exit = await _guarded_queue(
                            "embeddings",
                            queue_tracks_for_embeddings,
                            limit=100,
                        )
                        if forced_exit:
                            analyzed_count = embeddings_success
                            break

                    progress.set_embeddings(
                        analyzed=embeddings_success,
                        pending=pending_embeddings,
                        total=total_with_features,
                        scan_stats=scan_stats,
                    )

                    await asyncio.sleep(2)

            # Phase 4.5: Deep backfill — populate analysis_detail for existing tracks
            # One-time cost: runs cheap section analyzers on tracks that have
            # features but no analysis_detail yet.
            backfill_start = time.time()
            backfill_max_duration = 8 * 60 * 60  # 8 hours
            backfill_stall_threshold = 10 * 60  # 10 minutes
            last_backfill_progress_time = time.time()
            last_backfill_done = 0

            while True:
                async with local_session_maker() as db:
                    from app.db.models import TrackAnalysis

                    # Count tracks that already have analysis_detail
                    backfill_done_result = await db.execute(
                        select(func.count(TrackAnalysis.id)).where(
                            and_(
                                TrackAnalysis.features_version >= FEATURES_VERSION,
                                TrackAnalysis.analysis_detail.is_not(None),
                            )
                        )
                    )
                    backfill_done = backfill_done_result.scalar() or 0

                    # Total tracks with current version
                    backfill_total_result = await db.execute(
                        select(func.count(TrackAnalysis.id)).where(
                            TrackAnalysis.features_version >= FEATURES_VERSION,
                        )
                    )
                    backfill_total = backfill_total_result.scalar() or 0

                    pending_backfill = backfill_total - backfill_done

                if pending_backfill == 0:
                    logger.info(
                        f"Deep backfill complete: {backfill_done}/{backfill_total}"
                    )
                    break

                elapsed = time.time() - backfill_start
                if elapsed > backfill_max_duration:
                    logger.warning(
                        f"Deep backfill timed out after {elapsed/3600:.1f}h "
                        f"({backfill_done} done, {pending_backfill} pending)"
                    )
                    progress.set_forced_exit_reason("backfill", "timeout")
                    break

                if backfill_done > last_backfill_done:
                    last_backfill_progress_time = time.time()
                    last_backfill_done = backfill_done
                elif time.time() - last_backfill_progress_time > backfill_stall_threshold:
                    record_background_event(
                        "queue_stall",
                        {"phase": "backfill", "pending": pending_backfill},
                    )
                    # Mark longest stuck tracks as skipped (likely OOM victims)
                    skipped = await _mark_crashed_tracks_as_skipped("backfill")
                    queued, forced_exit = await _guarded_queue(
                        "backfill",
                        queue_tracks_for_backfill,
                        limit=200,
                        stall_recovery=True,
                    )
                    if forced_exit:
                        break
                    if queued == 0 and skipped == 0 and pending_backfill > 0:
                        progress.set_forced_exit_reason("backfill", "stalled_no_queueable_tracks")
                        logger.warning(
                            f"Backfill stalled with {pending_backfill} pending"
                        )
                        break
                    last_backfill_progress_time = time.time()

                if pending_backfill > 0:
                    _, forced_exit = await _guarded_queue(
                        "backfill",
                        queue_tracks_for_backfill,
                        limit=100,
                    )
                    if forced_exit:
                        break

                # Report as features phase since it's populating analysis data
                progress.set_features(
                    analyzed=backfill_done,
                    pending=pending_backfill,
                    total=backfill_total,
                    scan_stats=scan_stats,
                )

                await asyncio.sleep(5)

            # Phase 5: Melodic analysis (basic-pitch, optional)
            try:
                import basic_pitch  # noqa: F401
                melodic_available = True
            except ImportError:
                melodic_available = False
                logger.info("basic_pitch not installed — skipping melodic phase")

            if melodic_available:
                melodic_start_time = time.time()
                max_melodic_duration = 8 * 60 * 60  # 8 hours max
                melodic_stall_threshold = 10 * 60  # 10 minutes
                last_melodic_progress_time = time.time()
                last_melodic_done = 0

                while True:
                    async with local_session_maker() as db:
                        from app.db.models import TrackAnalysis

                        # Count tracks with melodic analysis done
                        melodic_done_result = await db.execute(
                            select(func.count(TrackAnalysis.id)).where(
                                and_(
                                    TrackAnalysis.features_version >= FEATURES_VERSION,
                                    TrackAnalysis.melodic_version >= MELODIC_VERSION,
                                )
                            )
                        )
                        melodic_done = melodic_done_result.scalar() or 0

                        # Total tracks eligible for melodic (have analysis_detail)
                        melodic_total_result = await db.execute(
                            select(func.count(TrackAnalysis.id)).where(
                                and_(
                                    TrackAnalysis.features_version >= FEATURES_VERSION,
                                    TrackAnalysis.analysis_detail.is_not(None),
                                )
                            )
                        )
                        melodic_total = melodic_total_result.scalar() or 0

                        pending_melodic = melodic_total - melodic_done

                    # Timeout
                    elapsed = time.time() - melodic_start_time
                    if elapsed > max_melodic_duration:
                        logger.warning(
                            f"Melodic phase timed out after {elapsed/3600:.1f}h "
                            f"({melodic_done} done, {pending_melodic} pending)"
                        )
                        progress.set_forced_exit_reason("melodic", "timeout")
                        break

                    # Stall detection
                    if melodic_done > last_melodic_done:
                        last_melodic_progress_time = time.time()
                        last_melodic_done = melodic_done
                    elif time.time() - last_melodic_progress_time > melodic_stall_threshold:
                        record_background_event(
                            "queue_stall",
                            {"phase": "melodic", "pending": pending_melodic},
                        )
                        # Mark longest stuck tracks as skipped (likely OOM victims)
                        skipped = await _mark_crashed_tracks_as_skipped("melodic")
                        queued, forced_exit = await _guarded_queue(
                            "melodic",
                            queue_tracks_for_melodic,
                            limit=200,
                            stall_recovery=True,
                        )
                        if forced_exit:
                            break
                        if queued == 0 and skipped == 0 and pending_melodic > 0:
                            progress.set_forced_exit_reason("melodic", "stalled_no_queueable_tracks")
                            logger.warning(
                                f"Melodic phase stalled with {pending_melodic} pending"
                            )
                            break
                        last_melodic_progress_time = time.time()

                    if pending_melodic == 0:
                        break

                    if pending_melodic > 0:
                        _, forced_exit = await _guarded_queue(
                            "melodic",
                            queue_tracks_for_melodic,
                            limit=100,
                        )
                        if forced_exit:
                            break

                    progress.set_melodic(
                        analyzed=melodic_done,
                        pending=pending_melodic,
                        total=melodic_total,
                        scan_stats=scan_stats,
                    )

                    await asyncio.sleep(5)

            # Phase 6: Mood tags (CLAP-based, fast — numpy only)
            from app.services.tasks.analysis_queue import queue_tracks_for_mood_tags

            mood_tags_queued = await queue_tracks_for_mood_tags(limit=200)
            if mood_tags_queued > 0:
                logger.info(f"Queued {mood_tags_queued} tracks for mood tag computation")
                # Brief wait for mood tags (they're fast — numpy dot products only)
                mood_start = time.time()
                while time.time() - mood_start < 300:  # 5 min max
                    remaining = await queue_tracks_for_mood_tags(limit=100)
                    if remaining == 0:
                        break
                    await asyncio.sleep(3)

        finally:
            await local_engine.dispose()

        # Mark complete
        progress.complete(
            new=scan_result.get("new", 0),
            updated=scan_result.get("updated", 0),
            unchanged=scan_result.get("unchanged", 0),
            relocated=scan_result.get("relocated", 0),
            marked_missing=scan_result.get("marked_missing", 0),
            recovered=scan_result.get("recovered", 0),
            analyzed=analyzed_count,
            total_tracks=analyzed_count,
        )

        logger.info(f"Library sync complete: {scan_result}, analyzed={analyzed_count}")
        return {
            "status": "success",
            **scan_result,
            "analyzed": analyzed_count,
            "phase_requeue_attempts": progress.phase_requeue_attempts,
            "phase_stall_recoveries": progress.phase_stall_recoveries,
            "phase_forced_exit_reasons": progress.phase_forced_exit_reasons,
        }

    except Exception as e:
        logger.error(f"Library sync failed: {e}", exc_info=True)
        progress.error(str(e))
        return {"status": "error", "error": str(e)}


class _SyncProgressAdapter:
    """Adapts SyncProgressReporter to the scanner's expected progress interface.

    This allows the LibraryScanner to report progress through the unified sync progress.
    """

    def __init__(self, sync_progress: SyncProgressReporter):
        self.sync_progress = sync_progress
        self.started_at = sync_progress.started_at
        self.warnings: list[str] = []

    def set_discovery(self, dirs_scanned: int, files_found: int) -> None:
        self.sync_progress.set_discovering(dirs_scanned, files_found)

    def set_processing(
        self,
        processed: int,
        total: int,
        new: int,
        updated: int,
        unchanged: int,
        current: str | None = None,
        recovered: int = 0,
    ) -> None:
        self.sync_progress.set_reading(
            processed=processed,
            total=total,
            new=new,
            updated=updated,
            unchanged=unchanged,
            current=current,
            recovered=recovered,
        )

    def set_cleanup(self, marked_missing: int, still_missing: int = 0) -> None:
        # Just update phase message, keep in reading phase
        pass

    def complete(self, *args, **kwargs) -> None:
        # Don't mark complete - sync orchestrator handles this
        pass

    def error(self, msg: str) -> None:
        self.sync_progress.error(msg)
