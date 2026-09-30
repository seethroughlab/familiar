"""The server adapts to a Mac, and yields to its owner (ADR-0136 points 3 and 5, ADR-0138)."""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import os
import stat
import sys
from concurrent.futures import ProcessPoolExecutor
from unittest.mock import AsyncMock, patch

import pytest

from app.process_setup import (
    SEMAPHORE_PREFIX_ENV,
    analysis_worker_init,
    apply_semaphore_prefix,
    darwin_background_clamped,
)
from app.services.background.pause import BackgroundPause


def _child_semprefix() -> str:
    return mp.current_process()._config["semprefix"]  # type: ignore[attr-defined]


def _child_clamped() -> bool:
    return darwin_background_clamped()


class TestSemaphorePrefix:
    """ADR-0136's spike: in the App Sandbox a semaphore must be named under the app group."""

    def test_unset_changes_nothing(self, monkeypatch):
        monkeypatch.delenv(SEMAPHORE_PREFIX_ENV, raising=False)
        before = mp.current_process()._config["semprefix"]  # type: ignore[attr-defined]
        assert apply_semaphore_prefix() is None
        assert mp.current_process()._config["semprefix"] == before  # type: ignore[attr-defined]

    def test_a_spawned_worker_names_its_semaphores_under_the_prefix(self, monkeypatch):
        # The pool worker applies it itself, because a worker that creates a lock names it.
        monkeypatch.setenv(SEMAPHORE_PREFIX_ENV, "7JL9RZ9C8P.fs/mp")
        with ProcessPoolExecutor(1, mp_context=mp.get_context("spawn"), initializer=apply_semaphore_prefix) as ex:
            assert ex.submit(_child_semprefix).result(timeout=60) == "7JL9RZ9C8P.fs/mp"


@pytest.mark.skipif(sys.platform != "darwin", reason="the background clamp is a Darwin facility")
def test_analysis_workers_run_under_the_darwin_background_clamp():
    """ADR-0138 point 3: efficiency cores and throttled I/O, not just `nice`."""
    with ProcessPoolExecutor(1, mp_context=mp.get_context("spawn"), initializer=analysis_worker_init) as ex:
        assert ex.submit(_child_clamped).result(timeout=60) is True


class TestZeroTouchPreflight:
    """ADR-0136 point 5: a writable library is refused, and the check no longer writes to test."""

    @pytest.fixture
    def library(self, tmp_path, monkeypatch):
        import app.main as main_module

        (tmp_path / "a.flac").write_bytes(b"x")
        monkeypatch.setattr(main_module, "MUSIC_LIBRARY_PATH", tmp_path)
        return tmp_path

    def test_a_writable_library_is_refused(self, library, monkeypatch):
        from app.main import app_config, validate_library_path

        monkeypatch.setattr(app_config, "allow_writable_library", False)
        with pytest.raises(RuntimeError, match="writable"):
            validate_library_path()

    def test_the_check_writes_nothing(self, library, monkeypatch):
        from app.main import app_config, validate_library_path

        monkeypatch.setattr(app_config, "allow_writable_library", False)
        with pytest.raises(RuntimeError):
            validate_library_path()
        assert sorted(p.name for p in library.iterdir()) == ["a.flac"]

    def test_the_opt_out_allows_it(self, library, monkeypatch):
        from app.main import app_config, validate_library_path

        monkeypatch.setattr(app_config, "allow_writable_library", True)
        validate_library_path()  # warns, does not raise

    @pytest.mark.skipif(os.geteuid() == 0, reason="root can write to a read-only directory")
    def test_a_read_only_library_passes(self, library, monkeypatch):
        from app.main import app_config, validate_library_path

        monkeypatch.setattr(app_config, "allow_writable_library", False)
        library.chmod(stat.S_IRUSR | stat.S_IXUSR)
        try:
            validate_library_path()
        finally:
            library.chmod(stat.S_IRWXU)


class TestPauseState:
    def test_not_paused_returns_at_once(self):
        assert asyncio.run(BackgroundPause().wait_while_paused()) == 0.0

    def test_a_wait_lasts_until_resume_and_reports_how_long(self):
        pause = BackgroundPause()
        pause.pause("on battery")

        async def scenario():
            waiter = asyncio.create_task(pause.wait_while_paused(poll_seconds=0.02))
            await asyncio.sleep(0.1)
            assert not waiter.done()
            pause.resume()
            return await waiter

        assert asyncio.run(scenario()) >= 0.1

    def test_pausing_again_changes_the_reason_not_the_start(self):
        pause = BackgroundPause()
        pause.pause("on battery")
        since = pause.since
        pause.pause("Low Power Mode")
        assert (pause.reason, pause.since) == ("Low Power Mode", since)

    def test_resume_hands_back_what_was_skipped_once(self):
        pause = BackgroundPause()
        pause.pause("paused by you")
        pause.note_skipped("periodic_sync")
        assert pause.resume() == {"periodic_sync"}
        assert pause.resume() == set()


class TestDeferrableJobs:
    def test_a_scheduled_job_is_skipped_and_recorded_while_paused(self):
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        from app.services.background.manager import BackgroundManager
        from app.services.background.pause import background_pause

        ran: list[str] = []

        async def job():
            ran.append("ran")

        async def scenario():
            manager = BackgroundManager()
            manager._scheduler = AsyncIOScheduler()
            manager._scheduler.add_job(job, "interval", hours=1, id="discovery_batch")
            manager._make_background_jobs_deferrable()
            manager._make_background_jobs_deferrable()  # idempotent
            wrapped = manager._scheduler.get_job("discovery_batch").func
            background_pause.pause("on battery")
            try:
                await wrapped()
                assert ran == [] and "discovery_batch" in background_pause.skipped
            finally:
                background_pause.resume()
            await wrapped()
            assert ran == ["ran"]

        asyncio.run(scenario())

    def test_resume_runs_one_sync_that_was_skipped(self):
        from app.services.background.manager import BackgroundManager
        from app.services.background.pause import background_pause

        async def scenario():
            manager = BackgroundManager()
            with patch.object(manager, "_periodic_sync", new=AsyncMock()) as sync, \
                 patch.object(manager, "is_sync_running", return_value=False):
                background_pause.pause("asleep")
                background_pause.note_skipped("periodic_sync")
                background_pause.note_skipped("periodic_sync")  # two missed slots
                state = manager.resume_background()
                await asyncio.sleep(0)
                assert state["resumed_sync"] is True
                assert sync.await_count == 1

        asyncio.run(scenario())


class TestPauseAPI:
    def test_pause_and_resume(self, client):
        from app.services.background.pause import background_pause

        try:
            body = client.post("/api/v1/background/pause", json={"reason": "on battery"}).json()
            assert body["paused"] is True and body["reason"] == "on battery"
            assert client.get("/api/v1/background/pause").json()["paused"] is True
            body = client.post("/api/v1/background/resume").json()
            assert body["paused"] is False
        finally:
            background_pause.resume()
