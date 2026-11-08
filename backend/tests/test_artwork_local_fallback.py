"""A track's cover, from the library's own files, when its file carries none (2026-11-07).

The server keys artwork by album and used to look only inside the one file a client asked
about. TR/ST's *TRST*: track 2 embeds the cover, track 4 does not, and the phone showed a cover
for one and not the other. On the measured library 58 of 719 coverless albums had a cover in
another of their files or folder, and the other 661 were never looked up online, because only
the web app's album cards ever queued that.
"""

from pathlib import Path

import pytest

from app.services import artwork
from app.services.artwork import MAX_LOCAL_FILES, find_local_artwork
from tests.factories import insert_test_track

JPEG = b"\xff\xd8\xff\xe0" + b"cover" * 10


def fake_extract(pictures: dict[Path, bytes], opened: list[Path]):
    def extract(path: Path) -> bytes | None:
        opened.append(path)
        return pictures.get(path)

    return extract


@pytest.fixture
def album_dir(tmp_path: Path) -> Path:
    d = tmp_path / "TR_ST" / "TRST"
    d.mkdir(parents=True)
    for name in ("01 Shoom.mp3", "02 Dressed for Space.mp3", "04 The Last Dregs.mp3"):
        (d / name).write_bytes(b"not really audio")
    return d


class TestFindLocalArtwork:
    def test_the_requested_file_first(self, album_dir, monkeypatch):
        own = album_dir / "04 The Last Dregs.mp3"
        opened: list[Path] = []
        monkeypatch.setattr(artwork, "extract_artwork", fake_extract({own: b"own"}, opened))
        assert find_local_artwork(own, [album_dir / "02 Dressed for Space.mp3"]) == b"own"
        assert opened == [own]

    def test_another_track_on_the_album(self, album_dir, monkeypatch):
        own, other = album_dir / "04 The Last Dregs.mp3", album_dir / "02 Dressed for Space.mp3"
        monkeypatch.setattr(artwork, "extract_artwork", fake_extract({other: JPEG}, []))
        assert find_local_artwork(own, [other]) == JPEG

    def test_an_unrelated_file_in_the_folder_lends_nothing(self, album_dir, monkeypatch):
        """*How to Take a Fall*: untagged, in a folder of seven unrelated songs, it took a
        stranger's photo. Only files the caller names as the same album may lend one."""
        own, other = album_dir / "04 The Last Dregs.mp3", album_dir / "02 Dressed for Space.mp3"
        monkeypatch.setattr(artwork, "extract_artwork", fake_extract({other: JPEG}, []))
        assert find_local_artwork(own, []) is None

    def test_a_cover_image_beside_the_files(self, album_dir, monkeypatch):
        monkeypatch.setattr(artwork, "extract_artwork", fake_extract({}, []))
        (album_dir / "Folder.JPG").write_bytes(JPEG)
        assert find_local_artwork(album_dir / "01 Shoom.mp3") == JPEG

    def test_nothing_anywhere(self, album_dir, monkeypatch):
        monkeypatch.setattr(artwork, "extract_artwork", fake_extract({}, []))
        (album_dir / "booklet-page-3.jpg").write_bytes(JPEG)  # not named like a cover
        assert find_local_artwork(album_dir / "01 Shoom.mp3") is None

    def test_opens_at_most_the_cap(self, tmp_path, monkeypatch):
        for i in range(MAX_LOCAL_FILES + 20):
            (tmp_path / f"{i:03d}.flac").write_bytes(b"x")
        opened: list[Path] = []
        monkeypatch.setattr(artwork, "extract_artwork", fake_extract({}, opened))
        album = [tmp_path / f"{i:03d}.flac" for i in range(MAX_LOCAL_FILES + 20)]
        assert find_local_artwork(tmp_path / "000.flac", album) is None
        assert len(opened) == MAX_LOCAL_FILES

    def test_a_missing_folder_is_a_miss(self, tmp_path, monkeypatch):
        monkeypatch.setattr(artwork, "extract_artwork", fake_extract({}, []))
        assert find_local_artwork(tmp_path / "gone" / "a.mp3") is None


