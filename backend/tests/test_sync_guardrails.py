"""Unit tests for sync queue-churn guardrails and shared retry policy cutoffs."""

from collections import deque
from datetime import timedelta
from unittest.mock import MagicMock, patch

from app.services.tasks.analysis_pipeline import (
    ANALYSIS_RETRY_WINDOW_HOURS,
    _analysis_failure_cutoff,
)
from app.services.tasks.library_sync import SyncProgressReporter
from app.services.tasks.library_sync_progress import (
    _register_phase_requeue_attempt,
    should_force_exit_for_churn,
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


class TestSyncProgressReporterResilience:
    def test_update_tolerates_missing_last_phase_attribute(self) -> None:
        mock_redis = MagicMock()
        with patch("app.services.tasks.library_sync_progress.get_redis", return_value=mock_redis):
            reporter = SyncProgressReporter()
            del reporter._last_phase_emitted
            reporter._update({"phase": "reading", "status": "running"})

        assert reporter._last_phase_emitted == "reading"

    def test_update_backfills_guardrail_fields_when_missing(self) -> None:
        mock_redis = MagicMock()
        with patch("app.services.tasks.library_sync_progress.get_redis", return_value=mock_redis):
            reporter = SyncProgressReporter()
            del reporter.phase_requeue_attempts
            del reporter.phase_stall_recoveries
            del reporter.phase_forced_exit_reasons
            reporter._update({"phase": "features", "status": "running"})

        assert isinstance(reporter.phase_requeue_attempts, dict)
        assert isinstance(reporter.phase_stall_recoveries, dict)
        assert isinstance(reporter.phase_forced_exit_reasons, dict)


class TestSyncLeavesEditedMetadataAlone:
    """A sync must not re-read tags for files that have not changed.

    This is a *user-visible promise*, not an implementation detail. The Mac's track editor and its
    library sync pane both say edits are kept, and the only thing making that true is
    `reread_unchanged` defaulting to False — `LibraryScanner._update_track` assigns title, artist,
    album, album_artist, the numbers, year and genre straight from the file and never consults the
    `user_overrides` column, so any path that reaches it discards deliberate corrections.

    The screens originally said the opposite — that a sync undoes your edits — which was wrong and
    went unchecked until Jeff asked. Both directions of that claim need something holding them still,
    because the copy is written once and the default can move underneath it.
    """

    def test_the_scanner_does_not_reread_unchanged_files_by_default(self) -> None:
        import inspect

        from app.services.scanner import LibraryScanner

        default = inspect.signature(LibraryScanner.scan).parameters["reread_unchanged"].default
        assert default is False, (
            "LibraryScanner.scan now re-reads unchanged files by default, which silently discards "
            "metadata edited in Familiar. The Mac's editor and sync pane both promise otherwise."
        )

    def test_the_sync_endpoint_does_not_reread_unchanged_files_by_default(self) -> None:
        import inspect

        from app.api.routes.library_sync import start_sync

        default = inspect.signature(start_sync).parameters["reread_unchanged"].default
        assert default is False, (
            "POST /library/sync now re-reads unchanged files by default. The Mac's Sync Now button "
            "sends no parameters, so this default is exactly what that button does."
        )

    def test_metadata_is_overwritten_only_when_asked_or_when_the_file_changed(self) -> None:
        """The condition itself, read from the source.

        Asserted against the text because the branch has no seam to call: `_update_track` runs deep
        inside a scan over a real directory. A brittle test that names the rule beats no test for a
        rule two screens quote to a listener.
        """
        from pathlib import Path

        from app.services import scanner

        source = Path(scanner.__file__).read_text()
        assert "if reread_unchanged or file_changed:" in source, (
            "the guard that keeps edited metadata has moved or changed shape — check what the Mac's "
            "track editor and sync pane now promise"
        )


class TestChurnGuardDoesNotPunishProgress:
    """The guard must distinguish churn from a phase that is simply busy.

    It could not. The phase loops sleep 2s and queue on every pass, so a phase
    with work to do makes 150 attempts per 300s window against a limit of 60 —
    meaning **any phase running longer than about two minutes force-exited**,
    however well it was going. Seen in production as
    `queue_churn_limit_exceeded:61/60:300s` on both features and embeddings
    during a healthy sync, capping every run at roughly two minutes of queueing.

    It stayed hidden because the background worker keeps draining the queue after
    the loop exits, so throughput looked fine until the work got fast enough to
    empty the queue before the next sync refilled it.
    """

    def test_the_loop_cadence_alone_exceeds_the_limit(self) -> None:
        """The arithmetic that made the old behaviour unavoidable.

        This asserts the *relationship* between the constants and the loop, which
        is what was actually wrong — not a bug in the counting.
        """
        from app.services.tasks.library_sync_progress import (
            SYNC_MAX_REQUEUE_ATTEMPTS_PER_WINDOW,
            SYNC_QUEUE_CHURN_WINDOW_SECONDS,
        )

        loop_sleep_seconds = 2
        attempts_per_window = SYNC_QUEUE_CHURN_WINDOW_SECONDS / loop_sleep_seconds
        assert attempts_per_window > SYNC_MAX_REQUEUE_ATTEMPTS_PER_WINDOW, (
            "a busy phase cannot stay under the limit on cadence alone, so the "
            "guard must be reset by progress rather than counting every attempt"
        )

    def test_progress_resets_the_window(self) -> None:
        """A phase completing tracks can queue indefinitely.

        200 iterations is 400 simulated seconds — well past the point where the
        old behaviour force-exited at 60.
        """
        attempts: deque[float] = deque()
        now = 0.0
        for _ in range(200):
            assert not should_force_exit_for_churn(attempts, now, made_progress=True)
            now += 2.0

    def test_churn_without_progress_still_trips(self) -> None:
        """The guard must keep doing its actual job.

        Queueing repeatedly while nothing completes is a genuine infinite loop and
        has to be caught — the fix must not amount to disabling it.
        """
        attempts: deque[float] = deque()
        now = 0.0
        tripped = False
        for _ in range(200):
            if should_force_exit_for_churn(attempts, now, made_progress=False):
                tripped = True
                break
            now += 2.0
        assert tripped, "no progress for 200 attempts must still force an exit"

    def test_progress_after_near_miss_clears_accumulated_attempts(self) -> None:
        """Intermittent progress must not leave the phase one attempt from death."""
        attempts: deque[float] = deque()
        now = 0.0
        for _ in range(59):
            assert not should_force_exit_for_churn(attempts, now, made_progress=False)
            now += 2.0
        assert len(attempts) == 59
        # one track completes
        assert not should_force_exit_for_churn(attempts, now, made_progress=True)
        assert len(attempts) == 1, "the window must reset, not merely not-trip"
