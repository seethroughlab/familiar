"""Last.fm's threshold, which is not Familiar's (ADR-0030)."""

import pytest

from app.services.scrobble_policy import should_scrobble


class TestScrobbleThreshold:
    def test_a_track_played_past_halfway_scrobbles(self):
        assert should_scrobble(played_seconds=100, track_duration=180) is True

    def test_a_track_barely_started_does_not(self):
        assert should_scrobble(played_seconds=10, track_duration=180) is False

    @pytest.mark.parametrize("played", [29.9, 0, 5])
    def test_the_thirty_second_floor_applies_however_short_the_track(self, played):
        # A 40-second interlude played to the end is a play to Familiar and not a scrobble to
        # Last.fm. Both must hold, so passing the halfway test is not enough.
        assert should_scrobble(played_seconds=played, track_duration=40) is False

    def test_exactly_at_both_thresholds_scrobbles(self):
        # 30s played, 60s track: meets the floor and is exactly half.
        assert should_scrobble(played_seconds=30, track_duration=60) is True

    def test_a_long_mix_scrobbles_at_four_minutes_not_at_half(self):
        # An hour-long set: half would be thirty minutes, which is not what Last.fm asks for.
        assert should_scrobble(played_seconds=240, track_duration=3600) is True
        assert should_scrobble(played_seconds=239, track_duration=3600) is False

    def test_a_missing_duration_falls_back_to_the_floor_alone(self):
        # Refusing on incomplete metadata would silently drop scrobbles for tracks the server has
        # not analysed, which is a worse failure than scrobbling one it should not have.
        assert should_scrobble(played_seconds=45, track_duration=None) is True
        assert should_scrobble(played_seconds=10, track_duration=None) is False

    def test_a_nonsense_duration_is_treated_as_missing(self):
        assert should_scrobble(played_seconds=45, track_duration=0) is True
        assert should_scrobble(played_seconds=45, track_duration=-10) is True

    def test_nothing_played_never_scrobbles(self):
        assert should_scrobble(played_seconds=None, track_duration=180) is False


class TestTheGapBetweenFamiliarAndLastfm:
    """The cases that make this a policy rather than a copy of `play_count`.

    Familiar's play means *reached the end*; Last.fm's means *half*. These are the events where the
    two disagree, and getting them wrong is what a design hanging off `/played` alone would do.
    """

    def test_a_track_abandoned_at_sixty_percent_is_a_skip_but_still_scrobbles(self):
        # Arrives on /skipped, never on /played. Last.fm wants it.
        assert should_scrobble(played_seconds=108, track_duration=180) is True

    def test_a_track_abandoned_early_is_a_skip_and_no_scrobble(self):
        assert should_scrobble(played_seconds=20, track_duration=180) is False

    def test_a_very_short_track_played_to_the_end_is_a_play_but_no_scrobble(self):
        # The mirror image: /played fires, Last.fm still says no.
        assert should_scrobble(played_seconds=20, track_duration=20) is False
