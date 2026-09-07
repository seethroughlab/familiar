"""A ceiling on how many files the API will read at once.

**This is the server half of ADR-0110, and it exists because the client half is not enough.**

Favourites auto-download has taken this server down twice, five weeks apart, by the same mechanism
against two different resources:

- 2026-08-02: 1,720 favourites produced 2,416 ``QueuePool limit ... timed out`` errors. Fixed by
  releasing the database connection before the body is sent (``streaming.py``), and that class of
  failure has not recurred.
- 2026-09-07: the same trigger took the disk and the thread pool instead. Load 41 on eight cores,
  82–89% iowait, 42 tasks blocked in uninterruptible reads — 37–39 of them uvicorn threads sitting
  on anyio's process-wide 40-token pool, which ``--workers 1`` makes the only pool this API has.
  Individual ``/stream`` requests took **180 to 424 seconds**.

The generalisable finding is that capping a downstream resource relocates the queue rather than
removing it. The client now bounds itself at three concurrent transfers, which is the fix that
matters most — but a server with no ceiling of its own is one bad client away from repeating this,
and "one bad client" includes an old build of our own app that has not been updated, a second
listener, or a browser tab with an aggressive prefetch.

**Why a middleware and not a dependency.** The scarce resource is held for as long as the *body* is
being sent, not for as long as the handler runs. A FastAPI dependency — even a ``yield`` one —
releases at the wrong moment for a 40 MB file, which is exactly the mistake the 2026-08-02 fix was
correcting. A pure-ASGI middleware can wrap ``send`` and release when the last body message goes
out, which is the only placement that actually bounds anything.

**Why 503 rather than a queue.** From the ops note, and it is the sharper half of this design: a
client that is told to back off can back off; a client whose request is accepted and then takes 424
seconds cannot tell the difference between slow and broken. The 2026-08-02 incident ended with a
client writing HTTP error bodies to disk as ``.mp3`` — an explicit, well-formed refusal is far
easier to handle correctly than a timeout.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

#: Total file responses in flight at once, of every kind.
#:
#: Twelve against anyio's 40 threads. The number is chosen to keep the disk usefully busy while
#: leaving most of the pool for everything else — during the incident, ``/health`` was answering
#: slowly because file reads for a background sync had taken every thread, which is what made this
#: a server concern rather than only a client one. The library lives on one 7,200 RPM disk that
#: serves on the order of 150 seeks a second, so twelve scattered whole-file reads is already
#: generous; the ceiling is here to stop forty, not to tune throughput.
MAX_CONCURRENT_FILE_RESPONSES = 12

#: How many of those may be background sync.
#:
#: **The reservation is the point of classifying at all.** Sync can never take more than a third of
#: the budget, so somebody pressing play always has eight slots that a cache fill cannot touch.
#: A single well-behaved client presents at most three sync transfers (ADR-0110's client bound), so
#: this fits one syncing device comfortably and makes a second one queue rather than compete.
MAX_CONCURRENT_SYNC_RESPONSES = 4

#: The header a client sets to say "this is a background cache fill, not a person pressing play".
#:
#: **A header rather than a query parameter**, though the ops note offered both. A parameter is part
#: of the URL, so the same track would have two cache keys — the client's ``URLCache`` would hold a
#: synced copy and a played copy separately, and every CDN or proxy in between would too. The
#: distinction is about the *intent* of a request, not about which bytes are wanted, and intent
#: belongs in a header.
INTENT_HEADER = b"x-familiar-intent"
SYNC_INTENT = b"sync"

#: Seconds to tell each class to wait before trying again.
#:
#: Different because the situations are different: a sync has a queue and nothing is waiting on any
#: particular track, so it can afford to come back in half a minute. A person pressing play is
#: watching a spinner.
SYNC_RETRY_AFTER = 30
INTERACTIVE_RETRY_AFTER = 5


def _is_file_response_path(path: str) -> bool:
    """Whether this path serves a file off the library disk.

    Both endpoints, because both were in the incident: 4,849 ``/stream`` requests and **3,458
    ``/artwork`` requests** in the same window. Artwork is small and fast, which is an argument for
    a shared budget rather than a separate one — a cover cycles through its slot in milliseconds,
    so it costs a stream almost nothing, while a thousand of them at once is the same thread-pool
    exhaustion by another name.
    """
    return path.startswith("/api/v1/tracks/") and (
        path.endswith("/stream") or path.endswith("/artwork")
    )


class FileResponseLimiter:
    """The two budgets, and the accounting for them.

    Split out from the middleware so the suite can drive it without an ASGI app, and so the
    counters have somewhere to live that a health check could read later.
    """

    def __init__(
        self,
        total: int = MAX_CONCURRENT_FILE_RESPONSES,
        sync: int = MAX_CONCURRENT_SYNC_RESPONSES,
    ) -> None:
        self.total_limit = total
        self.sync_limit = sync
        self.in_flight = 0
        self.sync_in_flight = 0
        #: The high-water mark, which is the number worth having: it says what the server was
        #: actually asked to do, where a refusal count only says when it said no.
        self.peak_in_flight = 0
        self.peak_sync_in_flight = 0
        #: Refusals since start, by class. Not a metric anybody watches yet; the reason it is here
        #: is that both incidents were diagnosed from the outside, by counting log lines on the NAS,
        #: because the server itself recorded nothing about the pressure it was under.
        self.refused_sync = 0
        self.refused_interactive = 0

    def try_acquire(self, *, is_sync: bool) -> bool:
        """Take a slot, or report that there is none.

        **Never waits, and that is deliberate for both classes.** Waiting is the failure mode this
        replaces: a request that is accepted and then sits for 424 seconds is indistinguishable
        from a broken server, and it holds a connection while it does. A refusal is information.

        Two plain counters rather than ``asyncio.Semaphore``, precisely *because* nothing here
        waits — a semaphore's value is the same arithmetic behind a queue nobody uses, and reading
        it back for the high-water mark means reaching into a private attribute. This is safe
        without a lock for the reason all of asyncio is: there is no ``await`` between the check
        and the increment, so no other task can run in between.
        """
        if self.in_flight >= self.total_limit:
            self._record_refusal(is_sync=is_sync)
            return False
        if is_sync and self.sync_in_flight >= self.sync_limit:
            self._record_refusal(is_sync=True)
            return False

        self.in_flight += 1
        if is_sync:
            self.sync_in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        self.peak_sync_in_flight = max(self.peak_sync_in_flight, self.sync_in_flight)
        return True

    def _record_refusal(self, *, is_sync: bool) -> None:
        if is_sync:
            self.refused_sync += 1
        else:
            self.refused_interactive += 1

    def release(self, *, is_sync: bool) -> None:
        self.in_flight -= 1
        if is_sync:
            self.sync_in_flight -= 1


#: One per process. ``--workers 1`` is pinned in the Dockerfile because CLAP needs ~1.5 GB, so a
#: module-level limiter really does bound the whole API rather than one worker's share of it. If
#: that ever changes, this number becomes per worker and has to be divided by hand.
limiter = FileResponseLimiter()


class FileResponseConcurrencyMiddleware:
    """Hold a slot for the whole of a file response, and refuse when there are none.

    Placed inside ``TokenAuthMiddleware`` so an unauthenticated request cannot spend a slot, and
    inside ``RequestIDMiddleware`` so a refusal carries the ``x-request-id`` that correlates it with
    the request that was turned away.
    """

    def __init__(self, app: Any, limiter_: FileResponseLimiter | None = None) -> None:
        self.app = app
        self.limiter = limiter_ or limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Reads only. The same `/artwork` path takes an upload, which is a small write that touches
        # neither the library disk nor the read path this bounds — and spending a slot on it would
        # let editing a cover be refused because somebody else is listening.
        if (
            scope["type"] != "http"
            or scope.get("method") not in ("GET", "HEAD")
            or not _is_file_response_path(scope.get("path", ""))
        ):
            await self.app(scope, receive, send)
            return

        is_sync = self._is_sync(scope)
        if not self.limiter.try_acquire(is_sync=is_sync):
            logger.warning(
                "Refused %s file response: %d in flight, limit %d (path=%s)",
                "sync" if is_sync else "interactive",
                self.limiter.in_flight,
                self.limiter.total_limit,
                scope.get("path", ""),
            )
            await self._refuse(scope, send, is_sync=is_sync)
            return

        released = False

        def release_once() -> None:
            nonlocal released
            if not released:
                released = True
                self.limiter.release(is_sync=is_sync)

        async def send_and_release(message: Message) -> None:
            await send(message)
            # **The last body message, not the response start.** A ``FileResponse`` sends its
            # headers immediately and then streams for as long as the file takes; releasing at the
            # start would bound nothing at all, which is the shape of the mistake this middleware
            # exists to avoid.
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                release_once()

        try:
            await self.app(scope, receive, send_and_release)
        finally:
            # A client that hangs up mid-track, an exception, a response that never reaches its
            # last body message — every one of them has to give the slot back, or the ceiling
            # ratchets down to zero and the server stops serving files at all. That failure is
            # worse than the one being fixed, because it is silent.
            release_once()

    @staticmethod
    def _is_sync(scope: Scope) -> bool:
        for name, value in scope.get("headers", []):
            if name.lower() == INTENT_HEADER:
                return value.strip().lower() == SYNC_INTENT
        # Unmarked traffic is interactive. That is the safe default: an old client, a browser, or
        # anything that has never heard of this header keeps the priority a listener expects, and
        # the only thing it loses is the reservation.
        return False

    async def _refuse(self, scope: Scope, send: Send, *, is_sync: bool) -> None:
        retry_after = SYNC_RETRY_AFTER if is_sync else INTERACTIVE_RETRY_AFTER
        # The envelope from `docs/ERROR-CONTRACTS.md`, built by hand rather than through
        # `create_error_response` in `main.py`: importing that here would be circular, since
        # `main` installs this middleware.
        body = {
            "error": True,
            "status_code": 503,
            "message": "The server is reading as many files as it can at once. Try again shortly.",
            "detail": (
                "Background sync is limited so that playback stays responsive."
                if is_sync
                else "Too many file transfers in flight."
            ),
        }
        request_id = scope.get("state", {}).get("request_id")
        if request_id:
            body["request_id"] = request_id
        payload = json.dumps(body).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 503,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode()),
                    (b"retry-after", str(retry_after).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload, "more_body": False})
