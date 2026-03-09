"""Tests for the background task manager service.

Tests cover task scheduling, executor circuit breaker, sync locking, and task deduplication.
Uses mocked Redis and ProcessPoolExecutor.
"""

import asyncio
import json
import time
from concurrent.futures.process import BrokenProcessPool
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.background import (
    EXECUTOR_MAX_CONSECUTIVE_FAILURES,
    SYNC_HEARTBEAT_STALE_SECONDS,
    BackgroundManager,
    get_background_manager,
)


class TestBackgroundManagerInit:
    """Tests for BackgroundManager initialization."""

    def test_initial_state(self):
        """Manager should initialize with correct default state."""
        manager = BackgroundManager()

        assert manager._executor is None
        assert manager._redis is None
        assert manager._current_sync_task is None
        assert manager._analysis_tasks == {}
        assert manager._executor_disabled is False
        assert manager._consecutive_executor_failures == 0

    def test_executor_created_lazily(self):
        """Executor should be created on first access."""
        manager = BackgroundManager()
        assert manager._executor is None

        with patch.object(manager, "_create_executor") as mock_create:
            _ = manager.executor
            mock_create.assert_called_once()


class TestExecutorCircuitBreaker:
    """Tests for executor circuit breaker logic."""

    def test_get_executor_status(self):
        """Status should return circuit breaker state."""
        manager = BackgroundManager()
        status = manager.get_executor_status()

        assert "disabled" in status
        assert "consecutive_failures" in status
        assert "max_failures" in status
        assert status["disabled"] is False
        assert status["consecutive_failures"] == 0

    def test_reset_executor_increments_failure_count(self):
        """Each reset should increment failure count."""
        manager = BackgroundManager()
        manager._executor = MagicMock()  # Fake executor exists

        # First reset should succeed
        result = manager._reset_executor()
        assert result is True
        assert manager._consecutive_executor_failures == 1

    def test_reset_executor_rate_limited(self):
        """Resets should be rate-limited."""
        manager = BackgroundManager()
        manager._executor = MagicMock()

        # First reset succeeds
        manager._reset_executor()
        assert manager._consecutive_executor_failures == 1

        # Immediate second reset should be rate-limited
        result = manager._reset_executor()
        assert result is False
        assert manager._consecutive_executor_failures == 1  # Not incremented

    def test_reset_executor_disables_after_max_failures(self):
        """Executor should be disabled after too many failures."""
        manager = BackgroundManager()
        manager._executor = MagicMock()

        # Simulate consecutive failures by bypassing rate limiting
        for i in range(EXECUTOR_MAX_CONSECUTIVE_FAILURES):
            manager._last_executor_reset = 0  # Bypass cooldown
            manager._reset_executor()

        assert manager._executor_disabled is True

        # Next reset should fail because disabled
        result = manager._reset_executor()
        assert result is False

    def test_reset_circuit_breaker_manual(self):
        """Manual reset should clear circuit breaker state."""
        manager = BackgroundManager()
        manager._executor_disabled = True
        manager._consecutive_executor_failures = 5
        manager._crashed_track_ids = {"track1", "track2"}

        result = manager.reset_executor_circuit_breaker()

        assert result["was_disabled"] is True
        assert result["previous_failure_count"] == 5
        assert len(result["crashed_track_ids"]) == 2
        assert manager._executor_disabled is False
        assert manager._consecutive_executor_failures == 0


