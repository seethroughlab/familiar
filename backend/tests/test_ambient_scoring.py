"""Characterisation tests for the ambient ranking engine.

These lock in what `app.services.ambient` does **today**, before ADR-0005 splits its
weights into named AMBIENT/RADIO profiles. Ambient mode is a shipped feature and had no
test coverage at all, so without this the refactor would have nothing to be checked
against.

They are deliberately written against observed behaviour rather than intended behaviour.
Where something looks questionable — `_safe_float` treating a missing feature as 0.0
(maximally distant) instead of neutral, `key_compatibility` scoring an unknown key higher
than an unrelated one — that is recorded as-is and marked. Changing any of it is a
separate decision, not a side effect of a refactor.

Every number here was read from the implementation, not assumed.
"""

from uuid import uuid4

import pytest

from app.services.ambient import (
    AmbientDescriptor,
    _safe_float,
    key_compatibility,
    parse_key,
    score_candidate,
    suggest_snippet_window,
)


def make_descriptor(**overrides) -> AmbientDescriptor:
    """A descriptor with every feature at a neutral mid-point unless overridden."""
    base = {
        "track_id": uuid4(),
        "title": "Test Track",
        "artist": "Test Artist",
        "album": "Test Album",
        "duration_seconds": 200.0,
        "key": "C",
        "bpm": 120.0,
        "energy": 0.5,
        "brightness": 0.5,
        "valence": 0.5,
        "instrumentalness": 0.5,
        "speechiness": 0.5,
        "dynamic_range_db": 10.0,
        "energy_shape": None,
        "section_count": None,
        "modal_character": None,
        "acousticness": 0.5,
    }
    base.update(overrides)
    return AmbientDescriptor(**base)


class TestParseKey:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("C", (0, "major")),
            ("C major", (0, "major")),
            ("C maj", (0, "major")),
            ("Am", (9, "minor")),
            ("A minor", (9, "minor")),
            ("A min", (9, "minor")),
            ("C#", (1, "major")),
            ("Db", (1, "major")),  # enharmonic spellings share a pitch class
            ("Eb", (3, "major")),
            ("Bb", (10, "major")),
        ],
    )
    def test_parses_known_spellings(self, text, expected):
        assert parse_key(text) == expected

    def test_is_case_insensitive_via_fallback_scan(self):
        assert parse_key("am") == (9, "minor")
        assert parse_key("C MAJOR") == (0, "major")

    def test_strips_surrounding_whitespace(self):
        assert parse_key("  Am  ") == (9, "minor")

    @pytest.mark.parametrize("text", [None, "", "   ", "H", "not-a-key", "Am7"])
    def test_unparseable_returns_none(self, text):
        assert parse_key(text) is None


class TestKeyCompatibility:
    def test_same_key(self):
        assert key_compatibility("Am", "Am") == 1.0
        assert key_compatibility("C", "C") == 1.0

    def test_relative_major_minor(self):
        # Am -> C and C -> Am, in both directions
        assert key_compatibility("Am", "C") == 0.9
        assert key_compatibility("C", "Am") == 0.9

    def test_perfect_fifth_same_mode(self):
        assert key_compatibility("C", "G") == 0.8   # +7
        assert key_compatibility("C", "F") == 0.8   # +5
        assert key_compatibility("Am", "Em") == 0.8

    def test_parallel_major_minor(self):
        assert key_compatibility("C", "Cm") == 0.7

    def test_two_steps_on_the_circle_same_mode(self):
        assert key_compatibility("C", "D") == 0.5   # +2
        assert key_compatibility("C", "Bb") == 0.5  # +10

    def test_unrelated(self):
        assert key_compatibility("C", "F#") == 0.2

    def test_unknown_key_is_neutral_not_penalised(self):
        # NOTE: an unknown key (0.5) scores HIGHER than a known-unrelated one (0.2).
        # Locked as observed; whether that is desirable is a separate question.
        assert key_compatibility(None, "C") == 0.5
        assert key_compatibility("C", None) == 0.5
        assert key_compatibility("garbage", "C") == 0.5
        assert key_compatibility("C", "F#") == 0.2

    def test_enharmonic_spellings_are_equivalent(self):
        assert key_compatibility("C#", "Db") == 1.0


