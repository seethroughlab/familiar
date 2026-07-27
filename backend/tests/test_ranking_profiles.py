"""Tests for the named ranking profiles (ADR-0005).

`tests/test_ambient_scoring.py` is the regression lock for `AMBIENT` — it characterised
the engine before the weights were extracted, so any drift in ambient behaviour fails
there. This file covers what the split *adds*: that `RADIO` differs in the ways the ADR
says it should, and that the taste and negative terms are genuinely inert under `AMBIENT`
rather than merely small.

`RADIO`'s specific weights are a starting guess and will change once ADR-0004 events
accumulate, so these assert relationships and invariants rather than exact scores. A test
that pinned `RADIO` to a number would have to be rewritten by the first tuning pass and
would be protecting nothing.
"""

from uuid import uuid4

import pytest

from app.services.ambient import AmbientDescriptor, score_candidate
from app.services.ranking_profiles import (
    AMBIENT,
    PROFILES,
    RADIO,
    WEIGHT_KEYS,
    get_profile,
)


def make_descriptor(**overrides) -> AmbientDescriptor:
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
        "section_count": 5,
        "modal_character": None,
        "acousticness": 0.5,
    }
    base.update(overrides)
    return AmbientDescriptor(**base)


class TestProfileIntegrity:
    @pytest.mark.parametrize("profile", list(PROFILES.values()), ids=lambda p: p.name)
    def test_covers_every_weight_key(self, profile):
        assert set(profile.weights) >= set(WEIGHT_KEYS)

    @pytest.mark.parametrize("profile", list(PROFILES.values()), ids=lambda p: p.name)
    def test_feature_weights_and_taste_sum_to_one(self, profile):
        """Taste is part of the convex combination, not a bonus on top of a full 1.0.

        Added on top it could only push an already-saturating score into the clamp, so it
        would barely reorder anything. Taking a share means it genuinely competes with
        similarity and harmonic fit. AMBIENT is 1.0 + 0.0; RADIO is 0.80 + 0.20.
        """
        total = sum(profile.weights[k] for k in WEIGHT_KEYS) + profile.taste_weight
        assert total == pytest.approx(1.0)

    @pytest.mark.parametrize("profile", list(PROFILES.values()), ids=lambda p: p.name)
    def test_intensity_overrides_preserve_the_sum(self, profile):
        for intensity in profile.intensity_overrides:
            merged = profile.weights_for(intensity)
            total = sum(merged[k] for k in WEIGHT_KEYS) + profile.taste_weight
            assert total == pytest.approx(1.0), intensity

    def test_unknown_profile_is_rejected_loudly(self):
        with pytest.raises(ValueError, match="Unknown ranking profile"):
            get_profile("jazz-o-matic")

    def test_missing_name_defaults_to_ambient(self):
        """Existing ambient callers pass nothing and must keep working."""
        assert get_profile(None) is AMBIENT
        assert get_profile("") is AMBIENT


class TestRadioDiffersAsTheADRSays:
    def test_radio_does_not_penalise_vocals(self):
        """The vocal term exists to keep ambient instrumental.

        Applying it to radio would demote most of a music library.
        """
        assert AMBIENT.weights["vocal"] > 0
        assert RADIO.weights["vocal"] == 0.0

    def test_a_vocal_track_is_not_disadvantaged_under_radio(self):
        current = make_descriptor()
        instrumental = make_descriptor(instrumentalness=1.0, speechiness=0.0)
        vocal = make_descriptor(instrumentalness=0.0, speechiness=0.6)

        radio_gap = (
            score_candidate(current, instrumental, profile=RADIO)
            - score_candidate(current, vocal, profile=RADIO)
        )
        ambient_gap = (
            score_candidate(current, instrumental, profile=AMBIENT)
            - score_candidate(current, vocal, profile=AMBIENT)
        )

        assert radio_gap == pytest.approx(0.0)
        assert ambient_gap > 0.0

    def test_radio_leans_on_similarity_more_than_ambient(self):
        assert RADIO.weights["embedding"] > AMBIENT.weights["embedding"]

    def test_ambient_leans_on_harmonic_key_more_than_radio(self):
        assert AMBIENT.weights["key"] > RADIO.weights["key"]

    def test_only_radio_weighs_taste(self):
        assert AMBIENT.taste_weight == 0.0
        assert RADIO.taste_weight > 0.0

    def test_radio_has_no_intensity_overrides(self):
        """Intensity is an ambient control with no radio equivalent."""
        assert RADIO.intensity_overrides == {}
        for intensity in ("quiet", "immersive", "balanced", "anything"):
            assert RADIO.weights_for(intensity) == RADIO.weights


