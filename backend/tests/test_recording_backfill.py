"""ADR-0115's job: two phases, each gated, each leaving state the next tick reads.

Offline. The database is a list of rows, AcoustID is a function, the corpus is a
function, and health is a recorder that remembers. What must hold: a phase that is
off sends nothing; a track gets its id and its marker in one commit; a refusal
keeps its candidates; an upstream that is down stops the phase rather than
burning the batch; and a dry run changes nothing anywhere.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.services.tasks import recording_backfill as rb

A = "aaaaaaaa-0000-4000-8000-000000000001"
B = "bbbbbbbb-0000-4000-8000-000000000002"


# --- doubles ------------------------------------------------------------------


class Recorder:
    def __init__(self, backing_off: set[str] | None = None) -> None:
        self.successes: list[tuple[str, int]] = []
        self.failures: list[tuple[str, str]] = []
        self.backing_off = backing_off or set()

    async def record_success(self, source, *, items=0):
        self.successes.append((source, items))

    async def record_failure(self, source, *, kind, detail=None, retry_after_seconds=None):
        self.failures.append((source, kind))

    async def should_skip(self, source):
        return source in self.backing_off


class Session:
    """Remembers commits and rollbacks; the rows are whatever the test hands in."""

    def __init__(self, rows):
        self.rows = rows
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class Engine:
    async def dispose(self):
        pass


def track(title="Zala", album="Reachy Prints", mbid=None, duration=300.0):
    return SimpleNamespace(
        id=f"track-{title}", title=title, album=album, musicbrainz_track_id=mbid, duration_seconds=duration
    )


def analysis(fp="AQADfingerprint", lookup=None):
    return SimpleNamespace(acoustid=fp, acoustid_lookup=lookup)


def settings(**over):
    base = {
        "recording_backfill_enabled": True,
        "community_cache_contribute": True,
        "community_cache_url": "https://corpus.invalid",
    }
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture
def world(monkeypatch):
    """Everything a phase reaches for, replaced. Returns a mutable bag the test steers."""
    w = SimpleNamespace(
        settings=settings(),
        api_key="key",
        recorder=Recorder(),
        rows=[],
        session=None,
        lookups=[],
        lookup=lambda key, fp, dur: {"results": []},
        outcomes=[],
        claims=[],
        minted=0,
    )

    def make_session():
        w.session = Session(w.rows)
        return Engine(), lambda: w.session

    async def candidates(db, limit):
        return list(w.rows)[:limit]

    def fake_lookup(key, fp, dur):
        w.lookups.append((fp, dur))
        return w.lookup(key, fp, dur)

    class Cache:
        async def claim_recording_outcome(self, fp, mbid):
            w.claims.append((fp, mbid))
            return w.outcomes.pop(0)

    class AppSettingsService:
        def get(self):
            return w.settings

        def get_effective(self, key):
            return w.api_key if key == "acoustid_api_key" else None

        def ensure_community_cache_client_id(self):
            w.minted += 1
            return "install-1"

    monkeypatch.setattr("app.db.session.create_task_engine_session", make_session)
    monkeypatch.setattr("app.services.discovery.get_recorder", lambda: w.recorder)
    monkeypatch.setattr(
        "app.services.app_settings.get_app_settings_service", lambda: AppSettingsService()
    )
    monkeypatch.setattr("app.services.community_cache.get_community_cache_service", lambda **kw: Cache())
    monkeypatch.setattr(rb, "_resolve_candidates", candidates)
    monkeypatch.setattr(rb, "_claim_candidates", candidates)
    monkeypatch.setattr(rb, "_lookup", fake_lookup)

    async def no_sleep(_):
        pass

    monkeypatch.setattr(rb.asyncio, "sleep", no_sleep)
    return w


def single(mbid=A, title="Zala"):
    return {"results": [{"score": 0.98, "recordings": [{"id": mbid, "title": title}]}]}


def two(title="Zala"):
    return {
        "results": [
            {"score": 0.98, "recordings": [{"id": A, "title": title}, {"id": B, "title": title}]}
        ]
    }


# --- resolve: gates ----------------------------------------------------------


def test_resolve_is_off_by_default_and_sends_nothing(world):
    world.settings = settings(recording_backfill_enabled=False)
    world.rows = [(track(), analysis())]
    out = asyncio.run(rb.run_resolve_phase())
    assert out["status"] == "disabled"
    assert world.lookups == [] and world.recorder.failures == [] and world.recorder.successes == []


def test_enabled_without_a_key_is_an_error_state_not_a_skip(world):
    world.api_key = None
    out = asyncio.run(rb.run_resolve_phase())
    assert out["status"] == "not_configured"
    assert world.recorder.failures == [(rb.SOURCE_ACOUSTID, "not_configured")]


def test_resolve_respects_backoff(world):
    world.recorder = Recorder(backing_off={rb.SOURCE_ACOUSTID})
    world.rows = [(track(), analysis())]
    out = asyncio.run(rb.run_resolve_phase())
    assert out["status"] == "backing_off" and world.lookups == []


# --- resolve: what one tick writes -------------------------------------------


def test_a_named_track_gets_its_id_and_its_marker_in_one_commit(world):
    t, a = track(), analysis()
    world.rows = [(t, a)]
    world.lookup = lambda k, fp, d: single()
    out = asyncio.run(rb.run_resolve_phase())
    assert out["resolved"] == 1 and out["by_tier"] == {1: 1}
    assert t.musicbrainz_track_id == A
    assert a.acoustid_lookup["resolved"]["recording_mbid"] == A
    assert a.acoustid_lookup["resolved"]["tier"] == 1
    assert a.acoustid_lookup["checked_at"] and a.acoustid_lookup["reason"] == "single"
    assert world.session.commits == 1
    assert world.recorder.successes == [(rb.SOURCE_ACOUSTID, 1)]


def test_the_stored_fingerprint_is_sent_canonically_and_never_a_file(world):
    """A hex-escaped column value goes out as the base64 chromaprint produced."""
    hexed = "\\x" + b"AQADfingerprint".hex()
    world.rows = [(track(duration=201.7), analysis(fp=hexed))]
    world.lookup = lambda k, fp, d: single()
    asyncio.run(rb.run_resolve_phase())
    assert world.lookups == [("AQADfingerprint", 201)]


def test_a_refusal_keeps_its_candidates_and_writes_no_id(world):
    t, a = track(title="Fenixfunk 5"), analysis()
    world.rows = [(t, a)]
    world.lookup = lambda k, fp, d: two(title="Fenix Funk 5")
    out = asyncio.run(rb.run_resolve_phase())
    assert out["refused"] == 1 and out["by_reason"] == {"no_title_match": 1}
    assert t.musicbrainz_track_id is None
    assert a.acoustid_lookup["resolved"] is None
    assert {c["musicbrainz_recording_id"] for c in a.acoustid_lookup["candidates"]} == {A, B}
    assert a.acoustid_lookup["checked_at"]


def test_an_existing_id_is_never_overwritten(world):
    t, a = track(mbid=B), analysis()
    world.rows = [(t, a)]
    world.lookup = lambda k, fp, d: single(mbid=A)
    asyncio.run(rb.run_resolve_phase())
    assert t.musicbrainz_track_id == B


def test_existing_lookup_keys_survive_the_merge(world):
    t, a = track(), analysis(lookup={"candidates": [{"old": True}], "something": "kept"})
    world.rows = [(t, a)]
    world.lookup = lambda k, fp, d: single()
    asyncio.run(rb.run_resolve_phase())
    assert a.acoustid_lookup["something"] == "kept"
    assert a.acoustid_lookup["candidates"][0]["musicbrainz_recording_id"] == A


def test_a_bad_fingerprint_costs_one_track_and_does_not_back_off_acoustid(world):
    bad, good = (track(title="bad"), analysis()), (track(title="good"), analysis())
    world.rows = [bad, good]

    def lookup(k, fp, d):
        if world.lookups[-1] == (fp, d) and len(world.lookups) == 1:
            raise RuntimeError("status: error, invalid fingerprint")
        return single()

    world.lookup = lookup
    out = asyncio.run(rb.run_resolve_phase())
    assert out["errors"] == 1 and out["resolved"] == 1
    assert bad[1].acoustid_lookup["error"].startswith("status: error")
    assert bad[1].acoustid_lookup["checked_at"]
    assert world.recorder.failures == []
    assert good[0].musicbrainz_track_id == A


def test_an_upstream_that_is_down_stops_the_phase_and_backs_off(world):
    world.rows = [(track(title=str(i)), analysis()) for i in range(10)]

    def lookup(k, fp, d):
        raise RuntimeError("HTTP request failed: 429 Too Many Requests")

    world.lookup = lookup
    out = asyncio.run(rb.run_resolve_phase())
    assert out["status"] == "upstream_failed"
    assert len(world.lookups) == rb.UPSTREAM_FAILURE_LIMIT
    assert world.recorder.failures == [(rb.SOURCE_ACOUSTID, "rate_limited")] * rb.UPSTREAM_FAILURE_LIMIT
    assert world.recorder.successes == []


def test_dry_run_decides_and_writes_nothing(world):
    t, a = track(), analysis()
    world.rows = [(t, a)]
    world.lookup = lambda k, fp, d: single()
    out = asyncio.run(rb.run_resolve_phase(dry_run=True))
    assert out["resolved"] == 1
    assert t.musicbrainz_track_id is None and a.acoustid_lookup is None
    assert world.session.commits == 0 and world.recorder.successes == []


# --- claim ---------------------------------------------------------------------


def test_claims_are_gated_by_contribute(world):
    world.settings = settings(community_cache_contribute=False)
    world.rows = [(track(mbid=A), analysis())]
    out = asyncio.run(rb.run_claim_phase())
    assert out["status"] == "disabled" and world.claims == []


def test_claims_run_when_resolution_is_off(world):
    """Point 8: the flag stops fingerprints leaving; ids the library holds still go."""
    world.settings = settings(recording_backfill_enabled=False)
    world.rows = [(track(mbid=A), analysis())]
    world.outcomes = ["claimed"]
    out = asyncio.run(rb.run_claim_phase())
    assert out["claimed"] == 1


def test_each_outcome_leaves_the_marker_the_next_tick_reads(world):
    claimed, not_held = (track(title="c", mbid=A), analysis()), (track(title="n", mbid=B), analysis())
    world.rows = [claimed, not_held]
    world.outcomes = ["claimed", "not_held"]
    out = asyncio.run(rb.run_claim_phase())
    assert out["claimed"] == 1 and out["not_held"] == 1 and out["errors"] == 0
    assert claimed[1].acoustid_lookup["claimed_at"]
    assert "claimed_at" not in not_held[1].acoustid_lookup
    assert not_held[1].acoustid_lookup["claim_outcome"] == "not_held"
    assert not_held[1].acoustid_lookup["claim_checked_at"]
    assert world.claims == [("AQADfingerprint", A), ("AQADfingerprint", B)]
    assert world.recorder.successes == [(rb.SOURCE_CLAIMS, 1)]


def test_a_corpus_that_is_down_stops_the_phase(world):
    world.rows = [(track(title=str(i), mbid=A), analysis()) for i in range(10)]
    world.outcomes = ["failed"] * 10
    out = asyncio.run(rb.run_claim_phase())
    assert out["status"] == "upstream_failed"
    assert len(world.claims) == rb.UPSTREAM_FAILURE_LIMIT
    assert world.recorder.failures == [(rb.SOURCE_CLAIMS, "http_error")] * rb.UPSTREAM_FAILURE_LIMIT
    for _, a in world.rows:
        assert a.acoustid_lookup is None


def test_claim_dry_run_mints_no_client_id_and_sends_nothing(world):
    world.rows = [(track(mbid=A), analysis())]
    out = asyncio.run(rb.run_claim_phase(dry_run=True))
    assert out["claimed"] == 1 and world.claims == [] and world.minted == 0


# --- the tick, and the arithmetic behind it -----------------------------------


def test_a_tick_is_resolve_then_claim(world):
    world.settings = settings(recording_backfill_enabled=False, community_cache_contribute=False)
    out = asyncio.run(rb.run_recording_backfill())
    assert out["resolve"]["status"] == "disabled" and out["claim"]["status"] == "disabled"


def test_a_tick_finishes_well_inside_its_interval():
    """`max_instances=1` drops ticks silently if a tick outruns the trigger."""
    from app.services.background.manager import RECORDING_BACKFILL_INTERVAL_MINUTES

    worst = rb.RESOLVE_BATCH * rb.ACOUSTID_PACE_SECONDS + rb.CLAIM_BATCH * rb.CLAIM_PACE_SECONDS
    assert worst < RECORDING_BACKFILL_INTERVAL_MINUTES * 60 * 0.8


def test_the_paces_stay_under_both_documented_limits():
    assert 1 / rb.ACOUSTID_PACE_SECONDS < 3, "AcoustID: no more than 3 requests a second"
    assert 60 / rb.CLAIM_PACE_SECONDS < 30, "the corpus: 30 writes a minute, and a claim is one"


def test_the_backfill_finishes_in_days_not_weeks():
    """23,853 unnamed tracks on 2026-09-14. The ADR promised about a day."""
    from app.services.background.manager import RECORDING_BACKFILL_INTERVAL_MINUTES

    per_day = rb.RESOLVE_BATCH * (60 / RECORDING_BACKFILL_INTERVAL_MINUTES) * 24
    assert 23_853 / per_day < 2


def test_the_job_is_registered():
    import inspect

    from app.services.background import manager

    src = inspect.getsource(manager)
    assert 'id="recording_backfill"' in src and "max_instances=1" in src
