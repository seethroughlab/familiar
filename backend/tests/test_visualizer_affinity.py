"""Tests for the visualizer affinity scorer (ADR-0064).

No database: the scorer is pure, and that is the point of it being pure. Following
`test_ranking_profiles.py`'s doctrine, these assert **relationships and invariants** rather than
exact scores — the weights are a starting guess the ADR says cannot be tuned without listening
data, so pinning "0.73" here would make retuning fail a test for no reason.
"""

import pytest

from app.services.mood_tags import KNOWN_TAGS
from app.services.visualizer_affinity import (
    NEUTRAL,
    NUMERIC_FEATURE_COLUMNS,
    WEIGHT_KEYS,
    WEIGHTS,
    Affinity,
    Candidate,
    FeatureRange,
    rank_candidates,
    score_candidate,
)


def tags(*pairs: tuple[str, float]) -> list[dict]:
    """Track mood tags in their stored shape: {"tag", "category", "confidence"}."""
    return [{"tag": t, "category": "mood", "confidence": c} for t, c in pairs]


def candidate(id_: str, *, tags_=(), ranges=()) -> Candidate:
    return Candidate(id=id_, affinity=Affinity(tags=tuple(tags_), ranges=tuple(ranges)))


class TestWeights:
    def test_weights_cover_exactly_the_declared_keys(self):
        assert set(WEIGHTS) == set(WEIGHT_KEYS)

    def test_weights_sum_to_one(self):
        assert sum(WEIGHTS[k] for k in WEIGHT_KEYS) == pytest.approx(1.0)

    def test_numeric_columns_exclude_the_string_ones(self):
        # Seven of the twenty-eight analysis columns hold strings; a numeric range over one of
        # them is meaningless and must not be offered as judgeable.
        for string_column in (
            "key",
            "key_stability",
            "modal_character",
            "tempo_character",
            "energy_shape",
            "form_string",
            "interval_character",
        ):
            assert string_column not in NUMERIC_FEATURE_COLUMNS

    def test_numeric_columns_include_the_obvious_ones(self):
        for numeric_column in ("energy", "valence", "bpm", "danceability", "brightness"):
            assert numeric_column in NUMERIC_FEATURE_COLUMNS


class TestNothingToJudge:
    def test_no_affinity_scores_neutral(self):
        result = score_candidate(candidate("plain"), {"energy": 0.9}, tags(("calm", 0.8)))
        assert result.score == NEUTRAL

    def test_track_with_no_tags_is_neutral_on_the_tag_term(self):
        # Neutral, not zero: an untagged track is not evidence the visualizer is wrong for it.
        result = score_candidate(candidate("c", tags_=["calm"]), {}, [])
        assert result.score == NEUTRAL

    def test_range_over_a_feature_the_track_lacks_is_inert(self):
        # `to_features_dict()` omits nulls, so a missing key means "not analysed for this".
        # Treating that as a miss would rank every declaring visualizer down on a partly
        # analysed library.
        result = score_candidate(
            candidate("c", ranges=[FeatureRange("bpm", 60, 100)]), {"energy": 0.5}, []
        )
        assert result.score == NEUTRAL
        assert result.unmatched_ranges == ()


class TestTags:
    def test_claiming_the_dominant_tag_beats_claiming_a_weak_one(self):
        track_tags = tags(("ambient", 0.9), ("playful", 0.1))
        strong = score_candidate(candidate("s", tags_=["ambient"]), {}, track_tags)
        weak = score_candidate(candidate("w", tags_=["playful"]), {}, track_tags)
        assert strong.score > weak.score

    def test_claiming_every_tag_scores_at_least_as_high_as_claiming_one(self):
        track_tags = tags(("ambient", 0.6), ("dreamy", 0.4))
        both = score_candidate(candidate("b", tags_=["ambient", "dreamy"]), {}, track_tags)
        one = score_candidate(candidate("o", tags_=["ambient"]), {}, track_tags)
        assert both.score >= one.score

    def test_matched_tags_are_reported(self):
        result = score_candidate(
            candidate("c", tags_=["ambient", "dreamy"]), {}, tags(("ambient", 0.7))
        )
        assert result.matched_tags == ("ambient",)

    def test_a_mismatched_tag_scores_below_neutral(self):
        # Declared something we understand, and none of it applies. That is a real signal.
        result = score_candidate(candidate("c", tags_=["metal"]), {}, tags(("ambient", 0.9)))
        assert result.score < NEUTRAL


