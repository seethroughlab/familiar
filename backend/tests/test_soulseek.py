"""Tests for the slskd client (ADR-0116).

Recorded shapes rather than the network — every fixture below is a trimmed copy of what a real
slskd 0.23-era instance returned on 2026-09-13, because the two things these tests exist to pin
are both invisible in slskd's schema:

1. **Responses are empty until the search completes.** `responseCount` reports 29 within seconds
   while `GET /searches/{id}/responses` returns `[]` — the responses are persisted only when the
   search ends. A client that reads on the first positive count gets nothing, silently, forever.
2. **`extension` is blank for most files.** 22 of 35 files in one real search had `extension: ""`
   with a perfectly good `.flac` or `.mp3` on the filename. Trusting the field drops most results
   as "not audio".

And the ranking, which is a decision: lossless beats lossy, a free slot beats a queue, and both
beat raw speed.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.container import Services
from app.services.soulseek import (
    SoulseekGateway,
    SoulseekNotConfigured,
    SoulseekService,
    SoulseekUnreachable,
    _extension,
    _split_path,
    group_responses,
)

SEARCH_ID = "fcc7212a-52b6-48fc-bac8-ba83685bccd7"

# One sharer with a lossless copy and a free slot; one fast sharer with an mp3 and a queue; one
# sharer whose only match is a cue sheet. Filenames are real, `extension` is blank as slskd sends it.
RESPONSES: list[dict[str, Any]] = [
    {
        "username": "electrobutch",
        "hasFreeUploadSlot": True,
        "uploadSpeed": 7_254_927,
        "queueLength": 0,
        "fileCount": 1,
        "files": [
            {
                "filename": "music\\Organized\\Trip Hop\\aso\\2023 - a.s.o\\a.s.o. - a.s.o. - 03 Rain Down.flac",
                "size": 64_054_823,
                "extension": "",
                "bitDepth": 24,
                "sampleRate": 44100,
                "length": 311,
            }
        ],
    },
    {
        "username": "speedy",
        "hasFreeUploadSlot": False,
        "uploadSpeed": 90_000_000,
        "queueLength": 40,
        "fileCount": 2,
        "files": [
            {
                "filename": "music\\a.s.o_\\a.s.o_\\03 Rain Down.mp3",
                "size": 9_000_000,
                "extension": "mp3",
                "bitRate": 320,
            },
            {
                "filename": "music\\a.s.o_\\a.s.o_\\04 Go On.mp3",
                "size": 8_000_000,
                "extension": "",
                "bitRate": 320,
            },
        ],
    },
    {
        "username": "cuesheets",
        "hasFreeUploadSlot": True,
        "uploadSpeed": 1_000,
        "queueLength": 0,
        "fileCount": 1,
        "files": [{"filename": "rips\\aso\\a.s.o.cue", "size": 1200, "extension": ""}],
    },
]

DIRECTORY_LISTING = [
    {
        "name": "music\\Organized\\Trip Hop\\aso\\2023 - a.s.o",
        "fileCount": 3,
        "files": [
            {
                "filename": "a.s.o. - a.s.o. - 01 Go On.flac",
                "size": 30_428_220,
                "extension": "flac",
            },
            {
                "filename": "a.s.o. - a.s.o. - 03 Rain Down.flac",
                "size": 64_054_823,
                "extension": "flac",
            },
            {"filename": "cover.jpg", "size": 200_000, "extension": "jpg"},
        ],
    }
]


class FakeSlskd:
    """Enough of slskd's API to drive one search end to end, with the persistence quirk."""

    def __init__(self, *, polls_until_complete: int = 2) -> None:
        self.polls_until_complete = polls_until_complete
        self.polls = 0
        self.calls: list[tuple[str, str, Any]] = []
        self.deleted = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, body))
        path = request.url.path
        if path.endswith("/searches") and request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "id": SEARCH_ID,
                    "isComplete": False,
                    "responseCount": 0,
                    "state": "InProgress",
                },
            )
        if path.endswith(f"/searches/{SEARCH_ID}") and request.method == "GET":
            self.polls += 1
            done = self.polls >= self.polls_until_complete
            return httpx.Response(
                200,
                json={
                    "id": SEARCH_ID,
                    "isComplete": done,
                    "responseCount": 29,
                    "state": "Completed, TimedOut" if done else "InProgress",
                },
            )
        if path.endswith(f"/searches/{SEARCH_ID}/responses"):
            # The quirk: nothing until complete.
            complete = self.polls >= self.polls_until_complete
            return httpx.Response(200, json=RESPONSES if complete else [])
        if path.endswith(f"/searches/{SEARCH_ID}") and request.method == "PUT":
            self.polls = self.polls_until_complete
            return httpx.Response(200, json={})
        if path.endswith(f"/searches/{SEARCH_ID}") and request.method == "DELETE":
            self.deleted = True
            return httpx.Response(204)
        if path.endswith("/users/electrobutch/directory"):
            return httpx.Response(200, json=DIRECTORY_LISTING)
        if path.startswith("/api/v0/transfers/downloads/"):
            return httpx.Response(201, json={})
        if path.endswith("/transfers/downloads"):
            return httpx.Response(200, json=[])
        if path.endswith("/options"):
            return httpx.Response(
                200,
                json={
                    "directories": {
                        "downloads": "/downloads/complete",
                        "incomplete": "/downloads/incomplete",
                    }
                },
            )
        if path.endswith("/application"):
            return httpx.Response(
                200,
                json={
                    "server": {"state": "Connected, LoggedIn", "isLoggedIn": True},
                    "user": {"username": "otterbad"},
                    "version": {"current": "0.23.1"},
                    "shares": {"files": 25575},
                },
            )
        return httpx.Response(404)


