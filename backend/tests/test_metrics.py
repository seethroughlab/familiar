"""Tests for app.services.metrics — per-phase gauges, pressure alarms, adaptive sizing, and query instrumentation."""

import logging
from unittest.mock import patch

import pytest

from app.config import adaptive_queue_limit
from app.services.metrics import (
    ALARM_ANALYSIS_QUEUE_DEPTH,
    ALARM_ERROR_RATE,
    ALARM_ERROR_RATE_MIN_REQUESTS,
    ALARM_STALL_RECOVERIES,
    MetricsCollector,
    check_pressure_alarms,
    get_query_count,
    increment_query_count,
    reset_query_count,
    update_background_gauges,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def collector() -> MetricsCollector:
    return MetricsCollector()


def _make_snapshot(
    *,
    queue_depth: int = 0,
    error_rate: float = 0.0,
    total_requests: int = 0,
    p95: float = 0.0,
    failure_rate: int = 0,
    phase_stalls: dict | None = None,
) -> dict:
    """Build a minimal metrics snapshot for pressure alarm tests."""
    bg: dict = {
        "analysis_queue_depth": queue_depth,
        "task_failure_rate_per_min": failure_rate,
    }
    if phase_stalls:
        for phase, count in phase_stalls.items():
            bg[f"phase:{phase}:stall_recoveries"] = count
    return {
        "request_metrics": {
            "total_requests": total_requests,
            "error_rate": error_rate,
            "duration_p95_ms": p95,
        },
        "background_gauges": bg,
    }


# ---------------------------------------------------------------------------
# Part 1: update_background_gauges per-phase tests
# ---------------------------------------------------------------------------

class TestUpdateBackgroundGaugesPhase:
    """Test per-phase gauge population from sync progress."""

    @patch("app.services.tasks.get_recent_failures", return_value=[])
    @patch("app.services.background.events.get_recent_background_events", return_value=[])
    @patch("app.services.background.get_background_manager")
    @patch("app.services.tasks.get_sync_progress")
    def test_running_sync_sets_phase_gauges(
        self, mock_progress, mock_bg, _mock_events, _mock_failures, collector
    ):
        mock_bg.return_value.get_analysis_task_count.return_value = 2
        mock_bg.return_value.is_sync_running.return_value = True
        mock_bg.return_value._executor_disabled = False

        mock_progress.return_value = {
            "status": "running",
            "phase": "embeddings",
            "tracks_analyzed": 100,
            "tracks_pending_analysis": 50,
            "tracks_total": 150,
            "phase_requeue_attempts": {"embeddings": 3, "features": 0},
            "phase_stall_recoveries": {"embeddings": 1},
            "phase_forced_exit_reasons": {"melodic": "timeout"},
        }

        update_background_gauges(collector)
        snap = collector.get_snapshot()
        bg = snap["background_gauges"]

        assert bg["current_phase"] == "embeddings"
        assert bg["phase_analyzed"] == 100
        assert bg["phase_pending"] == 50
        assert bg["phase_total"] == 150
        assert bg["phase:embeddings:requeue_attempts"] == 3
        assert bg["phase:embeddings:stall_recoveries"] == 1
        assert bg["phase:melodic:forced_exit_reason"] == "timeout"
        # Phases without data should still be set to 0
        assert bg["phase:features:requeue_attempts"] == 0
        assert bg["phase:features:stall_recoveries"] == 0

    @patch("app.services.tasks.get_recent_failures", return_value=[])
    @patch("app.services.background.events.get_recent_background_events", return_value=[])
    @patch("app.services.background.get_background_manager")
    @patch("app.services.tasks.get_sync_progress")
    def test_no_sync_does_not_crash(
        self, mock_progress, mock_bg, _mock_events, _mock_failures, collector
    ):
        mock_bg.return_value.get_analysis_task_count.return_value = 0
        mock_bg.return_value.is_sync_running.return_value = False
        mock_bg.return_value._executor_disabled = False
        mock_progress.return_value = None

        update_background_gauges(collector)
        snap = collector.get_snapshot()
        bg = snap["background_gauges"]

        # Phase gauges should not be present
        assert "current_phase" not in bg
        assert "phase_analyzed" not in bg


# ---------------------------------------------------------------------------
# Part 3: check_pressure_alarms tests
# ---------------------------------------------------------------------------

class TestCheckPressureAlarms:
    """Test pressure alarm threshold checks."""

    def test_all_clear(self):
        snapshot = _make_snapshot(queue_depth=10, error_rate=0.01, total_requests=100)
        alarms = check_pressure_alarms(snapshot, logging.getLogger("test"))
        assert alarms == []

    def test_high_queue_depth(self):
        snapshot = _make_snapshot(queue_depth=ALARM_ANALYSIS_QUEUE_DEPTH + 1)
        alarms = check_pressure_alarms(snapshot, logging.getLogger("test"))
        assert "high_analysis_queue_depth" in alarms

    def test_high_error_rate(self):
        snapshot = _make_snapshot(
            error_rate=ALARM_ERROR_RATE + 0.01,
            total_requests=ALARM_ERROR_RATE_MIN_REQUESTS + 1,
        )
        alarms = check_pressure_alarms(snapshot, logging.getLogger("test"))
        assert "high_error_rate" in alarms

    def test_low_request_count_guard(self):
        """High error rate but too few requests should NOT fire alarm."""
        snapshot = _make_snapshot(
            error_rate=0.50,
            total_requests=ALARM_ERROR_RATE_MIN_REQUESTS - 1,
        )
        alarms = check_pressure_alarms(snapshot, logging.getLogger("test"))
        assert "high_error_rate" not in alarms

    def test_high_p95_latency(self):
        snapshot = _make_snapshot(p95=6000)
        alarms = check_pressure_alarms(snapshot, logging.getLogger("test"))
        assert "high_p95_latency" in alarms

    def test_high_task_failure_rate(self):
        snapshot = _make_snapshot(failure_rate=10)
        alarms = check_pressure_alarms(snapshot, logging.getLogger("test"))
        assert "high_task_failure_rate" in alarms

    def test_phase_stall_recoveries(self):
        snapshot = _make_snapshot(
            phase_stalls={"embeddings": ALARM_STALL_RECOVERIES + 1},
        )
        alarms = check_pressure_alarms(snapshot, logging.getLogger("test"))
        assert "phase_embeddings_stall_recoveries" in alarms

    def test_multiple_alarms(self):
        """Multiple thresholds breached returns all alarms."""
        snapshot = _make_snapshot(
            queue_depth=ALARM_ANALYSIS_QUEUE_DEPTH + 100,
            failure_rate=10,
            p95=10000,
        )
        alarms = check_pressure_alarms(snapshot, logging.getLogger("test"))
        assert len(alarms) >= 3
        assert "high_analysis_queue_depth" in alarms
        assert "high_task_failure_rate" in alarms
        assert "high_p95_latency" in alarms


# ---------------------------------------------------------------------------
# Part 4: adaptive_queue_limit tests
# ---------------------------------------------------------------------------


class TestAdaptiveQueueLimit:
    """Test CPU-adaptive queue burst sizing.

    These patch `app.config.available_cpu_count`, not `os.cpu_count`. The count is now
    cgroup-aware (see `test_cpu_limits.py`), so patching `os.cpu_count` would no longer
    determine the answer on a host that has a CPU quota — these tests would start
    depending on the machine running them. The scaling behaviour asserted here is
    unchanged; only the seam moved.
    """

    def test_default_returns_int_in_range(self):
        """Default call returns an int clamped to [50, 500]."""
        result = adaptive_queue_limit()
        assert isinstance(result, int)
        assert 50 <= result <= 500

    @patch("app.config.available_cpu_count")
    def test_scales_with_cpu_count(self, mock_cpus):
        """Limit scales linearly with CPU count."""
        mock_cpus.return_value = 1
        assert adaptive_queue_limit() == 100  # 1 * 100

        mock_cpus.return_value = 4
        assert adaptive_queue_limit() == 400  # 4 * 100

        mock_cpus.return_value = 8
        assert adaptive_queue_limit() == 500  # 8 * 100 = 800 → clamped to 500

    @patch("app.config.available_cpu_count")
    def test_custom_base(self, mock_cpus):
        """Custom base value scales correctly."""
        mock_cpus.return_value = 4
        assert adaptive_queue_limit(base=50) == 200  # 4 * 50

    @patch("app.config.available_cpu_count")
    def test_clamp_floor(self, mock_cpus):
        """Very low CPU * base is clamped to 50."""
        mock_cpus.return_value = 1
        assert adaptive_queue_limit(base=10) == 50  # 1 * 10 = 10 → clamped to 50


# ---------------------------------------------------------------------------
# Part 5: Query counter contextvar tests
# ---------------------------------------------------------------------------


class TestQueryCounter:
    """Test per-request SQL query counter (contextvar-based)."""

    def test_default_is_zero(self):
        reset_query_count()
        assert get_query_count() == 0

    def test_increment_and_get(self):
        reset_query_count()
        increment_query_count()
        increment_query_count()
        increment_query_count()
        assert get_query_count() == 3

    def test_reset_clears_count(self):
        reset_query_count()
        increment_query_count()
        increment_query_count()
        assert get_query_count() == 2
        reset_query_count()
        assert get_query_count() == 0

    def test_record_request_with_query_count(self, collector: MetricsCollector):
        collector.record_request("GET", "/api/v1/tracks", 200, 10.0, query_count=5)
        collector.record_request("POST", "/api/v1/chat", 200, 50.0, query_count=12)
        snap = collector.get_snapshot(window_seconds=60)
        req = snap["request_metrics"]
        assert req["avg_queries_per_request"] == 8.5  # (5 + 12) / 2
        assert req["max_queries_per_request"] == 12

    def test_snapshot_empty_shows_zero_query_stats(self):
        c = MetricsCollector()
        snap = c.get_snapshot(window_seconds=60)
        req = snap["request_metrics"]
        assert req["avg_queries_per_request"] == 0.0
        assert req["max_queries_per_request"] == 0

    def test_record_request_default_query_count(self, collector: MetricsCollector):
        """Backward compat: query_count defaults to 0."""
        collector.record_request("GET", "/health", 200, 1.0)
        snap = collector.get_snapshot(window_seconds=60)
        assert snap["request_metrics"]["max_queries_per_request"] == 0


# ---------------------------------------------------------------------------
# Part 6: Worker scaling setting tests
# ---------------------------------------------------------------------------


class TestWorkerScalingSetting:
    """Test max_analysis_workers setting wires into executor creation."""

    @patch("app.services.background.executors.app_settings")
    def test_executor_uses_setting(self, mock_settings):
        from app.services.background.executors import ExecutorMixin

        mock_settings.max_analysis_workers = 2

        class TestMixin(ExecutorMixin):
            pass

        mixin = TestMixin()
        mixin._init_executor_state()
        mixin._create_executor()

        try:
            assert mixin._executor is not None
            assert mixin._executor._max_workers == 2
        finally:
            mixin._executor.shutdown(wait=False)

    @patch("app.services.background.executors.app_settings")
    def test_executor_default_one_worker(self, mock_settings):
        from app.services.background.executors import ExecutorMixin

        mock_settings.max_analysis_workers = 1

        class TestMixin(ExecutorMixin):
            pass

        mixin = TestMixin()
        mixin._init_executor_state()
        mixin._create_executor()

        try:
            assert mixin._executor._max_workers == 1
        finally:
            mixin._executor.shutdown(wait=False)