class TestTheRoute:
    @pytest.fixture(autouse=True)
    def art_dir(self, tmp_path, monkeypatch):
        from app.config import settings

        art = tmp_path / "art"
        monkeypatch.setattr(settings, "art_path", art)
        return art

    @pytest.fixture
    def saved(self, monkeypatch):
        """`save_artwork` without PIL: the bytes are not a real image."""
        from app.config import settings

        def save(image: bytes, album_key: str, sizes=None):
            settings.art_path.mkdir(parents=True, exist_ok=True)
            path = settings.art_path / f"{album_key}.jpg"
            path.write_bytes(image)
            return {"full": path}

        monkeypatch.setattr(artwork, "save_artwork", save)

    @pytest.fixture
    def queued(self, monkeypatch):
        calls: list[dict] = []

        class Manager:
            async def queue_artwork_fetch(self, **kwargs):
                calls.append(kwargs)
                return True

        monkeypatch.setattr("app.services.background.manager.get_background_manager", lambda: Manager())
        return calls

    async def _album_of_two(self, db, album_dir: Path):
        from app.db.models.albums import Album

        album = Album(name="TRST", sort_name="TRST")
        db.add(album)
        await db.flush()
        tracks = []
        for name in ("04 The Last Dregs.mp3", "02 Dressed for Space.mp3"):
            t = await insert_test_track(db, title=name, artist="TR/ST", album="TRST", file_path=str(album_dir / name))
            t.canonical_album_id = album.id
            tracks.append(t)
        await db.commit()
        return album, tracks

    @pytest.mark.asyncio
    async def test_a_track_without_a_picture_gets_its_albums_cover(
        self, async_db, client, album_dir, monkeypatch, saved, queued
    ):
        album, (bare, covered) = await self._album_of_two(async_db, album_dir)
        monkeypatch.setattr(artwork, "extract_artwork", fake_extract({Path(covered.file_path): JPEG}, []))

        resp = client.get(f"/api/v1/tracks/{bare.id}/artwork")
        assert resp.status_code == 200
        assert resp.content == JPEG
        assert queued == []

    @pytest.mark.asyncio
    async def test_a_miss_is_looked_up_online_once_and_not_reread_for_a_day(
        self, async_db, client, album_dir, monkeypatch, saved, queued
    ):
        album, (bare, _) = await self._album_of_two(async_db, album_dir)
        opened: list[Path] = []
        monkeypatch.setattr(artwork, "extract_artwork", fake_extract({}, opened))

        assert client.get(f"/api/v1/tracks/{bare.id}/artwork").status_code == 404
        assert [(c["artist"], c["album"], c["album_key"]) for c in queued] == [("TR/ST", "TRST", str(album.id))]
        reads = len(opened)
        assert reads > 0

        assert client.get(f"/api/v1/tracks/{bare.id}/artwork").status_code == 404
        assert len(opened) == reads, "a remembered miss must not search the disk again"
        assert len(queued) == 1

    @pytest.mark.asyncio
    async def test_a_split_album_borrows_from_its_other_half_in_the_folder(
        self, async_db, client, album_dir, monkeypatch, saved, queued
    ):
        """Two album-artist tags make two albums in the database; the folder and tag are one."""
        from app.db.models.albums import Album

        db = async_db
        halves = [Album(name="TRST", sort_name="TRST"), Album(name="TRST", sort_name="TRST")]
        db.add_all(halves)
        await db.flush()
        bare = await insert_test_track(db, title="4", artist="TR/ST", album="TRST", file_path=str(album_dir / "04 The Last Dregs.mp3"))
        covered = await insert_test_track(db, title="2", artist="TR/ST", album="trst", file_path=str(album_dir / "02 Dressed for Space.mp3"))
        bare.canonical_album_id, covered.canonical_album_id = halves[0].id, halves[1].id
        await db.commit()
        monkeypatch.setattr(artwork, "extract_artwork", fake_extract({Path(covered.file_path): JPEG}, []))

        resp = client.get(f"/api/v1/tracks/{bare.id}/artwork")

        assert resp.status_code == 200 and resp.content == JPEG

    @pytest.mark.asyncio
    async def test_an_untagged_track_borrows_from_nobody(
        self, async_db, client, tmp_path, monkeypatch, saved, queued
    ):
        """Elliott Smith's *Unknown Album* folder: seven songs, no album tags, one folder album."""
        from app.db.models.albums import Album

        db = async_db
        folder = tmp_path / "Elliott Smith" / "Unknown Album"
        folder.mkdir(parents=True)
        album = Album(name="Unknown Album", sort_name="Unknown Album")
        db.add(album)
        await db.flush()
        fall = await insert_test_track(db, title="How to Take a Fall", artist="Elliott Smith", album=None, file_path=str(folder / "How to Take a Fall.mp3"))
        other = await insert_test_track(db, title="Shake Sugaree", artist="Elliott Smith", album=None, file_path=str(folder / "Shake Sugaree.mp3"))
        fall.canonical_album_id = other.canonical_album_id = album.id
        await db.commit()
        for t in (fall, other):
            Path(t.file_path).write_bytes(b"x")
        monkeypatch.setattr(artwork, "extract_artwork", fake_extract({Path(other.file_path): JPEG}, []))

        assert client.get(f"/api/v1/tracks/{fall.id}/artwork").status_code == 404
