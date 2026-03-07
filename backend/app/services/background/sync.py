"""SyncMixin: Redis locks, run_sync, spotify_sync, maintenance."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from app.utils.time import utcnow

if TYPE_CHECKING:
    from app.services.background._typing import _BackgroundManagerProtocol

    _SyncBase = _BackgroundManagerProtocol
else:
    _SyncBase = object

logger = logging.getLogger(__name__)


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
                            if age < timedelta(seconds=60):
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
                        if age > timedelta(seconds=60):
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
        if self._current_sync_task and not self._current_sync_task.done():
            self._current_sync_task.cancel()
        self._release_sync_lock()

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
            return result
        except Exception as e:
            logger.error(f"Sync failed: {e}", exc_info=True)
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