class TestSyncLocking:
    """Tests for sync lock management."""

    @pytest.fixture
    def manager_with_redis(self):
        """Create manager with mocked Redis."""
        manager = BackgroundManager()
        manager._redis = MagicMock()
        return manager

    def test_acquire_sync_lock_success(self, manager_with_redis):
        """Lock acquisition should return True on success."""
        manager_with_redis._redis.set.return_value = True

        result = manager_with_redis._acquire_sync_lock()

        assert result is True
        manager_with_redis._redis.set.assert_called_once()
        call_args = manager_with_redis._redis.set.call_args
        assert call_args[0][0] == "familiar:sync:lock"
        assert call_args[1]["nx"] is True

    def test_acquire_sync_lock_already_locked(self, manager_with_redis):
        """Lock acquisition should return False when lock exists."""
        manager_with_redis._redis.set.return_value = False

        result = manager_with_redis._acquire_sync_lock()
        assert result is False

    def test_release_sync_lock(self, manager_with_redis):
        """Lock release should delete the Redis key."""
        manager_with_redis._release_sync_lock()

        manager_with_redis._redis.delete.assert_called_with("familiar:sync:lock")

    def test_is_sync_running_with_local_task(self, manager_with_redis):
        """Should return True when local sync task exists."""
        manager_with_redis._current_sync_task = MagicMock()
        manager_with_redis._current_sync_task.done.return_value = False

        assert manager_with_redis.is_sync_running() is True

    def test_is_sync_running_completed_task(self, manager_with_redis):
        """Should check Redis when local task is done."""
        manager_with_redis._current_sync_task = MagicMock()
        manager_with_redis._current_sync_task.done.return_value = True
        manager_with_redis._redis.get.return_value = None

        assert manager_with_redis.is_sync_running() is False

    def test_is_sync_running_uses_shared_staleness_threshold(self, manager_with_redis):
        """Heartbeat younger than threshold should be considered running."""
        from datetime import timedelta

        from app.utils.time import utcnow

        manager_with_redis._current_sync_task = None
        recent_heartbeat = (utcnow() - timedelta(seconds=SYNC_HEARTBEAT_STALE_SECONDS - 1)).isoformat()
        manager_with_redis._redis.get.side_effect = [
            b"1",
            json.dumps({"status": "running", "last_heartbeat": recent_heartbeat}).encode(),
        ]

        assert manager_with_redis.is_sync_running() is True


class TestAnalysisTaskManagement:
    """Tests for analysis task tracking."""

    @pytest.fixture
    def manager(self):
        """Create a BackgroundManager instance."""
        return BackgroundManager()

    def test_is_analysis_running_initially_false(self, manager):
        """No analysis should be running initially."""
        assert manager.is_analysis_running() is False

    def test_get_analysis_task_count_initially_zero(self, manager):
        """Task count should be zero initially."""
        assert manager.get_analysis_task_count() == 0

    def test_is_analysis_running_with_active_task(self, manager):
        """Should return True with active task."""
        mock_task = MagicMock()
        mock_task.done.return_value = False
        manager._analysis_tasks["track1:full"] = mock_task

        assert manager.is_analysis_running() is True

    def test_is_analysis_running_cleans_completed(self, manager):
        """Should clean up completed tasks."""
        mock_task = MagicMock()
        mock_task.done.return_value = True
        manager._analysis_tasks["track1:full"] = mock_task

        result = manager.is_analysis_running()

        assert result is False
        assert "track1:full" not in manager._analysis_tasks

    def test_get_analysis_task_count_cleans_completed(self, manager):
        """Task count should clean up completed tasks."""
        completed_task = MagicMock()
        completed_task.done.return_value = True

        active_task = MagicMock()
        active_task.done.return_value = False

        manager._analysis_tasks = {
            "track1:full": completed_task,
            "track2:full": active_task,
        }

        count = manager.get_analysis_task_count()

        assert count == 1
        assert "track1:full" not in manager._analysis_tasks
        assert "track2:full" in manager._analysis_tasks


