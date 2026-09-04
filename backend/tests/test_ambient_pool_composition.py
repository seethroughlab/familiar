"""An ambient pool stays ambient, whatever is playing.

`get_candidates` retrieved its pool by embedding distance from the current track, so from a
rock seed all 150 candidates were rock and `liveliness_penalty` could only pick the quietest
rock track. The pool is now composed from three branches, and the middle one — fit tracks drawn
from *anywhere* — is what makes eligibility independent of what is playing.

**The fixture is larger than `CANDIDATE_POOL` on purpose.** With fewer than 150 tracks the
`LIMIT` never binds, today's query returns the whole library, the liveliness penalty correctly
promotes the ambient tracks, and `test_a_rock_seed_still_yields_a_mostly_ambient_pool` **passes
against the broken code**. `test_ambient_pool_recall.py`'s docstring records the same trap in
its own words.
"""

from __future__ import annotations

import uuid

import pytest

from app.config import FEATURES_VERSION
from app.db.models import Track, TrackAnalysis, TrackStatus
from app.services.ambient import get_candidates
from app.services.ranking_profiles import AMBIENT, RADIO

pytestmark = pytest.mark.asyncio

#: Two clusters, far apart in embedding space and unmistakable in features.
ROCK = dict(energy=0.88, brightness=0.82, bpm=142.0, instrumentalness=0.05,
            acousticness=0.08, speechiness=0.18, valence=0.6, dynamic_range_db=7.0)
CALM = dict(energy=0.22, brightness=0.24, bpm=68.0, instrumentalness=0.96,
            acousticness=0.86, speechiness=0.02, valence=0.35, dynamic_range_db=14.0)

DIMENSIONS = 512


def _embedding(cluster: int, index: int) -> list[float]:
    """Two tight, well-separated clusters."""
    base = [0.0] * DIMENSIONS
    base[cluster] = 1.0
    base[(index % 32) + 100] = 0.01
    return base


async def _library(db, rock: int = 200, calm: int = 200) -> dict[str, list[uuid.UUID]]:
    ids: dict[str, list[uuid.UUID]] = {"rock": [], "calm": []}
    for kind, count, features, cluster in (
        ("rock", rock, ROCK, 0),
        ("calm", calm, CALM, 1),
    ):
        for i in range(count):
            track = Track(
                id=uuid.uuid4(),
                title=f"{kind} {i}",
                artist=f"{kind} artist {i % 40}",
                file_path=f"/music/{kind}/{i}.flac",
                file_hash=f"{kind}{i:04d}",
                duration_seconds=240.0,
                status=TrackStatus.ACTIVE,
            )
            db.add(track)
            db.add(
                TrackAnalysis(
                    track_id=track.id,
                    embedding=_embedding(cluster, i),
                    key="C major",
                    features_version=FEATURES_VERSION,
                    **features,
                )
            )
            ids[kind].append(track.id)
    await db.commit()
    return ids


class TestTheFixtureItself:
    async def test_the_library_is_larger_than_the_pool_limit(self, async_db):
        """Guards the trap in the module docstring: a smaller fixture would make the headline
        test pass against the unfixed code."""
        from app.services.ambient import CANDIDATE_POOL

        ids = await _library(async_db)
        assert len(ids["rock"]) + len(ids["calm"]) > CANDIDATE_POOL


class TestTheAmbientPool:
    async def test_a_rock_seed_still_yields_a_mostly_ambient_pool(self, async_db):
        """**The headline. Fails against today's code: 8 of 8 come back rock.**"""
        ids = await _library(async_db)
        candidates, pool_size, collapsed = await get_candidates(
            async_db, current_track_id=ids["rock"][0], limit=8, profile=AMBIENT
        )

        assert not collapsed
        calm_ids = set(ids["calm"])
        calm_count = sum(1 for c in candidates if c.descriptor.track_id in calm_ids)
        assert calm_count >= 6, (
            f"only {calm_count} of {len(candidates)} candidates were ambient — "
            "the pool is still whatever the seed sounds like"
        )

    async def test_the_excursion_is_still_reachable(self, async_db):
        """Over-correcting to zero variety is the other failure."""
        ids = await _library(async_db)
        candidates, _, _ = await get_candidates(
            async_db, current_track_id=ids["rock"][0], limit=16, profile=AMBIENT
        )
        rock_ids = set(ids["rock"])
        assert sum(1 for c in candidates if c.descriptor.track_id in rock_ids) >= 1

    async def test_a_calm_seed_stays_calm(self, async_db):
        """The case that already worked must keep working."""
        ids = await _library(async_db)
        candidates, _, _ = await get_candidates(
            async_db, current_track_id=ids["calm"][0], limit=8, profile=AMBIENT
        )
        calm_ids = set(ids["calm"])
        assert sum(1 for c in candidates if c.descriptor.track_id in calm_ids) >= 6


class TestItDegradesRatherThanCollapsing:
    async def test_a_library_with_nothing_ambient_still_returns_candidates(self, async_db):
        """An empty pool surfaces to the listener as "Session ended", which is worse than the
        bug being fixed. Falls back to nearest neighbours and says so in the log."""
        ids = await _library(async_db, rock=200, calm=0)
        candidates, pool_size, collapsed = await get_candidates(
            async_db, current_track_id=ids["rock"][0], limit=8, profile=AMBIENT
        )
        assert candidates
        assert not collapsed
        assert pool_size > 0

    async def test_the_soft_preset_stacked_on_the_floor_does_not_collapse(self, async_db):
        """`soft` gates energy <= 0.5 *and* the floor gates fitness — compounding."""
        ids = await _library(async_db)
        candidates, _, collapsed = await get_candidates(
            async_db,
            current_track_id=ids["calm"][0],
            limit=8,
            profile=AMBIENT,
            filter_preset="soft",
        )
        assert candidates and not collapsed


class TestBlastRadius:
    async def test_radio_pools_exactly_as_it_did(self, async_db):
        """`RADIO` carries no `AmbientPool`, so its query must be the single unchanged one.

        `get_candidates` is shared with radio and the MCP discovery tool (ADR-0005). A previous
        pool defect was noted with "this was never an ambient bug" — this is the guard.
        """
        ids = await _library(async_db)
        candidates, pool_size, _ = await get_candidates(
            async_db, current_track_id=ids["rock"][0], limit=10, profile=RADIO
        )
        rock_ids = set(ids["rock"])
        assert all(c.descriptor.track_id in rock_ids for c in candidates), (
            "radio drifted to the ambient end — it must still return neighbours"
        )

    async def test_radio_asks_for_one_query_not_three(self, async_db):
        """Pins the composition to profiles that opt in, at the level of the profile itself."""
        assert RADIO.pool is None
        assert AMBIENT.pool is not None


class TestTheExcursionRate:
    async def test_roughly_one_candidate_in_eight_leaves_the_ambient_end(self, async_db):
        ids = await _library(async_db)
        candidates, _, _ = await get_candidates(
            async_db, current_track_id=ids["calm"][0], limit=24, profile=AMBIENT
        )
        rock_ids = set(ids["rock"])
        excursions = sum(1 for c in candidates if c.descriptor.track_id in rock_ids)
        # 24 candidates at one in eight is three, give or take where the phase lands.
        assert 1 <= excursions <= 5, f"{excursions} of {len(candidates)}"
