"""How many files the API will read at once (ADR-0111, server half).

**The test the last one should have been.** `test_stream_concurrency.py` drives three threads at a
route that answers 404 immediately, so nothing ever overlaps — it passed on 2026-08-02 while 1,720
favourites exhausted the database pool, and again on 2026-09-07 while the same trigger took the disk
and individual `/stream` requests ran to 180–424 seconds. A concurrency test whose load is below the
bound proves only that the code parses.

Everything here therefore runs at several times the ceiling it is asserting, and reads the
high-water mark rather than the configured constant: a bound compared against its own setting cannot
fail.

Driven through a stand-in app rather than the real one. What is being measured is the middleware's
accounting; the route it protects needs a database and a library disk, and a test that needs those
is a test nobody runs.
"""

import asyncio

import httpx
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.api.concurrency import (
    FileResponseConcurrencyMiddleware,
    FileResponseLimiter,
)


def build_app(limiter: FileResponseLimiter, hold: float = 0.05):
    """A file-serving route that takes long enough to overlap, behind the middleware.

    ``hold`` stands in for a ``FileResponse`` pushing bytes off a spinning disk, and it is the
    entire apparatus: requests that complete instantly never overlap, and a bound is unobservable
    without contention.
    """

    async def stream(request):
        await asyncio.sleep(hold)
        return PlainTextResponse("audio")

    async def albums(request):
        return PlainTextResponse("[]")

    inner = Starlette(
        routes=[
            Route("/api/v1/tracks/{track_id}/stream", stream),
            Route("/api/v1/tracks/{track_id}/artwork", stream),
            Route("/api/v1/library/albums", albums),
        ]
    )
    return FileResponseConcurrencyMiddleware(inner, limiter)


