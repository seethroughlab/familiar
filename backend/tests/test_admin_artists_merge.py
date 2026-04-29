"""Tests for the admin artist-merge endpoint.

Endpoint: POST /api/v1/admin/artists/merge
Behavior: atomic move-aliases / repoint-tracks / delete-artists, with
keep-side wins for alias collisions, FK-safe ordering, and 404 on
already-merged ids.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.routes.admin_artists import MergeArtistsRequest, merge_artists
from app.db.models import Artist, ArtistAlias, Track, TrackStatus
from app.services import artist_resolver as ar


def _new_track(*, file: str, artist_id) -> Track:
    return Track(
        id=uuid4(),
        file_path=f"/music/{file}.mp3",
        file_hash=f"hash-{file}",
        title=file,
        artist="placeholder",  # actual value irrelevant; canonical is by id
        canonical_artist_id=artist_id,
        status=TrackStatus.ACTIVE,
    )


async def _make_artist(db, name: str, *, mbid: str | None = None) -> Artist:
    artist = Artist(name=name, sort_name=name, musicbrainz_id=mbid)
    db.add(artist)
    await db.flush()
    return artist


@pytest.mark.asyncio
async def test_merge_moves_aliases_repoints_tracks_deletes_source(async_db):
    """Happy path: A is canonical, B is the duplicate to fold in."""
    a = await _make_artist(async_db, "The Beatles", mbid="mb-beatles")
    b = await _make_artist(async_db, "Beatles")
    async_db.add(ArtistAlias(alias_normalized="the beatles", alias="The Beatles", artist_id=a.id, source="tag"))
    async_db.add(ArtistAlias(alias_normalized="beatles", alias="Beatles", artist_id=b.id, source="tag"))

    async_db.add(_new_track(file="t1", artist_id=a.id))
    async_db.add(_new_track(file="t2", artist_id=b.id))
    async_db.add(_new_track(file="t3", artist_id=b.id))
    await async_db.commit()

    # Mock the profile dep — the endpoint uses it only as a single-user gate.
    profile = type("FakeProfile", (), {"id": uuid4()})()
    response = await merge_artists(
        db=async_db,
        profile=profile,  # type: ignore[arg-type]
        request=MergeArtistsRequest(keep_id=a.id, merge_ids=[b.id]),
    )

    assert response.kept_artist_id == str(a.id)
    assert response.aliases_moved == 1
    assert response.tracks_repointed == 2
    assert response.artists_deleted == 1

    # Source artist gone.
    assert (await async_db.get(Artist, b.id)) is None
    # All aliases now point to A.
    aliases = (await async_db.execute(select(ArtistAlias))).scalars().all()
    assert {a.alias_normalized for a in aliases} == {"the beatles", "beatles"}
    assert all(al.artist_id == a.id for al in aliases)
    # All tracks point to A.
    tracks = (await async_db.execute(select(Track))).scalars().all()
    assert {t.canonical_artist_id for t in tracks} == {a.id}


@pytest.mark.asyncio
async def test_merge_consolidates_multiple_aliases(async_db):
    """A holds two aliases, B holds one — all three end up on A."""
    a = await _make_artist(async_db, "The Beatles", mbid="mb-beatles")
    b = await _make_artist(async_db, "Beatles")
    async_db.add(ArtistAlias(alias_normalized="the beatles", alias="The Beatles", artist_id=a.id, source="tag"))
    async_db.add(ArtistAlias(alias_normalized="beatles, the", alias="Beatles, The", artist_id=a.id, source="tag"))
    async_db.add(ArtistAlias(alias_normalized="beatles", alias="Beatles", artist_id=b.id, source="tag"))
    await async_db.commit()

    profile = type("FakeProfile", (), {"id": uuid4()})()
    response = await merge_artists(
        db=async_db,
        profile=profile,  # type: ignore[arg-type]
        request=MergeArtistsRequest(keep_id=a.id, merge_ids=[b.id]),
    )

    assert response.aliases_moved == 1
    aliases = (await async_db.execute(select(ArtistAlias))).scalars().all()
    assert {al.alias_normalized for al in aliases} == {
        "beatles", "beatles, the", "the beatles",
    }
    assert all(al.artist_id == a.id for al in aliases)


@pytest.mark.asyncio
async def test_merge_404_when_keep_id_missing(async_db):
    profile = type("FakeProfile", (), {"id": uuid4()})()
    bogus = uuid4()
    other = await _make_artist(async_db, "Other")
    await async_db.commit()

    from app.api.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        await merge_artists(
            db=async_db,
            profile=profile,  # type: ignore[arg-type]
            request=MergeArtistsRequest(keep_id=bogus, merge_ids=[other.id]),
        )


@pytest.mark.asyncio
async def test_merge_404_when_merge_id_already_gone(async_db):
    """Idempotency: re-running with a now-deleted merge_id returns 404."""
    a = await _make_artist(async_db, "The Beatles", mbid="mb-beatles")
    bogus_merge_id = uuid4()
    await async_db.commit()

    profile = type("FakeProfile", (), {"id": uuid4()})()
    from app.api.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        await merge_artists(
            db=async_db,
            profile=profile,  # type: ignore[arg-type]
            request=MergeArtistsRequest(keep_id=a.id, merge_ids=[bogus_merge_id]),
        )


@pytest.mark.asyncio
async def test_merge_400_when_keep_id_in_merge_ids(async_db):
    a = await _make_artist(async_db, "The Beatles")
    await async_db.commit()

    profile = type("FakeProfile", (), {"id": uuid4()})()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await merge_artists(
            db=async_db,
            profile=profile,  # type: ignore[arg-type]
            request=MergeArtistsRequest(keep_id=a.id, merge_ids=[a.id]),
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_merge_repoints_canonical_album_artist_id(async_db):
    """Pass 3: merge endpoint repoints both canonical FK columns.

    A track tagged ``album_artist="Beatles"`` (canonical_album_artist_id
    pointing at the source artist) should land on the keep artist after
    a merge. Mirrors how canonical_artist_id is repointed.
    """
    a = await _make_artist(async_db, "The Beatles", mbid="mb-beatles")
    b = await _make_artist(async_db, "Beatles")
    async_db.add(ArtistAlias(alias_normalized="the beatles", alias="The Beatles", artist_id=a.id, source="tag"))
    async_db.add(ArtistAlias(alias_normalized="beatles", alias="Beatles", artist_id=b.id, source="tag"))

    # Track A: only canonical_artist_id points at the merge artist.
    async_db.add(_new_track(file="t1", artist_id=b.id))
    # Track B: only canonical_album_artist_id points at the merge artist.
    track_with_album_artist = Track(
        id=uuid4(),
        file_path="/music/t2.mp3",
        file_hash="hash-t2",
        title="Imagine",
        artist="John Lennon",  # different canonical
        album_artist="Beatles",
        canonical_artist_id=a.id,  # already points at keep
        canonical_album_artist_id=b.id,  # this is what should repoint
        status=TrackStatus.ACTIVE,
    )
    async_db.add(track_with_album_artist)
    await async_db.commit()

    profile = type("FakeProfile", (), {"id": uuid4()})()
    response = await merge_artists(
        db=async_db,
        profile=profile,  # type: ignore[arg-type]
        request=MergeArtistsRequest(keep_id=a.id, merge_ids=[b.id]),
    )

    assert response.tracks_repointed == 1  # t1
    assert response.tracks_album_artist_repointed == 1  # t2's album_artist FK

    # Both tracks now point only at A.
    tracks = (await async_db.execute(select(Track))).scalars().all()
    for t in tracks:
        if t.canonical_artist_id is not None:
            assert t.canonical_artist_id == a.id
        if t.canonical_album_artist_id is not None:
            assert t.canonical_album_artist_id == a.id


@pytest.mark.asyncio
async def test_resolver_then_merge_dedupes_play_counts(async_db):
    """End-to-end: resolver creates two artists for "Beatles" + "The
    Beatles" (no MB lookup), then a merge consolidates them and
    track counts roll up correctly."""
    art_a = await ar.resolve_canonical_artist(
        async_db, "The Beatles", do_mb_lookup=False
    )
    art_b = await ar.resolve_canonical_artist(
        async_db, "Beatles", do_mb_lookup=False
    )
    assert art_a.id != art_b.id

    async_db.add(_new_track(file="t1", artist_id=art_a.id))
    async_db.add(_new_track(file="t2", artist_id=art_a.id))
    async_db.add(_new_track(file="t3", artist_id=art_b.id))
    await async_db.commit()

    profile = type("FakeProfile", (), {"id": uuid4()})()
    response = await merge_artists(
        db=async_db,
        profile=profile,  # type: ignore[arg-type]
        request=MergeArtistsRequest(keep_id=art_a.id, merge_ids=[art_b.id]),
    )

    assert response.tracks_repointed == 1
    # All 3 tracks now point to art_a.
    tracks = (await async_db.execute(select(Track))).scalars().all()
    assert {t.canonical_artist_id for t in tracks} == {art_a.id}
