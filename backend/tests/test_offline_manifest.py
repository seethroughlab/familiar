"""Tests for precomputed offline ranking manifests (ADR-0006).

The guarantee the whole ADR rests on is that a manifest score is *the same number* the
online path would produce for the same pair. If that drifts, offline and online ranking
diverge silently — which is the failure this ADR exists to prevent, and it would be close
to undetectable in use. `test_scores_match_the_online_scorer_exactly` is that check.

The second thing worth guarding is that neighbours never come from outside the submitted
set. A manifest suggesting a track the device has not downloaded would only fail once the
device is offline, which is the worst possible moment to discover it.
"""

from uuid import uuid4

import pytest

from app.services.ambient import AmbientDescriptor, score_candidate
from app.services.offline_manifest import (
    DEFAULT_NEIGHBOURS,
    build_manifest,
    eligible_seed_ids,
    known_presets,
)
from app.services.ranking_profiles import AMBIENT, RADIO
from tests.factories import insert_test_analysis, insert_test_track

pytestmark = pytest.mark.asyncio


async def _track(db, **features):
    """A track with analysis. Defaults are mid-range so features can be varied one at a time."""
    title = features.pop("title", "Track")
    artist = features.pop("artist", "Artist")
    duration = features.pop("duration_seconds", 200.0)
    track = await insert_test_track(db, title=title, artist=artist, duration_seconds=duration)
    await insert_test_analysis(
        db,
        track.id,
        {
            "energy": 0.5, "brightness": 0.5, "valence": 0.5, "key": "C", "bpm": 120.0,
            "instrumentalness": 0.5, "speechiness": 0.5, "dynamic_range_db": 10.0,
            "acousticness": 0.5,
            **features,
        },
    )
    return track


class TestTheSetBoundary:
    async def test_neighbours_come_only_from_the_submitted_set(self, async_db):
        """A track the device has not downloaded must never be suggested."""
        offline = [await _track(async_db, title=f"Offline {i}") for i in range(5)]
        not_downloaded = await _track(async_db, title="Not downloaded")

        entries = await build_manifest(async_db, [t.id for t in offline], AMBIENT)

        suggested = {n for e in entries for n, _ in e.neighbours}
        assert not_downloaded.id not in suggested
        assert suggested <= {t.id for t in offline}

    async def test_a_track_is_never_its_own_neighbour(self, async_db):
        offline = [await _track(async_db, title=f"T{i}") for i in range(5)]

        entries = await build_manifest(async_db, [t.id for t in offline], AMBIENT)

        for e in entries:
            assert e.track_id not in {n for n, _ in e.neighbours}

    async def test_empty_set_yields_nothing(self, async_db):
        assert await build_manifest(async_db, [], AMBIENT) == []

    async def test_single_track_yields_nothing(self, async_db):
        """One track has no neighbours; returning an entry with an empty list would
        invite the client to treat it as a usable seed."""
        only = await _track(async_db, title="Alone")
        assert await build_manifest(async_db, [only.id], AMBIENT) == []


class TestScoreIdentity:
    async def test_scores_match_the_online_scorer_exactly(self, async_db):
        """The guarantee the ADR rests on.

        Offline ranking is only trustworthy if it is the *same* computation, not a
        faithful-looking reimplementation.
        """
        a = await _track(async_db, title="A", key="C", energy=0.3)
        b = await _track(async_db, title="B", key="G", energy=0.6)

        entries = await build_manifest(async_db, [a.id, b.id], AMBIENT)
        entry_a = next(e for e in entries if e.track_id == a.id)
        manifest_score = dict(entry_a.neighbours)[b.id]

        desc_a = AmbientDescriptor(
            track_id=a.id, title="A", artist="Artist", album="Test Album",
            duration_seconds=200.0, key="C", bpm=120.0, energy=0.3, brightness=0.5,
            valence=0.5, instrumentalness=0.5, speechiness=0.5, dynamic_range_db=10.0,
            energy_shape=None, section_count=None, modal_character=None, acousticness=0.5,
        )
        desc_b = AmbientDescriptor(
            track_id=b.id, title="B", artist="Artist", album="Test Album",
            duration_seconds=200.0, key="G", bpm=120.0, energy=0.6, brightness=0.5,
            valence=0.5, instrumentalness=0.5, speechiness=0.5, dynamic_range_db=10.0,
            energy_shape=None, section_count=None, modal_character=None, acousticness=0.5,
        )
        expected = score_candidate(desc_a, desc_b, profile=AMBIENT)

        assert manifest_score == pytest.approx(expected, abs=1e-9)

    async def test_ambient_and_radio_rank_differently(self, async_db):
        """Both profiles must work offline (decision point 5), and they must differ —
        otherwise the per-profile manifest is pointless."""
        vocal = await _track(async_db, title="Vocal", instrumentalness=0.0, speechiness=0.6)
        instrumental = await _track(async_db, title="Inst", instrumentalness=1.0, speechiness=0.0)
        seed = await _track(async_db, title="Seed")
        ids = [vocal.id, instrumental.id, seed.id]

        amb = {e.track_id: dict(e.neighbours) for e in await build_manifest(async_db, ids, AMBIENT)}
        rad = {e.track_id: dict(e.neighbours) for e in await build_manifest(async_db, ids, RADIO)}

        # AMBIENT penalises vocals; RADIO zero-weights that term.
        amb_gap = amb[seed.id][instrumental.id] - amb[seed.id][vocal.id]
        rad_gap = rad[seed.id][instrumental.id] - rad[seed.id][vocal.id]
        assert amb_gap > 0
        assert rad_gap == pytest.approx(0.0, abs=1e-9)


