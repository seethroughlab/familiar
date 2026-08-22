"""Background fault-injection tests.

Tests resilience to Redis/DB transient failures, broken pools,
and malformed progress data.
"""

import asyncio
import json
import time
from unittest.mock import MagicMock

import pytest

from app.services.background import (
    SYNC_HEARTBEAT_STALE_SECONDS,
    BackgroundManager,
)


class TestRedisLockFailures:
    """Tests for Redis connection failures during lock operations."""

    def test_acquire_lock_redis_connection_error(self):
        """Lock acquisition should return False when Redis raises ConnectionError."""
        manager = BackgroundManager()
        manager._redis = MagicMock()
        manager._redis.get.side_effect = ConnectionError("Connection refused")

        result = manager._acquire_sync_lock()
        assert result is False

    def test_run_sync_redis_down(self):
        """run_sync should return already_running when Redis is unreachable."""
        manager = BackgroundManager()
        manager._redis = MagicMock()
        manager._redis.get.side_effect = ConnectionError("Connection refused")
        manager._redis.set.side_effect = ConnectionError("Connection refused")

        # is_sync_running catches exception and returns False,
        # but _acquire_sync_lock also catches and returns False
        result = asyncio.run(manager.run_sync())
        assert result["status"] == "already_running"

    def test_release_lock_redis_down(self):
        """Lock release should silently handle Redis failures."""
        manager = BackgroundManager()
        manager._redis = MagicMock()
        manager._redis.delete.side_effect = ConnectionError("Connection refused")

        # Should not raise
        manager._release_sync_lock()


class TestBrokenPoolEdgeCases:
    """Tests for executor circuit breaker edge cases."""

    def test_broken_pool_circuit_breaker_already_open(self):
        """run_cpu_bound should raise immediately when circuit breaker is open."""
        manager = BackgroundManager()
        manager._executor = MagicMock()
        manager._executor_disabled = True
        manager._executor_disabled_at = time.monotonic()

        with pytest.raises(RuntimeError, match="disabled"):
            asyncio.run(manager.run_cpu_bound(lambda x: x, 1))

    def test_broken_pool_reset_rate_limited(self):
        """Rapid consecutive resets should be rate-limited."""
        manager = BackgroundManager()
        manager._executor = MagicMock()

        # First reset succeeds
        result1 = manager._reset_executor()
        assert result1 is True
        assert manager._consecutive_executor_failures == 1

        # Immediate second reset should be rate-limited
        result2 = manager._reset_executor()
        assert result2 is False
        # Failure count should NOT increment on rate-limited reset
        assert manager._consecutive_executor_failures == 1


class TestHeartbeatEdgeCases:
    """Tests for heartbeat and progress edge cases."""

    @pytest.fixture
    def manager_with_redis(self):
        """Create manager with mocked Redis."""
        manager = BackgroundManager()
        manager._redis = MagicMock()
        manager._current_sync_task = None
        return manager

    def test_heartbeat_at_exact_threshold(self, manager_with_redis):
        """Heartbeat exactly at threshold boundary should be considered stale."""
        from datetime import timedelta

        from app.utils.time import utcnow

        # Set heartbeat to exactly SYNC_HEARTBEAT_STALE_SECONDS ago
        exact_threshold = (utcnow() - timedelta(seconds=SYNC_HEARTBEAT_STALE_SECONDS)).isoformat()
        manager_with_redis._redis.get.side_effect = [
            b"1",  # has_lock
            json.dumps({"status": "running", "last_heartbeat": exact_threshold}).encode(),
        ]

        # At exactly the threshold, age >= threshold, so it should be stale
        # (the code checks `age < timedelta(seconds=SYNC_HEARTBEAT_STALE_SECONDS)`)
        result = manager_with_redis.is_sync_running()
        assert result is False

    def test_progress_malformed_json(self, manager_with_redis):
        """Malformed JSON in progress key should not crash is_sync_running."""
        manager_with_redis._redis.get.side_effect = [
            b"1",  # has_lock
            b"not valid json{{{",  # malformed progress
        ]

        # json.loads raises JSONDecodeError → caught by outer except Exception → False
        result = manager_with_redis.is_sync_running()
        assert result is False

    def test_progress_running_no_heartbeat(self, manager_with_redis):
        """Progress with status=running but no last_heartbeat field."""
        manager_with_redis._redis.get.side_effect = [
            b"1",  # has_lock
            json.dumps({"status": "running"}).encode(),  # no last_heartbeat
        ]

        # No heartbeat field → heartbeat is None → not recent → falls through
        # has_lock is True and data exists → returns has_lock (True)
        result = manager_with_redis.is_sync_running()
        assert result is True

    @pytest.mark.parametrize("heartbeat_value,expected", [
        ("", True),           # empty string is falsy → skips heartbeat check → returns has_lock
        ("not-a-date", False), # ValueError in fromisoformat → clears lock → False
        ("12345", False),      # ValueError in fromisoformat → clears lock → False
    ])
    def test_progress_invalid_heartbeat_values(self, manager_with_redis, heartbeat_value, expected):
        """Invalid heartbeat values should be handled gracefully."""
        manager_with_redis._redis.get.side_effect = [
            b"1",  # has_lock
            json.dumps({"status": "running", "last_heartbeat": heartbeat_value}).encode(),
        ]

        result = manager_with_redis.is_sync_running()
        assert result is expected