class TestSafeFloat:
    def test_missing_reads_as_zero_not_neutral(self):
        # This is the consequential one: a NULL feature is treated as maximally
        # distant (0.0), not as "no information". Locked as-is.
        assert _safe_float(None) == 0.0
        assert _safe_float("nonsense") == 0.0
        assert _safe_float(None, default=0.5) == 0.5

    def test_passes_through_numbers(self):
        assert _safe_float(0.25) == 0.25
        assert _safe_float(3) == 3.0
        assert _safe_float("0.75") == 0.75


class TestScoreCandidateWeights:
    """The weighted sum, before any bonus or penalty applies."""

    def test_identical_track_scores_near_maximum(self):
        d = make_descriptor(key="C", energy=0.5, brightness=0.5, valence=0.5,
                            instrumentalness=1.0, speechiness=0.0, dynamic_range_db=10.0)
        score = score_candidate(d, d, embedding_similarity=1.0)
        assert score == pytest.approx(1.0, abs=1e-9)

    def test_balanced_weights_sum_to_one(self):
        # key .30 + energy .20 + embedding .15 + vocal .10
        # + brightness .10 + valence .10 + dr .05
        current = make_descriptor()
        candidate = make_descriptor(instrumentalness=1.0, speechiness=0.0)
        score = score_candidate(current, candidate, intensity="balanced",
                                embedding_similarity=1.0)
        assert score == pytest.approx(1.0, abs=1e-9)

    def test_quiet_shifts_weight_from_key_to_energy(self):
        # quiet: energy .30, key .20 — a candidate strong on energy but weak on key
        # scores higher under 'quiet' than under 'balanced'.
        current = make_descriptor(key="C", energy=0.5)
        candidate = make_descriptor(key="F#", energy=0.5,
                                    instrumentalness=1.0, speechiness=0.0)
        balanced = score_candidate(current, candidate, intensity="balanced",
                                   embedding_similarity=1.0)
        quiet = score_candidate(current, candidate, intensity="quiet",
                                embedding_similarity=1.0)
        assert quiet > balanced

    def test_immersive_shifts_weight_from_key_to_embedding(self):
        current = make_descriptor(key="C")
        candidate = make_descriptor(key="F#", instrumentalness=1.0, speechiness=0.0)
        balanced = score_candidate(current, candidate, intensity="balanced",
                                   embedding_similarity=1.0)
        immersive = score_candidate(current, candidate, intensity="immersive",
                                    embedding_similarity=1.0)
        assert immersive > balanced

    def test_absent_embedding_similarity_defaults_to_half(self):
        current = make_descriptor()
        candidate = make_descriptor(instrumentalness=1.0, speechiness=0.0)
        explicit = score_candidate(current, candidate, embedding_similarity=0.5)
        implicit = score_candidate(current, candidate, embedding_similarity=None)
        assert explicit == pytest.approx(implicit)

    def test_vocal_term_penalises_singing(self):
        # vocal_score = instrumentalness * 0.7 + (1 - speechiness) * 0.3, weight 0.10.
        # This is the ambient-specific bias ADR-0005's RADIO profile removes.
        current = make_descriptor()
        instrumental = make_descriptor(instrumentalness=1.0, speechiness=0.0)
        vocal = make_descriptor(instrumentalness=0.0, speechiness=0.0)
        assert score_candidate(current, instrumental, embedding_similarity=1.0) > \
               score_candidate(current, vocal, embedding_similarity=1.0)

    def test_dynamic_range_difference_saturates_at_20db(self):
        current = make_descriptor(dynamic_range_db=10.0)
        at_20 = make_descriptor(dynamic_range_db=30.0, instrumentalness=1.0, speechiness=0.0)
        beyond = make_descriptor(dynamic_range_db=60.0, instrumentalness=1.0, speechiness=0.0)
        assert score_candidate(current, at_20, embedding_similarity=1.0) == \
               pytest.approx(score_candidate(current, beyond, embedding_similarity=1.0))