def service(fake: FakeSlskd) -> SoulseekService:
    return SoulseekService("http://slskd:5030", "key", transport=httpx.MockTransport(fake.handler))


class FakeSoulseekConfiguration:
    """`SoulseekConfiguration` made of two strings — what a test hands the gateway (ADR-0130)."""

    def __init__(self, url: str | None = "http://slskd:5030", api_key: str | None = "k") -> None:
        self.url = url
        self.api_key = api_key

    def soulseek_url(self) -> str | None:
        return self.url

    def soulseek_api_key(self) -> str | None:
        return self.api_key


def services_for(
    transport: httpx.AsyncBaseTransport | None, *, url: str | None = "http://slskd:5030"
) -> Services:
    """A container whose Soulseek gateway talks to `transport`, or is unconfigured if `url` is None.

    This replaces monkeypatching `SoulseekService.from_settings` and the settings singleton's
    `has_soulseek_configured`, which is what every test of the poll and the tools used to do.
    """
    return Services(soulseek=SoulseekGateway(FakeSoulseekConfiguration(url), transport=transport))


class TestPaths:
    def test_backslash_paths_split(self):
        assert _split_path("a\\b\\c.flac") == ("a\\b", "c.flac")

    def test_forward_slash_paths_split_the_same_way(self):
        assert _split_path("a/b/c.flac") == ("a\\b", "c.flac")

    def test_extension_comes_from_the_filename_when_slskd_sends_none(self):
        assert _extension("x.FLAC", "") == "flac"
        assert _extension("x.mp3", None) == "mp3"
        assert _extension("README", "") == ""

    def test_a_reported_extension_wins(self):
        assert _extension("weird", "mp3") == "mp3"


class TestGrouping:
    def test_files_fold_into_folders_per_sharer(self):
        folders = group_responses(RESPONSES)
        assert [(f.username, len(f.audio_files)) for f in folders] == [
            ("electrobutch", 1),
            ("speedy", 2),
        ]

    def test_non_audio_matches_are_dropped_entirely(self):
        """A sharer whose only hit is a .cue is not a candidate."""
        assert all(f.username != "cuesheets" for f in group_responses(RESPONSES))

    def test_lossless_with_a_free_slot_outranks_fast_lossy_with_a_queue(self):
        best = group_responses(RESPONSES)[0]
        assert best.username == "electrobutch"
        assert best.formats == ["flac"]

    def test_the_summary_is_what_a_host_needs_to_choose(self):
        d = group_responses(RESPONSES)[1].to_dict()
        assert d["username"] == "speedy"
        assert d["has_free_upload_slot"] is False
        assert d["queue_length"] == 40
        assert d["formats"] == ["mp3"]
        assert d["files"] == ["03 Rain Down.mp3", "04 Go On.mp3"]


