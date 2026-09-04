"""How ambient-adjacent a track is, relative to the library it is in.

Ambient's candidate pool is a nearest-neighbour search on whatever is currently playing, and
every energy term in `score_candidate` is proximity to that same track. From a rock seed all
150 candidates are rock, and a penalty can only reorder the pool it is handed. This module is
the absolute measure that makes a floor possible.

**It is relative on purpose, and the first version was not.** Fixed thresholds looked
reasonable and were measured to be useless: on a 26,000-track library the quietest 5% sits at
energy 0.648, so a ramp reaching zero at 0.60 scored the *entire library* zero on its heaviest
term, and everything landed in a 0.25-wide band. These tests pin the relativity, because that
is the property that makes the measure work anywhere.
"""

from __future__ import annotations

import pytest

from app.services.ambient_fitness import (
    DEFAULT_CALIBRATION,
    AmbientCalibration,
    ambient_fitness,
    seed_fitness,
)

#: A library like Jeff's: median energy 0.83, median bpm 123, median acousticness 0.49.
LOUD_LIBRARY = DEFAULT_CALIBRATION

#: A library of quiet piano, where "loud" means something completely different.
QUIET_LIBRARY = AmbientCalibration(
    energy_full=0.12,
    energy_zero=0.34,
    bpm_full=52.0,
    bpm_zero=78.0,
    acoustic_full=0.94,
    acoustic_zero=0.81,
)


def fitness(calibration=LOUD_LIBRARY, **kwargs) -> float:
    defaults = {"energy": 0.83, "bpm": 123.0, "acousticness": 0.49}
    return ambient_fitness(**{**defaults, **kwargs}, calibration=calibration)


class TestItRanksWithinTheLibrary:
    """The property the absolute version could not have."""

    def test_the_quiet_end_of_a_loud_library_still_scores_high(self):
        """Energy 0.70 is the 10th percentile *here* — nothing about it is quiet absolutely."""
        assert fitness(energy=0.70, bpm=96, acousticness=0.58) == pytest.approx(1.0)

    def test_the_median_track_scores_low(self):
        # Deliberately not 0.5: the median of a library is not half-ambient, it is ordinary.
        assert fitness() < 0.25

    def test_the_loud_end_scores_zero(self):
        assert fitness(energy=0.95, bpm=160, acousticness=0.30) == pytest.approx(0.0)

    def test_the_same_track_scores_differently_in_different_libraries(self):
        """**The whole point.** A track is ambient *for* a collection, not in the abstract.

        Energy 0.70 is the quiet end of a rock library and the loud end of a piano one, and
        an absolute threshold cannot express both.
        """
        track = {"energy": 0.70, "bpm": 96.0, "acousticness": 0.58}
        assert ambient_fitness(**track, calibration=LOUD_LIBRARY) == pytest.approx(1.0)
        assert ambient_fitness(**track, calibration=QUIET_LIBRARY) == pytest.approx(0.0)

    def test_each_library_has_tracks_at_both_ends(self):
        """A measure that compressed everything into a narrow band would be useless, which is
        exactly what the absolute version did — the whole library scored 0.40 to 0.65."""
        for cal in (LOUD_LIBRARY, QUIET_LIBRARY):
            top = ambient_fitness(
                energy=cal.energy_full,
                bpm=cal.bpm_full,
                acousticness=cal.acoustic_full,
                calibration=cal,
            )
            bottom = ambient_fitness(
                energy=cal.energy_zero,
                bpm=cal.bpm_zero,
                acousticness=cal.acoustic_zero,
                calibration=cal,
            )
            assert top == pytest.approx(1.0)
            assert bottom == pytest.approx(0.0)


class TestDirection:
    def test_quieter_slower_and_more_acoustic_all_score_higher(self):
        base = fitness()
        assert fitness(energy=0.72) > base
        assert fitness(bpm=100) > base
        assert fitness(acousticness=0.57) > base

    def test_beyond_the_full_quantile_nothing_more_is_earned(self):
        """A ceiling, not a target. The first version scored energy as proximity to 0.25, so a
        0.10-energy drone came out *worse* than a 0.25 one — right for picking a representative
        seed, wrong as a floor where anything quiet enough should simply qualify."""
        assert fitness(energy=0.70) == fitness(energy=0.30) == fitness(energy=0.0)
        assert fitness(bpm=96) == fitness(bpm=40)


