"""The server watches its library (ADR-0142): what a change scans, and when."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.db.models import ArtistAlias, Track, TrackStatus
from app.services.library_watch import FolderClock, folder_to_scan
from app.services.scanner import LibraryScanner

FIXTURES = Path(__file__).parent / "fixtures" / "audio"


class TestWhatAChangeScans:
    def test_a_new_track_scans_its_folder(self, tmp_path):
        album = tmp_path / "Artist" / "Album"
        album.mkdir(parents=True)
        assert folder_to_scan(album / "01 Song.flac", [tmp_path]) == album

    def test_a_new_folder_scans_itself(self, tmp_path):
        album = tmp_path / "Artist" / "Album"
        album.mkdir(parents=True)
        assert folder_to_scan(album, [tmp_path]) == album

    def test_the_inbox_is_left_to_the_soulseek_poll(self, tmp_path):
        """ADR-0142 point 5: a file appearing is not a download finishing."""
        (tmp_path / "Inbox" / "x").mkdir(parents=True)
        assert folder_to_scan(tmp_path / "Inbox" / "x" / "01.mp3", [tmp_path]) is None
        assert folder_to_scan(tmp_path / "Inbox", [tmp_path]) is None

    def test_not_music_and_not_ours_are_ignored(self, tmp_path):
        assert folder_to_scan(tmp_path / "cover.jpg", [tmp_path]) is None
        assert folder_to_scan(Path("/elsewhere/song.mp3"), [tmp_path]) is None


class TestWhenItScans:
    def test_only_after_the_folder_goes_quiet(self):
        clock = FolderClock(quiet=180)
        a = Path("/m/A")
        clock.touch(a, now=0)
        clock.touch(a, now=100)  # still copying
        assert clock.due(now=200) == []
        assert clock.due(now=280) == [a]

    def test_an_ancestor_covers_its_children(self):
        clock = FolderClock(quiet=10)
        clock.touch(Path("/m/Artist"), now=0)
        clock.touch(Path("/m/Artist/Album"), now=0)
        assert clock.due(now=20) == [Path("/m/Artist")]
        clock.done([Path("/m/Artist")])
        assert clock.pending == 0


@pytest_asyncio.fixture(scope="function")
async def clean_db():
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.config import settings

    engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        await session.execute(delete(Track))
        await session.execute(delete(ArtistAlias))
        await session.commit()
        yield session
        await session.execute(delete(Track))
        await session.execute(delete(ArtistAlias))
        await session.commit()
    await engine.dispose()


@pytest.mark.asyncio(loop_scope="function")
class TestTheScanOfChangedFolders:
    async def test_it_adds_what_is_new_and_never_marks_anything_missing(self, clean_db, tmp_path):
        """ADR-0142 point 3. A track elsewhere whose file has gone stays as it was: only a full
        sync, which has looked at the whole library, may call it missing."""
        library = tmp_path / "music"
        shutil.copytree(FIXTURES, library)
        await LibraryScanner(clean_db, initial_import=True).scan(library)
        await clean_db.commit()
        before = {p: s for p, s in (await clean_db.execute(select(Track.file_path, Track.status))).all()}

        gone = next(p for p in before if "artist2" not in p)
        Path(gone).unlink()
        new_album = library / "New Artist" / "New Album"
        new_album.mkdir(parents=True)
        _write_unique_wav(new_album / "01 New.wav")

        result = await LibraryScanner(clean_db, initial_import=False).scan(library, only=[new_album])
        await clean_db.commit()
        after = {p: s for p, s in (await clean_db.execute(select(Track.file_path, Track.status))).all()}

        assert after[gone] == before[gone], "a scan of some folders marked a track elsewhere missing"
        assert result.get("marked_missing", 0) == 0
        new = str(new_album / "01 New.wav")
        assert set(after) - set(before) == {new}
        assert after[new] == TrackStatus.PENDING_REVIEW, "not a first import, so it waits for review"


def _write_unique_wav(path: Path) -> None:
    """Half a second of noise no other file in the library has, so it is new rather than a move."""
    import os
    import wave

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(os.urandom(22050))
