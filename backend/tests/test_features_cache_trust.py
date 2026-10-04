"""ADR-0144: a community cache hit is trusted, and checked by sample.

The end-to-end tests run ``run_track_features`` against the test database with every outside
service replaced — the cache, the fingerprint, artwork, AcoustID and MusicBrainz — and with the
decoder rigged to fail, so a trusted hit that decodes the file fails the test rather than only
running slowly.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.db.models import Track, TrackAnalysis, TrackStatus
from app.db.session import sync_session_maker
from app.services.tasks import analysis_pipeline as pipeline
from app.services.tasks.analysis_pipeline import HIT_SAMPLE_RATE, features_path, is_sampled_hit


def _fingerprint(sampled: bool) -> str:
    """A fingerprint that the sampling rule does, or does not, pick."""
    for i in range(10_000):
        fp = f"AQAD{i:06d}"
        if is_sampled_hit(fp) == sampled:
            return fp
    raise AssertionError("no fingerprint found")


# --- The rule ------------------------------------------------------------------------------------


def test_the_sample_is_the_same_on_every_run():
    fp = _fingerprint(sampled=True)
    assert all(is_sampled_hit(fp) for _ in range(5))


def test_about_one_hit_in_fifty_is_sampled():
    picked = sum(is_sampled_hit(f"AQAD-{i}") for i in range(20_000))
    assert 20_000 / HIT_SAMPLE_RATE * 0.8 < picked < 20_000 / HIT_SAMPLE_RATE * 1.2


def test_a_miss_is_always_local_and_no_fingerprint_is_never_sampled():
    assert features_path(False, _fingerprint(sampled=True)) == "local"
    assert features_path(True, _fingerprint(sampled=False)) == "hit"
    assert features_path(True, _fingerprint(sampled=True)) == "hit (sampled)"
    assert is_sampled_hit(None) is False


# --- The pipeline --------------------------------------------------------------------------------

CACHED = {"bpm": 128.0, "key": "A minor", "energy": 0.8, "danceability": 0.7}
LOCAL = {"bpm": 96.0, "key": "C major", "energy": 0.3, "danceability": 0.2}
CACHED_DETAIL = {"structural": {"boundary_confidence": 0.9}, "from": "cache"}
LOCAL_DETAIL = {"structural": {"boundary_confidence": 0.4}, "from": "local"}


@dataclass
class Harness:
    decoded: list
    contributed: list


@pytest.fixture
def harness(monkeypatch, tmp_path):
    decoded: list = []
    contributed: list = []
    state = SimpleNamespace(hit=True, detail=True)

    class FakeCache:
        async def lookup_features(self, fp):
            if not state.hit:
                return None
            return SimpleNamespace(features=dict(CACHED), contributor_count=2)

        async def lookup_analysis_detail(self, fp):
            return SimpleNamespace(detail=dict(CACHED_DETAIL)) if state.detail else None

        async def contribute_features(self, fp, features):
            contributed.append(("features", fp))

        async def contribute_analysis_detail(self, fp, detail):
            contributed.append(("detail", fp))

    def decode(path):
        decoded.append(path)
        return object(), 22050, {}

    import app.services.analysis as analysis
    import app.services.app_settings as app_settings
    import app.services.artwork as artwork
    import app.services.community_cache as community_cache
    import app.services.metadata.musicbrainz as musicbrainz
    import app.services.track_analysis as track_analysis

    monkeypatch.setattr(artwork, "extract_and_save_artwork", lambda *a, **k: None)
    monkeypatch.setattr(analysis, "precompute_shared", decode)
    monkeypatch.setattr(analysis, "derive_features", lambda y, sr, shared, path: (dict(LOCAL), {"bpm": 0.9}))
    monkeypatch.setattr(analysis, "identify_track", lambda path: {})
    monkeypatch.setattr(musicbrainz, "enrich_track", lambda **k: None)
    monkeypatch.setattr(track_analysis, "run_cheap_sections",
                        lambda *a, **k: (dict(LOCAL_DETAIL), {"spectral_centroid_mean": 1500.0}, []))
    monkeypatch.setattr(community_cache, "get_community_cache_service", lambda **k: FakeCache())
    settings = SimpleNamespace(community_cache_enabled=True, community_cache_url="http://cache.test",
                               community_cache_contribute=True)
    monkeypatch.setattr(app_settings, "get_app_settings_service", lambda: SimpleNamespace(get=lambda: settings))

    audio = tmp_path / "track.flac"
    audio.write_bytes(b"not really audio")
    track_ids: list = []

    def run(fingerprint: str, *, hit: bool = True, detail: bool = True):
        state.hit, state.detail = hit, detail
        monkeypatch.setattr(analysis, "generate_fingerprint", lambda path: (200, fingerprint))
        track_id = uuid4()
        track_ids.append(track_id)
        with sync_session_maker() as db:
            db.add(Track(id=track_id, file_path=str(audio), file_hash=uuid4().hex, title="Song",
                         artist="Artist", album="Album", duration_seconds=200.0,
                         status=TrackStatus.ACTIVE))
            db.commit()
        result = pipeline.run_track_features(str(track_id))
        with sync_session_maker() as db:
            row = db.execute(select(TrackAnalysis).where(TrackAnalysis.track_id == track_id)).scalar_one()
            db.expunge(row)
        return result, row

    yield SimpleNamespace(run=run, h=Harness(decoded, contributed))

    with sync_session_maker() as db:
        db.execute(delete(TrackAnalysis).where(TrackAnalysis.track_id.in_(track_ids)))
        db.execute(delete(Track).where(Track.id.in_(track_ids)))
        db.commit()


def test_a_trusted_hit_is_stored_without_decoding_the_track(harness):
    result, row = harness.run(_fingerprint(sampled=False))
    assert result["features_path"] == "hit"
    assert harness.h.decoded == [], "point 1: a trusted hit is not decoded"
    assert row.features_source == "community_cache"
    assert row.bpm == CACHED["bpm"] and row.key == CACHED["key"]
    assert row.local_features is None


def test_a_hits_cached_section_analysis_is_kept(harness):
    # Before ADR-0144 this was fetched and then reset to None and recomputed.
    _, row = harness.run(_fingerprint(sampled=False))
    assert row.analysis_detail == CACHED_DETAIL


def test_a_hit_without_cached_sections_leaves_them_to_the_backfill(harness):
    _, row = harness.run(_fingerprint(sampled=False), detail=False)
    assert harness.h.decoded == []
    assert row.analysis_detail is None, "point 3: the backfill selects analysis_detail IS NULL"


def test_a_sampled_hit_is_analysed_compared_and_not_contributed(harness):
    result, row = harness.run(_fingerprint(sampled=True))
    assert result["features_path"] == "hit (sampled)"
    assert len(harness.h.decoded) == 1
    assert row.bpm == CACHED["bpm"], "the cache's values stay primary"
    assert row.local_features["bpm"] == LOCAL["bpm"]
    assert "bpm_disagreement" in row.feature_confidence
    assert row.analysis_detail == CACHED_DETAIL
    assert harness.h.contributed == [], "point 2: a sampled track's local result is not contributed"


def test_a_miss_is_analysed_locally_and_contributed(harness):
    result, row = harness.run(_fingerprint(sampled=False), hit=False)
    assert result["features_path"] == "local"
    assert len(harness.h.decoded) == 1
    assert row.features_source == "local"
    assert row.bpm == LOCAL["bpm"]
    assert row.analysis_detail == LOCAL_DETAIL
    assert ("features", _fingerprint(sampled=False)) in harness.h.contributed
