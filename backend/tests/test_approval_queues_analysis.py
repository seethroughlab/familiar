"""Approving a pending track analyses it now, not at the next sync.

`_queue_for_analysis` was a no-op whose docstring said the next sync would pick the track up, and the
next sync can be two hours away; Familiar Server's integration check found an approved track still
unanalysed after one. The approve endpoints' `queue_analysis` flag did nothing.
"""

from __future__ import annotations

import asyncio
import time

import pytest

import app.services.background as background_module
from app.api.routes import pending_review
from app.db.models import TrackStatus
from app.services.background.pause import background_pause
from tests.conftest import make_profile_headers
from tests.factories import insert_test_track


class FakeManager:
    def __init__(self, syncing: bool = False):
        self.syncing = syncing
        self.queued: list[str] = []

    def is_sync_running(self) -> bool:
        return self.syncing

    async def run_analysis(self, track_id: str, phase: str = "full") -> dict:
        self.queued.append(track_id)
        return {"status": "queued"}


@pytest.fixture
def manager(monkeypatch):
    fake = FakeManager()
    monkeypatch.setattr(background_module, "get_background_manager", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def unpaused():
    background_pause.resume()
    yield
    background_pause.resume()


def _wait_for(predicate, seconds: float = 3.0) -> None:
    """The queueing runs on the TestClient's loop, after the response."""
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.02)


async def _pending(async_db, title: str):
    track = await insert_test_track(async_db, title=title)
    track.status = TrackStatus.PENDING_REVIEW
    await async_db.commit()
    return track


class TestTheEndpoints:
    @pytest.mark.asyncio
    async def test_approving_a_track_queues_its_analysis(self, async_db, client, test_profile, manager):
        track = await _pending(async_db, "Approved")
        resp = client.post(
            f"/api/v1/pending-tracks/{track.id}/approve", json={}, headers=make_profile_headers(test_profile)
        )
        assert resp.status_code == 200
        _wait_for(lambda: manager.queued)
        assert manager.queued == [str(track.id)]

    @pytest.mark.asyncio
    async def test_approving_everything_queues_every_track(self, async_db, client, test_profile, manager):
        tracks = [await _pending(async_db, f"T{i}") for i in range(3)]
        resp = client.post(
            "/api/v1/pending-tracks/bulk/approve-all", json={}, headers=make_profile_headers(test_profile)
        )
        assert resp.json()["count"] == 3
        _wait_for(lambda: len(manager.queued) == 3)
        assert sorted(manager.queued) == sorted(str(t.id) for t in tracks)

    @pytest.mark.asyncio
    async def test_the_flag_can_still_say_no(self, async_db, client, test_profile, manager):
        track = await _pending(async_db, "Not now")
        client.post(
            f"/api/v1/pending-tracks/{track.id}/approve",
            json={"queue_analysis": False},
            headers=make_profile_headers(test_profile),
        )
        time.sleep(0.3)
        assert manager.queued == []


@pytest.mark.asyncio(loop_scope="function")
class TestWhenItRuns:
    async def test_a_sync_in_progress_is_left_to_find_them(self, monkeypatch):
        """The sync queues by phase; a `full` request would analyse the same track twice at once."""
        fake = FakeManager(syncing=True)
        monkeypatch.setattr(background_module, "get_background_manager", lambda: fake)
        assert pending_review._queue_for_analysis(["a", "b"]) == 0
        await asyncio.sleep(0.05)
        assert fake.queued == []

    async def test_a_paused_server_analyses_on_resume(self, manager):
        """ADR-0138: approving on a hot laptop must not start the work the pause is holding back."""
        background_pause.pause("thermal")
        assert pending_review._queue_for_analysis(["a"]) == 1
        await asyncio.sleep(0.2)
        assert manager.queued == [], "nothing runs while paused"
        background_pause.resume()
        for _ in range(100):
            if manager.queued:
                break
            await asyncio.sleep(0.05)
        assert manager.queued == ["a"]
