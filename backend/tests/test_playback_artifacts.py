"""The command channel's return path (ADR-0053 point 3).

ADR-0044 chose SSE because "commands are one-way, so the return half of a socket would be unused".
A screenshot is a return, and this is how it comes back without reversing that: the client uploads
when it has something to send, and the stream stays one-way.

The properties worth pinning are the ones whose absence is silent — a tool that waits forever, and
an image that outlives the question it answered.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.playback_commands import ArtifactStore, ArtifactTimeout


class TestDelivery:
    @pytest.mark.asyncio
    async def test_an_upload_reaches_the_waiter(self) -> None:
        store = ArtifactStore()
        store.open("req-1")

        async def upload() -> None:
            await asyncio.sleep(0)
            assert store.deliver("req-1", b"PNGDATA", "image/png")

        async with asyncio.TaskGroup() as group:
            group.create_task(upload())
            waited = group.create_task(store.wait("req-1", timeout=2))

        assert waited.result() == (b"PNGDATA", "image/png")

    @pytest.mark.asyncio
    async def test_waiting_on_a_request_nobody_opened_raises(self) -> None:
        store = ArtifactStore()
        with pytest.raises(ArtifactTimeout):
            await store.wait("never-asked", timeout=0.1)


class TestTheDeadline:
    @pytest.mark.asyncio
    async def test_a_client_that_never_answers_times_out(self) -> None:
        """The load-bearing one. A tool that hangs is the failure ADR-0044 point 5 exists to
        prevent, and it fails invisibly — the host simply waits."""
        store = ArtifactStore()
        store.open("req-2")
        with pytest.raises(ArtifactTimeout):
            await store.wait("req-2", timeout=0.05)

    @pytest.mark.asyncio
    async def test_a_late_upload_is_discarded_rather_than_stored(self) -> None:
        """Point 8. The question has already been answered with a timeout; keeping the image would
        mean keeping it forever, and it is a picture of somebody's library."""
        store = ArtifactStore()
        store.open("req-3")
        with pytest.raises(ArtifactTimeout):
            await store.wait("req-3", timeout=0.05)

        assert store.deliver("req-3", b"LATE", "image/png") is False
        assert not store._waiting


class TestHousekeeping:
    @pytest.mark.asyncio
    async def test_an_unknown_upload_is_refused(self) -> None:
        assert ArtifactStore().deliver("nobody-asked", b"x", "image/png") is False

    @pytest.mark.asyncio
    async def test_cancelling_drops_the_request(self) -> None:
        """The path taken when no player is attached: the command never went out, so nothing should
        be left waiting for an answer that cannot come."""
        store = ArtifactStore()
        store.open("req-4")
        store.cancel("req-4")
        assert store.deliver("req-4", b"x", "image/png") is False

    @pytest.mark.asyncio
    async def test_nothing_is_retained_after_a_successful_read(self) -> None:
        store = ArtifactStore()
        store.open("req-5")
        store.deliver("req-5", b"PNG", "image/png")
        assert await store.wait("req-5", timeout=1) == (b"PNG", "image/png")
        assert not store._waiting, "the artifact outlived the question it answered"


class TestTheRaceThatLostScreenshots:
    """A client fast enough to upload before the tool starts waiting.

    `deliver` used to pop the entry, so this resolved a future nobody held any more; `wait` then
    found no outstanding request and reported a timeout for an image that had already arrived.
    Rare, load-dependent and invisible — which is why it is pinned rather than reasoned about.
    """

    @pytest.mark.asyncio
    async def test_an_upload_that_arrives_before_the_wait_is_still_read(self) -> None:
        store = ArtifactStore()
        store.open("req-fast")
        assert store.deliver("req-fast", b"EARLY", "image/png")
        assert await store.wait("req-fast", timeout=1) == (b"EARLY", "image/png")