class TestSearch:
    @pytest.mark.asyncio
    async def test_waits_for_completion_before_reading(self, monkeypatch):
        """Reading responses before `isComplete` gets `[]`; the client must not do that."""
        import app.services.soulseek as mod

        monkeypatch.setattr(mod, "SEARCH_POLL_SECONDS", 0)
        fake = FakeSlskd(polls_until_complete=3)
        svc = service(fake)
        try:
            folders = await svc.search("a.s.o. rain down")
        finally:
            await svc.close()
        assert len(folders) == 2
        reads = [c for c in fake.calls if c[1].endswith("/responses")]
        assert len(reads) == 1, "responses read exactly once, after completion"
        assert fake.polls >= 3

    @pytest.mark.asyncio
    async def test_the_search_is_deleted_afterwards(self, monkeypatch):
        """slskd keeps every search until told otherwise; a host's one-offs should not pile up."""
        import app.services.soulseek as mod

        monkeypatch.setattr(mod, "SEARCH_POLL_SECONDS", 0)
        fake = FakeSlskd()
        svc = service(fake)
        try:
            await svc.search("x")
        finally:
            await svc.close()
        assert fake.deleted

    @pytest.mark.asyncio
    async def test_a_wedged_search_is_stopped_at_the_deadline(self, monkeypatch):
        import app.services.soulseek as mod

        monkeypatch.setattr(mod, "SEARCH_POLL_SECONDS", 0)
        fake = FakeSlskd(polls_until_complete=10_000)
        svc = service(fake)
        try:
            folders = await svc.search("x", wait_seconds=0)
        finally:
            await svc.close()
        assert any(c[0] == "PUT" for c in fake.calls), "asked slskd to stop the search"
        assert fake.deleted
        assert len(folders) == 2

    @pytest.mark.asyncio
    async def test_limit_is_honoured(self, monkeypatch):
        import app.services.soulseek as mod

        monkeypatch.setattr(mod, "SEARCH_POLL_SECONDS", 0)
        svc = service(FakeSlskd())
        try:
            assert len(await svc.search("x", limit=1)) == 1
        finally:
            await svc.close()


class TestFolderAndEnqueue:
    @pytest.mark.asyncio
    async def test_the_full_listing_is_fetched_and_paths_rebuilt(self):
        fake = FakeSlskd()
        svc = service(fake)
        try:
            folder = await svc.folder(
                "electrobutch", "music\\Organized\\Trip Hop\\aso\\2023 - a.s.o"
            )
        finally:
            await svc.close()
        # The search matched one track; the folder has two audio files and a cover.
        assert [f.name for f in folder.audio_files] == [
            "a.s.o. - a.s.o. - 01 Go On.flac",
            "a.s.o. - a.s.o. - 03 Rain Down.flac",
        ]
        assert (
            folder.audio_files[0].filename
            == "music\\Organized\\Trip Hop\\aso\\2023 - a.s.o\\a.s.o. - a.s.o. - 01 Go On.flac"
        )
        body = next(c[2] for c in fake.calls if c[1].endswith("/directory"))
        assert body == {"directory": "music\\Organized\\Trip Hop\\aso\\2023 - a.s.o"}

    @pytest.mark.asyncio
    async def test_enqueue_posts_filename_and_size_per_file(self):
        fake = FakeSlskd()
        svc = service(fake)
        try:
            folder = await svc.folder(
                "electrobutch", "music\\Organized\\Trip Hop\\aso\\2023 - a.s.o"
            )
            n = await svc.enqueue("electrobutch", folder.audio_files)
        finally:
            await svc.close()
        assert n == 2
        method, path, body = next(c for c in fake.calls if "/transfers/downloads/" in c[1])
        assert (method, path) == ("POST", "/api/v0/transfers/downloads/electrobutch")
        assert body == [
            {
                "filename": "music\\Organized\\Trip Hop\\aso\\2023 - a.s.o\\a.s.o. - a.s.o. - 01 Go On.flac",
                "size": 30_428_220,
            },
            {
                "filename": "music\\Organized\\Trip Hop\\aso\\2023 - a.s.o\\a.s.o. - a.s.o. - 03 Rain Down.flac",
                "size": 64_054_823,
            },
        ]

    @pytest.mark.asyncio
    async def test_enqueue_of_nothing_posts_nothing(self):
        fake = FakeSlskd()
        svc = service(fake)
        try:
            assert await svc.enqueue("electrobutch", []) == 0
        finally:
            await svc.close()
        assert not any("/transfers/" in c[1] for c in fake.calls)


