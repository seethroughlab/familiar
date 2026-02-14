"""Async background tasks for audio analysis and library sync.

Tasks run in-process using asyncio and ProcessPoolExecutor.
Progress is reported via Redis for frontend consumption.
"""

import asyncio
import gc
import json
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy.orm.exc import StaleDataError

from app.config import ANALYSIS_VERSION, settings
from app.services.redis_client import ResilientRedisClient, get_resilient_redis

logger = logging.getLogger(__name__)


def get_memory_mb() -> float:
    """Get current process memory usage in MB."""
    try:
        import resource
        # Get memory in KB, convert to MB
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return usage.ru_maxrss / 1024  # macOS returns bytes, Linux returns KB
    except Exception:
        return 0.0


def log_memory(label: str) -> None:
    """Log current memory usage with a label."""
    mem_mb = get_memory_mb()
    logger.info(f"[MEMORY] {label}: {mem_mb:.1f} MB (PID {os.getpid()})")
    sys.stdout.flush()  # Ensure log is written before potential OOM

# Redis client for progress reporting (using resilient client for retry logic)
def get_redis() -> ResilientRedisClient:
    """Get resilient Redis client for progress updates.

    The resilient client automatically retries on transient failures
    and has configured socket timeouts.
    """
    return get_resilient_redis()


# Redis keys for progress tracking
SYNC_PROGRESS_KEY = "familiar:sync:progress"
TASK_FAILURES_KEY = "familiar:task:failures"
MAX_FAILURES_STORED = 50


def _record_task_failure(task_name: str, error: str, track_info: str | None = None) -> None:
    """Record a task failure in Redis for UI visibility."""
    try:
        r = get_redis()
        failure = json.dumps({
            "task": task_name,
            "error": error,
            "track": track_info,
            "timestamp": datetime.now().isoformat(),
        })
        r.lpush(TASK_FAILURES_KEY, failure)
        r.ltrim(TASK_FAILURES_KEY, 0, MAX_FAILURES_STORED - 1)
        r.expire(TASK_FAILURES_KEY, 86400)  # 24 hour expiry
    except Exception as e:
        logger.warning(f"Could not record task failure: {e}")


def get_recent_failures(limit: int = 10) -> list[dict[str, Any]]:
    """Get recent task failures from Redis."""
    try:
        r = get_redis()
        failures: list[bytes] = r.lrange(TASK_FAILURES_KEY, 0, limit - 1)  # type: ignore[assignment]
        return [json.loads(f) for f in failures]
    except Exception:
        return []


def clear_task_failures() -> None:
    """Clear all task failures from Redis."""
    try:
        r = get_redis()
        r.delete(TASK_FAILURES_KEY)
    except Exception:
        pass


# ============================================================================
# Unified Library Sync
# ============================================================================


