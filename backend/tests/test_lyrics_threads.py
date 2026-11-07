"""Lyrics and MusicBrainz each run on their own threads, not the default executor.

On 2026-11-07 MusicBrainz returned 503s, `musicbrainzngs` retried behind its one-per-second lock, and
callers' `asyncio.wait_for` timeouts cancelled coroutines while their threads carried on. The
orphans filled the default executor, and lyrics requests, which did their stat, kv lookup and tag
read through `asyncio.to_thread`, took 80-90 s before the 8 s deadline had even started.
"""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.api.routes.tracks import streaming
from app.services.metadata.musicbrainz import run_musicbrainz


async def _with_the_default_pool_full(work):
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
    gate = threading.Event()
    blocker = loop.run_in_executor(None, gate.wait)
    try:
        return await asyncio.wait_for(work(), timeout=2)
    finally:
        gate.set()
        await blocker


@pytest.mark.asyncio
async def test_lyrics_work_does_not_wait_for_the_default_pool():
    assert await _with_the_default_pool_full(lambda: streaming._lyrics_thread(lambda: 42)) == 42


@pytest.mark.asyncio
async def test_musicbrainz_calls_do_not_occupy_the_default_pool():
    assert await _with_the_default_pool_full(lambda: run_musicbrainz(lambda name: name.upper(), "x")) == "X"


@pytest.mark.asyncio
async def test_the_old_way_would_have_waited():
    # The control: the same work through `asyncio.to_thread` does not finish while the pool is full.
    with pytest.raises(TimeoutError):
        await _with_the_default_pool_full(lambda: asyncio.to_thread(lambda: 42))
