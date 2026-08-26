"""ADR-0048: seeded playlist generation.

The tests that matter here are about **what makes a playlist different from radio**, because the
ADR's Implementation block names that as the trap the implementation can still fall into: the engine
is shared, so reusing `RADIO`'s weights scores transitions rather than sets and nothing would look
obviously wrong.
"""

from uuid import uuid4

import pytest

from app.services.ambient import AmbientDescriptor
from app.services.playlist_generation import (
    HNSW_EF_SEARCH,
    POOL_SIZE,
    ResolvedSeed,
    _diverse_in_order,
    _mean_descriptor,
    _seed_label,
    playlist_name,
)
from app.services.ranking_profiles import AMBIENT, PLAYLIST, PROFILES, RADIO, WEIGHT_KEYS


class _Track:
    """Minimal stand-in — `_diverse_in_order` reads only artist and album."""

    def __init__(self, artist: str, album: str, title: str = "t"):
        self.id = uuid4()
        self.artist = artist
        self.album = album
        self.title = title


def _descriptor(**kwargs) -> AmbientDescriptor:
    base = dict(
        track_id=uuid4(), title=None, artist=None, album=None, duration_seconds=200.0,
        key="Am", bpm=120.0, energy=0.5, brightness=0.5, valence=0.5,
        instrumentalness=0.5, speechiness=0.1, dynamic_range_db=10.0,
        energy_shape=None, section_count=None, modal_character=None, acousticness=0.5,
    )
    base.update(kwargs)
    return AmbientDescriptor(**base)


class TestPlaylistProfile:
    """ADR-0048 point 4 — a playlist is judged as a set, not as a sequence of transitions."""

    def test_registered_and_valid(self):
        assert PROFILES["playlist"] is PLAYLIST
        # `_validate()` runs at import and would have raised; this pins the contract it enforces.
        assert set(PLAYLIST.weights) == set(WEIGHT_KEYS)
        assert round(sum(PLAYLIST.weights.values()) + PLAYLIST.taste_weight, 6) == 1.0

    def test_every_transition_term_is_off(self):
        # The three things that only mean something at the moment one track runs into the next.
        # Each is non-zero in RADIO, which is precisely why reusing RADIO would be wrong.
        assert PLAYLIST.bpm_penalty == 0.0 and RADIO.bpm_penalty > 0
        assert PLAYLIST.artist_cooldown_penalty == 0.0 and RADIO.artist_cooldown_penalty > 0
        assert PLAYLIST.weights["key"] == 0.0 and RADIO.weights["key"] > 0

    def test_it_is_not_radio_wearing_a_different_name(self):
        # A guard against the literal failure the ADR describes: someone "adding" the profile by
        # copying RADIO's numbers. If these ever become equal, this feature has silently become
        # radio-that-stops-after-20.
        assert PLAYLIST.weights != RADIO.weights
        assert PLAYLIST.weights != AMBIENT.weights

    def test_similarity_dominates(self):
        # "A playlist based on this album" is a similarity question almost to the exclusion of
        # everything else; the features exist to break ties.
        assert PLAYLIST.weights["embedding"] == max(PLAYLIST.weights.values())
        assert PLAYLIST.weights["embedding"] > RADIO.weights["embedding"]

    def test_taste_matters_more_than_in_radio(self):
        # Radio plays at you and should take risks; a playlist is asked for and kept.
        assert PLAYLIST.taste_weight > RADIO.taste_weight


class TestDiversityKeepsTheRanking:
    """The other half of the trap, found while building rather than in the ADR."""

    def test_best_of_each_artist_survives_not_a_random_one(self):
        # `ToolExecutor._apply_diversity` shuffles before capping, which is right where it is used
        # and would discard the scoring here. This is why generation does not reuse it.
        good = _Track("A", "a1", "best")
        worse = _Track("A", "a2", "worse")
        scored = [(good, 0.9), (worse, 0.5), (_Track("B", "b1"), 0.4)]

        kept = _diverse_in_order(scored, limit=10, max_per_artist=1, max_per_album=5)

        assert [t.title for t in kept if t.artist == "A"] == ["best"]

    def test_order_is_preserved(self):
        scored = [(_Track(f"artist{i}", f"al{i}"), 1.0 - i / 10) for i in range(5)]
        kept = _diverse_in_order(scored, limit=5, max_per_artist=2, max_per_album=2)
        assert [t.artist for t in kept] == [f"artist{i}" for i in range(5)]

    def test_artist_cap_is_enforced(self):
        scored = [(_Track("A", f"al{i}"), 0.9) for i in range(6)]
        kept = _diverse_in_order(scored, limit=10, max_per_artist=2, max_per_album=5)
        assert len(kept) == 2

    def test_album_cap_is_enforced_independently_of_artist(self):
        scored = [(_Track("A", "same"), 0.9) for _ in range(5)]
        kept = _diverse_in_order(scored, limit=10, max_per_artist=10, max_per_album=2)
        assert len(kept) == 2

    def test_limit_stops_early(self):
        scored = [(_Track(f"a{i}", f"al{i}"), 0.9) for i in range(50)]
        assert len(_diverse_in_order(scored, limit=7, max_per_artist=2, max_per_album=2)) == 7