class SyncProgressReporter:
    """Reports unified sync progress to Redis for API consumption.

    This class provides a single progress view that encompasses:
    - File discovery (finding audio files)
    - Metadata reading (extracting tags from files)
    - Audio analysis (feature extraction, embeddings)
    """

    def __init__(self):
        self.redis = get_redis()
        self.started_at = datetime.now().isoformat()
        self.errors: list[str] = []
        self._update({
            "status": "running",
            "phase": "starting",
            "phase_message": "Starting library sync...",
            "files_discovered": 0,
            "files_processed": 0,
            "files_total": 0,
            "new_tracks": 0,
            "updated_tracks": 0,
            "unchanged_tracks": 0,
            "relocated_tracks": 0,
            "marked_missing": 0,
            "recovered": 0,
            "tracks_analyzed": 0,
            "tracks_pending_analysis": 0,
            "tracks_total": 0,
            "analysis_percent": 0,
            "current_item": None,
            "started_at": self.started_at,
            "last_heartbeat": datetime.now().isoformat(),
            "errors": [],
        })

    def _update(self, data: dict[str, Any]) -> None:
        """Update progress in Redis with heartbeat."""
        data["last_heartbeat"] = datetime.now().isoformat()
        data["errors"] = self.errors
        self.redis.set(SYNC_PROGRESS_KEY, json.dumps(data), ex=3600)

    def set_discovering(self, dirs_scanned: int, files_found: int) -> None:
        """Phase 1: File discovery."""
        self._update({
            "status": "running",
            "phase": "discovering",
            "phase_message": f"Discovering files... ({dirs_scanned} dirs, {files_found} files)",
            "files_discovered": files_found,
            "files_processed": 0,
            "files_total": 0,
            "new_tracks": 0,
            "updated_tracks": 0,
            "unchanged_tracks": 0,
            "relocated_tracks": 0,
            "marked_missing": 0,
            "recovered": 0,
            "tracks_analyzed": 0,
            "tracks_pending_analysis": 0,
            "tracks_total": 0,
            "analysis_percent": 0,
            "current_item": None,
            "started_at": self.started_at,
        })

    def set_reading(
        self,
        processed: int,
        total: int,
        new: int,
        updated: int,
        unchanged: int,
        current: str | None = None,
        recovered: int = 0,
    ) -> None:
        """Phase 2: Reading metadata from files."""
        pct = int(processed / total * 100) if total > 0 else 0
        self._update({
            "status": "running",
            "phase": "reading",
            "phase_message": f"Reading metadata... {processed}/{total} ({pct}%)",
            "files_discovered": total,
            "files_processed": processed,
            "files_total": total,
            "new_tracks": new,
            "updated_tracks": updated,
            "unchanged_tracks": unchanged,
            "relocated_tracks": 0,
            "marked_missing": 0,
            "recovered": recovered,
            "tracks_analyzed": 0,
            "tracks_pending_analysis": 0,
            "tracks_total": 0,
            "analysis_percent": 0,
            "current_item": current,
            "started_at": self.started_at,
        })

    def set_features(
        self,
        analyzed: int,
        pending: int,
        total: int,
        scan_stats: dict[str, int] | None = None,
    ) -> None:
        """Phase 3: Feature extraction (librosa, artwork, AcoustID)."""
        pct = int(analyzed / total * 100) if total > 0 else 0
        stats = scan_stats or {}

        self._update({
            "status": "running",
            "phase": "features",
            "phase_message": f"Extracting features... {analyzed}/{total} ({pct}%)",
            "files_discovered": stats.get("files_total", 0),
            "files_processed": stats.get("files_total", 0),
            "files_total": stats.get("files_total", 0),
            "new_tracks": stats.get("new_tracks", 0),
            "updated_tracks": stats.get("updated_tracks", 0),
            "unchanged_tracks": stats.get("unchanged_tracks", 0),
            "relocated_tracks": stats.get("relocated_tracks", 0),
            "marked_missing": stats.get("marked_missing", 0),
            "recovered": stats.get("recovered", 0),
            "tracks_analyzed": analyzed,
            "tracks_pending_analysis": pending,
            "tracks_total": total,
            "analysis_percent": pct,
            "current_item": None,
            "started_at": self.started_at,
        })

    def set_embeddings(
        self,
        analyzed: int,
        pending: int,
        total: int,
        scan_stats: dict[str, int] | None = None,
    ) -> None:
        """Phase 4: Embedding generation (CLAP model)."""
        pct = int(analyzed / total * 100) if total > 0 else 0
        stats = scan_stats or {}

        self._update({
            "status": "running",
            "phase": "embeddings",
            "phase_message": f"Generating embeddings... {analyzed}/{total} ({pct}%)",
            "files_discovered": stats.get("files_total", 0),
            "files_processed": stats.get("files_total", 0),
            "files_total": stats.get("files_total", 0),
            "new_tracks": stats.get("new_tracks", 0),
            "updated_tracks": stats.get("updated_tracks", 0),
            "unchanged_tracks": stats.get("unchanged_tracks", 0),
            "relocated_tracks": stats.get("relocated_tracks", 0),
            "marked_missing": stats.get("marked_missing", 0),
            "recovered": stats.get("recovered", 0),
            "tracks_analyzed": analyzed,
            "tracks_pending_analysis": pending,
            "tracks_total": total,
            "analysis_percent": pct,
            "current_item": None,
            "started_at": self.started_at,
        })

    def complete(
        self,
        new: int = 0,
        updated: int = 0,
        unchanged: int = 0,
        relocated: int = 0,
        marked_missing: int = 0,
        recovered: int = 0,
        analyzed: int = 0,
        total_tracks: int = 0,
    ) -> None:
        """Mark sync as complete."""
        self._update({
            "status": "completed",
            "phase": "complete",
            "phase_message": f"Complete: {new} new, {updated} updated, {analyzed} analyzed",
            "files_discovered": 0,
            "files_processed": 0,
            "files_total": 0,
            "new_tracks": new,
            "updated_tracks": updated,
            "unchanged_tracks": unchanged,
            "relocated_tracks": relocated,
            "marked_missing": marked_missing,
            "recovered": recovered,
            "tracks_analyzed": analyzed,
            "tracks_pending_analysis": 0,
            "tracks_total": total_tracks,
            "analysis_percent": 100 if total_tracks > 0 else 0,
            "current_item": None,
            "started_at": self.started_at,
        })

    def error(self, msg: str) -> None:
        """Mark sync as failed."""
        self.errors.append(msg)
        self._update({
            "status": "error",
            "phase": "error",
            "phase_message": msg,
            "files_discovered": 0,
            "files_processed": 0,
            "files_total": 0,
            "new_tracks": 0,
            "updated_tracks": 0,
            "unchanged_tracks": 0,
            "relocated_tracks": 0,
            "marked_missing": 0,
            "recovered": 0,
            "tracks_analyzed": 0,
            "tracks_pending_analysis": 0,
            "tracks_total": 0,
            "analysis_percent": 0,
            "current_item": None,
            "started_at": self.started_at,
        })


def get_sync_progress() -> dict[str, Any] | None:
    """Get current sync progress from Redis."""
    try:
        r = get_redis()
        data: bytes | None = r.get(SYNC_PROGRESS_KEY)  # type: ignore[assignment]
        if data:
            return json.loads(data)
    except Exception as e:
        logger.error(f"Failed to get sync progress: {e}")
    return None