class TestTasteTerm:
    def test_raises_the_score_under_radio(self):
        current, cand = make_descriptor(), make_descriptor()
        low = score_candidate(current, cand, profile=RADIO, taste_score=0.0)
        high = score_candidate(current, cand, profile=RADIO, taste_score=1.0)
        assert high > low

    def test_is_bounded_by_its_weight(self):
        current, cand = make_descriptor(), make_descriptor()
        base = score_candidate(current, cand, profile=RADIO, taste_score=0.0)
        best = score_candidate(current, cand, profile=RADIO, taste_score=1.0)
        assert best - base == pytest.approx(RADIO.taste_weight, abs=1e-9)

    def test_out_of_range_taste_is_clamped_not_trusted(self):
        current, cand = make_descriptor(), make_descriptor()
        sane = score_candidate(current, cand, profile=RADIO, taste_score=1.0)
        absurd = score_candidate(current, cand, profile=RADIO, taste_score=99.0)
        assert absurd == pytest.approx(sane)

    def test_is_inert_under_ambient(self):
        current, cand = make_descriptor(), make_descriptor()
        assert score_candidate(current, cand, profile=AMBIENT, taste_score=1.0) == (
            score_candidate(current, cand, profile=AMBIENT, taste_score=0.0)
        )


class TestNegativeTerm:
    def test_skips_demote(self):
        current, cand = make_descriptor(), make_descriptor()
        clean = score_candidate(current, cand, profile=RADIO)
        skipped = score_candidate(current, cand, profile=RADIO, skip_count=2)
        assert skipped < clean

    def test_rejection_counts_for_more_than_a_skip(self):
        """Skipping is ambiguous — wrong moment, heard it recently. Rejecting is a
        stated judgement, so it should weigh more."""
        current, cand = make_descriptor(), make_descriptor()
        one_skip = score_candidate(current, cand, profile=RADIO, skip_count=1)
        one_reject = score_candidate(current, cand, profile=RADIO, reject_count=1)
        assert one_reject < one_skip

    def test_penalty_is_capped(self):
        """An uncapped penalty would permanently exile anything skipped often, and the
        candidate pool would shrink over time."""
        current, cand = make_descriptor(), make_descriptor()
        base = score_candidate(current, cand, profile=RADIO)
        hammered = score_candidate(current, cand, profile=RADIO, skip_count=500, reject_count=500)
        assert base - hammered <= RADIO.max_negative_penalty + 1e-9

    def test_is_inert_under_ambient(self):
        current, cand = make_descriptor(), make_descriptor()
        assert score_candidate(current, cand, profile=AMBIENT, skip_count=9, reject_count=9) == (
            score_candidate(current, cand, profile=AMBIENT)
        )


class TestScoresStayInRange:
    @pytest.mark.parametrize("profile", list(PROFILES.values()), ids=lambda p: p.name)
    def test_every_extreme_stays_within_zero_and_one(self, profile):
        current = make_descriptor(key="C", bpm=60.0, energy=0.0, brightness=0.0,
                                  valence=0.0, dynamic_range_db=0.0)
        candidate = make_descriptor(key="F#", bpm=200.0, energy=1.0, brightness=1.0,
                                    valence=1.0, dynamic_range_db=30.0,
                                    artist="Test Artist", modal_character="minor")

        for taste in (0.0, 1.0):
            for skips, rejects in ((0, 0), (50, 50)):
                score = score_candidate(
                    current, candidate,
                    intensity="quiet",
                    embedding_similarity=1.0,
                    recent_artist_names=["Test Artist"],
                    profile=profile,
                    taste_score=taste,
                    skip_count=skips,
                    reject_count=rejects,
                )
                assert 0.0 <= score <= 1.0


class TestDefaultProfileIsAmbient:
    def test_omitting_the_profile_scores_as_ambient(self):
        """Every existing ambient call site omits it."""
        current = make_descriptor(key="C", energy=0.4)
        cand = make_descriptor(key="G", energy=0.6, modal_character="minor")

        for intensity in ("quiet", "balanced", "immersive"):
            assert score_candidate(current, cand, intensity=intensity) == (
                score_candidate(current, cand, intensity=intensity, profile=AMBIENT)
            )