class TestRanges:
    def test_a_track_inside_the_range_beats_one_outside(self):
        vis = candidate("c", ranges=[FeatureRange("energy", 0.0, 0.4)])
        inside = score_candidate(vis, {"energy": 0.2}, [])
        outside = score_candidate(vis, {"energy": 0.9}, [])
        assert inside.score > outside.score

    def test_open_ended_ranges_work(self):
        vis = candidate("c", ranges=[FeatureRange("bpm", minimum=120)])
        assert score_candidate(vis, {"bpm": 140}, []).matched_ranges == ("bpm",)
        assert score_candidate(vis, {"bpm": 90}, []).unmatched_ranges == ("bpm",)

    def test_bounds_are_inclusive(self):
        vis = candidate("c", ranges=[FeatureRange("energy", 0.2, 0.8)])
        assert score_candidate(vis, {"energy": 0.2}, []).matched_ranges == ("energy",)
        assert score_candidate(vis, {"energy": 0.8}, []).matched_ranges == ("energy",)

    def test_an_integer_column_is_judgeable(self):
        vis = candidate("c", ranges=[FeatureRange("section_count", 4, 12)])
        assert score_candidate(vis, {"section_count": 8}, []).matched_ranges == ("section_count",)


class TestIgnoredRatherThanRefused:
    def test_an_unknown_tag_is_ignored_and_reported(self):
        result = score_candidate(candidate("c", tags_=["definitely-not-a-tag"]), {}, tags(("calm", 0.9)))
        assert "definitely-not-a-tag" in result.ignored
        # Ignored means inert: with nothing else declared, the verdict is "no opinion".
        assert result.score == NEUTRAL

    def test_a_range_over_a_string_column_is_ignored(self):
        result = score_candidate(
            candidate("c", ranges=[FeatureRange("form_string", 0, 1)]), {"form_string": "ABAB"}, []
        )
        assert "form_string" in result.ignored
        assert result.score == NEUTRAL

    def test_a_range_over_an_unknown_column_is_ignored(self):
        result = score_candidate(
            candidate("c", ranges=[FeatureRange("vibes", 0, 1)]), {"energy": 0.5}, []
        )
        assert "vibes" in result.ignored

    def test_an_unbounded_range_is_ignored(self):
        result = score_candidate(candidate("c", ranges=[FeatureRange("energy")]), {"energy": 0.5}, [])
        assert "energy" in result.ignored

    def test_an_unknown_tag_does_not_dilute_a_recognised_one(self):
        # The whole point of "inert": adding a typo must not change the score.
        track_tags = tags(("ambient", 0.9))
        clean = score_candidate(candidate("a", tags_=["ambient"]), {}, track_tags)
        typo = score_candidate(candidate("b", tags_=["ambient", "ambiant"]), {}, track_tags)
        assert typo.score == clean.score

    def test_every_known_tag_is_accepted(self):
        for tag in KNOWN_TAGS:
            result = score_candidate(candidate("c", tags_=[tag]), {}, tags((tag, 0.5)))
            assert result.ignored == (), f"{tag!r} should be recognised"


class TestRanking:
    def test_best_match_comes_first(self):
        track_tags = tags(("ambient", 0.9))
        ranked = rank_candidates(
            [candidate("wrong", tags_=["metal"]), candidate("right", tags_=["ambient"])],
            {},
            track_tags,
        )
        assert [r.id for r in ranked] == ["right", "wrong"]

    def test_ties_keep_the_submitted_order(self):
        # Stability matters: a visualizer that flickered between two equal matches on every
        # track would read as a bug rather than a choice.
        ranked = rank_candidates([candidate("a"), candidate("b"), candidate("c")], {}, [])
        assert [r.id for r in ranked] == ["a", "b", "c"]

    def test_scores_stay_within_bounds(self):
        ranked = rank_candidates(
            [
                candidate("a", tags_=["ambient"], ranges=[FeatureRange("energy", 0, 0.1)]),
                candidate("b", tags_=["metal"], ranges=[FeatureRange("energy", 0.9, 1.0)]),
            ],
            {"energy": 0.05},
            tags(("ambient", 1.0)),
        )
        for result in ranked:
            assert 0.0 <= result.score <= 1.0

    def test_empty_candidate_list_ranks_to_nothing(self):
        assert rank_candidates([], {"energy": 0.5}, tags(("calm", 0.5))) == []

    def test_a_declaring_visualizer_that_fits_beats_one_that_declared_nothing(self):
        ranked = rank_candidates(
            [candidate("silent"), candidate("fitting", tags_=["ambient"])],
            {},
            tags(("ambient", 0.95)),
        )
        assert ranked[0].id == "fitting"

    def test_a_declaring_visualizer_that_does_not_fit_loses_to_one_that_declared_nothing(self):
        # ADR-0064 point 4's concern from the other end: declaring must be able to hurt, or
        # declaring is free and every author over-claims.
        ranked = rank_candidates(
            [candidate("wrong", tags_=["metal"]), candidate("silent")],
            {},
            tags(("ambient", 0.95)),
        )
        assert ranked[0].id == "silent"
