"""ExecutorMixin: process pools, circuit breaker, health checks."""

import asyncio
import atexit
import logging
import multiprocessing as mp
import os
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any

from app.config import settings as app_settings
from app.services.background.events import record_background_event

logger = logging.getLogger(__name__)

# Rate limiting for executor recreation to prevent runaway process spawning
EXECUTOR_RESET_COOLDOWN = 30.0  # Minimum seconds between executor resets
EXECUTOR_MAX_CONSECUTIVE_FAILURES = 5  # Max failures before giving up
EXECUTOR_AUTO_RECOVERY_DELAY = 300.0  # Legacy: no longer used for auto-recovery

# Force spawn context to avoid fork issues with numpy/OpenBLAS
mp_context = mp.get_context("spawn")


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


class ExecutorMixin:
    """Mixin providing process pool executors with circuit breaker protection."""

    def _init_executor_state(self) -> None:
        """Initialize executor-related state. Call from __init__."""
        self._executor: ProcessPoolExecutor | None = None
        self._ondemand_executor: ProcessPoolExecutor | None = None
        # Executor rate limiting state
        self._executor_lock = asyncio.Lock()  # Protects executor reset
        self._last_executor_reset: float = 0.0
        self._consecutive_executor_failures: int = 0
        self._executor_disabled: bool = False
        self._executor_disabled_at: float = 0.0
        self._executor_auto_recovery_attempts: int = 0
        # Track current work for crash diagnostics
        self._current_track_id: str | None = None
        self._crashed_track_ids: set[str] = set()
        # Zombie process protection
        self._atexit_registered: bool = False
        self._last_task_started_at: float | None = None

    @property
    def executor(self) -> ProcessPoolExecutor:
        """Lazy ProcessPoolExecutor with spawn context."""
        if self._executor is None:
            self._create_executor()
        return self._executor  # type: ignore[return-value]

    def _create_executor(self) -> None:
        """Create a new ProcessPoolExecutor with spawn context."""
        workers = app_settings.max_analysis_workers
        self._executor = ProcessPoolExecutor(
            max_workers=workers,
            mp_context=mp_context,
            initializer=_analysis_worker_init,
            max_tasks_per_child=1,  # Fresh process per task to prevent memory accumulation
        )
        logger.info(f"ProcessPoolExecutor initialized with spawn context ({workers} worker(s), nice=10, max_tasks_per_child=1)")

        if not self._atexit_registered:
            atexit.register(self._atexit_cleanup)
            self._atexit_registered = True

    @property
    def ondemand_executor(self) -> ProcessPoolExecutor:
        """Lazy ProcessPoolExecutor for on-demand single-track analysis."""
        if self._ondemand_executor is None:
            self._create_ondemand_executor()
        return self._ondemand_executor  # type: ignore[return-value]

    def _create_ondemand_executor(self) -> None:
        """Create a separate ProcessPoolExecutor for on-demand analysis."""
        self._ondemand_executor = ProcessPoolExecutor(
            max_workers=1,
            mp_context=mp_context,
            initializer=_analysis_worker_init,
            max_tasks_per_child=1,  # Fresh process per task to prevent memory accumulation
        )
        logger.info("On-demand ProcessPoolExecutor initialized (1 worker, nice=10, max_tasks_per_child=1)")

    def _reset_executor(self) -> bool:
        """Reset the executor after a crash. Returns True if reset succeeded."""
        if self._executor_disabled:
            logger.error("Executor is disabled due to repeated failures - not resetting")
            return False

        now = time.monotonic()
        time_since_last_reset = now - self._last_executor_reset
        if time_since_last_reset < EXECUTOR_RESET_COOLDOWN:
            logger.warning(
                f"Executor reset rate-limited (last reset {time_since_last_reset:.1f}s ago, "
                f"cooldown is {EXECUTOR_RESET_COOLDOWN}s)"
            )
            return False

        self._consecutive_executor_failures += 1
        if self._consecutive_executor_failures >= EXECUTOR_MAX_CONSECUTIVE_FAILURES:
            self._executor_disabled = True
            self._executor_disabled_at = time.monotonic()
            record_background_event(
                "breaker_disabled",
                {
                    "reason": "max_consecutive_failures",
                    "consecutive_failures": self._consecutive_executor_failures,
                },
            )
            logger.error(
                f"Executor disabled after {self._consecutive_executor_failures} consecutive "
                f"failures. Manual reset required (POST /api/v1/analysis/reset-executor)."
            )
            return False

        if self._executor is not None:
            try:
                self._executor.shutdown(wait=True, cancel_futures=True)
            except Exception:
                pass
            self._executor = None

        self._create_executor()
        self._last_executor_reset = now
        self._executor_auto_recovery_attempts = 0
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
        record_background_event(
            "executor_reset",
            {
                "reason": "broken_process_pool",
                "consecutive_failures": self._consecutive_executor_failures,
                "current_track_id": self._current_track_id,
            },
        )
        return True

    def reset_executor_circuit_breaker(self) -> dict[str, Any]:
        """Manually reset the executor circuit breaker."""
        was_disabled = self._executor_disabled
        old_failure_count = self._consecutive_executor_failures
        crashed_tracks = list(self._crashed_track_ids)

        self._executor_disabled = False
        self._consecutive_executor_failures = 0
        self._last_executor_reset = 0.0
        self._executor_auto_recovery_attempts = 0
        self._crashed_track_ids.clear()

        if self._executor is not None:
            try:
                self._executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            self._executor = None

        self._create_executor()

        logger.info(
            f"Executor circuit breaker manually reset. Was disabled: {was_disabled}, "
            f"failures: {old_failure_count}, crashed tracks: {len(crashed_tracks)}"
        )
        record_background_event(
            "executor_reset",
            {
                "reason": "manual_reset",
                "was_disabled": was_disabled,
                "previous_failure_count": old_failure_count,
                "crashed_track_count": len(crashed_tracks),
            },
        )

        return {
            "status": "reset",
            "was_disabled": was_disabled,
            "previous_failure_count": old_failure_count,
            "crashed_track_ids": crashed_tracks,
        }

    def get_executor_status(self) -> dict[str, Any]:
        """Get current executor circuit breaker status."""
        task_duration = None
        if self._last_task_started_at is not None:
            task_duration = time.monotonic() - self._last_task_started_at
        return {
            "disabled": self._executor_disabled,
            "consecutive_failures": self._consecutive_executor_failures,
            "max_failures": EXECUTOR_MAX_CONSECUTIVE_FAILURES,
            "crashed_track_ids": list(self._crashed_track_ids),
            "last_reset_ago": time.monotonic() - self._last_executor_reset if self._last_executor_reset else None,
            "worker_healthy": self._check_worker_health(),
            "current_task_duration": task_duration,
        }

    def _atexit_cleanup(self) -> None:
        """Last-resort cleanup when the process exits without proper shutdown."""
        for executor in (self._executor, self._ondemand_executor):
            if executor is not None:
                try:
                    executor.shutdown(wait=False, cancel_futures=True)
                except Exception:
                    pass

    def _check_worker_health(self) -> bool:
        """Return False if a task has been running longer than 10 minutes."""
        if self._last_task_started_at is None:
            return True
        return (time.monotonic() - self._last_task_started_at) < 600

    async def _check_and_recover_worker(self) -> None:
        """Periodic health check: if a task is stuck, restart the executor."""
        if self._executor_disabled:
            await self._maybe_auto_recover_disabled_executor(trigger="health_check")
            return

        if self._check_worker_health():
            return

        duration = time.monotonic() - (self._last_task_started_at or 0)
        logger.warning(
            f"Worker appears stuck (task running for {duration:.0f}s, "
            f"track: {self._current_track_id}). Restarting executor."
        )

        if self._current_track_id:
            self._crashed_track_ids.add(self._current_track_id)

        if self._executor is not None:
            try:
                self._executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            self._executor = None

        self._last_task_started_at = None
        self._create_executor()
        record_background_event(
            "executor_reset",
            {
                "reason": "worker_stuck_restart",
                "current_track_id": self._current_track_id,
                "duration_seconds": round(duration, 1),
            },
        )

    async def _maybe_auto_recover_disabled_executor(self, trigger: str) -> bool:
        """Optionally auto-recover a disabled executor with bounded backoff."""
        if not self._executor_disabled:
            return False

        if not app_settings.executor_auto_recovery_enabled:
            return False

        if self._executor_auto_recovery_attempts >= app_settings.executor_auto_recovery_max_attempts:
            return False

        disabled_for = time.monotonic() - self._executor_disabled_at
        if disabled_for < app_settings.executor_auto_recovery_backoff_seconds:
            return False

        self._executor_auto_recovery_attempts += 1
        record_background_event(
            "executor_auto_recovery_attempt",
            {
                "trigger": trigger,
                "attempt": self._executor_auto_recovery_attempts,
                "disabled_for_seconds": round(disabled_for, 1),
            },
        )
        self.reset_executor_circuit_breaker()
        return True

    async def run_cpu_bound(self, func: Callable, *args: Any, max_retries: int = 1) -> Any:
        """Run CPU-bound function in process pool (spawned, not forked).

        If the process pool crashes (BrokenProcessPool), it will be automatically
        recreated and the operation retried once.
        """
        if self._executor_disabled:
            recovered = await self._maybe_auto_recover_disabled_executor(trigger="run_cpu_bound")
            if recovered:
                logger.info("Executor auto-recovery succeeded; continuing analysis task")
            else:
                raise RuntimeError(
                    "Process pool executor is disabled due to repeated OOM failures. "
                    "Reset manually via POST /api/v1/analysis/reset-executor "
                    "or restart the container with more memory."
                )

        if self._executor_disabled:
            raise RuntimeError(
                "Process pool executor is disabled due to repeated OOM failures. "
                "Reset manually via POST /api/v1/analysis/reset-executor "
                "or restart the container with more memory."
            )

        loop = asyncio.get_event_loop()
        retries = 0
        last_error: Exception | None = None

        while retries <= max_retries:
            try:
                result = await loop.run_in_executor(self.executor, func, *args)
                self._consecutive_executor_failures = 0
                return result
            except BrokenProcessPool as e:
                last_error = e
                if retries < max_retries:
                    async with self._executor_lock:
                        if self._executor_disabled:
                            raise RuntimeError(
                                "Process pool executor is disabled due to repeated failures"
                            )

                        time_since_reset = time.monotonic() - self._last_executor_reset
                        if time_since_reset < EXECUTOR_RESET_COOLDOWN:
                            logger.info(
                                f"Executor was reset {time_since_reset:.1f}s ago by another task, "
                                "retrying with fresh executor"
                            )
                        else:
                            logger.warning(
                                f"Process pool crashed, attempting reset "
                                f"(attempt {retries + 1}/{max_retries + 1})"
                            )
                            reset_ok = self._reset_executor()
                            if not reset_ok:
                                raise RuntimeError(
                                    "Process pool executor is disabled due to repeated failures"
                                ) from e

                    retries += 1
                else:
                    # Count exhausted retries toward circuit breaker
                    self._consecutive_executor_failures += 1
                    if self._consecutive_executor_failures >= EXECUTOR_MAX_CONSECUTIVE_FAILURES:
                        self._executor_disabled = True
                        self._executor_disabled_at = time.monotonic()
                        record_background_event(
                            "breaker_disabled",
                            {
                                "reason": "retry_exhausted",
                                "consecutive_failures": self._consecutive_executor_failures,
                            },
                        )
                        logger.error(
                            f"Executor disabled after {self._consecutive_executor_failures} "
                            f"consecutive failures. Manual reset required "
                            f"(POST /api/v1/analysis/reset-executor)."
                        )
                    raise
        raise last_error  # type: ignore[misc]

    async def run_cpu_bound_ondemand(self, func: Callable, *args: Any) -> Any:
        """Run CPU-bound function in the on-demand process pool."""
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(self.ondemand_executor, func, *args)
        except BrokenProcessPool:
            logger.warning("On-demand executor crashed, recreating")
            if self._ondemand_executor is not None:
                try:
                    self._ondemand_executor.shutdown(wait=False, cancel_futures=True)
                except Exception:
                    pass
                self._ondemand_executor = None
            return await loop.run_in_executor(self.ondemand_executor, func, *args)
