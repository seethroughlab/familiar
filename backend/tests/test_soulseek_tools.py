"""Tests for the four Soulseek tool handlers (ADR-0116).

The client is covered in `test_soulseek.py`; these pin what the *tools* decide:

- `find_missing_on_soulseek` checks the library before it touches the network, and searches
  nothing when the answer is "you already have it".
- `download_from_soulseek` fetches the whole folder rather than enqueueing the search's matches.
- A not-configured or unreachable slskd is an answer with a reason, never an exception — the
  executor would turn one into `Tool 'x' failed (SoulseekUnreachable)`, which loses the sentence
  that says what to fix.
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from app.services.llm.executor import ToolExecutor
from tests.test_soulseek import FakeSlskd, services_for


@pytest.fixture
def slskd(monkeypatch):
    """A fake slskd, with polling made instant."""
    import app.services.soulseek as mod

    monkeypatch.setattr(mod, "SEARCH_POLL_SECONDS", 0)
    return FakeSlskd()


@pytest.fixture
def executor(slskd) -> ToolExecutor:
    """An executor whose container's Soulseek gateway talks to the fake (ADR-0130).

    Given, not patched in: the executor reaches slskd only through `self.services.soulseek`.
    """
    return ToolExecutor(  # type: ignore[arg-type]
        db=None,
        profile_id=uuid4(),
        services=services_for(httpx.MockTransport(slskd.handler)),
    )


def _holdings(**result):
    async def _impl(self, artist, album):
        return {"in_library": False, "tracks": 0, "albums": [], **result}

    return _impl


class TestFindMissing:
    @pytest.mark.asyncio
    async def test_already_owned_searches_nothing(self, executor, slskd, monkeypatch):
        monkeypatch.setattr(
            ToolExecutor,
            "_library_holdings",
            _holdings(in_library=True, tracks=11, albums=["a.s.o."]),
        )
        result = await executor._find_missing_on_soulseek("a.s.o.", "a.s.o.")
        assert result["in_library"] is True
        assert result["library_tracks"] == 11
        assert slskd.calls == [], "nothing must reach the network"

    @pytest.mark.asyncio
    async def test_missing_album_is_searched_as_artist_plus_album(
        self, executor, slskd, monkeypatch
    ):
        monkeypatch.setattr(ToolExecutor, "_library_holdings", _holdings(albums=["Other Album"]))
        result = await executor._find_missing_on_soulseek("a.s.o.", "a.s.o. remixed")
        assert result["in_library"] is False
        posted = next(c[2] for c in slskd.calls if c[0] == "POST" and c[1].endswith("/searches"))
        assert posted == {"searchText": "a.s.o. a.s.o. remixed"}
        assert result["folders"][0]["username"] == "electrobutch"
        assert "Other Album" in result["note"], (
            "says which of the artist's albums are already owned"
        )

    @pytest.mark.asyncio
    async def test_artist_alone_is_searched_by_name(self, executor, slskd, monkeypatch):
        monkeypatch.setattr(ToolExecutor, "_library_holdings", _holdings())
        await executor._find_missing_on_soulseek("Lamb")
        posted = next(c[2] for c in slskd.calls if c[0] == "POST" and c[1].endswith("/searches"))
        assert posted == {"searchText": "Lamb"}

    @pytest.mark.asyncio
    async def test_blank_artist_is_refused(self, executor, slskd):
        assert "error" in await executor._find_missing_on_soulseek("  ")
        assert slskd.calls == []


class TestDownload:
    @pytest.mark.asyncio
    async def test_the_whole_folder_is_enqueued_not_the_matches(self, executor, slskd):
        result = await executor._download_from_soulseek(
            "electrobutch", "music\\Organized\\Trip Hop\\aso\\2023 - a.s.o"
        )
        assert result["queued"] == 2
        assert result["files"] == [
            "a.s.o. - a.s.o. - 01 Go On.flac",
            "a.s.o. - a.s.o. - 03 Rain Down.flac",
        ]
        assert "cover.jpg" not in result["files"]
        assert "Pending Review" in result["note"]


class TestTheHandoff:
    """ADR-0117 point 7: Familiar never moves files, so the tool says who should and where."""

    @pytest.mark.asyncio
    async def test_without_an_inbox_the_move_is_handed_off(
        self, executor, slskd, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("app.config.MUSIC_LIBRARY_PATH", tmp_path)  # no Inbox inside it
        result = await executor._download_from_soulseek(
            "electrobutch", "music\\Organized\\Trip Hop\\aso\\2023 - a.s.o"
        )
        h = result["handoff"]
        assert h["inbox_mounted"] is False
        assert h["folder"] == "2023 - a.s.o"
        assert h["slskd_path"] == "/downloads/complete/2023 - a.s.o"
        assert h["library_path"] == str(tmp_path)
        assert "move it" in h["how_to_file"] and "start_library_sync" in h["how_to_file"]
        assert result["note"].endswith(h["how_to_file"])

    @pytest.mark.asyncio
    async def test_with_an_inbox_nothing_needs_moving(self, executor, slskd, tmp_path, monkeypatch):
        (tmp_path / "Inbox").mkdir()
        monkeypatch.setattr("app.config.MUSIC_LIBRARY_PATH", tmp_path)
        result = await executor._download_from_soulseek(
            "electrobutch", "music\\Organized\\Trip Hop\\aso\\2023 - a.s.o"
        )
        h = result["handoff"]
        assert h["inbox_mounted"] is True
        assert "nothing needs moving" in h["how_to_file"]
        assert "Pending Review" in h["how_to_file"]

    @pytest.mark.asyncio
    async def test_transfers_carry_the_path_and_the_arrangement(
        self, executor, slskd, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("app.config.MUSIC_LIBRARY_PATH", tmp_path)
        result = await executor._get_soulseek_transfers()
        assert result["inbox_mounted"] is False
        assert result["library_path"] == str(tmp_path)
        assert "start_library_sync" in result["note"]


class TestStartLibrarySync:
    @pytest.mark.asyncio
    async def test_starts_a_sync_when_none_is_running(self, executor, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock

        bg = MagicMock()
        bg.is_sync_running.return_value = False
        bg.run_sync = AsyncMock(return_value={"status": "started"})
        monkeypatch.setattr("app.services.background.get_background_manager", lambda: bg)
        result = await executor._start_library_sync()
        assert result["status"] == "started"
        bg.run_sync.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_does_not_stack_a_second_sync(self, executor, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock

        bg = MagicMock()
        bg.is_sync_running.return_value = True
        bg.run_sync = AsyncMock()
        monkeypatch.setattr("app.services.background.get_background_manager", lambda: bg)
        result = await executor._start_library_sync()
        assert result["status"] == "already_running"
        bg.run_sync.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_empty_or_unshared_folder_is_an_answer(self, executor, slskd):
        result = await executor._download_from_soulseek("nobody", "gone")
        assert "error" in result
        assert not any("/transfers/" in c[1] for c in slskd.calls)


class TestSearchAndTransfers:
    @pytest.mark.asyncio
    async def test_search_returns_ranked_folders(self, executor, slskd):
        result = await executor._search_soulseek("a.s.o. rain down")
        assert result["count"] == 2
        assert [f["username"] for f in result["folders"]] == ["electrobutch", "speedy"]

    @pytest.mark.asyncio
    async def test_limit_is_clamped_and_tolerant(self, executor, slskd):
        assert (await executor._search_soulseek("x", limit="1"))["count"] == 1
        assert (await executor._search_soulseek("x", limit="junk"))["count"] == 2

    @pytest.mark.asyncio
    async def test_transfers_carry_the_connection_status(self, executor, slskd):
        result = await executor._get_soulseek_transfers()
        assert result["status"]["logged_in"] is True
        assert result["status"]["username"] == "otterbad"
        assert result["transfers"] == []


class TestFailuresAreAnswers:
    @pytest.mark.asyncio
    async def test_not_configured_says_where_to_configure_it(self, monkeypatch):
        """An executor built without a container is a server with no slskd — the null capability."""
        executor = ToolExecutor(db=None, profile_id=uuid4())  # type: ignore[arg-type]
        monkeypatch.setattr(ToolExecutor, "_library_holdings", _holdings())
        for call in (
            executor._search_soulseek("x"),
            executor._download_from_soulseek("u", "d"),
            executor._get_soulseek_transfers(),
            executor._find_missing_on_soulseek("Lamb"),
        ):
            result = await call
            assert "Integrations → Soulseek" in result["error"]

    @pytest.mark.asyncio
    async def test_unreachable_is_named_not_raised(self, monkeypatch):
        import app.services.soulseek as mod

        monkeypatch.setattr(mod, "SEARCH_POLL_SECONDS", 0)

        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        executor = ToolExecutor(  # type: ignore[arg-type]
            db=None,
            profile_id=uuid4(),
            services=services_for(httpx.MockTransport(refuse), url="http://down:5030"),
        )
        result = await executor._search_soulseek("x")
        assert "Nothing answered at http://down:5030" in result["error"]
        transfers = await executor._get_soulseek_transfers()
        assert transfers["status"]["reachable"] is False
        assert transfers["transfers"] == []
