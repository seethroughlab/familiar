"""BackgroundManager core: class composition, __init__, startup, shutdown."""

import asyncio
import json
import logging
from uuid import UUID

from app.services.redis_client import ResilientRedisClient, get_resilient_redis

from .analysis import AnalysisMixin
from .backup import BackupMixin
from .executors import ExecutorMixin
from .sync import SyncMixin

logger = logging.getLogger(__name__)


class BackgroundManager(ExecutorMixin, AnalysisMixin, SyncMixin, BackupMixin):
    """Manages background tasks in the API process.

    Key features:
    - ProcessPoolExecutor with spawn context (not fork) to avoid OpenBLAS crashes
    - APScheduler for periodic tasks
    - Redis for progress reporting
    - Task deduplication to prevent running multiple syncs simultaneously
    """

    def __init__(self):
        self._scheduler = None
        self._redis: ResilientRedisClient | None = None
        # Initialize mixin state
        self._init_executor_state()
        self._init_analysis_state()
        self._init_sync_state()

    @property
    def redis(self) -> ResilientRedisClient:
        """Lazy resilient Redis client with automatic retry."""
        if self._redis is None:
            self._redis = get_resilient_redis()
        return self._redis

    def _cleanup_stale_redis_state(self) -> None:
        """Clean up stale Redis state from previous runs."""
        try:
            data: bytes | None = self.redis.get("familiar:sync:progress")  # type: ignore[assignment]
            if data:
                progress = json.loads(data)
                if progress.get("status") == "running":
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
        self._cleanup_stale_redis_state()

        # Start artwork fetcher
        from app.services.artwork_fetcher import get_artwork_fetcher
        artwork_fetcher = get_artwork_fetcher()
        await artwork_fetcher.start()

        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger
            from apscheduler.triggers.interval import IntervalTrigger

            self._scheduler = AsyncIOScheduler()

            # Unified library sync every 2 hours
            self._scheduler.add_job(
                self._periodic_sync,
                CronTrigger(hour="*/2", minute=0),
                id="periodic_sync",
                replace_existing=True,
            )

            # Worker health check every 5 minutes
            self._scheduler.add_job(
                self._check_and_recover_worker,
                IntervalTrigger(minutes=5),
                id="worker_health_check",
                replace_existing=True,
            )

            # Daily cleanup of old frontend logs
            self._scheduler.add_job(
                self._cleanup_frontend_logs,
                CronTrigger(hour=4, minute=0),
                id="frontend_logs_cleanup",
                replace_existing=True,
            )

            # Daily update check at 3:30 AM
            self._scheduler.add_job(
                self._check_for_app_updates,
                CronTrigger(hour=3, minute=30),
                id="daily_update_check",
                replace_existing=True,
            )

            # Daily new-releases check (prioritized batch) at 3:00 AM
            self._scheduler.add_job(
                self._daily_new_releases_check,
                CronTrigger(hour=3, minute=0),
                id="daily_new_releases",
                replace_existing=True,
            )

            # Periodic metrics summary every 5 minutes
            self._scheduler.add_job(
                self._log_metrics_summary,
                IntervalTrigger(minutes=5),
                id="metrics_summary",
                replace_existing=True,
            )

            # Register S3 backup schedule if enabled
            self._register_s3_backup_schedule()

            self._scheduler.start()
            logger.info("APScheduler started with periodic sync (every 2 hours)")

            # Schedule startup sync after a short delay
            asyncio.create_task(self._startup_sync())

            # Check for updates on startup (30s delay)
            asyncio.create_task(self._startup_update_check())

        except ImportError:
            logger.warning("APScheduler not installed - periodic tasks disabled")
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")

    async def _log_metrics_summary(self) -> None:
        """Log a one-line metrics summary for operational visibility."""
        try:
            from app.services.metrics import (
                check_pressure_alarms,
                get_metrics_collector,
                update_background_gauges,
            )
            collector = get_metrics_collector()
            update_background_gauges(collector)
            snapshot = collector.get_snapshot(window_seconds=300)
            req = snapshot["request_metrics"]
            bg = snapshot["background_gauges"]
            logger.info(
                "metrics_summary",
                extra={
                    "requests_5m": req["total_requests"],
                    "client_disconnects": req["client_disconnects"],
                    "error_rate": req["error_rate"],
                    # API latency only. `transfer_*` covers audio/video bodies, whose
                    # elapsed time is byte-movement — a single skipped track used to set
                    # p95 for the whole window.
                    "p50_ms": req["duration_p50_ms"],
                    "p95_ms": req["duration_p95_ms"],
                    "transfers": req["transfer_requests"],
                    "transfer_p95_ms": req["transfer_p95_ms"],
                    "analysis_queue": bg.get("analysis_queue_depth", 0),
                    "sync_running": bg.get("sync_running", False),
                    "current_phase": bg.get("current_phase"),
                    "phase_pending": bg.get("phase_pending", 0),
                },
            )
            check_pressure_alarms(snapshot, logger)
        except Exception as e:
            logger.warning(f"Failed to log metrics summary: {e}")

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

        # Shutdown executors
        if self._executor:
            self._executor.shutdown(wait=False)
        if self._ondemand_executor:
            self._ondemand_executor.shutdown(wait=False)

        logger.info("BackgroundManager shutdown complete")

    async def queue_artwork_fetch(
        self,
        album_hash: str,
        artist: str,
        album: str,
        track_id: str | None = None,
    ) -> bool:
        """Queue artwork for background fetching."""
        from app.services.artwork_fetcher import ArtworkFetchRequest, get_artwork_fetcher

        fetcher = get_artwork_fetcher()
        request = ArtworkFetchRequest(
            album_hash=album_hash,
            artist=artist,
            album=album,
            track_id=track_id,
        )
        return await fetcher.queue(request)

    async def run_spotify_matching(self, task_id: str, profile_id: UUID) -> None:
        """Run Spotify track matching in the background with Redis progress tracking."""
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from app.config import settings as app_settings
        from app.services.spotify_import import SpotifyImportService

        key = f"familiar:spotify_import:{task_id}"
        well_known_key = "familiar:spotify_match:progress"

        def _update(message: str, matched: int = 0, total: int = 0) -> None:
            payload = json.dumps({"status": "processing", "message": message, "matched": matched, "total": total})
            self.redis.set(key, payload, ex=3600)
            self.redis.set(well_known_key, payload, ex=3600)

        initial = json.dumps({"status": "processing", "message": "Matching tracks...", "matched": 0, "total": 0})
        self.redis.set(key, initial, ex=3600)
        self.redis.set(well_known_key, initial, ex=3600)

        engine = create_async_engine(app_settings.database_url)
        async_session_factory = async_sessionmaker(engine, class_=AsyncSession)
        try:
            async with async_session_factory() as db:
                service = SpotifyImportService(db)
                import_ = await service.update_matches(profile_id, progress_cb=_update)
            if import_ is None:
                self.redis.set(key, json.dumps({"status": "error", "error": "No Spotify import found"}), ex=3600)
            else:
                self.redis.set(key, json.dumps({"status": "completed", "result": import_.summary}), ex=3600)
        except Exception as e:
            logger.error(f"Spotify matching task {task_id} failed: {e}", exc_info=True)
            self.redis.set(key, json.dumps({"status": "error", "error": str(e)}), ex=3600)
        finally:
            self.redis.delete(well_known_key)
            await engine.dispose()

    async def run_spotify_rematch(self, task_id: str, profile_id: UUID) -> None:
        """Run Spotify rematch in the background with Redis progress tracking."""
        await self.run_spotify_matching(task_id, profile_id)

    async def _startup_update_check(self) -> None:
        """Check for updates on startup after a short delay."""
        await asyncio.sleep(30)
        await self._check_for_app_updates()

    async def _check_for_app_updates(self) -> None:
        """Check GitHub for available updates."""
        try:
            from app.services.update_checker import check_for_updates
            await check_for_updates()
        except Exception as e:
            logger.warning(f"Update check failed: {e}")


# Global singleton instance
_background_manager: BackgroundManager | None = None


def get_background_manager() -> BackgroundManager:
    """Get the global BackgroundManager instance."""
    global _background_manager
    if _background_manager is None:
        _background_manager = BackgroundManager()
    return _background_manager