def clear_sync_progress() -> None:
    """Clear sync progress from Redis."""
    try:
        r = get_redis()
        r.delete(SYNC_PROGRESS_KEY)
    except Exception as e:
        logger.error(f"Failed to clear sync progress: {e}")


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
    import asyncio
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
    import asyncio

    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.db.models import Track

    progress = SyncProgressReporter()

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
            # Phase 3a: Feature extraction
            # Wait for all tracks to have features extracted
            while True:
                async with local_session_maker() as db:
                    total_result = await db.execute(select(func.count(Track.id)))
                    total_tracks = total_result.scalar() or 0

                    analyzed_result = await db.execute(
                        select(func.count(Track.id)).where(
                            Track.analysis_version >= ANALYSIS_VERSION
                        )
                    )
                    features_done = analyzed_result.scalar() or 0
                    pending_features = total_tracks - features_done

                if pending_features == 0:
                    break

                # Queue more tracks for feature extraction when queue might be low
                # Always queue if: first iteration OR progress stalled OR making progress
                # (the queue_tracks_for_features function handles deduplication)
                if pending_features > 0:
                    await queue_tracks_for_features(limit=100)

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
                failure_cutoff = datetime.utcnow() - timedelta(hours=24)

                while True:
                    async with local_session_maker() as db:
                        from app.db.models import TrackAnalysis

                        # Count tracks with successful embeddings
                        embeddings_success_result = await db.execute(
                            select(func.count(TrackAnalysis.id)).where(
                                and_(
                                    TrackAnalysis.version >= ANALYSIS_VERSION,
                                    TrackAnalysis.embedding.is_not(None),
                                )
                            )
                        )
                        embeddings_success = embeddings_success_result.scalar() or 0

                        # Count tracks with recent embedding failures (within 24h)
                        # These count as "done" for progress purposes
                        embeddings_failed_result = await db.execute(
                            select(func.count(TrackAnalysis.id)).where(
                                and_(
                                    TrackAnalysis.version >= ANALYSIS_VERSION,
                                    TrackAnalysis.embedding.is_(None),
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
                                TrackAnalysis.version >= ANALYSIS_VERSION
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
                        # If still no queueable tracks, exit gracefully
                        queued = await queue_tracks_for_embeddings(limit=200)
                        if queued == 0 and pending_embeddings > 0:
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
                        await queue_tracks_for_embeddings(limit=100)

                    progress.set_embeddings(
                        analyzed=embeddings_success,
                        pending=pending_embeddings,
                        total=total_with_features,
                        scan_stats=scan_stats,
                    )

                    await asyncio.sleep(2)

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
        return {"status": "success", **scan_result, "analyzed": analyzed_count}

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


def run_track_features(track_id: str) -> dict[str, Any]:
    """Extract audio features for a track - runs in subprocess via ProcessPoolExecutor.

    Phase 1 of analysis: artwork, librosa features, AcoustID, MusicBrainz.
    This is separated from embedding extraction to reduce peak memory usage.
    Each phase runs in its own subprocess that exits after completion.

    External Features Lookup:
    Before running expensive librosa analysis, checks if pre-computed features
    are available from external services (e.g., ReccoBeats via Spotify track ID).
    """
    # Configure logging for subprocess (spawned processes don't inherit parent's config)
    import asyncio
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s',
        force=True,  # Override any existing config
    )

    from sqlalchemy import select

    from app.db.models import SpotifyFavorite, Track, TrackAnalysis
    from app.db.session import sync_session_maker
    from app.services.analysis import (
        AnalysisError,
        extract_features,
        generate_fingerprint,
        identify_track,
    )
    from app.services.app_settings import get_app_settings_service
    from app.services.artwork import extract_and_save_artwork
    from app.services.community_cache import get_community_cache_service
    from app.services.external_features import get_external_features_service

    log_memory("features_start")

    track_info = None
    try:
        with sync_session_maker() as db:
            result = db.execute(
                select(Track).where(Track.id == UUID(track_id))
            )
            track = result.scalar_one_or_none()

            if not track:
                return {"error": f"Track not found: {track_id}", "permanent": True}

            track_info = f"{track.artist} - {track.title}"
            file_path = Path(track.file_path)

            if not file_path.exists():
                # Mark as analyzed so it won't be re-queued (file is missing)
                track.analysis_version = ANALYSIS_VERSION
                track.analyzed_at = datetime.utcnow()
                track.analysis_error = "File not found"
                db.commit()
                return {"error": f"File not found: {track.file_path}", "permanent": True}

            # Skip tracks outside the "normal song" duration range
            # - Too short (<30s): intros, sound effects, samples
            # - Too long (>15min): DJ mixes, podcasts, audiobooks
            MIN_ANALYSIS_DURATION = 30  # seconds
            MAX_ANALYSIS_DURATION = 15 * 60  # 15 minutes
            if track.duration_seconds:
                skip_reason = None
                if track.duration_seconds < MIN_ANALYSIS_DURATION:
                    skip_reason = f"Track too short ({int(track.duration_seconds)}s)"
                elif track.duration_seconds > MAX_ANALYSIS_DURATION:
                    duration_mins = int(track.duration_seconds / 60)
                    skip_reason = f"Track too long ({duration_mins} min)"

                if skip_reason:
                    # Mark as analyzed so it won't be re-queued
                    track.analysis_version = ANALYSIS_VERSION
                    track.analyzed_at = datetime.utcnow()
                    track.analysis_error = skip_reason
                    db.commit()
                    return {
                        "error": skip_reason,
                        "status": "skipped",
                        "permanent": True,
                    }

            logger.info(f"Extracting features: {track.title} by {track.artist}")

            # Extract and save artwork
            artwork_hash = extract_and_save_artwork(
                file_path,
                artist=track.artist,
                album=track.album,
            )
            log_memory("after_artwork")

            # Generate AcoustID fingerprint first (needed for community cache)
            acoustid_fingerprint = None
            fp_result = generate_fingerprint(file_path)
            if fp_result:
                _, acoustid_fingerprint = fp_result

            # Try external feature lookup first (ReccoBeats via Spotify ID)
            features: dict[str, Any] = {}
            features_source = "local"
            app_settings = get_app_settings_service().get()

            if app_settings.external_features_enabled:
                # Look up Spotify track ID from SpotifyFavorite
                spotify_fav_result = db.execute(
                    select(SpotifyFavorite.spotify_track_id)
                    .where(SpotifyFavorite.matched_track_id == track.id)
                )
                spotify_fav = spotify_fav_result.scalar_one_or_none()

                if spotify_fav:
                    logger.info(f"Looking up external features for Spotify ID: {spotify_fav}")
                    try:
                        ext_service = get_external_features_service()
                        ext_features = asyncio.run(
                            ext_service.lookup_features(spotify_track_id=spotify_fav)
                        )
                        if ext_features:
                            # Convert ExternalFeatures to our features dict format
                            features = {
                                "bpm": ext_features.bpm,
                                "key": ext_features.key,
                                "energy": ext_features.energy,
                                "danceability": ext_features.danceability,
                                "valence": ext_features.valence,
                                "acousticness": ext_features.acousticness,
                                "instrumentalness": ext_features.instrumentalness,
                                "speechiness": ext_features.speechiness,
                                "liveness": ext_features.liveness,
                                "loudness": ext_features.loudness,
                            }
                            # Remove None values
                            features = {k: v for k, v in features.items() if v is not None}
                            features_source = ext_features.source  # "reccobeats"
                            logger.info(
                                f"External features found from {features_source}: "
                                f"BPM={ext_features.bpm}, Key={ext_features.key}"
                            )
                    except Exception as e:
                        logger.warning(f"External feature lookup failed: {e}")

            # Try community cache for features if no external features found
            if not features.get("bpm") and app_settings.community_cache_enabled and acoustid_fingerprint:
                try:
                    cache_service = get_community_cache_service(
                        cache_url=app_settings.community_cache_url
                    )
                    cached_features = asyncio.run(
                        cache_service.lookup_features(acoustid_fingerprint)
                    )
                    if cached_features:
                        features = {
                            "bpm": cached_features.bpm,
                            "key": cached_features.key,
                            "energy": cached_features.energy,
                            "danceability": cached_features.danceability,
                            "valence": cached_features.valence,
                            "acousticness": cached_features.acousticness,
                            "instrumentalness": cached_features.instrumentalness,
                            "speechiness": cached_features.speechiness,
                            "liveness": cached_features.liveness,
                            "loudness": cached_features.loudness,
                        }
                        # Remove None values
                        features = {k: v for k, v in features.items() if v is not None}
                        features_source = "community_cache"
                        logger.info(
                            f"Community cache features hit for {track.title} "
                            f"(contributed by {cached_features.contributor_count} users)"
                        )
                except Exception as e:
                    logger.warning(f"Community cache features lookup failed: {e}")

            # Fall back to local librosa extraction if no external/cached features
            computed_locally = False
            if not features.get("bpm"):
                features = extract_features(file_path)
                features_source = "local"
                computed_locally = True
                gc.collect()

            # Contribute features to community cache if computed locally
            if (
                computed_locally
                and app_settings.community_cache_contribute
                and acoustid_fingerprint
                and features.get("bpm")
            ):
                try:
                    cache_service = get_community_cache_service(
                        cache_url=app_settings.community_cache_url
                    )
                    asyncio.run(
                        cache_service.contribute_features(acoustid_fingerprint, features)
                    )
                except Exception as e:
                    logger.warning(f"Failed to contribute features to community cache: {e}")

            log_memory("after_features")

            # Try to identify track via AcoustID
            acoustid_metadata = None
            musicbrainz_recording_id = None
            if acoustid_fingerprint:
                id_result = identify_track(file_path)
                if id_result.get("metadata"):
                    acoustid_metadata = id_result["metadata"]
                    musicbrainz_recording_id = acoustid_metadata.get("musicbrainz_recording_id")

            # Enrich with MusicBrainz metadata
            from app.services.musicbrainz import enrich_track
            musicbrainz_metadata = enrich_track(
                title=track.title,
                artist=track.artist,
                album=track.album,
                musicbrainz_recording_id=musicbrainz_recording_id,
            )

            if musicbrainz_metadata:
                features["musicbrainz"] = musicbrainz_metadata

            log_memory("after_metadata")

            # Create or update analysis record (without embedding - that comes in phase 2)
            # Query by track_id only - NOT by version, to avoid creating duplicates
            # when ANALYSIS_VERSION is bumped
            existing = db.execute(
                select(TrackAnalysis)
                .where(TrackAnalysis.track_id == track.id)
                .order_by(TrackAnalysis.version.desc())  # Get newest version if multiple
            )
            existing_analysis = existing.scalar_one_or_none()

            if existing_analysis:
                existing_analysis.features = features
                existing_analysis.features_source = features_source
                existing_analysis.acoustid = acoustid_fingerprint
                existing_analysis.version = ANALYSIS_VERSION  # Update version
                # Keep existing embedding if present
            else:
                analysis = TrackAnalysis(
                    track_id=track.id,
                    version=ANALYSIS_VERSION,
                    features=features,
                    features_source=features_source,
                    embedding=None,  # Embedding extracted in phase 2
                    acoustid=acoustid_fingerprint,
                )
                db.add(analysis)

            # Update track analysis status
            track.analysis_version = ANALYSIS_VERSION
            track.analyzed_at = datetime.utcnow()
            track.analysis_error = None
            track.analysis_failed_at = None

            db.commit()
            log_memory("after_commit")

            logger.info(
                f"Features extracted for {track.title} (source={features_source}): "
                f"BPM={features.get('bpm')}, Key={features.get('key')}"
            )

            gc.collect()
            log_memory("features_end")

            return {
                "track_id": track_id,
                "file_path": str(file_path),
                "status": "success",
                "phase": "features",
                "artwork_extracted": artwork_hash is not None,
                "features_extracted": bool(features.get("bpm")),
                "features_source": features_source,
                "bpm": features.get("bpm"),
                "key": features.get("key"),
            }

    except AnalysisError as e:
        error_msg = str(e)[:500]
        logger.error(f"Feature extraction error for {track_id}: {error_msg}")
        _record_task_failure("extract_features", error_msg, track_info)

        # Mark track as failed in DB so it won't be retried immediately
        try:
            with sync_session_maker() as db:
                result = db.execute(
                    select(Track).where(Track.id == UUID(track_id))
                )
                track = result.scalar_one_or_none()
                if track:
                    track.analysis_error = error_msg
                    track.analysis_failed_at = datetime.utcnow()
                    # Mark as "analyzed" so sync loop doesn't block on failed tracks
                    track.analysis_version = ANALYSIS_VERSION
                    track.analyzed_at = datetime.utcnow()
                    db.commit()
        except Exception as db_error:
            logger.warning(f"Could not record analysis failure to DB: {db_error}")

        return {"error": error_msg, "status": "failed", "permanent": True}
    except StaleDataError:
        logger.info(f"Track {track_id} was deleted during analysis, skipping")
        return {"status": "skipped", "reason": "track_deleted"}
    except Exception as e:
        error_msg = str(e)[:500]
        logger.error(f"Error extracting features for {track_id}: {error_msg}")
        _record_task_failure("extract_features", error_msg, track_info)

        try:
            with sync_session_maker() as db:
                result = db.execute(
                    select(Track).where(Track.id == UUID(track_id))
                )
                track = result.scalar_one_or_none()
                if track:
                    track.analysis_error = error_msg
                    track.analysis_failed_at = datetime.utcnow()
                    # Mark as "analyzed" so sync loop doesn't block on failed tracks
                    track.analysis_version = ANALYSIS_VERSION
                    track.analyzed_at = datetime.utcnow()
                    db.commit()
        except Exception as db_error:
            logger.warning(f"Could not record analysis failure to DB: {db_error}")

        return {"error": error_msg, "status": "failed", "permanent": True}


def _record_embedding_failure(track_id: str, error_msg: str) -> None:
    """Record embedding failure in TrackAnalysis so sync loop doesn't get stuck.

    This is called from exception handlers to mark embeddings as failed,
    allowing the sync progress query to count them as "done" (either success or failed).
    """
    from sqlalchemy import select

    from app.db.models import TrackAnalysis
    from app.db.session import sync_session_maker

    try:
        with sync_session_maker() as db:
            result = db.execute(
                select(TrackAnalysis)
                .where(TrackAnalysis.track_id == UUID(track_id))
                .order_by(TrackAnalysis.version.desc())
            )
            analysis = result.scalar_one_or_none()

            if analysis:
                analysis.embedding_error = error_msg[:500]
                analysis.embedding_failed_at = datetime.utcnow()
                db.commit()
                logger.info(f"Recorded embedding failure for track {track_id}")
            else:
                logger.warning(f"No TrackAnalysis record to record embedding failure for {track_id}")
    except Exception as db_error:
        logger.warning(f"Could not record embedding failure to DB: {db_error}")


def run_track_embedding(track_id: str) -> dict[str, Any]:
    """Extract CLAP embedding for a track - runs in subprocess via ProcessPoolExecutor.

    Phase 2 of analysis: CLAP embedding for similarity search.
    This runs in a separate subprocess from feature extraction to reduce peak memory.
    The CLAP model uses ~2-3GB of memory, so isolating it prevents OOM kills.

    Community Cache:
    Before running expensive CLAP extraction, checks if embedding is available in
    the community cache (keyed by AcoustID fingerprint hash). If contribution is
    enabled and we compute locally, the embedding is shared with other users.
    """
    import asyncio
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s',
        force=True,
    )

    from sqlalchemy import select

    from app.db.models import Track, TrackAnalysis
    from app.db.session import sync_session_maker
    from app.services.analysis import AnalysisError, extract_embedding
    from app.services.app_settings import get_app_settings_service
    from app.services.community_cache import get_community_cache_service

    log_memory("embedding_start")

    try:
        with sync_session_maker() as db:
            result = db.execute(
                select(Track).where(Track.id == UUID(track_id))
            )
            track = result.scalar_one_or_none()

            if not track:
                return {"error": f"Track not found: {track_id}", "permanent": True}

            file_path = Path(track.file_path)

            if not file_path.exists():
                return {"error": f"File not found: {track.file_path}", "permanent": True}

            logger.info(f"Extracting embedding: {track.title} by {track.artist}")

            # Get app settings for community cache
            app_settings = get_app_settings_service().get()
            embedding_source = "local"
            embedding: list[float] | None = None
            acoustid_fingerprint: str | None = None

            # Get the analysis record to get AcoustID fingerprint
            analysis_result = db.execute(
                select(TrackAnalysis)
                .where(TrackAnalysis.track_id == track.id)
                .order_by(TrackAnalysis.version.desc())
            )
            existing_analysis = analysis_result.scalar_one_or_none()

            if existing_analysis and existing_analysis.acoustid:
                acoustid_fingerprint = existing_analysis.acoustid

            # Try community cache first if enabled
            if app_settings.community_cache_enabled and acoustid_fingerprint:
                try:
                    cache_service = get_community_cache_service(
                        cache_url=app_settings.community_cache_url
                    )
                    cached = asyncio.run(
                        cache_service.lookup(acoustid_fingerprint)
                    )
                    if cached:
                        embedding = cached.embedding
                        embedding_source = "community_cache"
                        logger.info(
                            f"Community cache hit for {track.title} "
                            f"(contributed by {cached.contributor_count} users)"
                        )
                except Exception as e:
                    logger.warning(f"Community cache lookup failed: {e}")

            # Fall back to local CLAP extraction if no cache hit
            if embedding is None:
                embedding = extract_embedding(file_path)
                embedding_source = "local"
                gc.collect()

                # Contribute to community cache if enabled and we have a fingerprint
                if (
                    embedding is not None
                    and app_settings.community_cache_contribute
                    and acoustid_fingerprint
                ):
                    try:
                        cache_service = get_community_cache_service(
                            cache_url=app_settings.community_cache_url
                        )
                        asyncio.run(
                            cache_service.contribute(acoustid_fingerprint, embedding)
                        )
                    except Exception as e:
                        logger.debug(f"Community cache contribution failed: {e}")

            log_memory("after_embedding")

            if embedding is None:
                # Embeddings disabled or failed - not an error, just skip
                logger.info(f"No embedding generated for {track.title} (CLAP disabled or failed)")
                return {
                    "track_id": track_id,
                    "status": "success",
                    "phase": "embedding",
                    "embedding_generated": False,
                }

            # Update the existing analysis record with embedding
            # We already have existing_analysis from earlier fingerprint lookup
            if existing_analysis:
                existing_analysis.embedding = embedding
                existing_analysis.embedding_source = embedding_source
                existing_analysis.version = ANALYSIS_VERSION  # Ensure version is current
                db.commit()
                logger.info(f"Embedding saved for {track.title} (source={embedding_source})")
            else:
                # No analysis record yet - this shouldn't happen if phase 1 ran first
                logger.warning(f"No analysis record found for {track_id}, skipping embedding save")
                return {
                    "track_id": track_id,
                    "status": "skipped",
                    "reason": "no_analysis_record",
                    "embedding_generated": True,
                }

            gc.collect()
            log_memory("embedding_end")

            return {
                "track_id": track_id,
                "status": "success",
                "phase": "embedding",
                "embedding_generated": True,
                "embedding_source": embedding_source,
            }

    except AnalysisError as e:
        error_msg = str(e)[:500]
        logger.error(f"Embedding extraction error for {track_id}: {error_msg}")
        # Record embedding failure in TrackAnalysis so sync doesn't get stuck
        _record_embedding_failure(track_id, error_msg)
        return {"error": error_msg, "status": "partial", "phase": "embedding"}
    except StaleDataError:
        logger.info(f"Track {track_id} was deleted during embedding, skipping")
        return {"status": "skipped", "reason": "track_deleted"}
    except Exception as e:
        error_msg = str(e)[:500]
        logger.error(f"Error extracting embedding for {track_id}: {error_msg}")
        # Record embedding failure in TrackAnalysis so sync doesn't get stuck
        _record_embedding_failure(track_id, error_msg)
        return {"error": error_msg, "status": "partial", "phase": "embedding"}


def run_track_analysis(track_id: str) -> dict[str, Any]:
    """Analyze a single track - runs in subprocess via ProcessPoolExecutor.

    DEPRECATED: This function is kept for backwards compatibility.
    New code should use run_track_features + run_track_embedding separately.

    This combined function may cause OOM on memory-constrained systems.
    """
    # Run features first
    result = run_track_features(track_id)
    if result.get("status") != "success":
        return result

    # Then run embedding in same process (not ideal for memory, but maintains compatibility)
    embedding_result = run_track_embedding(track_id)

    # Merge results
    return {
        **result,
        "embedding_generated": embedding_result.get("embedding_generated", False),
    }


async def queue_tracks_for_features(limit: int = 500) -> int:
    """Queue tracks that need feature extraction (Phase 1).

    This includes tracks that haven't been analyzed or have old analysis version.
    Returns the number of tracks queued.
    """
    from sqlalchemy import and_, or_, select

    from app.db.models import Track
    from app.db.session import async_session_maker
    from app.services.background import get_background_manager

    queued = 0
    async with async_session_maker() as db:
        failure_cutoff = datetime.utcnow() - timedelta(hours=24)

        # Find tracks that need analysis:
        # 1. Never analyzed (version=0, analyzed_at=NULL)
        # 2. Outdated analysis version
        # 3. Previously failed but 24h has passed (retry window open)
        result = await db.execute(
            select(Track.id)
            .where(
                or_(
                    # Never analyzed or outdated version
                    and_(
                        or_(
                            Track.analysis_version == 0,
                            Track.analysis_version < ANALYSIS_VERSION,
                            Track.analyzed_at.is_(None),
                        ),
                        or_(
                            Track.analysis_failed_at.is_(None),
                            Track.analysis_failed_at < failure_cutoff,
                        ),
                    ),
                    # Previously failed, 24h passed - retry
                    and_(
                        Track.analysis_error.is_not(None),
                        Track.analysis_failed_at.is_not(None),
                        Track.analysis_failed_at < failure_cutoff,
                    ),
                )
            )
            .limit(limit)
        )
        track_ids = [str(row[0]) for row in result.fetchall()]

    if track_ids:
        manager = get_background_manager()
        for track_id in track_ids:
            await manager.run_analysis(track_id, phase="features")
            queued += 1

    return queued


async def queue_tracks_for_embeddings(limit: int = 500) -> int:
    """Queue tracks that need embedding generation (Phase 2).

    This includes tracks with features extracted but no embedding.
    Returns the number of tracks queued.
    """
    from sqlalchemy import and_, or_, select

    from app.db.models import Track, TrackAnalysis
    from app.db.session import async_session_maker
    from app.services.app_settings import get_app_settings_service
    from app.services.background import get_background_manager

    # Skip if CLAP is disabled via settings or env var
    clap_enabled, _ = get_app_settings_service().is_clap_embeddings_enabled()
    if not clap_enabled:
        return 0

    queued = 0
    async with async_session_maker() as db:
        failure_cutoff = datetime.utcnow() - timedelta(hours=24)

        # Find tracks with analysis record but no embedding
        # Exclude tracks that recently failed embedding (within 24h) to avoid infinite retry
        result = await db.execute(
            select(Track.id)
            .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
            .where(
                and_(
                    TrackAnalysis.version >= ANALYSIS_VERSION,
                    TrackAnalysis.embedding.is_(None),
                    # Exclude recently-failed embeddings (use TrackAnalysis.embedding_failed_at)
                    or_(
                        TrackAnalysis.embedding_failed_at.is_(None),
                        TrackAnalysis.embedding_failed_at < failure_cutoff,
                    ),
                )
            )
            .limit(limit)
        )
        track_ids = [str(row[0]) for row in result.fetchall()]

    if track_ids:
        manager = get_background_manager()
        for track_id in track_ids:
            await manager.run_analysis(track_id, phase="embedding")
            queued += 1

    return queued


async def queue_unanalyzed_tracks(limit: int = 500) -> int:
    """Queue analysis for tracks that need analysis.

    DEPRECATED: Use queue_tracks_for_features() and queue_tracks_for_embeddings()
    for better memory efficiency and progress tracking.

    This function is kept for backwards compatibility and queues for full analysis.
    """
    from sqlalchemy import and_, or_, select

    from app.db.models import Track, TrackAnalysis
    from app.db.session import async_session_maker
    from app.services.analysis import get_analysis_capabilities
    from app.services.background import get_background_manager

    caps = get_analysis_capabilities()
    embeddings_enabled = caps["embeddings_enabled"]

    queued = 0
    async with async_session_maker() as db:
        failure_cutoff = datetime.utcnow() - timedelta(hours=24)

        result = await db.execute(
            select(Track.id)
            .where(
                and_(
                    or_(
                        Track.analysis_version == 0,
                        Track.analysis_version < ANALYSIS_VERSION,
                        Track.analyzed_at.is_(None),
                    ),
                    or_(
                        Track.analysis_failed_at.is_(None),
                        Track.analysis_failed_at < failure_cutoff,
                    ),
                )
            )
            .limit(limit)
        )
        track_ids = set(str(row[0]) for row in result.fetchall())

        # If embeddings are now enabled, also get tracks missing embeddings
        if embeddings_enabled and len(track_ids) < limit:
            remaining_limit = limit - len(track_ids)
            result = await db.execute(
                select(Track.id)
                .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
                .where(
                    and_(
                        TrackAnalysis.version >= ANALYSIS_VERSION,  # Must check analysis record version!
                        TrackAnalysis.embedding.is_(None),
                        Track.analysis_version >= ANALYSIS_VERSION,
                        or_(
                            Track.analysis_failed_at.is_(None),
                            Track.analysis_failed_at < failure_cutoff,
                        ),
                    )
                )
                .limit(remaining_limit)
            )
            missing_embedding_ids = set(str(row[0]) for row in result.fetchall())

            if missing_embedding_ids:
                logger.info(
                    f"Found {len(missing_embedding_ids)} tracks with missing embeddings "
                    "(embeddings now enabled)"
                )
                # Queue embedding-only tasks instead of resetting to re-analyze everything
                # This preserves existing features and just adds embeddings
                bg = get_background_manager()
                for track_id in missing_embedding_ids:
                    await bg.run_analysis(track_id, phase="embedding")
                    queued += 1
                # Don't add to track_ids - we already queued them for embedding-only

        if not track_ids:
            logger.info("No tracks need analysis")
            return queued

        # Queue each track for analysis
        bg = get_background_manager()
        for track_id in track_ids:
            await bg.run_analysis(track_id)
            queued += 1

        logger.info(f"Queued {queued} tracks for analysis")

    return queued


# ============================================================================
# Spotify Sync
# ============================================================================

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
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.db.models import (
        ExternalTrack,
        ExternalTrackSource,
        ProfileExternalFavorite,
        ProfileFavorite,
        SpotifyFavorite,
        SpotifyProfile,
    )
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

    local_engine = create_async_engine(
        settings.database_url,
        echo=False,
        future=True,
    )
    local_session_maker = async_sessionmaker(
        local_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

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


# ============================================================================
# New Releases Check
# ============================================================================

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

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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

    local_engine = create_async_engine(
        settings.database_url,
        echo=False,
        future=True,
    )
    local_session_maker = async_sessionmaker(
        local_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

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

                        await asyncio.sleep(2.0)  # Rate limiting: ~4s per artist with throttled API calls

                    except SpotifyRateLimitError as e:
                        logger.warning(
                            f"Spotify rate limited during new releases check "
                            f"(retry_after={e.retry_after}s), disabling Spotify for remainder"
                        )
                        spotify_service = None  # Fall back to MusicBrainz for remaining artists
                    except Exception as e:
                        logger.warning(f"Spotify lookup failed for {artist_name}: {e}")

                # Fall back to MusicBrainz
                if not releases_for_artist:
                    try:
                        mb_id_to_use = mb_artist_id
                        if not mb_id_to_use:
                            mb_result = search_artist(artist_name)
                            if mb_result and mb_result.get("score", 0) >= 80:
                                mb_id_to_use = mb_result["musicbrainz_artist_id"]

                        if mb_id_to_use:
                            recent = get_artist_releases_recent(mb_id_to_use, days_back=days_back)
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

                await service.update_artist_cache(
                    artist_normalized=normalized,
                    musicbrainz_id=mb_artist_id,
                    spotify_id=spotify_artist_id,
                )

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

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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

    local_engine = create_async_engine(
        settings.database_url,
        echo=False,
        future=True,
    )
    local_session_maker = async_sessionmaker(
        local_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

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
                        mb_result = search_artist(artist_name)
                        if mb_result and mb_result.get("score", 0) >= 80:
                            mb_id_to_use = mb_result["musicbrainz_artist_id"]

                    if mb_id_to_use:
                        recent = get_artist_releases_recent(mb_id_to_use, days_back=days_back)
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

                # Update cache for this artist
                await service.update_artist_cache(
                    artist_normalized=normalized,
                    musicbrainz_id=mb_id_to_use,
                )

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


# ============================================================================
# Metadata Enrichment
# ============================================================================


async def run_track_enrichment(track_id: str) -> dict[str, Any]:
    """Enrich a track's metadata from MusicBrainz/AcoustID.

    This runs asynchronously as a background task.

    Actions:
    1. Look up track via AcoustID fingerprint
    2. Fetch full metadata from MusicBrainz
    3. Download album art from Cover Art Archive
    4. Write metadata to ID3 tags (respecting overwrite setting)
    5. Embed artwork in file
    6. Save artwork to data/art/
    7. Update database
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.db.models import Track
    from app.services.analysis import lookup_acoustid
    from app.services.app_settings import get_app_settings_service
    from app.services.artwork import compute_album_hash, save_artwork
    from app.services.import_service import embed_artwork
    from app.services.metadata_enrichment import (
        fetch_cover_art,
        needs_enrichment,
        write_metadata_to_file,
    )
    from app.services.musicbrainz import enrich_track

    result: dict[str, Any] = {
        "track_id": track_id,
        "status": "skipped",
        "fields_updated": [],
        "artwork_saved": False,
        "tags_written": False,
    }

    # Get settings
    app_settings = get_app_settings_service().get()
    overwrite_existing = app_settings.enrich_overwrite_existing

    local_engine = create_async_engine(settings.database_url, echo=False)
    local_session_maker = async_sessionmaker(
        local_engine, class_=AsyncSession, expire_on_commit=False
    )

    try:
        async with local_session_maker() as db:
            stmt = select(Track).where(Track.id == UUID(track_id))
            query_result = await db.execute(stmt)
            track = query_result.scalar_one_or_none()

            if not track:
                return {"status": "error", "error": "Track not found", **result}

            file_path = Path(track.file_path)
            if not file_path.exists():
                return {"status": "error", "error": "File not found", **result}

            # Check if enrichment is still needed
            if not needs_enrichment(track):
                return {"status": "skipped", "reason": "metadata complete", **result}

            logger.info(f"Enriching metadata for: {track.artist} - {track.title}")

            # Step 1: Lookup via AcoustID
            musicbrainz_id = None
            try:
                acoustid_result = lookup_acoustid(file_path)
                if acoustid_result:
                    musicbrainz_id = acoustid_result.get("musicbrainz_recording_id")
            except Exception as e:
                logger.debug(f"AcoustID lookup failed: {e}")

            # Step 2: Enrich from MusicBrainz
            mb_metadata = enrich_track(
                title=track.title,
                artist=track.artist,
                album=track.album,
                musicbrainz_recording_id=musicbrainz_id,
            )

            if not mb_metadata:
                return {"status": "no_match", "error": "No MusicBrainz match found", **result}

            # Step 3: Prepare metadata updates
            updates: dict[str, Any] = {}
            file_metadata: dict[str, Any] = {}

            def should_update(field: str, db_value: Any) -> bool:
                if overwrite_existing:
                    return True
                return db_value is None or (isinstance(db_value, str) and not db_value.strip())

            if mb_metadata.get("title") and should_update("title", track.title):
                updates["title"] = mb_metadata["title"]
                file_metadata["title"] = mb_metadata["title"]

            if mb_metadata.get("artist") and should_update("artist", track.artist):
                updates["artist"] = mb_metadata["artist"]
                file_metadata["artist"] = mb_metadata["artist"]

            if mb_metadata.get("album") and should_update("album", track.album):
                updates["album"] = mb_metadata["album"]
                file_metadata["album"] = mb_metadata["album"]

            if mb_metadata.get("tags") and should_update("genre", track.genre):
                genre = mb_metadata["tags"][0] if mb_metadata["tags"] else None
                if genre:
                    updates["genre"] = genre
                    file_metadata["genre"] = genre

            if mb_metadata.get("release_date") and should_update("year", track.year):
                try:
                    year = int(mb_metadata["release_date"][:4])
                    updates["year"] = year
                    file_metadata["year"] = year
                except (ValueError, IndexError):
                    pass

            # Store MusicBrainz IDs (always update these)
            if mb_metadata.get("musicbrainz_recording_id"):
                updates["musicbrainz_track_id"] = mb_metadata["musicbrainz_recording_id"]
            if mb_metadata.get("musicbrainz_release_id"):
                updates["musicbrainz_album_id"] = mb_metadata["musicbrainz_release_id"]
            if mb_metadata.get("musicbrainz_artist_ids"):
                updates["musicbrainz_artist_id"] = mb_metadata["musicbrainz_artist_ids"][0]

            # Step 4: Fetch album art from Cover Art Archive
            release_id = mb_metadata.get("musicbrainz_release_id")
            artwork_data = None
            if release_id:
                artwork_data = await fetch_cover_art(release_id)

            # Step 5: Write ID3 tags to file
            if file_metadata:
                tags_written = write_metadata_to_file(
                    file_path, file_metadata, overwrite_existing
                )
                result["tags_written"] = tags_written

            # Step 6: Embed and save artwork
            if artwork_data:
                # Embed in file
                try:
                    embed_artwork(file_path, artwork_data)
                except Exception as e:
                    logger.warning(f"Failed to embed artwork: {e}")

                # Save to art folder
                artist_for_hash = updates.get("artist") or track.artist
                album_for_hash = updates.get("album") or track.album
                album_hash = compute_album_hash(artist_for_hash, album_for_hash)
                try:
                    save_artwork(artwork_data, album_hash)
                    result["artwork_saved"] = True
                except Exception as e:
                    logger.warning(f"Failed to save artwork: {e}")

            # Step 7: Update database
            if updates:
                for key, value in updates.items():
                    setattr(track, key, value)
                track.updated_at = datetime.utcnow()
                await db.commit()

            result["status"] = "success"
            result["fields_updated"] = list(updates.keys())

            logger.info(
                f"Enriched track {track_id}: updated {list(updates.keys())}, "
                f"artwork={'yes' if artwork_data else 'no'}"
            )

    except Exception as e:
        logger.error(f"Enrichment failed for {track_id}: {e}", exc_info=True)
        result["status"] = "error"
        result["error"] = str(e)
    finally:
        await local_engine.dispose()

    return result


async def propose_enrichment_for_track(track_id: str) -> dict[str, Any]:
    """Propose metadata enrichment for a track with incomplete metadata.

    This runs asynchronously as a background task when a track is played.
    Unlike run_track_enrichment (which directly modifies files), this creates
    a ProposedChange for the user to review.

    Actions:
    1. Check if track already has a pending proposal
    2. Look up track metadata via MusicBrainz
    3. If confident match found (>0.8), create ProposedChange
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.db.models import ChangeSource, ChangeStatus, ProposedChange, Track
    from app.services.metadata_enrichment import get_missing_fields
    from app.services.metadata_lookup import MetadataLookupService
    from app.services.proposed_changes import ProposedChangesService

    result: dict[str, Any] = {
        "track_id": track_id,
        "status": "skipped",
        "reason": None,
        "proposal_created": False,
    }

    local_engine = create_async_engine(settings.database_url, echo=False)
    local_session_maker = async_sessionmaker(
        local_engine, class_=AsyncSession, expire_on_commit=False
    )

    try:
        async with local_session_maker() as db:
            # Get the track
            stmt = select(Track).where(Track.id == UUID(track_id))
            query_result = await db.execute(stmt)
            track = query_result.scalar_one_or_none()

            if not track:
                result["reason"] = "Track not found"
                return result

            # Check if track already has a pending proposal
            existing_stmt = select(ProposedChange).where(
                ProposedChange.target_ids.contains([track_id]),
                ProposedChange.status == ChangeStatus.PENDING,
                ProposedChange.source == ChangeSource.AUTO_ENRICHMENT,
            )
            existing_result = await db.execute(existing_stmt)
            if existing_result.scalar_one_or_none():
                result["reason"] = "Pending proposal already exists"
                return result

            # Get missing fields
            missing_fields = get_missing_fields(track)
            if not missing_fields:
                result["reason"] = "No missing fields"
                return result

            # Look up metadata from MusicBrainz
            lookup_service = MetadataLookupService()

            # We need at least title and artist to look up
            title = track.title or ""
            artist = track.artist or ""
            if not title or not artist:
                result["reason"] = "Track missing title or artist for lookup"
                return result

            candidates = await lookup_service.lookup_track(
                title=title,
                artist=artist,
                album=track.album,
                limit=1,
            )

            if not candidates:
                result["reason"] = "No MusicBrainz matches found"
                return result

            best_match = candidates[0]
            if best_match.confidence < 0.8:
                result["reason"] = f"Match confidence too low ({best_match.confidence:.2f})"
                return result

            # Create proposed changes for each missing field that has a value
            service = ProposedChangesService(db)
            proposals_created = 0

            for field in missing_fields:
                new_value = best_match.metadata.get(field)
                if new_value:
                    await service.create_change(
                        change_type="metadata",
                        target_type="track",
                        target_ids=[track_id],
                        source=ChangeSource.AUTO_ENRICHMENT,
                        field=field,
                        old_value=getattr(track, field, None),
                        new_value=new_value,
                        source_detail=f"MusicBrainz: {best_match.source_id}",
                        confidence=best_match.confidence,
                        reason=f"Auto-detected missing {field} during playback",
                    )
                    proposals_created += 1

            if proposals_created > 0:
                result["status"] = "success"
                result["proposal_created"] = True
                result["fields_proposed"] = [
                    f for f in missing_fields if best_match.metadata.get(f)
                ]
                logger.info(
                    f"Created {proposals_created} enrichment proposal(s) for track {track_id}"
                )
            else:
                result["reason"] = "No enrichable fields found in MusicBrainz data"

    except Exception as e:
        logger.error(f"Auto-enrichment proposal failed for {track_id}: {e}", exc_info=True)
        result["status"] = "error"
        result["error"] = str(e)
    finally:
        await local_engine.dispose()

    return result