class TestRunAnalysis:
    """Tests for run_analysis method."""

    @pytest.fixture
    def manager(self):
        """Create a BackgroundManager instance."""
        return BackgroundManager()

    @pytest.mark.asyncio
    async def test_run_analysis_returns_already_queued(self, manager):
        """Should return already_queued if task exists."""
        mock_task = MagicMock()
        mock_task.done.return_value = False
        manager._analysis_tasks["track1:full"] = mock_task

        result = await manager.run_analysis("track1", phase="full")

        assert result["status"] == "already_queued"

    @pytest.mark.asyncio
    async def test_run_analysis_creates_task_for_features(self, manager):
        """Should create task for features phase."""
        with patch.object(manager, "_do_features", new_callable=AsyncMock) as mock_do:
            mock_do.return_value = {"status": "success"}
            result = await manager.run_analysis("track1", phase="features")

            assert result["status"] == "queued"
            assert "track1:features" in manager._analysis_tasks

    @pytest.mark.asyncio
    async def test_run_analysis_creates_task_for_embedding(self, manager):
        """Should create task for embedding phase."""
        with patch.object(manager, "_do_embedding", new_callable=AsyncMock) as mock_do:
            mock_do.return_value = {"status": "success"}
            result = await manager.run_analysis("track1", phase="embedding")

            assert result["status"] == "queued"
            assert "track1:embedding" in manager._analysis_tasks


