"""BackgroundManager core: class composition, __init__, startup, shutdown."""

import asyncio
import json
import logging

from app.container import Services
from app.services.kv import KeyValueStore
from app.services.redis_client import get_resilient_redis

from .analysis import AnalysisMixin
from .backup import BackupMixin
from .executors import ExecutorMixin
from .soulseek import SOULSEEK_POLL_MINUTES, SoulseekMixin
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

#: ADR-0115 point 1. Ten minutes, two bounded phases per tick: 150 AcoustID lookups
#: (about a minute at the 3/s ceiling) then 150 corpus claims (six minutes at 25/min).
#: The 23,853 unnamed tracks measured on 2026-09-14 resolve in about 1.1 days.
RECORDING_BACKFILL_INTERVAL_MINUTES = 10
#: The artist-gallery sweep (ADR-0149 point 5): about sixty artists an hour, so a few-thousand-artist
#: library is covered in days without competing with a sync for MusicBrainz's one request a second.
ARTIST_GALLERY_INTERVAL_MINUTES = 60
ARTIST_GALLERY_PER_TICK = 60


class BackgroundManager(ExecutorMixin, AnalysisMixin, SyncMixin, BackupMixin, SoulseekMixin):
    """Manages background tasks in the API process.

    Key features:
    - ProcessPoolExecutor with spawn context (not fork) to avoid OpenBLAS crashes
    - APScheduler for periodic tasks
    - Redis for progress reporting
    - Task deduplication to prevent running multiple syncs simultaneously
    """

    def __init__(self):
        self._scheduler = None
        self._redis: KeyValueStore | None = None
        # The application's container (ADR-0130), handed in by `startup()`. Until every domain
        # has moved, the manager itself is still reached through `get_background_manager()`,
        # so this is the one thing it is *given* rather than looks up.
        self.services: Services = Services.unconfigured()
        # Initialize mixin state
        self._init_executor_state()
        self._init_analysis_state()
        self._init_sync_state()

    @property
    def redis(self) -> KeyValueStore:
        """The key/value store: Redis, or Postgres when REDIS_URL is unset (ADR-0133)."""
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

    async def startup(self, services: Services | None = None) -> None:
        """Initialize scheduler on app startup.

        `services` is the container the polls resolve their dependencies from (ADR-0130 point
        7): the Soulseek poll asks `services.soulseek`, never a settings singleton. Omitted, the
        manager runs as a server with no integrations configured — what the tests want.
        """
        if services is not None:
            self.services = services
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

            # Names the library's recordings through AcoustID and tells the corpus
            # (ADR-0115). Each phase gates itself — the resolve half on
            # `recording_backfill_enabled`, the claim half on
            # `community_cache_contribute` — so registering it unconditionally is
            # right: a disabled phase returns at once and records nothing.
            self._scheduler.add_job(
                self._recording_backfill,
                IntervalTrigger(minutes=RECORDING_BACKFILL_INTERVAL_MINUTES),
                id="recording_backfill",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=300,
                replace_existing=True,
            )

            # Artist photo galleries (ADR-0149 point 5), deferrable below like every background job.
            self._scheduler.add_job(
                self._artist_gallery_sweep,
                IntervalTrigger(minutes=ARTIST_GALLERY_INTERVAL_MINUTES),
                id="artist_gallery",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=600,
                replace_existing=True,
            )

            # A settled Soulseek download triggers a sync (ADR-0117 point 3). Registered whether
            # or not slskd is configured: the job returns at once when it is not, and that is
            # cheaper than re-registering from the settings route every time the URL changes.
            self._scheduler.add_job(
                self._soulseek_poll,
                IntervalTrigger(minutes=SOULSEEK_POLL_MINUTES),
                id="soulseek_poll",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=60,
                replace_existing=True,
            )

            # Periodic metrics summary every 5 minutes
            self._scheduler.add_job(
                self._log_metrics_summary,
                IntervalTrigger(minutes=5),
                id="metrics_summary",
                replace_existing=True,
            )

            # The Postgres key/value store ignores expired keys on read but does not delete them;
            # Redis does that itself. Without this, a key nobody reads again stays forever (ADR-0133).
            # Decided from configuration, as `build_store()` decides, so that startup does not build
            # the store early: the manager's store stays lazy, as it always was.
            from app.config import settings as app_settings

            if not app_settings.redis_url:
                self._scheduler.add_job(
                    self._sweep_kv_store,
                    IntervalTrigger(minutes=10),
                    id="kv_store_sweep",
                    replace_existing=True,
                )

            # Register S3 backup schedule if enabled
            self._register_s3_backup_schedule()
            self._make_background_jobs_deferrable()

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

    #: Scheduled jobs that are *background work* and wait out a pause (ADR-0138 point 1). The rest
    #: (health checks, metrics, log cleanup, the kv sweep, the restore checker) are housekeeping
    #: that must keep running whatever the machine is doing.
    DEFERRABLE_JOBS = (
        "periodic_sync",
        "discovery_batch",
        "daily_external_albums",
        "listenbrainz_fresh_releases",
        "recording_backfill",
        "artist_gallery",
        "soulseek_poll",
        "daily_update_check",
        "s3_backup",
    )

    def _make_background_jobs_deferrable(self) -> None:
        """Wrap each deferrable job so a run that falls during a pause is skipped and recorded."""
        from app.services.background.pause import background_pause

        for job_id in self.DEFERRABLE_JOBS:
            job = self._scheduler.get_job(job_id) if self._scheduler else None
            if job is None:
                continue
            original = job.func
            if getattr(original, "_familiar_deferrable", False):
                continue  # already wrapped; safe to call again after a job is re-registered

            async def deferrable(*args, _original=original, _job_id=job_id, **kwargs):
                if background_pause.paused:
                    background_pause.note_skipped(_job_id)
                    logger.info("Skipping %s: background work is paused (%s)", _job_id, background_pause.reason)
                    return None
                result = _original(*args, **kwargs)
                return await result if asyncio.iscoroutine(result) else result

            deferrable._familiar_deferrable = True  # type: ignore[attr-defined]
            job.modify(func=deferrable)

    def pause_background(self, reason: str) -> dict:
        """Pause background work (ADR-0138 point 1). Serving is never paused."""
        from app.services.background.pause import background_pause

        background_pause.pause(reason)
        logger.info("Background work paused: %s", reason)
        return background_pause.state()

    def resume_background(self) -> dict:
        """Resume. A periodic sync skipped while paused runs once now (ADR-0138 point 5)."""
        from app.services.background.pause import background_pause

        skipped = background_pause.resume()
        logger.info("Background work resumed (skipped while paused: %s)", sorted(skipped) or "nothing")
        if "periodic_sync" in skipped and not self.is_sync_running():
            asyncio.get_running_loop().create_task(self._periodic_sync())
        state = background_pause.state()
        state["resumed_sync"] = "periodic_sync" in skipped
        return state

    async def _sweep_kv_store(self) -> None:
        """Delete expired keys from the Postgres key/value store."""
        import asyncio

        try:
            store = self.redis
            removed = await asyncio.to_thread(store.sweep)  # type: ignore[attr-defined]
            if removed:
                logger.debug("kv_store sweep removed %d expired keys", removed)
        except Exception as e:
            logger.warning(f"kv_store sweep failed: {e}")

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