class TestStatus:
    """`status()` is the settings panel's "test connection" — each failure names its own fix."""

    @pytest.mark.asyncio
    async def test_a_logged_in_slskd_reports_itself(self):
        svc = service(FakeSlskd())
        try:
            status = await svc.status()
        finally:
            await svc.close()
        assert status.reachable and status.logged_in
        assert status.username == "otterbad"
        assert status.shared_files == 25575
        assert status.error is None

    @pytest.mark.asyncio
    async def test_nothing_listening_is_said_plainly(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        svc = SoulseekService("http://nowhere:5030", None, transport=httpx.MockTransport(handler))
        try:
            status = await svc.status()
        finally:
            await svc.close()
        assert not status.reachable
        assert "Nothing answered at http://nowhere:5030" in (status.error or "")

    @pytest.mark.asyncio
    async def test_a_bad_key_is_named(self):
        svc = SoulseekService(
            "http://slskd:5030",
            "wrong",
            transport=httpx.MockTransport(lambda r: httpx.Response(401)),
        )
        try:
            status = await svc.status()
        finally:
            await svc.close()
        assert not status.reachable
        assert "API key" in (status.error or "")

    @pytest.mark.asyncio
    async def test_a_server_that_is_not_slskd_is_named(self):
        """A 200 of HTML from some other service must not read as 'connected'."""
        svc = SoulseekService(
            "http://plex:32400",
            None,
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, text="<html>not json</html>")
            ),
        )
        try:
            status = await svc.status()
        finally:
            await svc.close()
        assert not status.reachable
        assert "not slskd" in (status.error or "")

    @pytest.mark.asyncio
    async def test_up_but_logged_out_is_reachable_with_a_reason(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "server": {"state": "Disconnected", "isLoggedIn": False},
                    "user": {},
                    "version": {"current": "x"},
                    "shares": {},
                },
            )

        svc = SoulseekService("http://slskd:5030", None, transport=httpx.MockTransport(handler))
        try:
            status = await svc.status()
        finally:
            await svc.close()
        assert status.reachable and not status.logged_in
        assert "not logged in" in (status.error or "")

    @pytest.mark.asyncio
    async def test_other_operations_raise_rather_than_return_empty(self):
        """Only status() swallows; a search against a dead slskd must not look like 'no results'."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        svc = SoulseekService("http://nowhere:5030", None, transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(SoulseekUnreachable):
                await svc.search("x")
        finally:
            await svc.close()


class TestDownloadsSummary:
    @pytest.mark.asyncio
    async def test_one_line_per_folder_with_counts(self):
        raw = [
            {
                "username": "late_late_nite",
                "directories": [
                    {
                        "directory": "MUSIC\\INDIE\\Felt",
                        "files": [
                            {"state": "Completed, Succeeded", "size": 100, "bytesTransferred": 100},
                            {"state": "InProgress", "size": 100, "bytesTransferred": 50},
                            {"state": "Queued, Remotely", "size": 100, "bytesTransferred": 0},
                            {"state": "Completed, Errored", "size": 100, "bytesTransferred": 0},
                        ],
                    }
                ],
            }
        ]
        svc = SoulseekService(
            "http://slskd:5030",
            None,
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=raw)),
        )
        try:
            rows = await svc.downloads()
        finally:
            await svc.close()
        assert rows == [
            {
                "username": "late_late_nite",
                "directory": "MUSIC\\INDIE\\Felt",
                "files": 4,
                "completed": 1,
                "failed": 1,
                "in_progress": 1,
                "queued": 1,
                "percent": 38,
                "settled": False,
            }
        ]


class TestGateway:
    """The application's handle on slskd (ADR-0130): configured-ness is asked every time."""

    def test_unconfigured_when_the_url_is_empty(self):
        for url in (None, ""):
            gateway = SoulseekGateway(FakeSoulseekConfiguration(url))
            assert gateway.configured is False
            assert gateway.url is None

    def test_the_url_alone_configures_it(self):
        gateway = SoulseekGateway(FakeSoulseekConfiguration("http://slskd:5030", api_key=None))
        assert gateway.configured is True

    @pytest.mark.asyncio
    async def test_a_client_is_closed_on_exit_and_talks_to_the_transport(self):
        fake = FakeSlskd()
        gateway = SoulseekGateway(
            FakeSoulseekConfiguration(), transport=httpx.MockTransport(fake.handler)
        )
        async with gateway.client() as slsk:
            status = await slsk.status()
            assert status.logged_in is True
        assert slsk._client.is_closed

    @pytest.mark.asyncio
    async def test_a_client_for_an_unconfigured_gateway_says_where_to_configure_it(self):
        gateway = SoulseekGateway(FakeSoulseekConfiguration(None))
        with pytest.raises(SoulseekNotConfigured, match="Integrations → Soulseek"):
            async with gateway.client():
                pass

    @pytest.mark.asyncio
    async def test_configuration_is_read_per_call_not_captured(self):
        """Setting the URL in the panel takes effect on the next use, without a restart."""
        configuration = FakeSoulseekConfiguration(None)
        gateway = SoulseekGateway(configuration)
        assert gateway.configured is False
        configuration.url = "http://slskd:5030"
        assert gateway.configured is True

