"""Unit tests for sync queue-churn guardrails and shared retry policy cutoffs."""

from collections import deque
from datetime import timedelta

from app.services.tasks.analysis_pipeline import (
    ANALYSIS_RETRY_WINDOW_HOURS,
    _analysis_failure_cutoff,
)
from app.services.tasks.library_sync import (
    _register_phase_requeue_attempt,
)
from app.utils.time import utcnow


class TestSyncQueueChurnGuardrail:
    def test_register_attempt_under_limit(self) -> None:
        attempts: deque[float] = deque()
        exceeded = False
        for i in range(3):
            exceeded = _register_phase_requeue_attempt(
                attempts,
                now=float(i),
                window_seconds=10.0,
                max_attempts=3,
            )
        assert exceeded is False
        assert len(attempts) == 3

    def test_register_attempt_exceeds_limit(self) -> None:
        attempts: deque[float] = deque()
        for i in range(3):
            _register_phase_requeue_attempt(
                attempts,
                now=float(i),
                window_seconds=10.0,
                max_attempts=3,
            )

        exceeded = _register_phase_requeue_attempt(
            attempts,
            now=3.0,
            window_seconds=10.0,
            max_attempts=3,
        )
        assert exceeded is True
        assert len(attempts) == 4

    def test_old_attempts_expire_outside_window(self) -> None:
        attempts: deque[float] = deque([0.0, 1.0, 2.0])
        exceeded = _register_phase_requeue_attempt(
            attempts,
            now=15.0,
            window_seconds=10.0,
            max_attempts=3,
        )
        assert exceeded is False
        assert list(attempts) == [15.0]


class TestSharedRetryWindow:
    def test_analysis_failure_cutoff_uses_shared_window_constant(self) -> None:
        cutoff = _analysis_failure_cutoff()
        now = utcnow()
        delta = now - cutoff
        expected = timedelta(hours=ANALYSIS_RETRY_WINDOW_HOURS)

        # Keep tolerance loose to avoid test flakiness from execution delay.
        assert abs(delta.total_seconds() - expected.total_seconds()) < 5
