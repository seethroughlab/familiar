"""The community cache answers every call an analysis worker makes, not only the first.

A worker calls asyncio.run() several times per track against one singleton service: the features
lookup, the detail lookup, the contribution. An httpx client is bound to the loop that first used
it, so every call after the first failed with "Event loop is closed" and was logged and treated as
a miss. Found 2026-10-02 on Familiar Server, where every cache hit's detail lookup failed this way.
"""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.services.community_cache import CommunityCacheService


@pytest.fixture
def answering():
    """A real HTTP server on localhost. A mock transport keeps no connections, so it cannot show
    the bug: what breaks is a pooled keep-alive connection reused from a loop that has closed."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"  # keep-alive, so the client pools the connection

        def _answer(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            body = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = _answer

        def log_message(self, *args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_each_asyncio_run_gets_an_answer(answering) -> None:
    service = CommunityCacheService(cache_url=answering)
    url = f"{answering}/v1/features/x"

    first = asyncio.run(service._request_with_retry("GET", url))
    second = asyncio.run(service._request_with_retry("GET", url))
    third = asyncio.run(service._request_with_retry("POST", url, json={}))

    assert first is not None and first.status_code == 200
    assert second is not None and second.status_code == 200, "the second asyncio.run() was a miss"
    assert third is not None and third.status_code == 200, "a contribution after a lookup was lost"


def test_one_loop_keeps_one_client(answering) -> None:
    service = CommunityCacheService(cache_url=answering)

    async def twice() -> bool:
        return await service._get_client() is await service._get_client()

    assert asyncio.run(twice())