class TestMissingFeatures:
    def test_a_null_reads_as_neutral_rather_than_as_zero(self):
        """`_safe_float` returns 0.0 for NULL — maximally unambient. Inheriting that would
        silently exile the 740 rows in this library with no analysis."""
        assert fitness(acousticness=None) > fitness(acousticness=0.30)

    def test_every_feature_may_be_absent(self):
        score = ambient_fitness(energy=None, bpm=None, acousticness=None)
        assert score == pytest.approx(0.5)

    def test_the_result_is_always_in_range(self):
        for e in (0.0, 0.7, 0.83, 1.0):
            for b in (40.0, 96.0, 123.0, 220.0):
                for a in (0.0, 0.49, 0.58, 1.0):
                    assert 0.0 <= fitness(energy=e, bpm=b, acousticness=a) <= 1.0


class TestDegenerateLibraries:
    def test_a_library_with_no_spread_is_detected(self):
        flat = AmbientCalibration(
            energy_full=0.5,
            energy_zero=0.5,
            bpm_full=120,
            bpm_zero=120,
            acoustic_full=0.5,
            acoustic_zero=0.5,
        )
        assert flat.is_degenerate

    def test_a_flat_feature_scores_neutral_rather_than_dividing_by_zero(self):
        flat = AmbientCalibration(
            energy_full=0.5,
            energy_zero=0.5,
            bpm_full=96,
            bpm_zero=130,
            acoustic_full=0.58,
            acoustic_zero=0.47,
        )
        score = ambient_fitness(energy=0.5, bpm=96, acousticness=0.58, calibration=flat)
        assert 0.0 <= score <= 1.0


class TestTheSeedPathsAgree:
    """The concrete defect the deduplication fixes — and why it needs its own function."""

    def test_within_a_gated_set_the_quieter_track_wins(self):
        """`ambient_fitness` cannot answer this.

        The seed paths gate on `energy <= 0.7` and then rank what is left. Every survivor is
        already past `ambient_fitness`'s energy ceiling, so scoring them with it makes them all
        tie — `fitness(0.20)` and `fitness(0.45)` are both 0.556 — and the seed becomes
        arbitrary. `seed_fitness` is proximity to a target for exactly that reason.
        """
        assert seed_fitness(energy=0.20, instrumentalness=0.9, speechiness=0.1) > seed_fitness(
            energy=0.45, instrumentalness=0.9, speechiness=0.1
        )

    def test_the_pool_measure_would_have_tied_them(self):
        """Pins the distinction, so nobody collapses the two functions back together."""
        assert ambient_fitness(energy=0.20, bpm=100, acousticness=0.5) == ambient_fitness(
            energy=0.45, bpm=100, acousticness=0.5
        )

    def test_the_old_artist_heuristic_disagreed_with_the_old_surprise_heuristic(self):
        """**The bug.** Two accidentally different answers to one question.

        old artist:    0.20 -> 0.870   0.45 -> 0.915   picks 0.45
        old surprise:  0.20 -> 0.880   0.45 -> 0.730   picks 0.20
        """

        def old_artist(energy: float) -> float:
            return 0.9 * 0.4 + (1.0 - 0.1) * 0.3 + (1.0 - abs(energy - 0.4)) * 0.3

        assert old_artist(0.45) > old_artist(0.20), "the artist path preferred the louder track"
        # Both paths now call one function, and it agrees with the surprise path's intent.
        assert seed_fitness(energy=0.20, instrumentalness=0.9, speechiness=0.1) > seed_fitness(
            energy=0.45, instrumentalness=0.9, speechiness=0.1
        )

    def test_seed_scoring_is_unchanged_from_pick_surprise_seed(self):
        """This deduplicates; it does not retune. The old arithmetic, inlined here as the
        reference, must give the same answer."""
        for e, i, sp in [(0.20, 0.9, 0.1), (0.45, 0.9, 0.1), (0.0, 1.0, 0.0), (0.7, 0.5, 0.5)]:
            old = i * 0.4 + (1.0 - sp) * 0.3 + max(0, 1.0 - abs(e - 0.25) * 3.33) * 0.3
            assert seed_fitness(energy=e, instrumentalness=i, speechiness=sp) == pytest.approx(old)
