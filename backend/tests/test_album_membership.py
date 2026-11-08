"""Moving tracks to the album they belong on, and back (ADR-0166).

The cases are from the live library on 2026-11-08: *TRST* was one folder on two albums, and
Portishead's and Soft Machine's *Third* were one album, fused by a compilation label.
"""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models import Album, AlbumAlias, ChangeSource, Track
from app.services.album_membership import move_tracks_to_album, undo_move
from app.services.album_resolver import album_alias_key
from app.services.auto_proposals import AlbumTrackRow, plan_album_moves
from app.services.compilations import VARIOUS_ARTISTS
from app.services.proposed_changes import MOVE_TO_ALBUM, ProposedChangesService
from tests.factories import insert_test_track

JPEG = b"\xff\xd8\xff\xe0" + b"cover" * 10


@pytest.fixture(autouse=True)
def art_dir(tmp_path, monkeypatch):
    from app.config import settings

    art = tmp_path / "art"
    art.mkdir()
    monkeypatch.setattr(settings, "art_path", art)
    return art


async def _album(db, name, *, artist_id=None, release_id=None, alias_key=None) -> Album:
    album = Album(
        name=name, sort_name=name, album_artist_id=artist_id, musicbrainz_release_id=release_id
    )
    db.add(album)
    await db.flush()
    if alias_key:
        db.add(AlbumAlias(alias_normalized=alias_key, alias=name, album_id=album.id, source="tag"))
        await db.flush()
    return album


async def _tracks(db, n, *, artist, album, album_artist, on: Album, folder: str) -> list[Track]:
    made = []
    for i in range(n):
        t = await insert_test_track(
            db,
            title=f"{artist} {i}",
            artist=artist,
            album=album,
            album_artist=album_artist,
            file_path=f"{folder}/{uuid4().hex[:8]}-{i}.mp3",
        )
        t.canonical_album_id = on.id
        made.append(t)
    await db.flush()
    return made


class TestMerge:
    async def _trst(self, db, art_dir: Path):
        self.va_key = f"va::trst-{uuid4().hex}"
        various = await _album(db, "TRST", alias_key=self.va_key)
        own = await _album(db, "TRST", alias_key=f"trst::{uuid4().hex}")
        labelled = await _tracks(
            db,
            3,
            artist="TR/ST",
            album="TRST",
            album_artist=VARIOUS_ARTISTS,
            on=various,
            folder="/music/TR_ST/TRST",
        )
        blank = await _tracks(
            db,
            1,
            artist="TR/ST",
            album="TRST",
            album_artist=None,
            on=own,
            folder="/music/TR_ST/TRST",
        )
        various.musicbrainz_release_id = self.release = str(uuid4())
        (art_dir / f"{various.id}.jpg").write_bytes(JPEG)
        await db.commit()
        return various, own, labelled, blank

    @pytest.mark.asyncio
    async def test_a_merge_leaves_one_album_with_the_cover_and_the_aliases(self, async_db, art_dir):
        db = async_db
        various, own, labelled, blank = await self._trst(db, art_dir)
        various_id = various.id

        record = await move_tracks_to_album(
            db,
            [t.id for t in labelled + blank],
            kind="merge",
            album_artist="TR/ST",
            album_id=own.id,
        )
        await db.commit()

        rows = (
            await db.execute(
                select(Track.canonical_album_id, Track.album_artist, Track.metadata_overrides)
            )
        ).all()
        assert {r.canonical_album_id for r in rows} == {own.id}
        assert {r.album_artist for r in rows} == {"TR/ST"}
        assert all(r.metadata_overrides["album_artist"] == "TR/ST" for r in rows)
        assert await db.get(Album, various_id) is None
        # The aliases moved, so a rescan of the files' own tags lands on the kept album.
        assert (await db.get(AlbumAlias, self.va_key)).album_id == own.id
        await db.refresh(own)
        assert own.musicbrainz_release_id == self.release
        assert (art_dir / f"{own.id}.jpg").read_bytes() == JPEG

        await undo_move(db, record)
        await db.commit()

        restored = await db.get(Album, various_id)
        assert restored is not None and restored.musicbrainz_release_id == self.release
        assert (await db.get(AlbumAlias, self.va_key)).album_id == various_id
        for t in labelled:
            await db.refresh(t)
            assert t.canonical_album_id == various_id
            assert t.album_artist == VARIOUS_ARTISTS
            assert "album_artist" not in (t.metadata_overrides or {}), "an undo is a retraction"
        await db.refresh(own)
        assert own.musicbrainz_release_id is None
        # The source's cover was copied, not moved, so it comes back with the album.
        assert (art_dir / f"{various_id}.jpg").exists()

    @pytest.mark.asyncio
    async def test_undo_restores_an_override_that_was_there_before(self, async_db, art_dir):
        db = async_db
        various, own, labelled, blank = await self._trst(db, art_dir)
        labelled[0].metadata_overrides = {"album_artist": "Somebody's choice"}
        await db.commit()

        record = await move_tracks_to_album(
            db, [labelled[0].id], kind="merge", album_artist="TR/ST", album_id=own.id
        )
        await undo_move(db, record)
        await db.commit()

        await db.refresh(labelled[0])
        assert labelled[0].metadata_overrides == {"album_artist": "Somebody's choice"}


