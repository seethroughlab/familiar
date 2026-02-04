"""In-process background task manager using asyncio and ProcessPoolExecutor.

Key features:
1. Uses spawn-based ProcessPoolExecutor (avoids fork/OpenBLAS SIGSEGV)
2. Runs periodic tasks via APScheduler
3. Reports progress via Redis for frontend consumption
"""

import asyncio
import json
import logging
import multiprocessing as mp
import os
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any

from app.services.redis_client import ResilientRedisClient, get_resilient_redis

# Rate limiting for executor recreation to prevent runaway process spawning
EXECUTOR_RESET_COOLDOWN = 30.0  # Minimum seconds between executor resets
EXECUTOR_MAX_CONSECUTIVE_FAILURES = 5  # Max failures before giving up
EXECUTOR_AUTO_RECOVERY_DELAY = 300.0  # Auto-recover after 5 minutes of being disabled

logger = logging.getLogger(__name__)


def _analysis_worker_init() -> None:
    """Initialize analysis worker process with low priority.

    Sets nice value to 10 (lower priority) so analysis doesn't starve
    other system processes. Nice range is -20 (highest) to 19 (lowest).
    """
    try:
        os.nice(10)
        logging.info(f"Analysis worker started with nice=10 (PID {os.getpid()})")
    except Exception as e:
        logging.warning(f"Could not set nice priority: {e}")

# Force spawn context to avoid fork issues with numpy/OpenBLAS
mp_context = mp.get_context("spawn")


