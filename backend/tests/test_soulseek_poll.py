"""Tests for the settled-folder poll (ADR-0117 point 3).

What is pinned is the rule, because the rule is where the two obvious implementations go wrong:

- **Settled is per folder, not per file.** slskd moves each file to `complete` as it finishes.
  A poll that fired on "a file arrived" would sync once per track.
- **Once per success count.** A folder that settled with 8 of 11 and later settled with 11
  triggers twice; one that is merely still listed on the next poll does not trigger again.
- **A running sync defers rather than marks.** If the marks were set while another sync was mid-
  walk, a folder that landed after the walk passed the inbox would never trigger.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.background.soulseek import (
    SoulseekMixin,
    folders_to_trigger,
    settled_key,
)
from app.services.soulseek import SoulseekService


def folder(
    username: str, directory: str, *, completed: int, in_progress: int = 0, queued: int = 0
) -> dict[str, Any]:
    return {
        "username": username,
        "directory": directory,
        "files": completed + in_progress + queued,
        "completed": completed,
        "failed": 0,
        "in_progress": in_progress,
        "queued": queued,
        "percent": 0,
        "settled": in_progress == 0 and queued == 0 and completed >= 1,
    }


class TestSettledIsDerivedFromTheSummary:
    """`SoulseekService.downloads()` computes `settled`; these pin what it means."""

    @pytest.mark.asyncio
    async def test_a_folder_with_a_file_still_moving_is_not_settled(self):
        import httpx

        raw = [
            {
                "username": "u",
                "directories": [
                    {
                        "directory": "d",
                        "files": [
                            {"state": "Completed, Succeeded", "size": 1, "bytesTransferred": 1},
                            {"state": "InProgress", "size": 1, "bytesTransferred": 0},
                        ],
                    }
                ],
            }
        ]
        svc = SoulseekService(
            "http://s:5030",
            None,
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=raw)),
        )
        try:
            rows = await svc.downloads()
        finally:
            await svc.close()
        assert rows[0]["settled"] is False

    @pytest.mark.asyncio
    async def test_all_terminal_with_one_success_is_settled(self):
        import httpx

        raw = [
            {
                "username": "u",
                "directories": [
                    {
                        "directory": "d",
                        "files": [
                            {"state": "Completed, Succeeded", "size": 1, "bytesTransferred": 1},
                            {"state": "Completed, Errored", "size": 1, "bytesTransferred": 0},
                        ],
                    }
                ],
            }
        ]
        svc = SoulseekService(
            "http://s:5030",
            None,
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=raw)),
        )
        try:
            rows = await svc.downloads()
        finally:
            await svc.close()
        assert rows[0]["settled"] is True

    @pytest.mark.asyncio
    async def test_all_failed_is_not_settled(self):
        """Nothing to scan. The tool still reports the folder; the poll ignores it."""
        import httpx

        raw = [
            {
                "username": "u",
                "directories": [
                    {
                        "directory": "d",
                        "files": [
                            {"state": "Completed, Errored", "size": 1, "bytesTransferred": 0},
                        ],
                    }
                ],
            }
        ]
        svc = SoulseekService(
            "http://s:5030",
            None,
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=raw)),
        )
        try:
            rows = await svc.downloads()
        finally:
            await svc.close()
        assert rows[0]["settled"] is False


class TestTheTriggerRule:
    def test_unsettled_folders_never_trigger(self):
        assert folders_to_trigger([folder("u", "d", completed=3, in_progress=1)], {}) == []

    def test_a_new_settled_folder_triggers(self):
        f = folder("u", "d", completed=11)
        assert folders_to_trigger([f], {}) == [f]

    def test_a_folder_already_triggered_at_this_count_does_not(self):
        f = folder("u", "d", completed=11)
        assert folders_to_trigger([f], {settled_key("u", "d"): 11}) == []

    def test_more_successes_than_last_time_triggers_again(self):
        """8 of 11 landed, sync ran; slskd retried; now 11. The three new files need a sync."""
        f = folder("u", "d", completed=11)
        assert folders_to_trigger([f], {settled_key("u", "d"): 8}) == [f]

    def test_keys_are_per_sharer_and_directory(self):
        assert settled_key("a", "x\\y") != settled_key("b", "x\\y")
        assert settled_key("a", "x\\y") != settled_key("a", "x\\z")
        assert settled_key("a", "x\\y") == settled_key("a", "x\\y")


class FakeManager(SoulseekMixin):
    """Just enough BackgroundManager for the mixin: redis, sync state, run_sync."""

    def __init__(self, transfers: list[dict[str, Any]], *, running: bool = False) -> None:
        self.store: dict[str, str] = {}
        self.redis = MagicMock()
        self.redis.get.side_effect = lambda k: self.store.get(k)
        self.redis.set.side_effect = lambda k, v, ex=None: self.store.__setitem__(k, v)
        self._running = running
        self.run_sync = AsyncMock(return_value={"status": "started"})
        self._transfers = transfers

    def is_sync_running(self) -> bool:
        return self._running


@pytest.fixture
def configured(monkeypatch):
    """A configured slskd whose `downloads()` returns whatever the manager was built with."""
    monkeypatch.setattr(
        "app.services.app_settings.AppSettingsService.has_soulseek_configured", lambda self: True
    )

    svc = MagicMock()
    svc.close = AsyncMock()
    monkeypatch.setattr(SoulseekService, "from_settings", classmethod(lambda cls: svc))
    return svc


class TestThePoll:
    @pytest.mark.asyncio
    async def test_unconfigured_does_nothing(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.app_settings.AppSettingsService.has_soulseek_configured",
            lambda self: False,
        )
        called = []
        monkeypatch.setattr(
            SoulseekService, "from_settings", classmethod(lambda cls: called.append(1))
        )
        m = FakeManager([])
        await m._soulseek_poll()
        assert called == []
        m.run_sync.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_settled_folder_starts_a_sync_and_is_remembered(self, configured):
        m = FakeManager([folder("u", "d", completed=11)])
        configured.downloads = AsyncMock(return_value=m._transfers)
        await m._soulseek_poll()
        m.run_sync.assert_awaited_once()
        assert m.store[settled_key("u", "d")] == "11"
        assert m.soulseek_sync_triggered("u", "d") is True

    @pytest.mark.asyncio
    async def test_the_next_poll_does_not_sync_again(self, configured):
        m = FakeManager([folder("u", "d", completed=11)])
        configured.downloads = AsyncMock(return_value=m._transfers)
        await m._soulseek_poll()
        await m._soulseek_poll()
        assert m.run_sync.await_count == 1

    @pytest.mark.asyncio
    async def test_a_running_sync_defers_without_marking(self, configured):
        m = FakeManager([folder("u", "d", completed=11)], running=True)
        configured.downloads = AsyncMock(return_value=m._transfers)
        await m._soulseek_poll()
        m.run_sync.assert_not_called()
        assert settled_key("u", "d") not in m.store, "must trigger on a later poll"

    @pytest.mark.asyncio
    async def test_an_in_flight_folder_waits(self, configured):
        m = FakeManager([folder("u", "d", completed=3, queued=8)])
        configured.downloads = AsyncMock(return_value=m._transfers)
        await m._soulseek_poll()
        m.run_sync.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_unreachable_slskd_is_quiet(self, configured, caplog):
        from app.services.soulseek import SoulseekUnreachable

        m = FakeManager([])
        configured.downloads = AsyncMock(side_effect=SoulseekUnreachable("down"))
        with caplog.at_level("WARNING"):
            await m._soulseek_poll()
        m.run_sync.assert_not_called()
        assert not [r for r in caplog.records if r.levelname == "WARNING"]
