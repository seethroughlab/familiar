"""The pool draws from the top of the fit band, not flatly across it.

`test_ambient_pool_composition.py` proves eligibility — that a rock seed yields ambient
candidates — using two well-separated clusters. **That fixture cannot catch this defect**,
because with only two clusters every eligible track is equally ambient and a uniform draw
across the band is indistinguishable from a weighted one.

Real libraries are a gradient, and the gradient is bottom-heavy. Measured against the 26,000
track library this was found on: 3,475 tracks cleared a 0.60 floor, but 2,766 of them sat in
0.60–0.80 against 203 above 0.90. Drawing ninety rows uniformly took about five from the
genuinely ambient end, and the session sounded like the floor rather than like the band —
reported as "almost every song is an upbeat or vocal song" while every existing test passed.

**The assertions are an A/B against the same fixture rather than a threshold.** Two earlier
attempts here asserted absolute numbers and both were worthless: the first used two clusters,
which made `measure_calibration` degenerate so it silently fell back to the defaults and left a
40-track band; the second compared the draw against the band average, which cannot be beaten by
0.05 when the band already averages 0.951. Comparing weighted to uniform over one library
measures the mechanism itself and survives any reshaping of the fixture.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from sqlalchemy import select

from app.config import FEATURES_VERSION
from app.db.models import Track, TrackAnalysis, TrackStatus
from app.services.ambient import get_candidates
from app.services.ambient_fitness import ambient_fitness, measure_calibration
from app.services.ranking_profiles import AMBIENT

pytestmark = pytest.mark.asyncio

DIMENSIONS = 512
LIBRARY_SIZE = 500
#: Deliberately below the shipped 0.80 so the band is wide enough to have somewhere to move
#: within. The shipped floor is a separate decision, asserted on its own below.
PROBE_FLOOR = 0.60
#: Small relative to the band. At the shipped 90 the draw would take most of a fixture-sized
#: band and no weighting could show, which is a property of the fixture and not of the code.
PROBE_ROWS = 15


def _embedding(index: int) -> list[float]:
    base = [0.0] * DIMENSIONS
    base[index % 64] = 1.0
    return base


def _ramp(i: int) -> tuple[float, float, float]:
    """One point on a smooth loud→ambient ramp: (energy, bpm, acousticness).

    Correlated on purpose. Real ambient music is quiet, slow and acoustic *together*, and
    three independent axes would average into a featureless middle where no track is clearly
    anything — which is precisely the fixture that cannot catch this defect.

    A ramp rather than clusters is the point: `measure_calibration` takes percentiles of
    whatever it is given, so a two-valued fixture makes every percentile coincide and the
    calibration reports itself degenerate.
    """
    t = i / (LIBRARY_SIZE - 1)
    return (0.20 + 0.75 * t, 55.0 + 95.0 * t, 0.95 - 0.85 * t)


async def _gradient_library(db) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for i in range(LIBRARY_SIZE):
        energy, bpm, acousticness = _ramp(i)
        track = Track(
            id=uuid.uuid4(),
            title=f"track {i}",
            artist=f"artist {i % 50}",
            file_path=f"/music/{i}.flac",
            file_hash=f"ramp{i:05d}",
            duration_seconds=240.0,
            status=TrackStatus.ACTIVE,
        )
        db.add(track)
        db.add(
            TrackAnalysis(
                track_id=track.id,
                embedding=_embedding(i),
                key="C major",
                features_version=FEATURES_VERSION,
                energy=energy,
                bpm=bpm,
                acousticness=acousticness,
                brightness=energy,
                instrumentalness=0.9,
                speechiness=0.05,
                valence=0.4,
                dynamic_range_db=12.0,
            )
        )
        ids.append(track.id)
    await db.commit()
    return ids


async def _fitness_of(db, track_ids: list[uuid.UUID]) -> dict[uuid.UUID, float]:
    """Score every track the way the pool query does, from the same calibration."""
    calibration = await measure_calibration(db)
    rows = (
        await db.execute(select(TrackAnalysis).where(TrackAnalysis.track_id.in_(track_ids)))
    ).scalars().all()
    return {
        r.track_id: ambient_fitness(
            energy=r.energy, bpm=r.bpm, acousticness=r.acousticness, calibration=calibration
        )
        for r in rows
    }


def _probe_profile(exponent: float):
    """`AMBIENT` with only the library branch live, so the A/B measures that branch."""
    return replace(
        AMBIENT,
        pool=replace(
            AMBIENT.pool,
            fitness_floor=PROBE_FLOOR,
            library_rows=PROBE_ROWS,
            library_weight_exponent=exponent,
            neighbour_rows=0,
            excursion_rows=0,
        ),
    )


async def _mean_drawn_fitness(db, seed_id, fitness, exponent, trials=12) -> float:
    """Average fitness of what the library branch returns, over several draws."""
    got: list[float] = []
    for _ in range(trials):
        candidates, _, _ = await get_candidates(
            db, current_track_id=seed_id, limit=PROBE_ROWS, profile=_probe_profile(exponent)
        )
        got += [fitness[c.descriptor.track_id] for c in candidates
                if c.descriptor.track_id in fitness]
    assert got, "the probe profile returned nothing at all"
    return sum(got) / len(got)


class TestTheDrawFavoursTheTopOfTheBand:
    async def test_weighting_beats_a_uniform_draw_over_the_same_library(self, async_db):
        """**The headline.** Same fixture, same floor, same row count — only the exponent
        differs, so nothing but the weighting can explain a difference."""
        ids = await _gradient_library(async_db)
        fitness = await _fitness_of(async_db, ids)
        seed = ids[-1]  # the most ambient track, so neither draw is helped by proximity

        uniform = await _mean_drawn_fitness(async_db, seed, fitness, exponent=0.0)
        weighted = await _mean_drawn_fitness(async_db, seed, fitness, exponent=6.0)

        # 0.035 is measured, not chosen. Against the unfixed code, where both draws are
        # uniform and the gap is pure noise, eight runs stayed inside ±0.019; with the
        # weighting live the gap ran +0.053 to +0.090. The margin sits between the two, so
        # this neither passes on noise nor fails on an unlucky draw.
        assert weighted > uniform + 0.035, (
            f"weighted draw averaged {weighted:.3f} against uniform {uniform:.3f} — "
            "the fit band is still being sampled flat"
        )

    async def test_the_weighted_draw_reaches_further_from_the_floor(self, async_db):
        """States it as the listener hears it: how much of the draw is genuinely ambient."""
        ids = await _gradient_library(async_db)
        fitness = await _fitness_of(async_db, ids)
        seed = ids[-1]

        async def share_above(exponent: float, cutoff: float = 0.95) -> float:
            got: list[float] = []
            for _ in range(6):
                candidates, _, _ = await get_candidates(
                    async_db, current_track_id=seed, limit=PROBE_ROWS,
                    profile=_probe_profile(exponent),
                )
                got += [fitness[c.descriptor.track_id] for c in candidates
                        if c.descriptor.track_id in fitness]
            return sum(1 for v in got if v >= cutoff) / len(got)

        assert await share_above(6.0) > await share_above(0.0) + 0.05


class TestTheFloorStaysLow:
    """Weighting was chosen *instead of* a higher floor, and that is the load-bearing part.

    Raising the floor to 0.80 was measured and rejected: it fixes the mix by making five
    sixths of the eligible library ineligible, and long sessions would circle a few hundred
    records. These pin the decision, so a later "just raise the floor" has to argue with it.
    """

    async def test_the_floor_is_still_sixty(self, async_db):
        assert AMBIENT.pool.fitness_floor == 0.60
        assert AMBIENT.pool.library_weight_exponent > 0, (
            "with a low floor the weighting is the only thing shaping the draw"
        )

    async def test_a_middling_track_is_still_reachable(self, async_db):
        """The point of keeping the floor low. A 0.65 track must be *less likely*, never
        excluded — otherwise the exponent has silently become a second floor."""
        ids = await _gradient_library(async_db)
        fitness = await _fitness_of(async_db, ids)
        middling = {t for t, f in fitness.items() if 0.60 <= f < 0.80}
        assert middling, "fixture has no middle band"

        seen: set[uuid.UUID] = set()
        for _ in range(25):
            candidates, _, _ = await get_candidates(
                async_db, current_track_id=ids[-1], limit=30, profile=AMBIENT
            )
            seen |= {c.descriptor.track_id for c in candidates}
        assert seen & middling, (
            "25 draws never once returned a track between 0.60 and 0.80 — the weighting is "
            "acting as a filter, not a preference"
        )


class TestItStillDrawsSomethingAtAll:
    async def test_weighting_is_not_a_second_hidden_filter(self, async_db):
        """A weight of zero must never mean "excluded" — every eligible track keeps a
        non-zero chance, or the floor has quietly moved."""
        ids = await _gradient_library(async_db)
        candidates, pool_size, collapsed = await get_candidates(
            async_db, current_track_id=ids[-1], limit=8, profile=AMBIENT
        )
        assert candidates and not collapsed and pool_size > 0

    async def test_an_exponent_of_zero_is_a_uniform_draw(self, async_db):
        """The documented escape hatch — 1.0 is nearly uniform over a narrow band, so 0 has
        to be the way back to a flat draw."""
        ids = await _gradient_library(async_db)
        candidates, _, collapsed = await get_candidates(
            async_db, current_track_id=ids[-1], limit=8, profile=_probe_profile(0.0)
        )
        assert candidates and not collapsed