class BackgroundManager:
    """Manages background tasks in the API process.

    Key features:
    - ProcessPoolExecutor with spawn context (not fork) to avoid OpenBLAS crashes
    - APScheduler for periodic tasks
    - Redis for progress reporting
    - Task deduplication to prevent running multiple syncs simultaneously
    """

    def __init__(self):
        self._executor: ProcessPoolExecutor | None = None
        self._scheduler = None
        self._redis: ResilientRedisClient | None = None
        self._current_sync_task: asyncio.Task | None = None
        self._analysis_tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        # Executor rate limiting state
        self._executor_lock = asyncio.Lock()  # Protects executor reset
        self._last_executor_reset: float = 0.0
        self._consecutive_executor_failures: int = 0
        self._executor_disabled: bool = False
        self._executor_disabled_at: float = 0.0  # Timestamp when executor was disabled
        # Track current work for crash diagnostics
        self._current_track_id: str | None = None
        self._crashed_track_ids: set[str] = set()  # Tracks that have caused crashes

    @property
    def redis(self) -> ResilientRedisClient:
        """Lazy resilient Redis client with automatic retry."""
        if self._redis is None:
            self._redis = get_resilient_redis()
        return self._redis

    @property
    def executor(self) -> ProcessPoolExecutor:
        """Lazy ProcessPoolExecutor with spawn context."""
        if self._executor is None:
            self._create_executor()
        return self._executor

    def _create_executor(self) -> None:
        """Create a new ProcessPoolExecutor with spawn context."""
        # Use spawn to get clean processes (fork can inherit corrupted OpenBLAS state)
        self._executor = ProcessPoolExecutor(
            max_workers=1,  # Single worker to limit memory (CLAP model is ~1.5GB)
            mp_context=mp_context,
            initializer=_analysis_worker_init,  # Run workers at lower priority
        )
        logger.info("ProcessPoolExecutor initialized with spawn context (1 worker, nice=10)")

    def _reset_executor(self) -> bool:
        """Reset the executor after a crash. Creates a fresh process pool.

        Returns True if reset succeeded, False if rate-limited or disabled.
        """
        # Check if executor is disabled due to too many failures
        if self._executor_disabled:
            logger.error("Executor is disabled due to repeated failures - not resetting")
            return False

        # Check cooldown period
        now = time.monotonic()
        time_since_last_reset = now - self._last_executor_reset
        if time_since_last_reset < EXECUTOR_RESET_COOLDOWN:
            logger.warning(
                f"Executor reset rate-limited (last reset {time_since_last_reset:.1f}s ago, "
                f"cooldown is {EXECUTOR_RESET_COOLDOWN}s)"
            )
            return False

        # Track consecutive failures
        self._consecutive_executor_failures += 1
        if self._consecutive_executor_failures >= EXECUTOR_MAX_CONSECUTIVE_FAILURES:
            self._executor_disabled = True
            self._executor_disabled_at = time.monotonic()
            logger.error(
                f"Executor disabled after {self._consecutive_executor_failures} consecutive "
                f"failures - will auto-recover in {EXECUTOR_AUTO_RECOVERY_DELAY}s"
            )
            return False

        # Shutdown old executor (wait briefly to allow cleanup)
        if self._executor is not None:
            try:
                self._executor.shutdown(wait=True, cancel_futures=True)
            except Exception:
                pass
            self._executor = None

        self._create_executor()
        self._last_executor_reset = now
        # Log which track was being processed when the crash occurred
        if self._current_track_id:
            self._crashed_track_ids.add(self._current_track_id)
            logger.warning(
                f"ProcessPoolExecutor was reset after crash "
                f"(failure {self._consecutive_executor_failures}/{EXECUTOR_MAX_CONSECUTIVE_FAILURES}). "
                f"Track being processed: {self._current_track_id}"
            )
        else:
            logger.warning(
                f"ProcessPoolExecutor was reset after crash "
                f"(failure {self._consecutive_executor_failures}/{EXECUTOR_MAX_CONSECUTIVE_FAILURES})"
            )
        return True

    def reset_executor_circuit_breaker(self) -> dict[str, Any]:
        """Manually reset the executor circuit breaker.

        Use this to recover from a disabled executor without restarting.
        Returns status info about what was reset.
        """
        was_disabled = self._executor_disabled
        old_failure_count = self._consecutive_executor_failures
        crashed_tracks = list(self._crashed_track_ids)

        # Reset state
        self._executor_disabled = False
        self._consecutive_executor_failures = 0
        self._last_executor_reset = 0.0
        self._crashed_track_ids.clear()

        # Shutdown old executor if exists
        if self._executor is not None:
            try:
                self._executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            self._executor = None

        # Create fresh executor
        self._create_executor()

        logger.info(
            f"Executor circuit breaker manually reset. Was disabled: {was_disabled}, "
            f"failures: {old_failure_count}, crashed tracks: {len(crashed_tracks)}"
        )

        return {
            "status": "reset",
            "was_disabled": was_disabled,
            "previous_failure_count": old_failure_count,
            "crashed_track_ids": crashed_tracks,
        }

    def get_executor_status(self) -> dict[str, Any]:
        """Get current executor circuit breaker status."""
        return {
            "disabled": self._executor_disabled,
            "consecutive_failures": self._consecutive_executor_failures,
            "max_failures": EXECUTOR_MAX_CONSECUTIVE_FAILURES,
            "crashed_track_ids": list(self._crashed_track_ids),
            "last_reset_ago": time.monotonic() - self._last_executor_reset if self._last_executor_reset else None,
        }

    def _cleanup_stale_redis_state(self) -> None:
        """Clean up stale Redis state from previous runs.

        This handles the case where the container was restarted while a sync
        was running - the Redis state would still show "running" with a stale
        heartbeat, blocking new syncs from starting.

        On startup, we ALWAYS clear any "running" sync state because:
        1. We just started - there's no sync running in memory
        2. Any "running" state in Redis is leftover from a previous process
        3. Waiting for heartbeat timeout causes unnecessary delays
        """
        try:
            # Check sync progress for "running" state
            data: bytes | None = self.redis.get("familiar:sync:progress")  # type: ignore[assignment]
            if data:
                progress = json.loads(data)
                if progress.get("status") == "running":
                    # On startup, always clear running state - we know nothing is running
                    # because we just started up
                    heartbeat = progress.get("last_heartbeat", "unknown")
                    phase = progress.get("phase", "unknown")
                    logger.info(
                        f"Clearing orphaned sync state on startup "
                        f"(was in phase '{phase}', last heartbeat: {heartbeat})"
                    )
                    self.redis.delete("familiar:sync:lock", "familiar:sync:progress")
        except Exception as e:
            logger.warning(f"Failed to cleanup stale Redis state: {e}")

    async def startup(self) -> None:
        """Initialize scheduler on app startup."""
        # Clean up any stale Redis state from previous runs
        self._cleanup_stale_redis_state()

        # Start artwork fetcher
        from app.services.artwork_fetcher import get_artwork_fetcher
        artwork_fetcher = get_artwork_fetcher()
        await artwork_fetcher.start()

        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger

            self._scheduler = AsyncIOScheduler()

            # Unified library sync every 2 hours (replaces separate scan + analysis catch-up)
            self._scheduler.add_job(
                self._periodic_sync,
                CronTrigger(hour="*/2", minute=0),
                id="periodic_sync",
                replace_existing=True,
            )

            # Daily new releases check at 3 AM
            self._scheduler.add_job(
                self._daily_new_releases_check,
                CronTrigger(hour=3, minute=0),
                id="daily_new_releases",
                replace_existing=True,
            )

            self._scheduler.start()
            logger.info("APScheduler started with periodic sync (every 2 hours) and daily new releases check (3 AM)")

            # Schedule startup sync after a short delay
            asyncio.create_task(self._startup_sync())

        except ImportError:
            logger.warning("APScheduler not installed - periodic tasks disabled")
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")

    async def shutdown(self) -> None:
        """Cleanup on app shutdown."""
        logger.info("Shutting down BackgroundManager...")

        # Stop artwork fetcher
        from app.services.artwork_fetcher import get_artwork_fetcher
        artwork_fetcher = get_artwork_fetcher()
        await artwork_fetcher.stop()

        # Cancel running tasks
        if self._current_sync_task and not self._current_sync_task.done():
            self._current_sync_task.cancel()
            try:
                await self._current_sync_task
            except asyncio.CancelledError:
                pass

        for task in self._analysis_tasks.values():
            if not task.done():
                task.cancel()

        # Stop scheduler
        if self._scheduler:
            self._scheduler.shutdown(wait=False)

        # Shutdown executor
        if self._executor:
            self._executor.shutdown(wait=False)

        logger.info("BackgroundManager shutdown complete")

    async def queue_artwork_fetch(
        self,
        album_hash: str,
        artist: str,
        album: str,
        track_id: str | None = None,
    ) -> bool:
        """Queue artwork for background fetching.

        Returns True if queued, False if skipped (already exists or in progress).
        """
        from app.services.artwork_fetcher import ArtworkFetchRequest, get_artwork_fetcher

        fetcher = get_artwork_fetcher()
        request = ArtworkFetchRequest(
            album_hash=album_hash,
            artist=artist,
            album=album,
            track_id=track_id,
        )
        return await fetcher.queue(request)

    def is_analysis_running(self) -> bool:
        """Check if any analysis tasks are currently running."""
        # Clean up completed tasks first
        completed = [tid for tid, task in self._analysis_tasks.items() if task.done()]
        for tid in completed:
            self._analysis_tasks.pop(tid, None)

        return len(self._analysis_tasks) > 0

    def get_analysis_task_count(self) -> int:
        """Get the number of active analysis tasks."""
        # Clean up completed tasks first
        completed = [tid for tid, task in self._analysis_tasks.items() if task.done()]
        for tid in completed:
            self._analysis_tasks.pop(tid, None)

        return len(self._analysis_tasks)

    def is_sync_running(self) -> bool:
        """Check if a library sync is currently running.

        Also detects and clears stale locks from crashed syncs.
        """
        from datetime import datetime, timedelta

        # Check local task first
        if self._current_sync_task and not self._current_sync_task.done():
            return True

        # Check Redis state
        try:
            has_lock = bool(self.redis.get("familiar:sync:lock"))
            data: bytes | None = self.redis.get("familiar:sync:progress")  # type: ignore[assignment]

            if data:
                progress = json.loads(data)
                if progress.get("status") == "running":
                    # Check if heartbeat is recent (60 second threshold)
                    heartbeat = progress.get("last_heartbeat")
                    if heartbeat:
                        try:
                            hb_time = datetime.fromisoformat(heartbeat)
                            age = datetime.utcnow() - hb_time
                            if age < timedelta(seconds=60):
                                # Recent heartbeat = sync is actively running
                                return True
                            elif has_lock:
                                # Stale heartbeat with lock = crashed sync, clean up
                                logger.info(
                                    f"Clearing stale sync lock (heartbeat was {age.total_seconds():.0f}s ago)"
                                )
                                self.redis.delete("familiar:sync:lock", "familiar:sync:progress")
                                return False
                        except (ValueError, TypeError):
                            # Invalid timestamp with lock = stale, clean up
                            if has_lock:
                                logger.info("Clearing sync lock with invalid heartbeat")
                                self.redis.delete("familiar:sync:lock", "familiar:sync:progress")
                            return False

            # Lock exists but no progress data = stale lock, clean up
            if has_lock and not data:
                logger.info("Clearing orphaned sync lock (no progress data)")
                self.redis.delete("familiar:sync:lock")
                return False

            return has_lock

        except Exception:
            pass

        return False

    def _acquire_sync_lock(self) -> bool:
        """Try to acquire the sync lock in Redis. Returns True if acquired.

        If a stale lock exists (no recent heartbeat), it will be cleared first.
        """
        from datetime import datetime, timedelta

        try:
            # First, try to clear any stale locks based on heartbeat
            data: bytes | None = self.redis.get("familiar:sync:progress")  # type: ignore[assignment]
            if data:
                try:
                    progress = json.loads(data)
                    heartbeat = progress.get("last_heartbeat")
                    if heartbeat:
                        hb_time = datetime.fromisoformat(heartbeat)
                        age = datetime.utcnow() - hb_time
                        # If heartbeat is older than 60 seconds, consider the lock stale
                        if age > timedelta(seconds=60):
                            logger.info(
                                f"Clearing stale sync lock before acquire "
                                f"(heartbeat was {age.total_seconds():.0f}s ago)"
                            )
                            self.redis.delete("familiar:sync:lock", "familiar:sync:progress")
                except (ValueError, TypeError, json.JSONDecodeError):
                    # Invalid progress data, clear it
                    self.redis.delete("familiar:sync:lock", "familiar:sync:progress")

            # Now try to acquire
            return bool(self.redis.set("familiar:sync:lock", "1", nx=True, ex=7200))  # 2 hour expiry
        except Exception:
            return False

    def _release_sync_lock(self) -> None:
        """Release the sync lock in Redis."""
        try:
            self.redis.delete("familiar:sync:lock")
        except Exception:
            pass

    def _cancel_sync(self) -> None:
        """Cancel the current sync task."""
        if self._current_sync_task and not self._current_sync_task.done():
            self._current_sync_task.cancel()
        self._release_sync_lock()

    async def run_cpu_bound(self, func: Callable, *args: Any, max_retries: int = 1) -> Any:
        """Run CPU-bound function in process pool (spawned, not forked).

        This is the key to avoiding OpenBLAS SIGSEGV - spawned processes
        don't inherit corrupted library state from the parent.

        If the process pool crashes (BrokenProcessPool), it will be automatically
        recreated and the operation retried once.

        When multiple tasks hit a crash simultaneously, only one will reset the
        executor (others are rate-limited). Rate-limited tasks will retry with
        the newly-reset executor rather than failing immediately.

        If the executor is disabled, it will auto-recover after 5 minutes.
        """
        # Check if executor is disabled - but allow auto-recovery after delay
        if self._executor_disabled:
            time_since_disabled = time.monotonic() - self._executor_disabled_at
            if time_since_disabled >= EXECUTOR_AUTO_RECOVERY_DELAY:
                logger.info(
                    f"Auto-recovering executor after {time_since_disabled:.0f}s "
                    f"(threshold: {EXECUTOR_AUTO_RECOVERY_DELAY}s)"
                )
                # Reset the circuit breaker
                self._executor_disabled = False
                self._consecutive_executor_failures = 0
                self._executor_disabled_at = 0.0
                # Old executor is broken, will be recreated on access
                if self._executor is not None:
                    try:
                        self._executor.shutdown(wait=False, cancel_futures=True)
                    except Exception:
                        pass
                    self._executor = None
            else:
                remaining = EXECUTOR_AUTO_RECOVERY_DELAY - time_since_disabled
                raise RuntimeError(
                    f"Process pool executor is disabled due to repeated failures. "
                    f"Will auto-recover in {remaining:.0f}s."
                )

        loop = asyncio.get_event_loop()
        retries = 0
        last_error: Exception | None = None

        while retries <= max_retries:
            try:
                result = await loop.run_in_executor(self.executor, func, *args)
                # Success! Reset failure counter
                self._consecutive_executor_failures = 0
                return result
            except BrokenProcessPool as e:
                last_error = e
                if retries < max_retries:
                    # Use lock to serialize reset attempts
                    async with self._executor_lock:
                        # Check if executor was disabled while waiting for lock
                        if self._executor_disabled:
                            raise RuntimeError(
                                "Process pool executor is disabled due to repeated failures"
                            )

                        # Check if executor was already reset by another task while we waited
                        # If so, _reset_executor will be rate-limited but that's OK - we'll
                        # just retry with the already-reset executor
                        time_since_reset = time.monotonic() - self._last_executor_reset
                        if time_since_reset < EXECUTOR_RESET_COOLDOWN:
                            # Another task just reset it - the executor should be fresh
                            logger.info(
                                f"Executor was reset {time_since_reset:.1f}s ago by another task, "
                                "retrying with fresh executor"
                            )
                        else:
                            # No recent reset - we need to do it
                            logger.warning(
                                f"Process pool crashed, attempting reset "
                                f"(attempt {retries + 1}/{max_retries + 1})"
                            )
                            reset_ok = self._reset_executor()
                            if not reset_ok:
                                # Disabled due to too many failures
                                raise RuntimeError(
                                    "Process pool executor is disabled due to repeated failures"
                                ) from e

                    # Retry with the (potentially new) executor
                    retries += 1
                else:
                    raise
        raise last_error  # Should not reach here, but for type safety

    async def run_analysis(
        self,
        track_id: str,
        phase: str = "full",
    ) -> dict[str, Any]:
        """Queue a track for analysis.

        Args:
            track_id: Track UUID
            phase: Which phase to run:
                - "full": Features + embeddings (default, for backwards compatibility)
                - "features": Only extract features (librosa, artwork, AcoustID)
                - "embedding": Only generate CLAP embedding

        Runs in process pool to isolate potential crashes.
        """
        # Use different task keys for different phases to allow tracking separately
        task_key = f"{track_id}:{phase}"

        # Check if already analyzing this track+phase
        if task_key in self._analysis_tasks:
            task = self._analysis_tasks[task_key]
            if not task.done():
                return {"status": "already_queued"}

        # Create analysis task for the specified phase
        if phase == "features":
            task = asyncio.create_task(self._do_features(track_id))
        elif phase == "embedding":
            task = asyncio.create_task(self._do_embedding(track_id))
        else:
            task = asyncio.create_task(self._do_analysis(track_id))

        self._analysis_tasks[task_key] = task
        return {"status": "queued"}

    async def _do_features(self, track_id: str) -> dict[str, Any]:
        """Execute feature extraction only (Phase 1).

        Runs librosa, artwork extraction, AcoustID in a subprocess.
        Memory usage: ~1-2GB peak.
        """
        from app.services.tasks import run_track_features

        task_key = f"{track_id}:features"
        try:
            self._current_track_id = track_id
            result = await self.run_cpu_bound(run_track_features, track_id)
            return result
        except Exception as e:
            logger.error(f"Feature extraction failed for {track_id}: {e}")
            return {"status": "error", "error": str(e)}
        finally:
            self._current_track_id = None
            self._analysis_tasks.pop(task_key, None)

    async def _do_embedding(self, track_id: str) -> dict[str, Any]:
        """Execute embedding generation only (Phase 2).

        Runs CLAP model in a subprocess.
        Memory usage: ~2-3GB peak.
        """
        import os

        from app.services.tasks import run_track_embedding

        task_key = f"{track_id}:embedding"
        try:
            # Check if CLAP embeddings are disabled
            clap_disabled = os.environ.get("DISABLE_CLAP_EMBEDDINGS", "").lower() in (
                "1", "true", "yes"
            )
            if clap_disabled:
                return {"status": "skipped", "embedding_generated": False}

            self._current_track_id = track_id
            result = await self.run_cpu_bound(run_track_embedding, track_id)
            return result
        except Exception as e:
            logger.error(f"Embedding generation failed for {track_id}: {e}")
            return {"status": "error", "error": str(e)}
        finally:
            self._current_track_id = None
            self._analysis_tasks.pop(task_key, None)

    async def _do_analysis(self, track_id: str) -> dict[str, Any]:
        """Execute full track analysis in process pool.

        Runs in two separate subprocess phases to reduce peak memory:
        1. Features phase: librosa, artwork, AcoustID (~1-2GB memory)
        2. Embedding phase: CLAP model (~2-3GB memory)

        Each subprocess exits after completion, freeing its memory before
        the next phase starts. This keeps peak memory under ~3GB instead
        of ~5GB when both run together.
        """
        import os

        from app.services.tasks import run_track_embedding, run_track_features

        task_key = f"{track_id}:full"
        try:
            self._current_track_id = track_id

            # Phase 1: Extract features (librosa, artwork, fingerprint)
            features_result = await self.run_cpu_bound(run_track_features, track_id)

            if features_result.get("status") != "success":
                return features_result

            # Phase 2: Extract CLAP embedding (if enabled)
            clap_disabled = os.environ.get("DISABLE_CLAP_EMBEDDINGS", "").lower() in (
                "1", "true", "yes"
            )

            if clap_disabled:
                return {
                    **features_result,
                    "embedding_generated": False,
                    "embedding_skipped": True,
                }

            embedding_result = await self.run_cpu_bound(run_track_embedding, track_id)

            return {
                **features_result,
                "embedding_generated": embedding_result.get("embedding_generated", False),
                "embedding_error": embedding_result.get("error"),
            }

        except Exception as e:
            logger.error(f"Analysis failed for {track_id}: {e}")
            return {"status": "error", "error": str(e)}
        finally:
            self._current_track_id = None
            self._analysis_tasks.pop(task_key, None)

    async def run_spotify_sync(
        self,
        profile_id: str,
        include_top_tracks: bool = True,
        favorite_matched: bool = False,
    ) -> dict[str, Any]:
        """Start Spotify sync in the background."""
        from app.services.tasks import run_spotify_sync

        try:
            result = await run_spotify_sync(
                profile_id=profile_id,
                include_top_tracks=include_top_tracks,
                favorite_matched=favorite_matched,
            )
            return result
        except Exception as e:
            logger.error(f"Spotify sync failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    async def run_new_releases_check(
        self,
        profile_id: str | None = None,
        days_back: int = 90,
        force: bool = False,
    ) -> dict[str, Any]:
        """Start new releases check in the background."""
        from app.services.tasks import run_new_releases_check

        try:
            result = await run_new_releases_check(
                profile_id=profile_id,
                days_back=days_back,
                force=force,
            )
            return result
        except Exception as e:
            logger.error(f"New releases check failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    async def run_prioritized_new_releases_check(
        self,
        profile_id: str,
        batch_size: int = 75,
        days_back: int = 90,
    ) -> dict[str, Any]:
        """Start priority-based new releases check in the background.

        This checks a batch of artists prioritized by recent listening activity.
        Only artists the user has actually listened to are checked.
        """
        from app.services.tasks import run_prioritized_new_releases_check

        try:
            result = await run_prioritized_new_releases_check(
                profile_id=profile_id,
                batch_size=batch_size,
                days_back=days_back,
            )
            return result
        except Exception as e:
            logger.error(f"Priority-based new releases check failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    async def _daily_new_releases_check(self) -> None:
        """Run daily priority-based new releases check.

        Called by the scheduler at 3 AM daily. Gets the most recently active
        profile and uses it for prioritization.
        """
        logger.info("Starting daily new releases check")

        try:
            # Get the most recently active profile for prioritization
            from sqlalchemy import select
            from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

            from app.config import settings
            from app.db.models import Profile

            engine = create_async_engine(settings.database_url)
            async_session = async_sessionmaker(engine, class_=AsyncSession)

            profile_id = None
            async with async_session() as db:
                # Get any profile (prefer the one with most recent activity, but for now just get first)
                db_result = await db.execute(
                    select(Profile.id).limit(1)
                )
                row = db_result.scalar_one_or_none()
                if row:
                    profile_id = str(row)

            await engine.dispose()

            if not profile_id:
                logger.warning("No profiles found - skipping daily new releases check")
                return

            check_result = await self.run_prioritized_new_releases_check(
                profile_id=profile_id,
                batch_size=75,
                days_back=90,
            )
            logger.info(f"Daily new releases check completed: {check_result}")

        except Exception as e:
            logger.error(f"Daily new releases check failed: {e}", exc_info=True)

    async def run_bulk_identify(
        self,
        task_id: str,
        track_ids: list[str],
    ) -> dict[str, Any]:
        """Run bulk audio fingerprint identification.

        Processes tracks sequentially to respect API rate limits:
        - AcoustID: 3 requests/second
        - MusicBrainz: 1 request/second

        Progress is stored in Redis for polling.
        """
        from datetime import datetime
        from uuid import UUID

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from app.config import settings
        from app.services.audio_identification import get_audio_identification_service

        logger.info(f"Starting bulk identify task {task_id} for {len(track_ids)} tracks")

        # Initialize progress in Redis
        progress: dict[str, Any] = {
            "status": "running",
            "phase": "identifying",
            "total_tracks": len(track_ids),
            "processed_tracks": 0,
            "current_track": None,
            "results": [],
            "errors": [],
            "started_at": datetime.utcnow().isoformat(),
        }
        self.redis.set(
            f"familiar:identify:{task_id}",
            json.dumps(progress),
            ex=3600,  # 1 hour expiry
        )

        # Create database session
        engine = create_async_engine(settings.database_url)
        async_session = async_sessionmaker(engine, class_=AsyncSession)

        service = get_audio_identification_service()

        try:
            async with async_session() as db:
                for i, track_id_str in enumerate(track_ids):
                    try:
                        track_id = UUID(track_id_str)

                        # Update progress
                        progress["current_track"] = track_id_str
                        progress["processed_tracks"] = i
                        self.redis.set(
                            f"familiar:identify:{task_id}",
                            json.dumps(progress),
                            ex=3600,
                        )

                        # Run identification
                        result = await service.identify_track(
                            track_id=track_id,
                            db=db,
                            min_score=0.5,
                            limit=5,
                        )

                        # Add result
                        progress["results"].append(result.to_dict())

                    except Exception as e:
                        logger.error(f"Error identifying track {track_id_str}: {e}")
                        progress["errors"].append(f"Track {track_id_str}: {e}")

                    # Rate limiting delay (respect MusicBrainz 1/sec limit)
                    await asyncio.sleep(1.0)

            # Mark complete
            progress["status"] = "completed"
            progress["phase"] = "done"
            progress["processed_tracks"] = len(track_ids)
            progress["current_track"] = None

        except Exception as e:
            logger.error(f"Bulk identify task {task_id} failed: {e}", exc_info=True)
            progress["status"] = "error"
            progress["phase"] = "error"
            progress["errors"].append(str(e))

        finally:
            # Save final progress
            self.redis.set(
                f"familiar:identify:{task_id}",
                json.dumps(progress),
                ex=3600,
            )
            await engine.dispose()

        logger.info(
            f"Bulk identify task {task_id} completed: "
            f"{len(progress['results'])} results, {len(progress['errors'])} errors"
        )

        return {"status": progress["status"], "task_id": task_id}

    async def run_sync(
        self,
        reread_unchanged: bool = False,
    ) -> dict[str, Any]:
        """Start a unified library sync (scan + analysis) in the background.

        Returns immediately with status. Progress is reported via Redis.
        Uses Redis-based locking to prevent concurrent syncs across workers.

        Args:
            reread_unchanged: Re-read metadata for files even if unchanged.
        """
        async with self._lock:
            # Check if already running (local or other worker)
            if self.is_sync_running():
                return {"status": "already_running"}

            # Try to acquire Redis lock
            if not self._acquire_sync_lock():
                return {"status": "already_running"}

            # Create task and store reference
            self._current_sync_task = asyncio.create_task(
                self._do_sync(reread_unchanged)
            )

        return {"status": "started"}

    async def _do_sync(
        self,
        reread_unchanged: bool,
    ) -> dict[str, Any]:
        """Execute the unified library sync."""
        from app.services.tasks import run_library_sync

        try:
            result = await run_library_sync(reread_unchanged=reread_unchanged)
            return result
        except Exception as e:
            logger.error(f"Sync failed: {e}", exc_info=True)
            # Update Redis progress with error
            try:
                progress = {"status": "error", "phase_message": str(e)}
                self.redis.set("familiar:sync:progress", json.dumps(progress), ex=3600)
            except Exception:
                pass
            return {"status": "error", "error": str(e)}
        finally:
            self._current_sync_task = None
            self._release_sync_lock()

    async def _startup_sync(self) -> None:
        """Run initial sync on startup after a short delay."""
        # Wait for server to fully start
        await asyncio.sleep(5)

        # Only run if no sync is already in progress
        if self.is_sync_running():
            logger.info("Skipping startup sync - another sync is already running")
            return

        logger.info("Starting automatic library sync on startup")
        try:
            await self.run_sync()
        except Exception as e:
            logger.error(f"Startup sync failed: {e}")

    async def _periodic_sync(self) -> None:
        """Run periodic unified library sync."""
        logger.info("Starting periodic library sync")
        try:
            await self.run_sync()
        except Exception as e:
            logger.error(f"Periodic sync failed: {e}")


# Global singleton instance
_background_manager: BackgroundManager | None = None


def get_background_manager() -> BackgroundManager:
    """Get the global BackgroundManager instance."""
    global _background_manager
    if _background_manager is None:
        _background_manager = BackgroundManager()
    return _background_manager
