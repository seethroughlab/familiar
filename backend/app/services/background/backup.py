"""BackupMixin: S3 backup, Glacier restore, schedule registration."""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class BackupMixin:
    """Mixin providing S3 backup and restore management for BackgroundManager."""

    async def _post_sync_backup(self) -> None:
        """Trigger S3 backup after a successful library sync, if enabled."""
        try:
            from app.services.app_settings import get_app_settings_service

            settings = get_app_settings_service().get()
            if not settings.s3_backup_enabled or not settings.s3_backup_bucket:
                return

            logger.info("Post-sync S3 backup triggered")
            await self.run_s3_backup()
        except Exception as e:
            logger.warning(f"Post-sync S3 backup failed (non-fatal): {e}")

    async def run_s3_backup(self) -> dict[str, Any]:
        """Run S3 backup in a thread executor (boto3 is synchronous)."""
        from app.services.s3_backup import get_s3_backup_service

        service = get_s3_backup_service()
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, service.run_backup)
            return result
        except Exception as e:
            logger.error(f"S3 backup failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    async def _scheduled_s3_backup(self) -> None:
        """Run scheduled S3 backup."""
        logger.info("Starting scheduled S3 backup")
        try:
            result = await self.run_s3_backup()
            logger.info(f"Scheduled S3 backup completed: {result.get('status')}")
        except Exception as e:
            logger.error(f"Scheduled S3 backup failed: {e}", exc_info=True)

    async def _check_restore_status(self) -> None:
        """Periodically check Glacier retrieval status."""
        from app.services.s3_backup import get_s3_backup_service

        service = get_s3_backup_service()
        loop = asyncio.get_event_loop()
        try:
            state = await loop.run_in_executor(None, service.check_restore_status)
            if state.get("status") == "available":
                logger.info("Glacier retrieval complete — files are now available for download")
                if self._scheduler:
                    try:
                        self._scheduler.remove_job("s3_restore_checker")
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Restore status check failed: {e}")

    def _register_s3_backup_schedule(self) -> None:
        """Register or update the S3 backup APScheduler job based on settings."""
        from apscheduler.triggers.cron import CronTrigger

        from app.services.app_settings import get_app_settings_service

        settings = get_app_settings_service().get()

        if self._scheduler:
            try:
                self._scheduler.remove_job("s3_backup")
            except Exception:
                pass

        if not settings.s3_backup_enabled:
            return

        schedule_map = {
            "daily": CronTrigger(hour=3, minute=30),
            "weekly": CronTrigger(day_of_week=0, hour=3, minute=30),
            "monthly": CronTrigger(day=1, hour=3, minute=30),
        }
        trigger = schedule_map.get(settings.s3_backup_schedule, schedule_map["weekly"])

        if self._scheduler:
            self._scheduler.add_job(
                self._scheduled_s3_backup,
                trigger,
                id="s3_backup",
                replace_existing=True,
            )
            logger.info(f"S3 backup scheduled: {settings.s3_backup_schedule}")

    def register_restore_checker(self) -> None:
        """Register a periodic restore status checker (every 30 min)."""
        if not self._scheduler:
            return

        from apscheduler.triggers.interval import IntervalTrigger

        try:
            self._scheduler.remove_job("s3_restore_checker")
        except Exception:
            pass

        self._scheduler.add_job(
            self._check_restore_status,
            IntervalTrigger(minutes=30),
            id="s3_restore_checker",
            replace_existing=True,
        )
        logger.info("S3 restore status checker registered (every 30 min)")
