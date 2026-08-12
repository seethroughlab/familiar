"""Tests for the canonical album resolver (ADR-0052).

The cascade these cover, in order: a verified release id, an alias hit keyed on the
canonical *artist id*, a folder fallback for tracks with no album tag, and creation.

The one worth reading first is
``test_two_artists_with_the_same_album_title_stay_apart`` — "Greatest Hits" is the
reason the artist half of the key exists at all.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete

from app.db.models import Album, AlbumAlias, Artist
from app.services import album_resolver as ar


@pytest.fixture(autouse=True)
async def _cleanup_albums(async_db):
    await async_db.execute(delete(AlbumAlias))
    await async_db.execute(delete(Album))
    await async_db.commit()
    yield
    await async_db.execute(delete(AlbumAlias))
    await async_db.execute(delete(Album))
    await async_db.commit()


async def _artist(async_db, name: str) -> Artist:
    artist = Artist(name=name, sort_name=name)
    async_db.add(artist)
    await async_db.flush()
    return artist


class TestCreatingAndReusing:
    @pytest.mark.asyncio
    async def test_creates_an_album_and_registers_its_alias(self, async_db):
        artist = await _artist(async_db, "Rachel's")
        album = await ar.resolve_canonical_album(
            async_db, "Selenography", album_artist_id=artist.id
        )
        await async_db.commit()

        assert album is not None
        assert album.name == "Selenography"
        assert album.album_artist_id == artist.id

        alias = await async_db.get(AlbumAlias, ar.album_alias_key(artist.id, "Selenography"))
        assert alias is not None
        assert alias.album_id == album.id
        assert alias.source == "tag"

    @pytest.mark.asyncio
    async def test_the_same_tag_resolves_to_the_same_row(self, async_db):
        artist = await _artist(async_db, "Rachel's")
        first = await ar.resolve_canonical_album(async_db, "Selenography", album_artist_id=artist.id)
        second = await ar.resolve_canonical_album(async_db, "Selenography", album_artist_id=artist.id)
        await async_db.commit()
        assert first.id == second.id

    @pytest.mark.asyncio
    async def test_spelling_variants_collapse(self, async_db):
        """Case, diacritics and — since the normaliser was fixed — curly quotes."""
        artist = await _artist(async_db, "A")
        a = await ar.resolve_canonical_album(async_db, "Don’t Stop", album_artist_id=artist.id)
        b = await ar.resolve_canonical_album(async_db, "don't stop", album_artist_id=artist.id)
        await async_db.commit()
        assert a.id == b.id

    @pytest.mark.asyncio
    async def test_two_artists_with_the_same_album_title_stay_apart(self, async_db):
        """The reason the key holds an artist id and not just a title.

        Two artists both have a "Greatest Hits"; they are not the same record and must
        not share a cover.
        """
        one = await _artist(async_db, "Artist One")
        two = await _artist(async_db, "Artist Two")
        a = await ar.resolve_canonical_album(async_db, "Greatest Hits", album_artist_id=one.id)
        b = await ar.resolve_canonical_album(async_db, "Greatest Hits", album_artist_id=two.id)
        await async_db.commit()
        assert a.id != b.id

    @pytest.mark.asyncio
    async def test_sort_name_moves_a_leading_article(self, async_db):
        artist = await _artist(async_db, "Pink Floyd")
        album = await ar.resolve_canonical_album(async_db, "The Wall", album_artist_id=artist.id)
        await async_db.commit()
        assert album.sort_name == "Wall, The"


class TestTheFolderFallback:
    @pytest.mark.asyncio
    async def test_an_untagged_track_groups_by_its_directory(self, async_db):
        album = await ar.resolve_canonical_album(
            async_db, None, file_path="/music/Unsorted/Live Set/01.mp3"
        )
        await async_db.commit()
        assert album is not None
        assert album.name == "Live Set"

        alias = await async_db.get(AlbumAlias, ar.folder_alias_key("/music/Unsorted/Live Set"))
        assert alias is not None
        assert alias.source == "folder"

    @pytest.mark.asyncio
    async def test_two_untagged_tracks_in_one_directory_share_an_album(self, async_db):
        a = await ar.resolve_canonical_album(async_db, None, file_path="/music/Live/01.mp3")
        b = await ar.resolve_canonical_album(async_db, "", file_path="/music/Live/02.mp3")
        await async_db.commit()
        assert a.id == b.id

    @pytest.mark.asyncio
    async def test_different_directories_do_not_share(self, async_db):
        """What the single `unknown::unknown` bucket used to get wrong — one dropped
        cover reaching 61 unrelated tracks."""
        a = await ar.resolve_canonical_album(async_db, None, file_path="/music/One/01.mp3")
        b = await ar.resolve_canonical_album(async_db, None, file_path="/music/Two/01.mp3")
        await async_db.commit()
        assert a.id != b.id

    @pytest.mark.asyncio
    async def test_nothing_to_go_on_returns_none(self, async_db):
        assert await ar.resolve_canonical_album(async_db, None) is None
        assert await ar.resolve_canonical_album(async_db, "   ") is None


class TestTheReleaseId:
    @pytest.mark.asyncio
    async def test_a_matching_release_id_reuses_the_album(self, async_db):
        artist = await _artist(async_db, "A")
        first = await ar.resolve_canonical_album(
            async_db, "Kid A", album_artist_id=artist.id, musicbrainz_release_id="mbid-1"
        )
        await async_db.commit()

        # A different artist id and spelling, but the same release.
        second = await ar.resolve_canonical_album(
            async_db, "kid a", album_artist_id=None, musicbrainz_release_id="mbid-1"
        )
        await async_db.commit()
        assert second.id == first.id

    @pytest.mark.asyncio
    async def test_a_release_id_that_disagrees_with_the_title_is_not_trusted(self, async_db):
        """The guard the artist resolver has because a track carried somebody else's
        MBID. Release ids are no better curated, and folding two records together on a
        bad one is worse than missing the match."""
        artist = await _artist(async_db, "A")
        kid_a = await ar.resolve_canonical_album(
            async_db, "Kid A", album_artist_id=artist.id, musicbrainz_release_id="mbid-1"
        )
        await async_db.commit()

        other = await ar.resolve_canonical_album(
            async_db, "Amnesiac", album_artist_id=artist.id, musicbrainz_release_id="mbid-1"
        )
        await async_db.commit()
        assert other.id != kid_a.id


class TestSideEffects:
    @pytest.mark.asyncio
    async def test_create_if_missing_false_writes_nothing(self, async_db):
        artist = await _artist(async_db, "A")
        album = await ar.resolve_canonical_album(
            async_db, "Nothing Here", album_artist_id=artist.id, create_if_missing=False
        )
        assert album is None

    @pytest.mark.asyncio
    async def test_resolving_twice_registers_one_alias(self, async_db):
        """`ON CONFLICT DO NOTHING` — two scan sessions racing on one key must not raise
        and poison the transaction."""
        artist = await _artist(async_db, "A")
        await ar.resolve_canonical_album(async_db, "Twice", album_artist_id=artist.id)
        await ar.resolve_canonical_album(async_db, "Twice", album_artist_id=artist.id)
        await async_db.commit()

        from sqlalchemy import func, select

        count = (await async_db.execute(select(func.count()).select_from(AlbumAlias))).scalar()
        assert count == 1