class TestRunCpuBound:
    """Tests for run_cpu_bound method."""

    @pytest.fixture
    def manager(self):
        """Create a BackgroundManager instance."""
        manager = BackgroundManager()
        manager._executor = MagicMock()
        return manager

    @pytest.mark.asyncio
    async def test_run_cpu_bound_success(self, manager):
        """Successful execution should return result."""
        def test_func(x):
            return x * 2

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(return_value=10)

            result = await manager.run_cpu_bound(test_func, 5)

            assert result == 10

    @pytest.mark.asyncio
    async def test_run_cpu_bound_resets_failure_count(self, manager):
        """Successful execution should reset failure count."""
        manager._consecutive_executor_failures = 3

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(return_value=42)

            await manager.run_cpu_bound(lambda x: x, 1)

            assert manager._consecutive_executor_failures == 0

    @pytest.mark.asyncio
    async def test_run_cpu_bound_disabled_executor_raises(self, manager):
        """Should raise when executor is disabled."""
        manager._executor_disabled = True
        manager._executor_disabled_at = time.monotonic()

        def identity(x):
            return x

        with pytest.raises(RuntimeError, match="disabled"):
            await manager.run_cpu_bound(identity, 1)

    @pytest.mark.asyncio
    async def test_run_cpu_bound_handles_broken_pool(self, manager):
        """Should handle BrokenProcessPool by resetting."""
        call_count = 0

        async def mock_run_in_executor(executor, func, *args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise BrokenProcessPool()
            return 42

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = mock_run_in_executor
            with patch.object(manager, "_reset_executor", return_value=True):
                result = await manager.run_cpu_bound(lambda x: x, 1)

                assert result == 42
                assert call_count == 2


class TestExecutorAutoRecovery:
    """Tests for optional disabled-executor auto recovery."""

    @pytest.fixture
    def manager(self):
        manager = BackgroundManager()
        manager._executor = MagicMock()
        return manager

    @pytest.mark.asyncio
    async def test_auto_recovery_disabled_by_default(self, manager):
        manager._executor_disabled = True
        manager._executor_disabled_at = time.monotonic() - 9999

        with patch("app.services.background.executors.app_settings.executor_auto_recovery_enabled", False):
            recovered = await manager._maybe_auto_recover_disabled_executor(trigger="test")
            assert recovered is False

    @pytest.mark.asyncio
    async def test_auto_recovery_resets_after_backoff(self, manager):
        manager._executor_disabled = True
        manager._executor_disabled_at = time.monotonic() - 9999
        manager._consecutive_executor_failures = 5

        with patch("app.services.background.executors.app_settings.executor_auto_recovery_enabled", True), \
             patch("app.services.background.executors.app_settings.executor_auto_recovery_backoff_seconds", 1), \
             patch("app.services.background.executors.app_settings.executor_auto_recovery_max_attempts", 3), \
             patch.object(manager, "reset_executor_circuit_breaker") as reset_mock:
            recovered = await manager._maybe_auto_recover_disabled_executor(trigger="test")
            assert recovered is True
            reset_mock.assert_called_once()


class TestRunSync:
    """Tests for run_sync method."""

    @pytest.fixture
    def manager_with_redis(self):
        """Create manager with mocked Redis."""
        manager = BackgroundManager()
        manager._redis = MagicMock()
        manager._redis.get.return_value = None
        manager._redis.set.return_value = True
        return manager

    @pytest.mark.asyncio
    async def test_run_sync_starts_task(self, manager_with_redis):
        """Should start sync task and return started status."""
        result = await manager_with_redis.run_sync()

        assert result["status"] == "started"
        assert manager_with_redis._current_sync_task is not None

        # Clean up
        manager_with_redis._current_sync_task.cancel()
        try:
            await manager_with_redis._current_sync_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_run_sync_returns_already_running(self, manager_with_redis):
        """Should return already_running when sync is active."""
        # Simulate running sync
        manager_with_redis._current_sync_task = MagicMock()
        manager_with_redis._current_sync_task.done.return_value = False

        result = await manager_with_redis.run_sync()

        assert result["status"] == "already_running"

    @pytest.mark.asyncio
    async def test_run_sync_fails_to_acquire_lock(self, manager_with_redis):
        """Should return already_running when lock fails."""
        manager_with_redis._redis.set.return_value = False

        result = await manager_with_redis.run_sync()

        assert result["status"] == "already_running"


class TestCleanupStaleRedisState:
    """Tests for stale Redis state cleanup."""

    @pytest.fixture
    def manager_with_redis(self):
        """Create manager with mocked Redis."""
        manager = BackgroundManager()
        manager._redis = MagicMock()
        return manager

    def test_cleanup_clears_running_state(self, manager_with_redis):
        """Should clear running state on startup."""
        stale_progress = json.dumps({
            "status": "running",
            "phase": "scanning",
            "last_heartbeat": "2024-01-01T00:00:00"
        }).encode()
        manager_with_redis._redis.get.return_value = stale_progress

        manager_with_redis._cleanup_stale_redis_state()

        manager_with_redis._redis.delete.assert_called()

    def test_cleanup_ignores_non_running_state(self, manager_with_redis):
        """Should not clear completed/error states."""
        completed_progress = json.dumps({
            "status": "completed",
        }).encode()
        manager_with_redis._redis.get.return_value = completed_progress

        manager_with_redis._cleanup_stale_redis_state()

        manager_with_redis._redis.delete.assert_not_called()

    def test_cleanup_handles_no_state(self, manager_with_redis):
        """Should handle missing Redis state."""
        manager_with_redis._redis.get.return_value = None

        # Should not raise
        manager_with_redis._cleanup_stale_redis_state()


class TestStartupShutdown:
    """Tests for startup and shutdown lifecycle."""

    @pytest.fixture
    def manager(self):
        """Create a BackgroundManager instance."""
        return BackgroundManager()

    @pytest.mark.asyncio
    async def test_shutdown_cancels_sync_task(self, manager):
        """Shutdown should cancel running sync task."""
        # Create a real asyncio task that we can cancel
        async def long_running():
            await asyncio.sleep(100)

        task = asyncio.create_task(long_running())
        manager._current_sync_task = task

        await manager.shutdown()

        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_shutdown_cancels_analysis_tasks(self, manager):
        """Shutdown should cancel analysis tasks."""
        mock_task = MagicMock()
        mock_task.done.return_value = False
        manager._analysis_tasks = {"track1:full": mock_task}

        await manager.shutdown()

        mock_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_stops_scheduler(self, manager):
        """Shutdown should stop scheduler."""
        mock_scheduler = MagicMock()
        manager._scheduler = mock_scheduler

        await manager.shutdown()

        mock_scheduler.shutdown.assert_called_with(wait=False)

    @pytest.mark.asyncio
    async def test_shutdown_shuts_down_executor(self, manager):
        """Shutdown should shut down executor."""
        mock_executor = MagicMock()
        manager._executor = mock_executor

        await manager.shutdown()

        mock_executor.shutdown.assert_called_with(wait=False)


class TestGetBackgroundManager:
    """Tests for the singleton getter."""

    def test_returns_singleton(self):
        """Should return the same instance."""
        import app.services.background as bg_module

        # Reset singleton
        bg_module._background_manager = None

        manager1 = get_background_manager()
        manager2 = get_background_manager()

        assert manager1 is manager2

        # Clean up
        bg_module._background_manager = None


class TestCrashedTrackTracking:
    """Tests for crashed track ID tracking."""

    def test_reset_executor_tracks_crashed_track(self):
        """Executor reset should track current track ID."""
        manager = BackgroundManager()
        manager._executor = MagicMock()
        manager._current_track_id = "track-123"

        manager._reset_executor()

        assert "track-123" in manager._crashed_track_ids

    def test_reset_circuit_breaker_clears_crashed_tracks(self):
        """Manual reset should clear crashed track list."""
        manager = BackgroundManager()
        manager._crashed_track_ids = {"track1", "track2", "track3"}

        manager.reset_executor_circuit_breaker()

        assert len(manager._crashed_track_ids) == 0

    def test_get_executor_status_includes_crashed_tracks(self):
        """Status should include crashed track IDs."""
        manager = BackgroundManager()
        manager._crashed_track_ids = {"track1", "track2"}

        status = manager.get_executor_status()

        assert len(status["crashed_track_ids"]) == 2
        assert "track1" in status["crashed_track_ids"]


class TestCancelSync:
    """Tests for sync cancellation."""

    def test_cancel_sync_cancels_task(self):
        """Public cancel should cancel running task and return semantics."""
        manager = BackgroundManager()
        manager._redis = MagicMock()

        mock_task = MagicMock()
        mock_task.done.return_value = False
        manager._current_sync_task = mock_task

        result = manager.cancel_sync()

        mock_task.cancel.assert_called_once()
        manager._redis.delete.assert_called_with("familiar:sync:lock")
        assert result["requested"] is True
        assert result["in_process_tasks_cancelled"] == 1
        assert result["subprocess_may_continue"] is True

    def test_cancel_sync_no_task(self):
        """Public cancel should handle no running task."""
        manager = BackgroundManager()
        manager._redis = MagicMock()
        manager._current_sync_task = None

        # Should not raise
        result = manager.cancel_sync()
        manager._redis.delete.assert_called()
        assert result["requested"] is True
        assert result["in_process_tasks_cancelled"] == 0
        assert result["subprocess_may_continue"] is False

    def test_cancel_sync_legacy_private_method_delegates(self):
        """Private alias should delegate to public method for compatibility."""
        manager = BackgroundManager()
        manager._redis = MagicMock()
        with patch.object(manager, "cancel_sync", return_value={"requested": True}):
            manager._cancel_sync()
            manager.cancel_sync.assert_called_once()


class TestCancelAnalysis:
    """Tests for analysis cancellation semantics."""

    def test_cancel_analysis_returns_structured_result(self):
        """Cancel analysis should return explicit semantics and clear task map."""
        manager = BackgroundManager()
        running_task = MagicMock()
        running_task.done.return_value = False
        done_task = MagicMock()
        done_task.done.return_value = True
        manager._analysis_tasks = {
            "track1:features": running_task,
            "track2:embedding": done_task,
        }

        result = manager.cancel_analysis()

        running_task.cancel.assert_called_once()
        assert result["requested"] is True
        assert result["in_process_tasks_cancelled"] == 1
        assert result["subprocess_may_continue"] is True
        assert manager._analysis_tasks == {}