class TestScoreCandidateAdjustments:
    """Each bonus and penalty, isolated."""

    def test_bpm_penalty_beyond_40(self):
        current = make_descriptor(bpm=120.0)
        close = make_descriptor(bpm=155.0, instrumentalness=1.0, speechiness=0.0)   # 35 apart
        far = make_descriptor(bpm=165.0, instrumentalness=1.0, speechiness=0.0)     # 45 apart
        assert score_candidate(current, close, embedding_similarity=1.0) - \
               score_candidate(current, far, embedding_similarity=1.0) == pytest.approx(0.15)

    def test_bpm_penalty_needs_both_tempos_known(self):
        current = make_descriptor(bpm=None)
        far = make_descriptor(bpm=200.0, instrumentalness=1.0, speechiness=0.0)
        known = make_descriptor(bpm=120.0, instrumentalness=1.0, speechiness=0.0)
        assert score_candidate(current, far, embedding_similarity=1.0) == \
               pytest.approx(score_candidate(current, known, embedding_similarity=1.0))

    def test_quiet_energy_bonus_below_035(self):
        # Needs headroom below the 1.0 clamp for the +0.10 to be observable, hence the
        # deliberately imperfect embedding similarity.
        current = make_descriptor(energy=0.3)
        low = make_descriptor(energy=0.3, instrumentalness=1.0, speechiness=0.0)
        high = make_descriptor(energy=0.4, instrumentalness=1.0, speechiness=0.0)

        # Below 0.35 gets the bonus under 'quiet'...
        assert score_candidate(current, low, intensity="quiet", embedding_similarity=0.3) > \
               score_candidate(current, low, intensity="balanced", embedding_similarity=0.3)

        # ...and a candidate at or above 0.35 does not.
        quiet_high = score_candidate(current, high, intensity="quiet", embedding_similarity=0.3)
        balanced_high = score_candidate(current, high, intensity="balanced", embedding_similarity=0.3)
        assert quiet_high - balanced_high < 0.10

    def test_minor_key_bonus(self):
        # +0.02, but an identical track already clamps at 1.0, so give it headroom.
        current = make_descriptor(energy=0.9)
        minor = make_descriptor(energy=0.5, modal_character="natural minor",
                                instrumentalness=1.0, speechiness=0.0)
        major = make_descriptor(energy=0.5, modal_character="major",
                                instrumentalness=1.0, speechiness=0.0)
        assert score_candidate(current, minor, embedding_similarity=0.5) - \
               score_candidate(current, major, embedding_similarity=0.5) == pytest.approx(0.02)

    def test_artist_cooldown(self):
        current = make_descriptor(energy=0.9)
        candidate = make_descriptor(energy=0.5, artist="Recently Played",
                                    instrumentalness=1.0, speechiness=0.0)
        without = score_candidate(current, candidate, embedding_similarity=0.5)
        with_cooldown = score_candidate(current, candidate, embedding_similarity=0.5,
                                        recent_artist_names=["Recently Played"])
        assert without - with_cooldown == pytest.approx(0.25)

    def test_artist_cooldown_is_case_insensitive(self):
        current = make_descriptor(energy=0.9)
        candidate = make_descriptor(energy=0.5, artist="Boards of Canada",
                                    instrumentalness=1.0, speechiness=0.0)
        assert score_candidate(current, candidate, embedding_similarity=0.5,
                               recent_artist_names=["BOARDS OF CANADA"]) == \
               pytest.approx(score_candidate(current, candidate, embedding_similarity=0.5,
                                             recent_artist_names=["Boards of Canada"]))

    def test_score_is_clamped_to_unit_range(self):
        current = make_descriptor(bpm=120.0)
        # Stack every penalty: unrelated key, opposite energy, huge BPM gap, cooldown.
        worst = make_descriptor(key="F#", energy=1.0, brightness=1.0, valence=1.0,
                                bpm=300.0, instrumentalness=0.0, speechiness=1.0,
                                dynamic_range_db=100.0, artist="Same")
        current = make_descriptor(key="C", energy=0.0, brightness=0.0, valence=0.0,
                                  bpm=120.0, dynamic_range_db=0.0, artist="Same")
        score = score_candidate(current, worst, embedding_similarity=0.0,
                                recent_artist_names=["Same"])
        assert 0.0 <= score <= 1.0
        assert score == 0.0


class TestSuggestSnippetWindow:
    def test_short_tracks_use_full_bounds(self):
        assert suggest_snippet_window(20.0) == (0.1, 0.9)
        assert suggest_snippet_window(None) == (0.1, 0.9)

    def test_energy_shape_shifts_the_window(self):
        building = suggest_snippet_window(300.0, "building")
        declining = suggest_snippet_window(300.0, "declining")
        assert building[0] > declining[0]

    def test_window_is_ordered_and_within_bounds(self):
        for duration in (60.0, 200.0, 600.0):
            for shape in (None, "building", "declining", "peak_middle"):
                start, end = suggest_snippet_window(duration, shape)
                assert 0.0 <= start < end <= 1.0
