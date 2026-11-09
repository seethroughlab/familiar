"""ADR-0173 point 4: the playlist and favourite operations, tested once at the operation level.

The routes (`test_api_playlists.py`) and the tools (`test_llm_library_tools.py`) are adapters, and
their tests cover what each adapter adds: status codes and serialisation, or summaries and messages
a model can act on.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.db.models import Playlist, PlaylistTrack, Profile, ProfileFavorite, Track
from app.operations import favorites, playlists
from app.operations.errors import PlaylistNotFound, TrackNotFound


def _track() -> Track:
    return Track(id=uuid4(), file_path=f"/music/{uuid4()}.mp3", file_hash=uuid4().hex, title="t")


_created_profiles: list = []


@pytest.fixture(autouse=True)
async def _remove_profiles(async_db):
    """`async_db` cleans playlists and tracks but not profiles or favourites, which other tests
    count; these tests delete what they made."""
    from sqlalchemy import delete

    yield
    if _created_profiles:
        ids = [p.id for p in _created_profiles]
        await async_db.execute(delete(ProfileFavorite).where(ProfileFavorite.profile_id.in_(ids)))
        await async_db.execute(delete(Playlist).where(Playlist.profile_id.in_(ids)))
        await async_db.execute(delete(Profile).where(Profile.id.in_(ids)))
        await async_db.commit()
        _created_profiles.clear()


async def _setup(db, n_tracks: int = 3):
    me, other = Profile(id=uuid4(), name="me"), Profile(id=uuid4(), name="other")
    _created_profiles.extend([me, other])
    tracks = [_track() for _ in range(n_tracks)]
    db.add_all([me, other, *tracks])
    await db.flush()
    return me, other, tracks


async def _playlist(db, profile, tracks=(), **kw) -> Playlist:
    playlist = Playlist(id=uuid4(), profile_id=profile.id, name=kw.pop("name", "p"), **kw)
    db.add(playlist)
    await db.flush()
    for position, track in enumerate(tracks):
        db.add(PlaylistTrack(playlist_id=playlist.id, track_id=track.id, position=position))
    await db.commit()
    return playlist


# ── Playlists ───────────────────────────────────────────────────────────────────────────────────


async def test_list_counts_tracks_and_can_leave_out_generated_ones(async_db):
    me, other, tracks = await _setup(async_db)
    mine = await _playlist(async_db, me, tracks[:2], name="mine")
    generated = await _playlist(async_db, me, name="generated", is_auto_generated=True)
    await _playlist(async_db, other, tracks, name="not mine")

    every = await playlists.list_playlists(async_db, me.id)
    assert {(s.playlist.id, s.track_count) for s in every} == {(mine.id, 2), (generated.id, 0)}
    handmade = await playlists.list_playlists(async_db, me.id, include_auto=False)
    assert [s.playlist.id for s in handmade] == [mine.id]


async def test_another_profiles_playlist_is_not_found(async_db):
    me, other, _ = await _setup(async_db)
    theirs = await _playlist(async_db, other)
    with pytest.raises(PlaylistNotFound):
        await playlists.get_playlist(async_db, me.id, theirs.id)
    with pytest.raises(PlaylistNotFound):
        await playlists.add_tracks(async_db, me.id, theirs.id, [])
    with pytest.raises(PlaylistNotFound):
        await playlists.get_playlist(async_db, me.id, uuid4())


async def test_get_returns_tracks_in_order(async_db):
    me, _, tracks = await _setup(async_db)
    playlist = await _playlist(async_db, me, list(reversed(tracks)))
    detail = await playlists.get_playlist(async_db, me.id, playlist.id)
    assert [e.track.id for e in detail.entries] == [t.id for t in reversed(tracks)]


async def test_add_skips_malformed_unknown_and_present_ids(async_db):
    me, _, tracks = await _setup(async_db)
    playlist = await _playlist(async_db, me, tracks[:1])
    result = await playlists.add_tracks(
        async_db, me.id, playlist.id,
        ["not-a-uuid", str(uuid4()), str(tracks[0].id), str(tracks[1].id)],
    )
    assert (result.requested, result.added) == (4, 1)
    detail = await playlists.get_playlist(async_db, me.id, playlist.id)
    assert [e.track.id for e in detail.entries] == [tracks[0].id, tracks[1].id]


async def test_adding_to_a_one_track_playlist_goes_after_it(async_db):
    """The route computed `max(position) or -1`, so a playlist whose last position was 0 looked
    empty and the new track also got position 0, tied with the first."""
    me, _, tracks = await _setup(async_db)
    playlist = await _playlist(async_db, me, tracks[:1])
    await playlists.add_tracks(async_db, me.id, playlist.id, [str(tracks[1].id)])
    detail = await playlists.get_playlist(async_db, me.id, playlist.id)
    assert [e.item.position for e in detail.entries] == [0, 1]


async def test_a_repeated_id_in_one_request_is_added_once(async_db):
    me, _, tracks = await _setup(async_db)
    playlist = await _playlist(async_db, me)
    result = await playlists.add_tracks(
        async_db, me.id, playlist.id, [str(tracks[0].id), str(tracks[0].id)]
    )
    assert result.added == 1
    detail = await playlists.get_playlist(async_db, me.id, playlist.id)
    assert len(detail.entries) == 1


# ── Favourites ──────────────────────────────────────────────────────────────────────────────────


async def _is_favorite(db, profile, track) -> bool:
    from sqlalchemy import select

    rows = await db.execute(
        select(ProfileFavorite).where(
            ProfileFavorite.profile_id == profile.id, ProfileFavorite.track_id == track.id
        )
    )
    return rows.scalar_one_or_none() is not None


async def test_favourites_are_set_not_toggled(async_db):
    """Idempotent both ways: a retried call must not undo the first."""
    me, _, tracks = await _setup(async_db)
    await favorites.add(async_db, me.id, tracks[0].id)
    await favorites.add(async_db, me.id, tracks[0].id)
    assert await _is_favorite(async_db, me, tracks[0])
    await favorites.remove(async_db, me.id, tracks[0].id)
    await favorites.remove(async_db, me.id, tracks[0].id)
    assert not await _is_favorite(async_db, me, tracks[0])


async def test_favouriting_an_unknown_track_is_not_found(async_db):
    me, _, _ = await _setup(async_db)
    with pytest.raises(TrackNotFound):
        await favorites.add(async_db, me.id, uuid4())