class TestShape:
    async def test_respects_the_neighbour_count(self, async_db):
        offline = [await _track(async_db, title=f"T{i}") for i in range(8)]

        entries = await build_manifest(async_db, [t.id for t in offline], AMBIENT, neighbours=3)

        assert all(len(e.neighbours) <= 3 for e in entries)

    async def test_defaults_to_ten(self, async_db):
        offline = [await _track(async_db, title=f"T{i}") for i in range(15)]

        entries = await build_manifest(async_db, [t.id for t in offline], AMBIENT)

        assert max(len(e.neighbours) for e in entries) == DEFAULT_NEIGHBOURS

    async def test_neighbours_are_ranked_best_first(self, async_db):
        offline = [await _track(async_db, title=f"T{i}", energy=i / 10) for i in range(8)]

        entries = await build_manifest(async_db, [t.id for t in offline], AMBIENT)

        for e in entries:
            scores = [s for _, s in e.neighbours]
            assert scores == sorted(scores, reverse=True)

    async def test_tracks_without_analysis_are_excluded(self, async_db):
        """No features means nothing to rank on; including them would put an unrankable
        track in the manifest as though it were a real candidate."""
        analysed = [await _track(async_db, title=f"T{i}") for i in range(4)]
        bare = await insert_test_track(async_db, title="No analysis")

        entries = await build_manifest(async_db, [t.id for t in analysed] + [bare.id], AMBIENT)

        assert bare.id not in {e.track_id for e in entries}
        assert bare.id not in {n for e in entries for n, _ in e.neighbours}


class TestFilterPresets:
    async def test_a_preset_narrows_the_pool(self, async_db):
        """Presets change which tracks are eligible, which is why the manifest is
        generated per preset rather than once."""
        quiet = [await _track(async_db, title=f"Quiet {i}", energy=0.2, brightness=0.3,
                              acousticness=0.8) for i in range(4)]
        loud = [await _track(async_db, title=f"Loud {i}", energy=0.95, brightness=0.95,
                             acousticness=0.05) for i in range(4)]
        ids = [t.id for t in quiet + loud]

        all_entries = await build_manifest(async_db, ids, AMBIENT, filter_preset="all")
        soft_entries = await build_manifest(async_db, ids, AMBIENT, filter_preset="soft")

        assert len(soft_entries) < len(all_entries)
        assert {t.id for t in loud}.isdisjoint({e.track_id for e in soft_entries})

    async def test_every_known_preset_is_usable(self, async_db):
        offline = [await _track(async_db, title=f"T{i}") for i in range(6)]
        ids = [t.id for t in offline]

        for preset in known_presets():
            await build_manifest(async_db, ids, AMBIENT, filter_preset=preset)


class TestSeeds:
    async def test_seeds_match_the_online_surprise_filters(self, async_db):
        good = await _track(async_db, title="Good seed", instrumentalness=0.9,
                            speechiness=0.1, energy=0.4, duration_seconds=200.0)
        too_vocal = await _track(async_db, title="Vocal", instrumentalness=0.1,
                                 speechiness=0.1, energy=0.4)
        too_short = await _track(async_db, title="Short", instrumentalness=0.9,
                                 speechiness=0.1, energy=0.4, duration_seconds=30.0)
        too_loud = await _track(async_db, title="Loud", instrumentalness=0.9,
                                speechiness=0.1, energy=0.95)

        seeds = await eligible_seed_ids(
            async_db, [good.id, too_vocal.id, too_short.id, too_loud.id]
        )

        assert good.id in seeds
        assert too_vocal.id not in seeds
        assert too_short.id not in seeds
        assert too_loud.id not in seeds

    async def test_seeds_come_only_from_the_submitted_set(self, async_db):
        mine = await _track(async_db, title="Mine", instrumentalness=0.9, speechiness=0.1,
                            energy=0.4, duration_seconds=200.0)
        theirs = await _track(async_db, title="Theirs", instrumentalness=0.9, speechiness=0.1,
                              energy=0.4, duration_seconds=200.0)

        assert theirs.id not in await eligible_seed_ids(async_db, [mine.id])


class TestEndpoint:
    async def test_requires_a_profile(self, client):
        r = client.post("/api/v1/offline/manifest", json={"track_ids": []})
        assert r.status_code == 401

    async def test_returns_a_variant_per_profile_and_preset(self, client, test_profile):
        from tests.conftest import make_profile_headers

        r = client.post(
            "/api/v1/offline/manifest",
            json={"track_ids": []},
            headers=make_profile_headers(test_profile),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Four ambient presets plus radio.
        assert len(body["variants"]) == len(known_presets()) + 1
        assert {v["profile"] for v in body["variants"]} == {"ambient", "radio"}

    async def test_an_oversized_request_is_rejected(self, client, test_profile):
        from tests.conftest import make_profile_headers

        r = client.post(
            "/api/v1/offline/manifest",
            json={"track_ids": [str(uuid4()) for _ in range(10_001)]},
            headers=make_profile_headers(test_profile),
        )
        assert r.status_code == 422, r.status_code
