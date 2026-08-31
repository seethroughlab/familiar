"""SyncMixin: Redis locks, run_sync, maintenance."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from app.services.background.events import record_background_event
from app.services.redis_client import get_redis
from app.utils.time import utcnow

if TYPE_CHECKING:
    from app.services.background._typing import _BackgroundManagerProtocol

    _SyncBase = _BackgroundManagerProtocol
else:
    _SyncBase = object

logger = logging.getLogger(__name__)

SYNC_HEARTBEAT_STALE_SECONDS = 300


def is_heartbeat_stale(progress: dict) -> bool:
    """Check if a running sync's heartbeat exceeds the stale threshold."""
    from datetime import datetime, timedelta

    last_heartbeat = progress.get("last_heartbeat")
    if not last_heartbeat:
        return False
    try:
        heartbeat_time = datetime.fromisoformat(last_heartbeat)
        return datetime.now() - heartbeat_time > timedelta(seconds=SYNC_HEARTBEAT_STALE_SECONDS)
    except (ValueError, TypeError):
        return False


class SyncMixin(_SyncBase):
    """Mixin providing sync and maintenance task management for BackgroundManager."""

    def _init_sync_state(self) -> None:
        """Initialize sync-related state. Call from __init__."""
        self._current_sync_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def is_sync_running(self) -> bool:
        """Check if a library sync is currently running.

        Also detects and clears stale locks from crashed syncs.
        """
        from datetime import datetime, timedelta

        if self._current_sync_task and not self._current_sync_task.done():
            return True

        try:
            has_lock = bool(self.redis.get("familiar:sync:lock"))
            data: bytes | None = self.redis.get("familiar:sync:progress")  # type: ignore[assignment]

            if data:
                progress = json.loads(data)
                if progress.get("status") == "running":
                    heartbeat = progress.get("last_heartbeat")
                    if heartbeat:
                        try:
                            hb_time = datetime.fromisoformat(heartbeat)
                            age = utcnow() - hb_time
                            if age < timedelta(seconds=SYNC_HEARTBEAT_STALE_SECONDS):
                                return True
                            elif has_lock:
                                logger.info(
                                    f"Clearing stale sync lock (heartbeat was {age.total_seconds():.0f}s ago)"
                                )
                                self.redis.delete("familiar:sync:lock", "familiar:sync:progress")
                                return False
                        except (ValueError, TypeError):
                            if has_lock:
                                logger.info("Clearing sync lock with invalid heartbeat")
                                self.redis.delete("familiar:sync:lock", "familiar:sync:progress")
                            return False

            if has_lock and not data:
                logger.info("Clearing orphaned sync lock (no progress data)")
                self.redis.delete("familiar:sync:lock")
                return False

            return has_lock

        except Exception:
            pass

        return False

    def _acquire_sync_lock(self) -> bool:
        """Try to acquire the sync lock in Redis. Returns True if acquired."""
        from datetime import datetime, timedelta

        try:
            data: bytes | None = self.redis.get("familiar:sync:progress")  # type: ignore[assignment]
            if data:
                try:
                    progress = json.loads(data)
                    heartbeat = progress.get("last_heartbeat")
                    if heartbeat:
                        hb_time = datetime.fromisoformat(heartbeat)
                        age = utcnow() - hb_time
                        if age > timedelta(seconds=SYNC_HEARTBEAT_STALE_SECONDS):
                            logger.info(
                                f"Clearing stale sync lock before acquire "
                                f"(heartbeat was {age.total_seconds():.0f}s ago)"
                            )
                            self.redis.delete("familiar:sync:lock", "familiar:sync:progress")
                except (ValueError, TypeError, json.JSONDecodeError):
                    self.redis.delete("familiar:sync:lock", "familiar:sync:progress")

            return bool(self.redis.set("familiar:sync:lock", "1", nx=True, ex=7200))
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
        self.cancel_sync()

    def cancel_sync(self) -> dict[str, Any]:
        """Cancel sync orchestration and release lock.

        Returns structured cancellation semantics for API responses.
        """
        cancelled = 0
        if self._current_sync_task and not self._current_sync_task.done():
            self._current_sync_task.cancel()
            cancelled = 1
        self._release_sync_lock()
        record_background_event(
            "cancel_requested",
            {"scope": "sync", "in_process_tasks_cancelled": cancelled},
        )
        return {
            "requested": True,
            "in_process_tasks_cancelled": cancelled,
            # The scan/analyzer subprocess may continue even after task cancellation.
            "subprocess_may_continue": cancelled > 0,
        }

    async def run_sync(
        self,
        reread_unchanged: bool = False,
    ) -> dict[str, Any]:
        """Start a unified library sync (scan + analysis) in the background."""
        async with self._lock:
            if self.is_sync_running():
                return {"status": "already_running"}

            if not self._acquire_sync_lock():
                return {"status": "already_running"}

            self._current_sync_task = asyncio.create_task(
                self._do_sync(reread_unchanged)
            )
            record_background_event(
                "sync_start",
                {"reread_unchanged": reread_unchanged},
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
            await self._post_sync_backup()
            await self._post_sync_auto_proposals()
            record_background_event(
                "sync_complete",
                {
                    "status": result.get("status", "unknown"),
                    "analyzed": result.get("analyzed"),
                    "phase_forced_exit_reasons": result.get("phase_forced_exit_reasons", {}),
                },
            )
            return result
        except Exception as e:
            logger.error(f"Sync failed: {e}", exc_info=True)
            record_background_event(
                "sync_error",
                {"error": str(e)[:300]},
            )
            try:
                progress = {"status": "error", "phase_message": str(e)}
                self.redis.set("familiar:sync:progress", json.dumps(progress), ex=3600)
            except Exception:
                pass
            return {"status": "error", "error": str(e)}
        finally:
            self._current_sync_task = None
            self._release_sync_lock()

    async def _post_sync_auto_proposals(self) -> None:
        """Best-effort: queue auto-generated metadata proposals after a sync.

        Never raises — a failed scan must not break the sync flow.
        """
        try:
            from app.services.auto_proposals import run_auto_proposal_scan

            count = await run_auto_proposal_scan()
            if count:
                logger.info(f"Post-sync auto-proposals: queued {count} change(s)")
        except Exception as e:
            logger.warning(f"Post-sync auto-proposal scan failed: {e}")

    async def _startup_sync(self) -> None:
        """Run initial sync on startup after a short delay."""
        await asyncio.sleep(5)

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

    async def run_bulk_identify(
        self,
        task_id: str,
        track_ids: list[str],
    ) -> dict[str, Any]:
        """Run bulk audio fingerprint identification."""
        from uuid import UUID

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from app.config import settings
        from app.services.metadata.audio_identification import get_audio_identification_service

        logger.info(f"Starting bulk identify task {task_id} for {len(track_ids)} tracks")

        progress: dict[str, Any] = {
            "status": "running",
            "phase": "identifying",
            "total_tracks": len(track_ids),
            "processed_tracks": 0,
            "current_track": None,
            "results": [],
            "errors": [],
            "started_at": utcnow().isoformat(),
        }
        self.redis.set(
            f"familiar:identify:{task_id}",
            json.dumps(progress),
            ex=3600,
        )

        engine = create_async_engine(settings.database_url)
        async_session = async_sessionmaker(engine, class_=AsyncSession)

        service = get_audio_identification_service()

        try:
            async with async_session() as db:
                for i, track_id_str in enumerate(track_ids):
                    try:
                        track_id = UUID(track_id_str)

                        progress["current_track"] = track_id_str
                        progress["processed_tracks"] = i
                        self.redis.set(
                            f"familiar:identify:{task_id}",
                            json.dumps(progress),
                            ex=3600,
                        )

                        result = await service.identify_track(
                            track_id=track_id,
                            db=db,
                            min_score=0.5,
                            limit=5,
                        )

                        progress["results"].append(result.to_dict())

                    except Exception as e:
                        logger.error(f"Error identifying track {track_id_str}: {e}")
                        progress["errors"].append(f"Track {track_id_str}: {e}")

                    await asyncio.sleep(1.0)

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

    async def run_new_releases_check(
        self,
        profile_id: str | None = None,
        days_back: int = 90,
        force: bool = False,
    ) -> dict[str, Any]:
        """Kick off a full new-releases check (every library artist, MB only)."""
        from app.services.tasks import run_new_releases_check

        try:
            return await run_new_releases_check(
                profile_id=profile_id, days_back=days_back, force=force
            )
        except Exception as e:
            logger.error(f"new_releases check failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    async def run_prioritized_new_releases_check(
        self,
        profile_id: str,
        batch_size: int = 75,
        days_back: int = 90,
    ) -> dict[str, Any]:
        """Kick off a prioritized batch new-releases check."""
        from app.services.tasks import run_prioritized_new_releases_check

        try:
            return await run_prioritized_new_releases_check(
                profile_id=profile_id, batch_size=batch_size, days_back=days_back
            )
        except Exception as e:
            logger.error(f"prioritized new_releases check failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    async def _discovery_batch(self) -> None:
        """APScheduler entry: one small prioritised batch, for one profile in turn.

        **Profiles take turns rather than the first one always winning.** This used to
        `select(Profile.id).limit(1)`, so on a shared library one listener's play
        history decided what the whole household discovered — while the rows it writes
        are not profile-scoped at all, so everyone saw the result of one person's taste.
        `_daily_external_albums_refresh` directly below already made the opposite choice
        for its own case.

        The cursor lives in Redis because it is a hint, not state worth a table: if it
        is lost the rotation restarts at the first profile, which costs one batch.
        """
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        from app.config import settings
        from app.db.models import Profile
        from app.services.background.manager import DISCOVERY_BATCH_SIZE

        cursor_key = "familiar:discovery:profile_cursor"

        try:
            engine = create_async_engine(settings.database_url)
            async_session = async_sessionmaker(engine, class_=AsyncSession)
            try:
                async with async_session() as db:
                    # Ordered by id so the rotation is stable across restarts — without
                    # an ORDER BY the cursor indexes into an arbitrary order and can
                    # revisit one profile while skipping another indefinitely.
                    result = await db.execute(select(Profile.id).order_by(Profile.id))
                    profile_ids = [str(row[0]) for row in result.all()]
            finally:
                await engine.dispose()

            if not profile_ids:
                logger.info("discovery_batch_skipped", extra={"reason": "no profiles"})
                return

            index = 0
            try:
                raw = get_redis().get(cursor_key)
                if raw is not None:
                    index = int(raw) % len(profile_ids)
            except Exception:
                # A missing or unreadable cursor costs one batch, not a failure.
                index = 0

            profile_id = profile_ids[index]
            try:
                get_redis().set(cursor_key, (index + 1) % len(profile_ids))
            except Exception:
                logger.debug("discovery cursor not persisted", exc_info=True)

            await self.run_prioritized_new_releases_check(
                profile_id=profile_id,
                batch_size=DISCOVERY_BATCH_SIZE,
            )
        except Exception as e:
            logger.warning(f"Discovery batch failed: {e}")

    async def _daily_external_albums_refresh(self) -> None:
        """APScheduler entry: recompute "Albums you might want" for every profile.

        **This is the only thing that recomputes it now.** The endpoint reads the cache and never
        computes, because computing means Last.fm plus MusicBrainz plus Cover Art Archive for every
        seed artist — 71 seconds against the real library, paid by whichever request first found the
        TTL expired. Moving it here trades freshness for a page that loads.

        Every profile, not just the first: unlike new releases, these recommendations are seeded by
        *that* profile's top-played artists, so doing one would leave the others permanently empty.
        One profile's failure does not stop the rest.
        """
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        from app.config import settings
        from app.db.models import Profile
        from app.services.recommendations import RecommendationsService

        try:
            engine = create_async_engine(settings.database_url)
            async_session = async_sessionmaker(engine, class_=AsyncSession)
            try:
                async with async_session() as db:
                    result = await db.execute(select(Profile.id))
                    profile_ids = [row[0] for row in result.all()]

                if not profile_ids:
                    logger.info("Daily external albums refresh: no profiles, skipping")
                    return

                for profile_id in profile_ids:
                    async with async_session() as db:
                        service = RecommendationsService(db)
                        try:
                            rows = await service.get_listening_profile_external_albums(
                                profile_id, refresh=True
                            )
                            await db.commit()
                            logger.info(
                                "Daily external albums refresh: profile %s -> %d album(s)",
                                profile_id,
                                len(rows),
                            )
                        except Exception as e:
                            # One profile with no play history, or a rate-limited third party,
                            # must not cost the others their refresh.
                            logger.warning(
                                "Daily external albums refresh failed for profile %s: %s",
                                profile_id,
                                e,
                            )
                        finally:
                            await service.close()
            finally:
                await engine.dispose()
        except Exception as e:
            logger.warning(f"Daily external albums refresh failed: {e}")

    async def _cleanup_frontend_logs(self) -> None:
        """Delete frontend_logs older than 7 days."""
        from datetime import timedelta

        from sqlalchemy import delete
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from app.config import settings
        from app.db.models import FrontendLog

        try:
            engine = create_async_engine(settings.database_url)
            async_session = async_sessionmaker(engine, class_=AsyncSession)
            cutoff = utcnow() - timedelta(days=7)

            async with async_session() as db:
                result = await db.execute(
                    delete(FrontendLog).where(FrontendLog.server_ts < cutoff)
                )
                await db.commit()
                logger.info(f"Frontend logs cleanup: deleted {result.rowcount} entries older than 7 days")  # type: ignore[attr-defined]

            await engine.dispose()
        except Exception as e:
            logger.warning(f"Frontend logs cleanup failed: {e}")