class TestSeedCentroid:
    """Point 3 — a multi-track seed is a centroid, not a loop."""

    def test_mean_descriptor_averages_features(self):
        mean = _mean_descriptor([_descriptor(energy=0.2), _descriptor(energy=0.8)])
        assert mean is not None
        assert mean.energy == pytest.approx(0.5)

    def test_mean_descriptor_drops_key_rather_than_inventing_one(self):
        # There is no meaningful average of keys. PLAYLIST weights key at zero, so a guess would
        # only matter if the profile changed underneath — and then it would matter silently.
        mean = _mean_descriptor([_descriptor(key="Am"), _descriptor(key="C#m")])
        assert mean is not None and mean.key is None

    def test_mean_descriptor_ignores_missing_values(self):
        mean = _mean_descriptor([_descriptor(valence=None), _descriptor(valence=0.6)])
        assert mean is not None and mean.valence == pytest.approx(0.6)

    def test_mean_descriptor_of_all_missing_is_none_not_zero(self):
        # Zero is a valid feature value; absent is not the same thing, and averaging to 0.0 would
        # score every candidate against a seed that claims to be silent and joyless.
        mean = _mean_descriptor([_descriptor(energy=None), _descriptor(energy=None)])
        assert mean is not None and mean.energy is None

    def test_empty_seed_has_no_descriptor(self):
        assert _mean_descriptor([]) is None


class TestNaming:
    """Point 7 — deterministic, and says what the seed was. Never a timestamp."""

    def _seed(self, kind: str, label: str) -> ResolvedSeed:
        return ResolvedSeed(track_ids=[uuid4()], centroid=None, descriptor=None, label=label, kind=kind)

    def test_album_and_track_read_as_based_on(self):
        assert playlist_name(self._seed("album", "OK Computer")) == "Based on OK Computer"
        assert playlist_name(self._seed("track", "Paranoid Android")) == "Based on Paranoid Android"

    def test_artist_and_sets_read_as_like(self):
        assert playlist_name(self._seed("artist", "Cocteau Twins")) == "Like Cocteau Twins"
        assert playlist_name(self._seed("tracks", "A and B")) == "Like A and B"

    def test_it_is_deterministic(self):
        seed = self._seed("album", "Loveless")
        assert playlist_name(seed) == playlist_name(seed)

    def test_no_date_in_the_name(self):
        # `AI Playlist — Aug 09` was acceptable when a sentence described the intent somewhere the
        # listener could see it. A button leaves no such record.
        name = playlist_name(self._seed("album", "Souvlaki"))
        assert not any(month in name for month in ("Jan", "Feb", "Aug", "Dec"))


class TestSeedLabels:
    def _rows(self, pairs):
        return [(_Track(artist, album), None) for artist, album in pairs]

    def test_two_artists_are_joined_with_and(self):
        label = _seed_label("tracks", self._rows([("A", "x"), ("B", "y")]), artist=None, album=None)
        assert label == "A and B"

    def test_many_artists_are_summarised(self):
        rows = self._rows([("A", "x"), ("B", "y"), ("C", "z"), ("D", "w")])
        label = _seed_label("tracks", rows, artist=None, album=None)
        assert label.endswith("and 2 more")

    def test_album_prefers_the_requested_name(self):
        rows = self._rows([("Artist", "Stored Name")])
        assert _seed_label("album", rows, artist=None, album="Asked Name") == "Asked Name"


class TestCandidatePool:
    """`POOL_SIZE` is only real if `hnsw.ef_search` is raised to match it.

    pgvector caps an HNSW scan at `ef_search` — default **40** — whatever the `LIMIT` says. Measured
    on the 26k library, `ORDER BY embedding <=> … LIMIT 400` returned exactly 40 rows, so this
    module's pool had been a tenth of its documented size since ADR-0048 shipped. Nothing made it
    visible: the query is correct, the plan looks right, and a short pool reads as a small library.
    """

    def test_ef_search_is_at_least_the_pool_size(self):
        assert HNSW_EF_SEARCH >= POOL_SIZE, "ef_search below POOL_SIZE just moves the cap"

    def test_the_pool_query_sets_it(self):
        """Asserted on the source because the alternative is a 26k-row fixture.

        A unit-sized library cannot show the difference between a cap of 40 and a cap of 400 — which
        is exactly why this went unnoticed for so long.
        """
        import inspect

        from app.services import playlist_generation

        source = inspect.getsource(playlist_generation.generate_seeded_playlist)
        assert "hnsw.ef_search" in source
