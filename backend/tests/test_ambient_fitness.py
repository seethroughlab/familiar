"""How ambient-adjacent a track is, from audio features alone.

Ambient's candidate pool is a pgvector nearest-neighbour search on whatever is currently
playing, and every energy term in `score_candidate` is proximity to that track. From a rock
seed all 150 candidates are rock, and a penalty can only reorder the pool it is handed. This
module is the absolute measure that makes a floor possible.

It also replaces three inline copies that had diverged. Two of them disagreed about which
track by the same artist was the more ambient — `test_the_two_seed_paths_agree_about_one_artist`
fails against the code this replaced.
"""

from __future__ import annotations

import pytest

from app.services.ambient_fitness import (
    AMBIENT_BPM_CEILING,
    AMBIENT_ENERGY_CEILING,
    ambient_fitness,
)


def fitness(**kwargs) -> float:
    defaults = {
        "energy": 0.5,
        "bpm": 100.0,
        "acousticness": 0.5,
        "instrumentalness": 0.5,
        "speechiness": 0.1,
    }
    return ambient_fitness(**{**defaults, **kwargs})


class TestTheWorkedExamples:
    """The three rows in the module docstring, which are the definition in practice."""

    def test_a_drone_scores_near_the_top(self):
        assert ambient_fitness(
            energy=0.15, bpm=60, acousticness=0.9, instrumentalness=0.98, speechiness=0.02
        ) == pytest.approx(0.973, abs=0.01)

    def test_quiet_acoustic_folk_lands_on_the_boundary(self):
        """The row that matters: this is what "ambient-adjacent" should stop just short of."""
        assert ambient_fitness(
            energy=0.45, bpm=110, acousticness=0.7, instrumentalness=0.30, speechiness=0.15
        ) == pytest.approx(0.55, abs=0.01)

    def test_rock_scores_near_the_bottom(self):
        assert ambient_fitness(
            energy=0.85, bpm=140, acousticness=0.05, instrumentalness=0.05, speechiness=0.20
        ) == pytest.approx(0.128, abs=0.01)

    def test_the_ambient_end_outranks_the_rock_end_by_a_wide_margin(self):
        drone = ambient_fitness(
            energy=0.15, bpm=60, acousticness=0.9, instrumentalness=0.98, speechiness=0.02
        )
        rock = ambient_fitness(
            energy=0.85, bpm=140, acousticness=0.05, instrumentalness=0.05, speechiness=0.20
        )
        assert drone - rock > 0.7, "the two ends must be separable by any sane floor"


class TestItIsACeilingNotATarget:
    """The deliberate difference from the copies this replaces."""

    def test_quieter_than_the_ceiling_is_never_penalised(self):
        """`pick_surprise_seed` scored energy as proximity to 0.25, so a 0.10-energy drone came
        out *worse* than a 0.25 one. Right for choosing a representative seed, wrong as a floor."""
        assert fitness(energy=0.0) == fitness(energy=AMBIENT_ENERGY_CEILING)
        assert fitness(energy=0.05) >= fitness(energy=0.25)

    def test_slower_than_the_ceiling_is_never_penalised(self):
        assert fitness(bpm=40) == fitness(bpm=AMBIENT_BPM_CEILING)

    def test_energy_and_tempo_still_fall_away_above_it(self):
        assert fitness(energy=0.3) > fitness(energy=0.5) > fitness(energy=0.9)
        assert fitness(bpm=90) > fitness(bpm=120) > fitness(bpm=170)


class TestMissingFeatures:
    def test_a_null_reads_as_neutral_rather_than_as_zero(self):
        """`_safe_float` returns 0.0 for NULL — maximally unambient. Inheriting that would
        silently exile every track whose analyser never wrote `acousticness`."""
        assert fitness(acousticness=None) == fitness(acousticness=0.5)
        assert fitness(acousticness=None) > fitness(acousticness=0.0)

    def test_every_feature_may_be_absent(self):
        score = ambient_fitness(
            energy=None, bpm=None, acousticness=None, instrumentalness=None, speechiness=None
        )
        assert 0.0 <= score <= 1.0

    def test_the_result_is_always_in_range(self):
        for e in (0.0, 0.5, 1.0):
            for b in (0.0, 90.0, 300.0):
                for a in (0.0, 1.0):
                    score = ambient_fitness(
                        energy=e, bpm=b, acousticness=a, instrumentalness=a, speechiness=1 - a
                    )
                    assert 0.0 <= score <= 1.0


class TestTheSeedPathsAgree:
    """The concrete defect this deduplication fixes."""

    def test_the_two_seed_paths_agree_about_one_artist(self):
        """**Fails against the code this replaces.**

        `pick_surprise_seed` targeted energy 0.25 with a 3.33 slope; `find_seed_by_artist`
        targeted 0.4 with no slope, so its energy term spanned only [0.4, 1.0]. Given one
        artist with tracks at 0.20 and 0.45, otherwise identical:

            surprise:  0.20 -> 0.25   0.45 -> 0.10   picks 0.20
            artist:    0.20 -> 0.24   0.45 -> 0.285  picks 0.45

        They disagreed about which track by the same artist was the more ambient. Both now
        call one function, so the quieter track wins on both paths.
        """
        quiet = fitness(energy=0.20, instrumentalness=0.9, speechiness=0.1)
        louder = fitness(energy=0.45, instrumentalness=0.9, speechiness=0.1)
        assert quiet > louder

    def test_the_old_artist_heuristic_would_have_disagreed(self):
        """Pins the arithmetic above, so the docstring cannot quietly stop being true."""

        def old_artist_fitness(energy: float) -> float:
            return 0.9 * 0.4 + (1.0 - 0.1) * 0.3 + (1.0 - abs(energy - 0.4)) * 0.3

        assert old_artist_fitness(0.45) > old_artist_fitness(0.20)
        assert fitness(energy=0.20, instrumentalness=0.9, speechiness=0.1) > fitness(
            energy=0.45, instrumentalness=0.9, speechiness=0.1
        )