async def get_all(app, path, count, headers=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await asyncio.gather(
            *(client.get(path, headers=headers or {}) for _ in range(count))
        )


class TestTheBound:
    async def test_never_more_than_the_limit_are_in_flight(self):
        """Thirty at once against a ceiling of four."""
        limiter = FileResponseLimiter(total=4, sync=2)
        responses = await get_all(build_app(limiter), "/api/v1/tracks/x/stream", 30)

        assert limiter.peak_in_flight <= 4, "the ceiling is what this whole file is about"
        assert limiter.peak_in_flight > 1, "and a serial server would satisfy an upper bound alone"
        assert limiter.in_flight == 0, "every slot came back"
        assert len(responses) == 30, "and every request got an answer rather than hanging"
        assert limiter.refused_interactive > 0, "with the excess refused rather than queued"

    async def test_artwork_is_bounded_too(self):
        """3,458 artwork requests rode along with the 4,849 stream requests. A ceiling that covers
        only audio leaves the same thread-pool exhaustion reachable by another route."""
        limiter = FileResponseLimiter(artwork=3)
        await get_all(build_app(limiter), "/api/v1/tracks/x/artwork", 24)

        assert limiter.peak_artwork_in_flight <= 3
        assert limiter.peak_artwork_in_flight > 1


class TestArtworkWaitsWhereAudioRefuses:
    """**The correction the deploy produced, and the reason it is a rule rather than an exception.**

    Covers first shared the audio budget and were refused like anything else. Against the deployed
    ceiling, 24 concurrent cover requests produced 8 refusals — and a refused cover is a permanent
    hole in a grid, because nothing retries an `<img>`. The principle underneath both behaviours is
    the same: refuse when waiting would be indistinguishable from broken. A stream lasts minutes, so
    waiting tells a client nothing; a cover lasts milliseconds, so waiting is invisible.
    """

    async def test_a_burst_of_covers_is_served_rather_than_refused(self):
        limiter = FileResponseLimiter(artwork=4)
        responses = await get_all(build_app(limiter, hold=0.02), "/api/v1/tracks/x/artwork", 40)

        assert all(r.status_code == 200 for r in responses), "a grid must not come back full of holes"
        assert limiter.peak_artwork_in_flight <= 4, "and it is still bounded while it does that"
        assert limiter.refused_artwork == 0

    async def test_a_cover_is_still_refused_if_the_wait_runs_out(self):
        """The wait is a ceiling, not a promise. A server that is genuinely saturated says so rather
        than holding connections open indefinitely — which is the failure this whole file replaces.
        """
        limiter = FileResponseLimiter(artwork=1, artwork_wait=0.05)
        responses = await get_all(build_app(limiter, hold=0.2), "/api/v1/tracks/x/artwork", 10)

        assert any(r.status_code == 503 for r in responses)
        assert limiter.refused_artwork > 0
        assert limiter.peak_artwork_in_flight == 1

    async def test_covers_and_audio_do_not_share_a_budget(self):
        """Two different kinds of work on two different parts of the disk: a cover is 9–88 KB out of
        the artwork cache, a track is a whole-file read scattered across 16 TB of spinning rust."""
        limiter = FileResponseLimiter(total=2, sync=1, artwork=4)
        app = build_app(limiter, hold=0.1)

        streams, covers = await asyncio.gather(
            get_all(app, "/api/v1/tracks/x/stream", 12),
            get_all(app, "/api/v1/tracks/x/artwork", 12),
        )

        assert any(r.status_code == 503 for r in streams), "audio is over its own ceiling"
        assert all(r.status_code == 200 for r in covers), "and the covers are unaffected by that"
        assert limiter.peak_in_flight <= 2
        assert limiter.peak_artwork_in_flight <= 4

    async def test_only_file_responses_are_bounded(self):
        """Browsing must not queue behind a sync. The bound is about the library disk, and a JSON
        list of albums does not touch it."""
        limiter = FileResponseLimiter(total=2, sync=1)
        responses = await get_all(build_app(limiter), "/api/v1/library/albums", 30)

        assert all(r.status_code == 200 for r in responses)
        assert limiter.peak_in_flight == 0, "no slot was ever taken"


class TestTheReservation:
    async def test_sync_cannot_take_more_than_its_share(self):
        """**The reason intent is classified at all.**

        Twenty background transfers arrive at a server with twelve slots. Without the reservation
        they would take all twelve, which is 2026-09-07 at smaller scale: a cache fill occupying
        every thread while somebody tries to press play.
        """
        limiter = FileResponseLimiter(total=12, sync=4)
        await get_all(
            build_app(limiter),
            "/api/v1/tracks/x/stream",
            20,
            headers={"X-Familiar-Intent": "sync"},
        )

        assert limiter.peak_sync_in_flight <= 4
        assert limiter.refused_sync > 0
        assert limiter.refused_interactive == 0, "nobody was playing anything"

    async def test_playback_gets_through_while_a_sync_saturates_its_share(self):
        """The behavioural half of the point above, which counters alone do not prove."""
        limiter = FileResponseLimiter(total=6, sync=2)
        transport = httpx.ASGITransport(app=build_app(limiter, hold=0.15))

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            syncing = [
                asyncio.create_task(
                    client.get(
                        "/api/v1/tracks/x/stream",
                        headers={"X-Familiar-Intent": "sync"},
                    )
                )
                for _ in range(20)
            ]
            # Long enough for the sync transfers to have claimed everything they can.
            await asyncio.sleep(0.02)
            played = await client.get("/api/v1/tracks/y/stream")
            await asyncio.gather(*syncing)

        assert played.status_code == 200, "a person pressing play outranks a cache fill"
        assert limiter.peak_sync_in_flight <= 2

    async def test_unmarked_traffic_is_treated_as_playback(self):
        """The safe default: a client that has never heard of the header keeps a listener's
        priority and loses only the reservation."""
        limiter = FileResponseLimiter(total=4, sync=1)
        await get_all(build_app(limiter), "/api/v1/tracks/x/stream", 12)

        assert limiter.peak_sync_in_flight == 0
        assert limiter.peak_in_flight > 1


class TestRefusals:
    async def test_a_refusal_says_what_happened_and_when_to_come_back(self):
        """A refusal a client can act on, which a 424-second response is not.

        The envelope is `docs/ERROR-CONTRACTS.md`'s, deliberately: the 2026-08-02 incident ended
        with a client storing 834 error bodies as `.mp3`, so an error shaped like every other error
        is worth more here than a bespoke one.
        """
        limiter = FileResponseLimiter(total=2, sync=1)
        responses = await get_all(build_app(limiter), "/api/v1/tracks/x/stream", 12)

        refused = [r for r in responses if r.status_code == 503]
        assert refused, "twelve against two has to refuse something"
        for response in refused:
            assert response.headers["retry-after"] == "5"
            body = response.json()
            assert body["error"] is True
            assert body["status_code"] == 503
            assert "message" in body

    async def test_a_sync_refusal_is_told_to_wait_longer(self):
        """Nothing is watching a spinner for a background transfer, so it can come back later."""
        limiter = FileResponseLimiter(total=2, sync=1)
        responses = await get_all(
            build_app(limiter),
            "/api/v1/tracks/x/stream",
            12,
            headers={"X-Familiar-Intent": "sync"},
        )

        refused = [r for r in responses if r.status_code == 503]
        assert refused
        assert all(r.headers["retry-after"] == "30" for r in refused)


class TestSlotsComeBack:
    async def test_the_ceiling_does_not_ratchet_down(self):
        """**The failure worse than the one being fixed.**

        A slot taken and never returned makes the server refuse files forever, silently. Sixty
        sequential requests through a ceiling of two can only pass if every one of them released.
        """
        limiter = FileResponseLimiter(total=2, sync=1)
        transport = httpx.ASGITransport(app=build_app(limiter, hold=0))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(60):
                response = await client.get("/api/v1/tracks/x/stream")
                assert response.status_code == 200

        assert limiter.in_flight == 0
        assert limiter.refused_interactive == 0

    async def test_a_handler_that_raises_still_gives_its_slot_back(self):
        """An exception is one of the ways a response ends, and the rarest paths are the ones that
        leak. This is the middleware's `finally`, asserted."""

        async def explode(request):
            raise RuntimeError("the disk went away")

        limiter = FileResponseLimiter(total=2, sync=1)
        app = FileResponseConcurrencyMiddleware(
            Starlette(routes=[Route("/api/v1/tracks/{track_id}/stream", explode)]),
            limiter,
        )
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(5):
                await client.get("/api/v1/tracks/x/stream")

        assert limiter.in_flight == 0, "five failures must not consume the whole ceiling"
