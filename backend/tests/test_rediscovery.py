"""Owned, unheard, ranked against real listening (ADR-0101).

The largest discovery opportunity in the product: 23,683 of 26,434 tracks on the
production library have never been played, and a streaming service cannot compete
on a collection it cannot see.
"""

from datetime import timedelta

import pytest

from app.services.rediscovery import HEARD_THRESHOLD, suggest_rediscovery
from app.utils.time import utcnow
from tests.factories import (
    insert_test_analysis,
    insert_test_play_history,
    insert_test_profile,
    insert_test_track,
)


async def _track_with_embedding(async_db, *, title, artist, embedding):
    """A track carrying an embedding, which is what the ranker needs to see it."""
    track = await insert_test_track(async_db, title=title, artist=artist, album=artist)
    # `energy` as well as the embedding: the vote query requires it, because a
    # candidate with no features cannot be scored. A track analysed for embeddings but
    # not features is invisible to rediscovery — see the note in `suggest_rediscovery`.
    await insert_test_analysis(
        async_db, track.id, {"embedding": embedding, "energy": 0.5}
    )
    return track


def _vec(lead: float) -> list[float]:
    """A 512-dim vector whose first component dominates, so similarity is controllable."""
    return [lead] + [0.0] * 511


@pytest.mark.asyncio
async def test_no_listening_history_returns_nothing_and_says_so(async_db):
    """An empty result must be able to explain itself (ADR-0101 point 7).

    Zero seeds and "nothing similar found" are different answers, and a surface that
    renders both as an empty list is the defect this ADR is about.
    """
    profile = await insert_test_profile(async_db)
    await insert_test_track(async_db, artist="Unplayed", album="A")
    await async_db.commit()

    suggestions, seed_count = await suggest_rediscovery(async_db, profile_id=profile.id)

    assert suggestions == []
    assert seed_count == 0


@pytest.mark.asyncio
async def test_an_unheard_track_by_an_artist_never_played_can_surface(async_db):
    """The limit that made the old list useless, removed.

    `unheard_tracks` filtered candidates to `Track.canonical_artist_id.in_(top_artists)`,
    so a record that sounds exactly like a favourite was unreachable if its artist had
    never been played. The candidate pool is now the whole library.
    """
    profile = await insert_test_profile(async_db)
    seed = await _track_with_embedding(
        async_db, title="Played", artist="Known Artist", embedding=_vec(1.0)
    )
    await _track_with_embedding(
        async_db, title="Sounds Alike", artist="Never Played Artist", embedding=_vec(0.99)
    )
    await insert_test_play_history(
        async_db, profile.id, seed.id, play_count=10, last_played_at=utcnow()
    )
    await async_db.commit()

    suggestions, seed_count = await suggest_rediscovery(async_db, profile_id=profile.id)

    assert seed_count == 1
    names = {s.track.artist for s in suggestions}
    assert "Never Played Artist" in names, (
        "the candidate pool must not be limited to artists already played"
    )


@pytest.mark.asyncio
async def test_every_suggestion_carries_a_real_played_track_as_its_reason(async_db):
    """ADR-0101 point 3, inherited from ADR-0093.

    Three attempts at naming a cluster failed; "because you play X" is true and
    checkable where a generated label is neither.
    """
    profile = await insert_test_profile(async_db)
    seed = await _track_with_embedding(
        async_db, title="The Seed", artist="Seed Artist", embedding=_vec(1.0)
    )
    await _track_with_embedding(
        async_db, title="Candidate", artist="Other", embedding=_vec(0.98)
    )
    await insert_test_play_history(
        async_db, profile.id, seed.id, play_count=5, last_played_at=utcnow()
    )
    await async_db.commit()

    suggestions, _ = await suggest_rediscovery(async_db, profile_id=profile.id)

    assert suggestions
    for s in suggestions:
        assert s.because_of is not None
        assert s.because_of.id == seed.id
        assert s.similarity > 0


@pytest.mark.asyncio
async def test_a_track_in_rotation_is_not_suggested_back(async_db):
    """Suggesting something played every week is the failure mode of a bad ranker."""
    profile = await insert_test_profile(async_db)
    seed = await _track_with_embedding(
        async_db, title="Seed", artist="A", embedding=_vec(1.0)
    )
    in_rotation = await _track_with_embedding(
        async_db, title="In Rotation", artist="B", embedding=_vec(0.99)
    )
    await insert_test_play_history(
        async_db, profile.id, seed.id, play_count=20, last_played_at=utcnow()
    )
    await insert_test_play_history(
        async_db,
        profile.id,
        in_rotation.id,
        play_count=HEARD_THRESHOLD + 5,
        last_played_at=utcnow(),
    )
    await async_db.commit()

    suggestions, _ = await suggest_rediscovery(async_db, profile_id=profile.id)

    assert in_rotation.id not in {s.track.id for s in suggestions}


@pytest.mark.asyncio
async def test_a_track_played_once_long_ago_can_still_come_back(async_db):
    """The case the old `deep_cuts` list existed for, kept.

    This section replaces that list rather than joining it, so excluding everything
    with any play history at all would have silently dropped what it covered.
    """
    profile = await insert_test_profile(async_db)
    seed = await _track_with_embedding(
        async_db, title="Seed", artist="A", embedding=_vec(1.0)
    )
    forgotten = await _track_with_embedding(
        async_db, title="Forgotten", artist="B", embedding=_vec(0.99)
    )
    await insert_test_play_history(
        async_db, profile.id, seed.id, play_count=20, last_played_at=utcnow()
    )
    await insert_test_play_history(
        async_db,
        profile.id,
        forgotten.id,
        play_count=1,
        last_played_at=utcnow() - timedelta(days=900),
    )
    await async_db.commit()

    suggestions, _ = await suggest_rediscovery(async_db, profile_id=profile.id)

    assert forgotten.id in {s.track.id for s in suggestions}, (
        "a track sampled once years ago is exactly what rediscovery is for"
    )


@pytest.mark.asyncio
async def test_a_second_file_of_a_played_track_is_not_suggested(async_db):
    """"Listen to this thing you already play" is worse than no suggestion.

    `exclude_track_ids` works on ids, so a library holding the same recording twice
    has one copy excluded and the other free to come back — with similarity 1.0 and
    its own seed as the reason. Four of ten suggestions did exactly this on the live
    library the day rediscovery shipped.
    """
    profile = await insert_test_profile(async_db)
    played = await _track_with_embedding(
        async_db, title="Anywhere", artist="Interpol", embedding=_vec(1.0)
    )
    # A second file of the same recording: different row, identical metadata.
    await _track_with_embedding(
        async_db, title="Anywhere", artist="Interpol", embedding=_vec(1.0)
    )
    await _track_with_embedding(
        async_db, title="Genuinely New", artist="Someone Else", embedding=_vec(0.97)
    )
    await insert_test_play_history(
        async_db, profile.id, played.id, play_count=10, last_played_at=utcnow()
    )
    await async_db.commit()

    suggestions, _ = await suggest_rediscovery(async_db, profile_id=profile.id)

    titles = {s.track.title for s in suggestions}
    assert "Anywhere" not in titles, "a duplicate file of a played track is not a discovery"
    assert "Genuinely New" in titles, "and the real suggestion still comes through"
