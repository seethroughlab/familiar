"""A ceiling on how many files the API will read at once.

**This is the server half of ADR-0111, and it exists because the client half is not enough.**

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

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

#: Audio responses in flight at once.
#:
#: Twelve against anyio's 40 threads. The number is chosen to keep the disk usefully busy while
#: leaving most of the pool for everything else — during the incident, ``/health`` was answering
#: slowly because file reads for a background sync had taken every thread, which is what made this
#: a server concern rather than only a client one. The library lives on one 7,200 RPM disk that
#: serves on the order of 150 seeks a second, so twelve scattered whole-file reads is already
#: generous; the ceiling is here to stop forty, not to tune throughput.
MAX_CONCURRENT_STREAM_RESPONSES = 12

#: Artwork responses in flight at once, on a budget of its own.
#:
#: **Found by deploying, not by reasoning**, and the first version of this file got it wrong. Covers
#: shared the audio budget on the argument that a cover cycles through its slot in milliseconds and
#: therefore costs a stream almost nothing. That is true and it is not the point: 24 concurrent
#: cover requests against the deployed ceiling produced **8 refusals**, and a refused cover is a
#: permanent hole in a grid. Nothing retries an ``<img>``.
#:
#: So the two are separated, and the difference in the numbers follows the difference in the work.
#: A cover is 9–88 KB from the artwork cache, usually already in the page cache; a track is a
#: whole-file read scattered across a 16 TB spinning disk. Sixteen of the former is not sixteen of
#: the latter, and 12 + 16 still sits comfortably under the 40-token pool because artwork holds its
#: thread for milliseconds.
MAX_CONCURRENT_ARTWORK_RESPONSES = 16

#: How long a cover may wait for a slot before it is refused.
#:
#: **Artwork waits where audio does not, and the asymmetry is the principle rather than an
#: exception.** The rule underneath both is the same: refuse when waiting would be indistinguishable
#: from broken. A stream response lasts minutes, so a queued request tells a client nothing and
#: holds a connection while doing it. A cover response lasts milliseconds, so a two-second ceiling
#: on waiting is invisible to a person and strictly better than the alternative, which is a
#: placeholder where an album used to be.
ARTWORK_WAIT_SECONDS = 2.0

#: How many of those may be background sync.
#:
#: **The reservation is the point of classifying at all.** Sync can never take more than a third of
#: the budget, so somebody pressing play always has eight slots that a cache fill cannot touch.
#: A single well-behaved client presents at most three sync transfers (ADR-0111's client bound), so
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


def classify_path(path: str) -> str | None:
    """Which budget this path draws on, or ``None`` if it is not bounded here.

    Both endpoints are bounded, because both were in the incident: 4,849 ``/stream`` requests and
    **3,458 ``/artwork`` requests** in the same window. They are bounded separately for the reason
    given at ``MAX_CONCURRENT_ARTWORK_RESPONSES``.
    """
    if not path.startswith("/api/v1/tracks/"):
        return None
    if path.endswith("/stream"):
        return "stream"
    if path.endswith("/artwork"):
        return "artwork"
    return None


class FileResponseLimiter:
    """The budgets, and the accounting for them.

    Split out from the middleware so the suite can drive it without an ASGI app, and so the
    counters have somewhere to live that a health check could read later.
    """

    def __init__(
        self,
        total: int = MAX_CONCURRENT_STREAM_RESPONSES,
        sync: int = MAX_CONCURRENT_SYNC_RESPONSES,
        artwork: int = MAX_CONCURRENT_ARTWORK_RESPONSES,
        artwork_wait: float = ARTWORK_WAIT_SECONDS,
    ) -> None:
        self.total_limit = total
        self.sync_limit = sync
        self.artwork_limit = artwork
        self.artwork_wait = artwork_wait
        self.in_flight = 0
        self.sync_in_flight = 0
        self.artwork_in_flight = 0
        self.peak_artwork_in_flight = 0
        self.refused_artwork = 0
        # A semaphore here and counters above, because this is the one budget anybody waits on.
        # Loop-agnostic since Python 3.10, so constructing it at import time is safe; the container
        # runs 3.11.
        self._artwork = asyncio.Semaphore(artwork)
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

    async def acquire_artwork(self) -> bool:
        """Wait briefly for a cover slot, and refuse only if the wait runs out.

        See ``ARTWORK_WAIT_SECONDS``: a cover that waits 20 ms is invisible, and a cover that is
        refused is a hole in a grid that nothing will fill, because no ``<img>`` retries.
        """
        try:
            await asyncio.wait_for(self._artwork.acquire(), self.artwork_wait)
        except TimeoutError:
            self.refused_artwork += 1
            return False
        self.artwork_in_flight += 1
        self.peak_artwork_in_flight = max(self.peak_artwork_in_flight, self.artwork_in_flight)
        return True

    def release_artwork(self) -> None:
        self.artwork_in_flight -= 1
        self._artwork.release()


#: One per process. ``--workers 1`` is pinned in the Dockerfile because CLAP needs ~1.5 GB, so a
#: module-level limiter really does bound the whole API rather than one worker's share of it. If
#: that ever changes, this number becomes per worker and has to be divided by hand.
limiter = FileResponseLimiter()


#: ffmpeg encodes running at once (ADR-0118 point 5).
#:
#: **A third bound, on a third resource.** The file-response ceiling above assumes a slot is held
#: for a network transfer. An AAC encode holds a *core* — 12.4 s for a 4:32 FLAC, measured on the
#: NAS, one core each — before the transfer even begins. The finding this whole module records is
#: that a ceiling on one resource moves the queue to the next; the encoder is the next. Four of
#: eight cores leaves the API, Postgres and analysis the rest.
#:
#: Waits rather than refuses, which is the opposite of the stream budget and for the same rule —
#: refuse only when waiting would be indistinguishable from broken. A wait here is a few encodes,
#: seconds, and only ever on the *first* request for a track; after that the cache answers.
MAX_CONCURRENT_ENCODES = 4


class EncoderLimiter:
    """The bound on concurrent ffmpeg runs, and the accounting for it.

    Acquired around the encode only, never around the serve, so a cache hit never touches it.
    """

    def __init__(self, limit: int = MAX_CONCURRENT_ENCODES) -> None:
        self.limit = limit
        self._slots = asyncio.Semaphore(limit)
        self.in_flight = 0
        #: The high-water mark, for the same reason the stream limiter keeps one.
        self.peak_in_flight = 0
        #: How many encodes had to wait for a slot. Above zero during a first sync is expected;
        #: above zero during ordinary listening means the bound is too low or the cache is cold.
        self.waited = 0

    async def acquire(self) -> None:
        if self._slots.locked():
            self.waited += 1
        await self._slots.acquire()
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)

    def release(self) -> None:
        self.in_flight -= 1
        self._slots.release()


#: One per process, for the reason ``limiter`` is. Sized from settings so the first real sync can
#: be tuned without a deploy (``TRANSCODE_CONCURRENCY``); the constant above is the default.
def _configured_encoder_limiter() -> EncoderLimiter:
    from app.config import settings

    return EncoderLimiter(settings.transcode_concurrency)


encoder_limiter = _configured_encoder_limiter()


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
        kind = (
            classify_path(scope.get("path", ""))
            if scope["type"] == "http" and scope.get("method") in ("GET", "HEAD")
            else None
        )
        if kind is None:
            await self.app(scope, receive, send)
            return

        is_sync = self._is_sync(scope)
        if kind == "artwork":
            admitted = await self.limiter.acquire_artwork()
        else:
            admitted = self.limiter.try_acquire(is_sync=is_sync)

        if not admitted:
            logger.warning(
                "Refused %s %s response: %d streams and %d covers in flight (limits %d/%d)",
                "sync" if is_sync else "interactive",
                kind,
                self.limiter.in_flight,
                self.limiter.artwork_in_flight,
                self.limiter.total_limit,
                self.limiter.artwork_limit,
            )
            await self._refuse(scope, send, is_sync=is_sync)
            return

        released = False

        def release_once() -> None:
            nonlocal released
            if not released:
                released = True
                if kind == "artwork":
                    self.limiter.release_artwork()
                else:
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
