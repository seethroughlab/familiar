"""AnalysisMixin: run_analysis, phase orchestration, batch, on-demand."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.background._typing import _BackgroundManagerProtocol

    _AnalysisBase = _BackgroundManagerProtocol
else:
    _AnalysisBase = object

logger = logging.getLogger(__name__)


class AnalysisMixin(_AnalysisBase):
    """Mixin providing analysis task management for BackgroundManager."""

    def _init_analysis_state(self) -> None:
        """Initialize analysis-related state. Call from __init__."""
        self._analysis_tasks: dict[str, asyncio.Task] = {}

    def is_analysis_running(self) -> bool:
        """Check if any analysis tasks are currently running."""
        completed = [tid for tid, task in self._analysis_tasks.items() if task.done()]
        for tid in completed:
            self._analysis_tasks.pop(tid, None)
        return len(self._analysis_tasks) > 0

    def get_analysis_task_count(self) -> int:
        """Get the number of active analysis tasks."""
        completed = [tid for tid, task in self._analysis_tasks.items() if task.done()]
        for tid in completed:
            self._analysis_tasks.pop(tid, None)
        return len(self._analysis_tasks)

    async def run_analysis(
        self,
        track_id: str,
        phase: str = "full",
    ) -> dict[str, Any]:
        """Queue a track for analysis.

        Args:
            track_id: Track UUID
            phase: Which phase to run:
                - "full": Features + embeddings (default)
                - "features": Only extract features
                - "embedding": Only generate CLAP embedding
        """
        task_key = f"{track_id}:{phase}"

        if task_key in self._analysis_tasks:
            task = self._analysis_tasks[task_key]
            if not task.done():
                return {"status": "already_queued"}

        if phase == "features":
            task = asyncio.create_task(self._do_features(track_id))
        elif phase == "embedding":
            task = asyncio.create_task(self._do_embedding(track_id))
        elif phase == "deep_backfill":
            task = asyncio.create_task(self._do_backfill(track_id))
        elif phase == "melodic":
            task = asyncio.create_task(self._do_melodic(track_id))
        else:
            task = asyncio.create_task(self._do_analysis(track_id))

        self._analysis_tasks[task_key] = task
        return {"status": "queued"}

    async def _do_features(self, track_id: str) -> dict[str, Any]:
        """Execute feature extraction only (Phase 1)."""
        from app.services.tasks import run_track_features

        task_key = f"{track_id}:features"
        try:
            self._current_track_id = track_id
            self._last_task_started_at = time.monotonic()
            result = await self.run_cpu_bound(run_track_features, track_id)
            return result
        except Exception as e:
            logger.error(f"Feature extraction failed for {track_id}: {e}")
            return {"status": "error", "error": str(e)}
        finally:
            self._current_track_id = None
            self._last_task_started_at = None
            self._analysis_tasks.pop(task_key, None)

    async def _do_embedding(self, track_id: str) -> dict[str, Any]:
        """Execute embedding generation only (Phase 2)."""
        import os

        from app.services.tasks import run_track_embedding

        task_key = f"{track_id}:embedding"
        try:
            clap_disabled = os.environ.get("DISABLE_CLAP_EMBEDDINGS", "").lower() in (
                "1", "true", "yes"
            )
            if clap_disabled:
                return {"status": "skipped", "embedding_generated": False}

            self._current_track_id = track_id
            self._last_task_started_at = time.monotonic()
            result = await self.run_cpu_bound(run_track_embedding, track_id)
            return result
        except Exception as e:
            logger.error(f"Embedding generation failed for {track_id}: {e}")
            return {"status": "error", "error": str(e)}
        finally:
            self._current_track_id = None
            self._last_task_started_at = None
            self._analysis_tasks.pop(task_key, None)

    async def _do_backfill(self, track_id: str) -> dict[str, Any]:
        """Execute analysis backfill (cheap sections only)."""
        from app.services.track_analysis import run_backfill

        task_key = f"{track_id}:deep_backfill"
        try:
            self._current_track_id = track_id
            self._last_task_started_at = time.monotonic()
            result = await self.run_cpu_bound(run_backfill, track_id)
            return result
        except Exception as e:
            logger.error(f"Backfill failed for {track_id}: {e}")
            return {"status": "error", "error": str(e)}
        finally:
            self._current_track_id = None
            self._last_task_started_at = None
            self._analysis_tasks.pop(task_key, None)

    async def _do_melodic(self, track_id: str) -> dict[str, Any]:
        """Execute melodic analysis only (Phase 3)."""
        from app.services.track_analysis import run_track_melodic

        task_key = f"{track_id}:melodic"
        try:
            self._current_track_id = track_id
            self._last_task_started_at = time.monotonic()
            result = await self.run_cpu_bound(run_track_melodic, track_id)
            return result
        except Exception as e:
            logger.error(f"Melodic analysis failed for {track_id}: {e}")
            return {"status": "error", "error": str(e)}
        finally:
            self._current_track_id = None
            self._last_task_started_at = None
            self._analysis_tasks.pop(task_key, None)

    async def _do_analysis(self, track_id: str) -> dict[str, Any]:
        """Execute full track analysis in process pool (features + embedding)."""
        import os

        from app.services.tasks import run_track_embedding, run_track_features

        task_key = f"{track_id}:full"
        try:
            self._current_track_id = track_id
            self._last_task_started_at = time.monotonic()

            features_result = await self.run_cpu_bound(run_track_features, track_id)
            if features_result.get("status") != "success":
                return features_result

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
            self._last_task_started_at = None
            self._analysis_tasks.pop(task_key, None)

    async def run_track_analysis(self, track_id: str) -> dict[str, Any]:
        """Run track analysis in process pool."""
        from app.services.track_analysis import run_analysis

        task_key = f"{track_id}:deep"

        if task_key in self._analysis_tasks:
            task = self._analysis_tasks[task_key]
            if not task.done():
                return {"status": "already_queued"}

        async def _do_deep(tid: str) -> dict[str, Any]:
            try:
                self._current_track_id = tid
                self._last_task_started_at = time.monotonic()
                result = await self.run_cpu_bound(run_analysis, tid)
                return result
            except Exception as e:
                logger.error(f"Analysis failed for {tid}: {e}")
                return {"status": "error", "error": str(e)}
            finally:
                self._current_track_id = None
                self._last_task_started_at = None
                self._analysis_tasks.pop(task_key, None)

        task = asyncio.create_task(_do_deep(track_id))
        self._analysis_tasks[task_key] = task
        return {"status": "queued", "task_key": task_key}

    async def run_track_analysis_full(self, track_id: str) -> dict[str, Any]:
        """Run the full analysis pipeline for a single track on-demand."""
        import os

        from app.services.tasks import run_track_embedding, run_track_features
        from app.services.track_analysis import run_analysis

        task_key = f"{track_id}:full_ondemand"

        if task_key in self._analysis_tasks:
            task = self._analysis_tasks[task_key]
            if not task.done():
                return {"status": "already_queued"}

        async def _do_full_ondemand(tid: str) -> dict[str, Any]:
            from uuid import UUID

            from sqlalchemy import select
            from sqlalchemy.ext.asyncio import (
                AsyncSession,
                async_sessionmaker,
                create_async_engine,
            )

            from app.config import EMBEDDING_VERSION, FEATURES_VERSION
            from app.db.models import TrackAnalysis

            try:
                from app.config import settings as app_settings

                engine = create_async_engine(app_settings.database_url)
                async_session = async_sessionmaker(engine, class_=AsyncSession)

                need_features = True
                need_embedding = True

                try:
                    async with async_session() as db:
                        analysis = (
                            await db.execute(
                                select(TrackAnalysis).where(
                                    TrackAnalysis.track_id == UUID(tid)
                                )
                            )
                        ).scalar_one_or_none()

                        if analysis:
                            need_features = (
                                analysis.features_version is None
                                or analysis.features_version < FEATURES_VERSION
                            )
                            need_embedding = (
                                analysis.embedding_version is None
                                or analysis.embedding_version < EMBEDDING_VERSION
                            )
                finally:
                    await engine.dispose()

                if need_features:
                    logger.info(f"On-demand full: running features for {tid}")
                    result = await self.run_cpu_bound_ondemand(run_track_features, tid)
                    if result.get("status") == "error":
                        return result

                clap_disabled = os.environ.get("DISABLE_CLAP_EMBEDDINGS", "").lower() in (
                    "1", "true", "yes"
                )
                if need_embedding and not clap_disabled:
                    logger.info(f"On-demand full: running embedding for {tid}")
                    await self.run_cpu_bound_ondemand(run_track_embedding, tid)

                logger.info(f"On-demand full: running deep analysis for {tid}")
                result = await self.run_cpu_bound_ondemand(run_analysis, tid)
                return result

            except Exception as e:
                logger.error(f"On-demand full analysis failed for {tid}: {e}")
                return {"status": "error", "error": str(e)}
            finally:
                self._analysis_tasks.pop(task_key, None)

        task = asyncio.create_task(_do_full_ondemand(track_id))
        self._analysis_tasks[task_key] = task
        return {"status": "queued", "task_key": task_key}

    async def run_analyses_for_download(
        self,
        task_id: str,
        track_ids: list[str],
    ) -> dict[str, Any]:
        """Run analysis for multiple tracks (for download ZIP)."""
        from app.services.tasks import run_track_embedding, run_track_features
        from app.services.track_analysis import run_analysis

        redis_key = f"familiar:download_analysis:{task_id}"
        logger.info(f"Starting analyses for download {task_id}: {len(track_ids)} tracks")

        progress: dict[str, Any] = {
            "status": "processing",
            "completed": 0,
            "total": len(track_ids),
            "needs_analysis": len(track_ids),
            "errors": [],
        }
        self.redis.set(redis_key, json.dumps(progress), ex=3600)

        for i, tid in enumerate(track_ids):
            try:
                await self.run_cpu_bound_ondemand(run_track_features, tid)
                await self.run_cpu_bound_ondemand(run_track_embedding, tid)
                await self.run_cpu_bound_ondemand(run_analysis, tid)
            except Exception as e:
                logger.error(f"Analysis for download failed for {tid}: {e}")
                progress["errors"].append({"track_id": tid, "error": str(e)})

            progress["completed"] = i + 1
            self.redis.set(redis_key, json.dumps(progress), ex=3600)

        progress["status"] = "ready"
        self.redis.set(redis_key, json.dumps(progress), ex=3600)

        logger.info(
            f"Analyses for download {task_id} completed: "
            f"{progress['completed']}/{progress['total']}, {len(progress['errors'])} errors"
        )
        return {"status": "ready", "task_id": task_id}

    async def run_bulk_analysis(
        self,
        task_id: str,
        track_ids: list[str],
    ) -> dict[str, Any]:
        """Run analysis for multiple tracks with Redis progress tracking."""
        from app.services.track_analysis import run_analysis

        logger.info(f"Starting bulk analysis {task_id} for {len(track_ids)} tracks")

        progress: dict[str, Any] = {
            "status": "processing",
            "completed": 0,
            "total": len(track_ids),
            "track_ids": track_ids,
            "errors": [],
        }
        self.redis.set(
            f"familiar:analysis:{task_id}",
            json.dumps(progress),
            ex=3600,
        )

        for i, tid in enumerate(track_ids):
            try:
                self._current_track_id = tid
                self._last_task_started_at = time.monotonic()
                result = await self.run_cpu_bound(run_analysis, tid)

                if result.get("status") == "error":
                    progress["errors"].append({"track_id": tid, "error": result["error"]})
            except Exception as e:
                logger.error(f"Bulk analysis failed for {tid}: {e}")
                progress["errors"].append({"track_id": tid, "error": str(e)})
            finally:
                self._current_track_id = None
                self._last_task_started_at = None

            progress["completed"] = i + 1
            self.redis.set(
                f"familiar:analysis:{task_id}",
                json.dumps(progress),
                ex=3600,
            )

        progress["status"] = "completed"
        self.redis.set(
            f"familiar:analysis:{task_id}",
            json.dumps(progress),
            ex=3600,
        )

        logger.info(
            f"Bulk analysis {task_id} completed: "
            f"{progress['completed']}/{progress['total']}, {len(progress['errors'])} errors"
        )

        return {"status": "completed", "task_id": task_id}
