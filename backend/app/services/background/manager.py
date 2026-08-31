"""BackgroundManager core: class composition, __init__, startup, shutdown."""

import asyncio
import json
import logging

from app.services.redis_client import ResilientRedisClient, get_resilient_redis

from .analysis import AnalysisMixin
from .backup import BackupMixin
from .executors import ExecutorMixin
from .sync import SyncMixin

logger = logging.getLogger(__name__)

#: How often a discovery batch runs, and how many artists it checks (ADR-0099 point 3).
#:
#: The pair is the decision, not either number alone: ten per twenty minutes is 720 a
#: day against a library of 3,453 artists on a seven-day re-check window, which needs
#: 493 a day to keep up. Raising the batch without lengthening the interval is what
#: would make this a bad citizen of a public, unauthenticated, one-request-per-second
#: service — so change them together and recompute the duty cycle.
DISCOVERY_INTERVAL_MINUTES = 20
DISCOVERY_BATCH_SIZE = 10

#: ListenBrainz runs on its own, much slower cadence (ADR-0099 point 11).
#:
#: It is a different *shape* of request: one call returning every fresh release
#: rather than one call per artist. Folding it into the twenty-minute batch would
#: fetch well over a megabyte to look at ten artists. Three hours is eight calls a
#: day against a limit that reports 30 remaining per window, and the source's
#: thirty-day lookback means nothing is missed between runs.
LISTENBRAINZ_INTERVAL_HOURS = 3


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

            # Discovery runs continuously, in small prioritised batches (ADR-0099 point 3).
            #
            # **A single nightly sweep is why one bad window cost a whole day.** The job
            # either won the race at 03:00 or the library learned nothing for
            # twenty-four hours — and when it crashed, it crashed on the same artist at
            # the same time every night for nineteen nights. On a short interval a
            # rate-limited window costs one batch and the next picks up where it
            # stopped, because `ArtistCheckCache.last_checked_at` is the resumption
            # state.
            #
            # Ten artists per twenty minutes is 720 a day. The library has 3,453 artists
            # and a seven-day re-check window, so keeping up needs 493 a day — this has
            # headroom without being greedy. MusicBrainz allows one request a second, so
            # a batch is roughly 10-20 seconds of upstream time out of 1,200: a duty
            # cycle near 1%, which is what "small enough to be a good citizen" has to
            # mean for an unauthenticated public service.
            self._scheduler.add_job(
                self._discovery_batch,
                IntervalTrigger(minutes=DISCOVERY_INTERVAL_MINUTES),
                id="discovery_batch",
                # None of the daily jobs needed these, because a run could not overlap
                # its own next trigger. At twenty minutes it can: a batch stalled behind
                # a rate-limited upstream must not have a second copy started on top of
                # it, and a container restart must not replay every tick it missed.
                max_instances=1,
                coalesce=True,
                misfire_grace_time=300,
                replace_existing=True,
            )

            # Keeps "Albums you might want" warm. 03:15 sits between the new-releases check at
            # 03:00 and the S3 backup at 03:30, so the three daily jobs do not overlap on a box
            # that is also serving music.
            self._scheduler.add_job(
                self._daily_external_albums_refresh,
                CronTrigger(hour=3, minute=15),
                id="daily_external_albums",
                replace_existing=True,
            )

            self._scheduler.add_job(
                self._listenbrainz_fresh_releases,
                IntervalTrigger(hours=LISTENBRAINZ_INTERVAL_HOURS),
                id="listenbrainz_fresh_releases",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=600,
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
        album_key: str,
        artist: str,
        album: str,
        track_id: str | None = None,
    ) -> bool:
        """Queue artwork for background fetching."""
        from app.services.artwork_fetcher import ArtworkFetchRequest, get_artwork_fetcher

        fetcher = get_artwork_fetcher()
        request = ArtworkFetchRequest(
            album_key=album_key,
            artist=artist,
            album=album,
            track_id=track_id,
        )
        return await fetcher.queue(request)

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