class TestSplit:
    @pytest.mark.asyncio
    async def test_a_split_gives_each_record_its_own_album_and_undo_refuses_them(self, async_db):
        db = async_db
        va_key = f"va::third-{uuid4().hex}"
        fused = await _album(db, "Third", alias_key=va_key)
        portishead = await insert_test_track(
            db,
            title="seed",
            artist="Portishead",
            album="Third",
            file_path="/music/Portishead/Third/seed.mp3",
        )
        own = await _album(
            db,
            "Third",
            artist_id=portishead.canonical_artist_id,
            alias_key=album_alias_key(portishead.canonical_artist_id, "Third"),
        )
        portishead.canonical_album_id = own.id
        p = await _tracks(
            db,
            3,
            artist="Portishead",
            album="Third",
            album_artist=VARIOUS_ARTISTS,
            on=fused,
            folder="/music/Portishead/Third",
        )
        s = await _tracks(
            db,
            3,
            artist="The Soft Machine",
            album="Third",
            album_artist=VARIOUS_ARTISTS,
            on=fused,
            folder="/music/The Soft Machine/Third",
        )
        await db.commit()
        fused_id = fused.id

        # Portishead's tracks join the album Portishead already had.
        await move_tracks_to_album(
            db, [t.id for t in p], kind="split", album_artist="Portishead", title="Third"
        )
        await db.commit()
        for t in p:
            await db.refresh(t)
            assert t.canonical_album_id == own.id
        assert await db.get(Album, fused_id) is not None, "Soft Machine is still on it"

        # Soft Machine's get an album of their own, and the fused album goes, label and all.
        record = await move_tracks_to_album(
            db, [t.id for t in s], kind="split", album_artist="The Soft Machine", title="Third"
        )
        await db.commit()
        new_ids = set()
        for t in s:
            await db.refresh(t)
            new_ids.add(t.canonical_album_id)
        assert len(new_ids) == 1 and new_ids.isdisjoint({own.id, fused_id})
        assert record["target_created"] is True
        assert await db.get(Album, fused_id) is None
        assert await db.get(AlbumAlias, va_key) is None, (
            "a split's emptied album keys on the false label"
        )

        await undo_move(db, record)
        await db.commit()
        assert await db.get(Album, fused_id) is not None
        assert await db.get(Album, next(iter(new_ids))) is None, (
            "the album the split created is gone again"
        )
        for t in s:
            await db.refresh(t)
            assert t.canonical_album_id == fused_id


@pytest.mark.asyncio
async def test_a_move_applies_and_undoes_through_proposed_changes(async_db):
    db = async_db
    various = await _album(db, "Cro Magnox")
    own = await _album(db, "Cro Magnox")
    a = await _tracks(
        db,
        2,
        artist="Ceephax",
        album="Cro Magnox",
        album_artist=VARIOUS_ARTISTS,
        on=various,
        folder="/music/Ceephax/Cro Magnox",
    )
    await db.commit()

    service = ProposedChangesService(db)
    change = await service.create_change(
        change_type=MOVE_TO_ALBUM,
        target_type="album",
        target_ids=[str(t.id) for t in a],
        source=ChangeSource.AUTO_ENRICHMENT,
        field="album",
        new_value={
            "kind": "merge",
            "album_id": str(own.id),
            "album_artist": "Ceephax",
            "title": "Cro Magnox",
        },
        old_value=None,
        reason="test",
    )

    applied = await service.apply(change.id)
    assert applied.success, applied.error
    for t in a:
        await db.refresh(t)
        assert t.canonical_album_id == own.id

    undone = await service.undo(change.id)
    assert undone.success, undone.error
    for t in a:
        await db.refresh(t)
        assert t.canonical_album_id == various.id


@pytest.mark.asyncio
async def test_a_change_type_nothing_implements_is_refused_not_marked_applied(async_db):
    """Before this, any type but "metadata" was marked applied and did nothing."""
    db = async_db
    t = await insert_test_track(db)
    await db.commit()
    service = ProposedChangesService(db)
    change = await service.create_change(
        change_type="artwork",
        target_type="album",
        target_ids=[str(t.id)],
        source=ChangeSource.USER_REQUEST,
        new_value={"url": "x"},
        old_value=None,
    )

    result = await service.apply(change.id)

    assert not result.success
    assert (await service.get_by_id(change.id)).status.value == "pending"


