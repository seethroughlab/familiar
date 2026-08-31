"""Source health is durable, and the job acts on it (ADR-0099 points 4, 6, 8, 10).

The question is whether a source is *working*, not whether a key is configured.
A source can hold a valid key, be scheduled, run every night, fail every time, and
look identical to a healthy one — which is exactly what happened for nineteen
nights.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.models import DiscoverySourceHealth
from app.services.discovery.sources import (
    BACKOFF_MAX_SECONDS,
    SourceHealthRecorder,
    backoff_seconds,
)
from app.utils.time import utcnow


def _recorder(async_db):
    """A recorder over the test session.

    Production uses its own engine per the class docstring; here one session keeps
    the assertions readable, and the separate-session requirement has its own test.
    """
    class _Factory:
        def __call__(self):
            return _Ctx(async_db)

    class _Ctx:
        def __init__(self, db):
            self.db = db

        async def __aenter__(self):
            return self.db

        async def __aexit__(self, *exc):
            return False

    return SourceHealthRecorder(_Factory())


async def _row(async_db, source: str):
    return (
        await async_db.execute(
            select(DiscoverySourceHealth).where(DiscoverySourceHealth.source == source)
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Backoff arithmetic
# ---------------------------------------------------------------------------


def test_backoff_grows_and_is_capped():
    """Capped so a recovered source is not ignored for hours after an outage ends."""
    assert backoff_seconds(0) == 0
    assert backoff_seconds(1) == 60
    assert backoff_seconds(2) == 120
    assert backoff_seconds(3) == 240
    assert backoff_seconds(99) == BACKOFF_MAX_SECONDS


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failure_sets_backoff_and_success_clears_it(async_db):
    rec = _recorder(async_db)

    await rec.record_failure("musicbrainz", kind="rate_limited", detail="503")
    assert await rec.should_skip("musicbrainz") is True
    row = await _row(async_db, "musicbrainz")
    assert row.consecutive_failures == 1
    assert row.last_failure_kind == "rate_limited"

    await rec.record_success("musicbrainz", items=3)
    assert await rec.should_skip("musicbrainz") is False
    row = await _row(async_db, "musicbrainz")
    assert row.consecutive_failures == 0
    assert row.backoff_until is None
    assert row.items_contributed == 3


@pytest.mark.asyncio
async def test_retry_after_is_preferred_to_our_guess(async_db):
    """The source telling us when to return beats an exponential guess — including
    when it is shorter, which a `max()` would have thrown away."""
    rec = _recorder(async_db)
    for _ in range(5):
        await rec.record_failure("lastfm", kind="rate_limited")
    await rec.record_failure("lastfm", kind="rate_limited", retry_after_seconds=5)

    row = await _row(async_db, "lastfm")
    assert (row.backoff_until - utcnow().replace(tzinfo=None)) < timedelta(seconds=30)


@pytest.mark.asyncio
async def test_items_contributed_accumulates(async_db):
    """A source that answers every call and yields nothing is a different problem
    from one that errors, and a success timestamp cannot tell them apart."""
    rec = _recorder(async_db)
    await rec.record_success("bandcamp", items=2)
    await rec.record_success("bandcamp", items=5)
    row = await _row(async_db, "bandcamp")
    assert row.items_contributed == 7


@pytest.mark.asyncio
async def test_a_source_in_backoff_does_not_block_the_others(async_db):
    """Point 4's only real assertion.

    With one source wired this looks trivial; it is the property that has to hold
    before a second source can be added, and asserting it now is what stops the
    shape regressing while nobody is looking.
    """
    rec = _recorder(async_db)
    await rec.record_failure("musicbrainz", kind="rate_limited")

    assert await rec.should_skip("musicbrainz") is True
    assert await rec.should_skip("lastfm") is False
    assert await rec.should_skip("bandcamp") is False


@pytest.mark.asyncio
async def test_an_unreadable_health_record_does_not_stop_discovery(async_db):
    """Failing open is deliberate.

    Skipping on an unknown state would let a database blip silently stop discovery —
    which is the failure mode this whole ADR exists to prevent, reintroduced by the
    mechanism meant to detect it.
    """
    class _Broken:
        def __call__(self):
            raise RuntimeError("no database")

    assert await SourceHealthRecorder(_Broken()).should_skip("musicbrainz") is False


# ---------------------------------------------------------------------------
# The endpoint the Server page reads
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_never_succeeded_is_distinct_from_working(async_db, client):
    """ADR-0099 point 8, as a shape a client can render.

    A seeded row with no success is *not* "nothing found yet" — it was the true
    state for nineteen nights and nothing said so.
    """
    async_db.add(DiscoverySourceHealth(source="musicbrainz"))
    await async_db.commit()

    data = client.get("/api/v1/health/discovery-sources").json()
    by_source = {s["source"]: s for s in data["sources"]}

    assert by_source["musicbrainz"]["state"] == "never_succeeded"
    assert data["status"] == "never_succeeded"


@pytest.mark.asyncio
async def test_a_source_failing_for_days_does_not_look_healthy(async_db, client):
    """The acceptance criterion, in the ADR's own terms.

    A source with a valid key that has failed every night for nineteen days must
    not be indistinguishable from a working one — which is precisely what
    `ApiKeyStatus.tsx` showed, because it answers a different question.
    """
    long_ago = utcnow().replace(tzinfo=None) - timedelta(days=19)
    async_db.add(
        DiscoverySourceHealth(
            source="musicbrainz",
            last_success_at=long_ago,
            last_failure_at=utcnow().replace(tzinfo=None),
            last_failure_kind="rate_limited",
            consecutive_failures=19,
            items_contributed=600,
        )
    )
    await async_db.commit()

    data = client.get("/api/v1/health/discovery-sources").json()
    mb = next(s for s in data["sources"] if s["source"] == "musicbrainz")

    assert mb["state"] == "failing"
    assert mb["consecutive_failures"] == 19
    assert mb["last_failure_kind"] == "rate_limited"
    assert data["status"] == "failing"


@pytest.mark.asyncio
async def test_backing_off_says_when_it_will_retry(async_db, client):
    async_db.add(
        DiscoverySourceHealth(
            source="lastfm",
            last_success_at=utcnow().replace(tzinfo=None) - timedelta(hours=1),
            backoff_until=utcnow().replace(tzinfo=None) + timedelta(minutes=4),
            consecutive_failures=2,
        )
    )
    await async_db.commit()

    data = client.get("/api/v1/health/discovery-sources").json()
    lf = next(s for s in data["sources"] if s["source"] == "lastfm")

    assert lf["state"] == "backing_off"
    assert lf["backoff_until"] is not None


@pytest.mark.asyncio
async def test_a_working_source_reads_as_working(async_db, client):
    async_db.add(
        DiscoverySourceHealth(
            source="bandcamp",
            last_success_at=utcnow().replace(tzinfo=None),
            consecutive_failures=0,
            items_contributed=12,
        )
    )
    await async_db.commit()

    data = client.get("/api/v1/health/discovery-sources").json()
    bc = next(s for s in data["sources"] if s["source"] == "bandcamp")
    assert bc["state"] == "working"
    assert bc["items_contributed"] == 12
