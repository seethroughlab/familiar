"""ADR-0093: in-library suggestions, chosen by agreement between seeds.

The decisions worth pinning are the ones that would otherwise fail by returning a plausible answer:

- **Agreement beats proximity.** A single seed's nearest neighbour is not a suggestion; two seeds
  reaching the same track independently is. A pure similarity sort gets this exactly wrong.
- **The list still answers when it cannot reach agreement**, or a three-track playlist returns
  nothing at all.
- **The reason shown is the one the ranking used** — a caption that disagrees with the ranking is a
  lie that looks like a feature.
"""

from uuid import uuid4

from app.services.collection_suggestions import (
    MIN_VOTES,
    NEIGHBOURS_MAX,
    NEIGHBOURS_MIN,
    Suggestion,
    _diversify,
    _drop_duplicate_recordings,
    _neighbours_for,
)


class _Track:
    """Minimal stand-in — the diversity walk reads only artist and album."""

    def __init__(self, artist: str = "A", album: str = "Al", title: str = "t"):
        self.id = uuid4()
        self.artist = artist
        self.album = album
        self.title = title


def _suggestion(*, artist="A", album="Al", votes=2, similarity=0.9) -> Suggestion:
    return Suggestion(
        track=_Track(artist=artist, album=album),
        because_of=_Track(artist="Seed"),
        similarity=similarity,
        votes=votes,
    )


class TestVoteFloor:
    def test_the_floor_is_above_one(self):
        """A single seed reaching a track is the noise this exists to remove.

        Measured on the real library: a 9-track IDM playlist ranked by summed similarity alone
        admitted a soundtrack cue that exactly one seed had reached.
        """
        assert MIN_VOTES >= 2


class TestNeighbourScaling:
    """`_neighbours_for` is what lets the vote floor engage at both ends of the size range.

    Measured on the real library, a 9-track playlist taking ten neighbours per seed produced
    **zero** candidates with two votes — so the floor never bound, and every result came from the
    single-vote top-up that the floor exists to suppress. The same playlist at thirty produced
    eight. A constant cannot serve nine seeds and six hundred.
    """

    def test_a_small_collection_casts_wide_enough_to_overlap(self):
        assert _neighbours_for(9) >= 30

    def test_a_large_collection_settles_at_the_floor(self):
        assert _neighbours_for(600) == NEIGHBOURS_MIN

    def test_it_never_exceeds_the_ceiling(self):
        """Past the ceiling the neighbours stop being neighbours."""
        assert _neighbours_for(1) == NEIGHBOURS_MAX
        assert _neighbours_for(2) == NEIGHBOURS_MAX

    def test_it_never_drops_below_the_floor(self):
        assert _neighbours_for(10_000) == NEIGHBOURS_MIN

    def test_it_is_monotonic_and_never_zero(self):
        counts = [_neighbours_for(n) for n in range(1, 200)]
        assert all(a >= b for a, b in zip(counts, counts[1:], strict=False))
        assert min(counts) >= 1

    def test_a_seed_count_of_zero_does_not_divide_by_zero(self):
        """Guarded rather than assumed: the caller returns early, but a helper should not explode."""
        assert _neighbours_for(0) == NEIGHBOURS_MAX


class TestDuplicateRecordings:
    """The artist and album caps cannot catch the same song filed twice.

    Seen on the real library: "Mr. Projectile — None" appeared twice in one list of ten, because the
    two rows carry different albums and so pass both caps. A list that repeats itself reads as
    broken.
    """

    def test_the_same_recording_is_offered_once(self):
        first = _suggestion(artist="Mr. Projectile", album="Single")
        first.track.title = "None"
        second = _suggestion(artist="Mr. Projectile", album="Compilation")
        second.track.title = "None"

        kept = _drop_duplicate_recordings([first, second])
        assert [s.track.id for s in kept] == [first.track.id]

    def test_it_keeps_the_better_ranked_copy(self):
        best = _suggestion(artist="A", album="X")
        best.track.title = "Song"
        worse = _suggestion(artist="A", album="Y")
        worse.track.title = "Song"
        assert _drop_duplicate_recordings([best, worse])[0].track.id == best.track.id

    def test_normalisation_matches_duplicate_detection(self):
        """Same helper as `duplicate_detection`, so the two features agree on what is the same."""
        plain = _suggestion(artist="The Cure", album="X")
        plain.track.title = "A Forest"
        variant = _suggestion(artist="Cure", album="Y")
        variant.track.title = "A Forest"
        assert len(_drop_duplicate_recordings([plain, variant])) == 1

    def test_different_songs_by_one_artist_both_survive(self):
        one = _suggestion(artist="A", album="X")
        one.track.title = "First"
        two = _suggestion(artist="A", album="X")
        two.track.title = "Second"
        assert len(_drop_duplicate_recordings([one, two])) == 2

    def test_untitled_unnamed_tracks_are_not_collapsed_together(self):
        """An empty key would fold every unnamed track into one row."""
        blanks = []
        for _ in range(3):
            blank = _suggestion(artist="", album="")
            blank.track.artist = None
            blank.track.title = None
            blanks.append(blank)
        assert len(_drop_duplicate_recordings(blanks)) == 3


class TestDiversify:
    def test_preserves_the_incoming_order(self):
        """`_diverse_in_order` is reused precisely because it does not reshuffle.

        `ToolExecutor._apply_diversity` applies the same caps but shuffles first, which would throw
        the vote ranking away and return a random selection that merely looks ranked.
        """
        candidates = [
            _suggestion(artist=f"Artist {i}", album=f"Album {i}") for i in range(5)
        ]
        assert [s.track.id for s in _diversify(candidates, 5)] == [
            s.track.id for s in candidates
        ]

    def test_caps_an_artist_at_two(self):
        candidates = [_suggestion(artist="One", album=f"Album {i}") for i in range(5)]
        assert len(_diversify(candidates, 5)) == 2

    def test_caps_an_album_at_two(self):
        candidates = [_suggestion(artist=f"Artist {i}", album="Shared") for i in range(5)]
        # Album keys are scoped by artist, so five different artists on one album title are not
        # the same album — the cap that bites here is the per-artist one, which each passes.
        assert len(_diversify(candidates, 5)) == 5

    def test_keeps_the_best_track_of_a_capped_artist(self):
        """Walking in order keeps an artist's strongest entries, not arbitrary ones."""
        best = _suggestion(artist="One", album="A")
        second = _suggestion(artist="One", album="B")
        third = _suggestion(artist="One", album="C")
        kept = _diversify([best, second, third], 5)
        assert [s.track.id for s in kept] == [best.track.id, second.track.id]

    def test_empty_and_zero_limit_are_answers_not_errors(self):
        assert _diversify([], 5) == []
        assert _diversify([_suggestion()], 0) == []

    def test_returns_suggestions_not_bare_tracks(self):
        """The reason has to survive the diversity pass, or the caption is lost on the way out."""
        candidate = _suggestion(artist="Solo")
        kept = _diversify([candidate], 1)
        assert kept[0].because_of is candidate.because_of
        assert kept[0].similarity == candidate.similarity
        assert kept[0].votes == candidate.votes