# ── The planner ─────────────────────────────────────────────────────────────────


def rows(title, artist, folder, numbers, *, album_artist="", album_id="a", release=False):
    return [
        AlbumTrackRow(
            id=f"{album_id}:{artist}:{n}:{folder}",
            album=title,
            artist=artist,
            album_artist=album_artist,
            folder=folder,
            disc_number=None,
            track_number=n,
            album_id=album_id,
            album_has_release_id=release,
        )
        for n in numbers
    ]


class TestPlanner:
    def test_third_is_split_into_its_two_records(self):
        library = rows(
            "Third",
            "Portishead",
            "/m/Portishead/Third",
            range(1, 10),
            album_artist=VARIOUS_ARTISTS,
            album_id="fused",
        ) + rows(
            "Third",
            "The Soft Machine",
            "/m/Soft Machine/Third",
            range(1, 5),
            album_artist=VARIOUS_ARTISTS,
            album_id="fused",
        )

        splits, merges = plan_album_moves(library)

        assert sorted(p.album_artist for p in splits) == ["Portishead", "The Soft Machine"]
        assert all(p.album_id is None and p.kind == "split" for p in splits)
        assert "Soft Machine" in next(p.reason for p in splits if p.album_artist == "Portishead")
        assert merges == []

    def test_a_soundtrack_mostly_by_its_composer_is_not_split(self):
        """*Mistress America*: one artist holds most of a compilation, numbered as one record."""
        library = (
            rows(
                "Mistress America",
                "Dean Wareham",
                "/m/Dean Wareham/MA",
                [1, 3, 4, 6, 7, 8],
                album_artist=VARIOUS_ARTISTS,
            )
            + rows(
                "Mistress America", "Suicide", "/m/Suicide/MA", [2], album_artist=VARIOUS_ARTISTS
            )
            + rows(
                "Mistress America",
                "Hot Chocolate",
                "/m/Hot Chocolate/MA",
                [5],
                album_artist=VARIOUS_ARTISTS,
            )
        )

        splits, _ = plan_album_moves(library)

        assert splits == []

    def test_a_compilation_holding_one_artists_few_tracks_is_not_split(self):
        """sinkfield's three tracks on the seventeen-artist *One on Twoism Volume 2*."""
        library = rows(
            "Twoism 2", "sinkfield", "/m/sinkfield/T2", [1, 2, 3], album_artist=VARIOUS_ARTISTS
        )
        for i in range(8):
            library += rows(
                "Twoism 2", f"Artist {i}", f"/m/A{i}/T2", [i % 3 + 1], album_artist=VARIOUS_ARTISTS
            )

        splits, _ = plan_album_moves(library)

        assert splits == []

    def test_a_folder_split_by_a_stray_label_merges_under_its_artist(self):
        folder = "/m/Ceephax/Cro Magnox"
        library = rows(
            "Cro Magnox",
            "Ceephax",
            folder,
            range(1, 17),
            album_artist=VARIOUS_ARTISTS,
            album_id="va",
        ) + rows("Cro Magnox", "Ceephax", folder, [17], album_id="own", release=True)

        splits, merges = plan_album_moves(library)

        assert splits == []
        (merge,) = merges
        assert (
            merge.album_id == "va"
            and merge.album_artist == "Ceephax"
            and len(merge.track_ids) == 17
        )

    def test_a_compilation_folder_merges_under_various_artists(self):
        folder = "/m/Compilations/sii-comp07"
        library = (
            rows("sii-comp07", "A", folder, [1, 2], album_artist=VARIOUS_ARTISTS, album_id="va")
            + rows("sii-comp07", "B", folder, [3, 4], album_artist=VARIOUS_ARTISTS, album_id="va")
            + rows(
                "sii-comp07", "Marc Houle", folder, [5], album_artist="Marc Houle", album_id="mh"
            )
        )

        _, (merge,) = plan_album_moves(library)

        assert merge.album_artist == VARIOUS_ARTISTS and merge.album_id == "va"

    def test_a_folder_whose_other_album_reaches_elsewhere_is_left_alone(self):
        """Moving those tracks here would take them out of an album no single folder holds."""
        library = (
            rows(
                "Parts",
                "Plaid",
                "/m/Plaid/Parts",
                [1, 2, 3],
                album_artist=VARIOUS_ARTISTS,
                album_id="va",
            )
            + rows("Parts", "Plaid", "/m/Plaid/Parts", [4], album_artist="Plaid", album_id="spread")
            + rows(
                "Parts",
                "Goldfrapp",
                "/m/Goldfrapp/Parts",
                [5],
                album_artist="Plaid",
                album_id="spread",
            )
        )

        _, merges = plan_album_moves(library)

        assert merges == []
