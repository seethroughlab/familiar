"""The album backfill populates canonical_album_id for an existing library (ADR-0052).

The properties that matter: every track ends up pointing somewhere, tracks that belong
together share a row, album-less tracks group by folder rather than into one bucket, and
running it twice changes nothing.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, func, select

from app.cli.backfill_albums import (
    _distinct_albumless_folders,
    _distinct_titled_albums,
    _point_albumless_tracks,
    _point_titled_tracks,
)
from app.db.models import Album, AlbumAlias, Track
from app.services.album_resolver import resolve_canonical_album
from tests.factories import insert_test_track


@pytest.fixture(autouse=True)
async def _cleanup_albums(async_db):
    await async_db.execute(delete(AlbumAlias))
    await async_db.execute(delete(Album))
    await async_db.commit()
    yield
    await async_db.execute(delete(AlbumAlias))
    await async_db.execute(delete(Album))
    await async_db.commit()


async def _backfill(async_db) -> None:
    """The CLI's two passes, against the test session."""
    for artist_id, title in await _distinct_titled_albums(async_db):
        album = await resolve_canonical_album(async_db, title, album_artist_id=artist_id)
        if album:
            await _point_titled_tracks(async_db, artist_id, title, album.id)

    for sample in await _distinct_albumless_folders(async_db):
        album = await resolve_canonical_album(async_db, None, file_path=sample)
        if album:
            await _point_albumless_tracks(async_db, sample.rsplit("/", 1)[0], album.id)
    await async_db.commit()


class TestPointingTracks:
    @pytest.mark.asyncio
    async def test_tracks_of_one_album_share_a_row(self, async_db):
        for n in (1, 2):
            await insert_test_track(
                async_db, title=f"T{n}", artist="Rachel's", album="Selenography",
                file_path=f"/music/rachels/{n}.mp3",
            )
        await async_db.commit()
        await _backfill(async_db)

        ids = (
            await async_db.execute(
                select(Track.canonical_album_id).where(Track.album == "Selenography")
            )
        ).scalars().all()
        assert len(ids) == 2
        assert all(i is not None for i in ids)
        assert len(set(ids)) == 1

    @pytest.mark.asyncio
    async def test_a_compilation_is_one_album_despite_differing_artists(self, async_db):
        """The defect that started ADR-0052: keyed on `track.artist`, this was one
        artwork slot per track artist."""
        for n, artist in enumerate(("Artist A", "Artist B", "Artist C"), start=1):
            await insert_test_track(
                async_db, title=f"T{n}", artist=artist, album="A Compilation",
                album_artist="Various Artists", file_path=f"/music/comp/{n}.mp3",
            )
        await async_db.commit()
        await _backfill(async_db)

        ids = (
            await async_db.execute(
                select(Track.canonical_album_id).where(Track.album == "A Compilation")
            )
        ).scalars().all()
        assert len(ids) == 3
        assert len(set(ids)) == 1, "a compilation must be one album, not one per artist"

    @pytest.mark.asyncio
    async def test_two_artists_with_the_same_title_stay_apart(self, async_db):
        await insert_test_track(
            async_db, artist="One", album="Greatest Hits", file_path="/music/one/1.mp3"
        )
        await insert_test_track(
            async_db, artist="Two", album="Greatest Hits", file_path="/music/two/1.mp3"
        )
        await async_db.commit()
        await _backfill(async_db)

        ids = (
            await async_db.execute(
                select(Track.canonical_album_id).where(Track.album == "Greatest Hits")
            )
        ).scalars().all()
        assert len(set(ids)) == 2


class TestAlbumlessTracks:
    @pytest.mark.asyncio
    async def test_they_group_by_folder(self, async_db):
        for n in (1, 2):
            await insert_test_track(
                async_db, title=f"L{n}", artist="", album="",
                file_path=f"/music/Unsorted/Live/{n}.mp3",
            )
        await insert_test_track(
            async_db, title="Other", artist="", album="",
            file_path="/music/Unsorted/Elsewhere/1.mp3",
        )
        await async_db.commit()
        await _backfill(async_db)

        rows = (
            await async_db.execute(
                select(Track.file_path, Track.canonical_album_id).where(Track.album == "")
            )
        ).all()
        by_path = {p: a for p, a in rows}
        assert all(a is not None for a in by_path.values()), "none may be left unplaced"
        assert by_path["/music/Unsorted/Live/1.mp3"] == by_path["/music/Unsorted/Live/2.mp3"]
        assert by_path["/music/Unsorted/Live/1.mp3"] != by_path["/music/Unsorted/Elsewhere/1.mp3"]


class TestIdempotence:
    @pytest.mark.asyncio
    async def test_a_second_run_changes_nothing(self, async_db):
        await insert_test_track(
            async_db, artist="Rachel's", album="Selenography", file_path="/music/r/1.mp3"
        )
        await async_db.commit()

        await _backfill(async_db)
        first = (await async_db.execute(select(Track.canonical_album_id))).scalars().all()
        albums_after_first = (
            await async_db.execute(select(func.count()).select_from(Album))
        ).scalar()

        await _backfill(async_db)
        second = (await async_db.execute(select(Track.canonical_album_id))).scalars().all()
        albums_after_second = (
            await async_db.execute(select(func.count()).select_from(Album))
        ).scalar()

        assert first == second
        assert albums_after_first == albums_after_second

    @pytest.mark.asyncio
    async def test_an_already_pointed_track_is_not_repointed(self, async_db):
        """The `IS NULL` guard. Without it the backfill would undo a future merge."""
        track = await insert_test_track(
            async_db, artist="A", album="B", file_path="/music/a/1.mp3"
        )
        other = Album(name="Somewhere Else", sort_name="Somewhere Else")
        async_db.add(other)
        await async_db.flush()
        track.canonical_album_id = other.id
        await async_db.commit()

        await _backfill(async_db)
        await async_db.refresh(track)
        assert track.canonical_album_id == other.id
