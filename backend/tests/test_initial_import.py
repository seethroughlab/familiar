"""A library's first import arrives active; review is for what arrives later.

Every new file used to enter PENDING_REVIEW, so a first-time user (on Familiar Server especially)
saw an empty library: analysis skips pending tracks, and the web admin has no Review screen. Review
exists to vet additions to a library (duplicates, better copies, Soulseek downloads under ADR-0117),
and a first import has nothing to compare against.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

import app.services.app_settings as app_settings_module
from app.db.models import ArtistAlias, Track, TrackStatus
from app.services.app_settings import AppSettingsService
from app.services.scanner import LibraryScanner

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "audio"


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


@pytest.fixture
def library(tmp_path) -> Path:
    """The fixture library, with one album moved into the Soulseek Inbox."""
    music = tmp_path / "music"
    shutil.copytree(FIXTURES_DIR, music)
    (music / "Inbox").mkdir()
    shutil.move(str(music / "artist2"), str(music / "Inbox" / "artist2"))
    return music


async def _statuses(db) -> dict[str, TrackStatus]:
    rows = (await db.execute(select(Track.file_path, Track.status))).all()
    return {Path(path).name: status for path, status in rows}


@pytest.mark.asyncio(loop_scope="function")
class TestScanner:
    async def test_a_first_import_arrives_active(self, clean_db, library):
        results = await LibraryScanner(clean_db, initial_import=True).scan(library)
        statuses = await _statuses(clean_db)

        assert statuses["ambient_loop.mp3"] == TrackStatus.ACTIVE
        assert statuses["epic_boss_battle.mp3"] == TrackStatus.ACTIVE
        # 8 unique files; one of them is in the Inbox.
        assert results["new"] == 7
        assert results["pending_review"] == 1

    async def test_the_inbox_is_reviewed_even_during_a_first_import(self, clean_db, library):
        await LibraryScanner(clean_db, initial_import=True).scan(library)
        statuses = await _statuses(clean_db)
        assert statuses["comedy_intro.mp3"] == TrackStatus.PENDING_REVIEW

    async def test_after_the_first_import_new_files_are_reviewed_as_before(self, clean_db, library):
        results = await LibraryScanner(clean_db, initial_import=False).scan(library)
        statuses = await _statuses(clean_db)
        # The fixture's identical copy (`electronic_short_relocated.mp3`) is handled as a relocation,
        # as it always was; every genuinely new file waits for review.
        statuses.pop("electronic_short_relocated.mp3", None)
        statuses.pop("electronic_short.mp3", None)
        assert set(statuses.values()) == {TrackStatus.PENDING_REVIEW}
        assert results["pending_review"] == 8 and results["new"] == 0


@pytest.fixture
def this_loops_sessions(clean_db, monkeypatch):
    """`_initial_import_pending` opens its own session; give it one on this test's event loop."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.db.session as session_module

    monkeypatch.setattr(
        session_module, "async_session_maker",
        async_sessionmaker(clean_db.bind, class_=AsyncSession, expire_on_commit=False),
    )


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    service = AppSettingsService(settings_path=tmp_path / "settings.json")
    monkeypatch.setattr(app_settings_module, "_app_settings_service", service)
    return service


@pytest.mark.asyncio(loop_scope="function")
class TestWhoDecides:
    async def test_an_empty_library_is_a_first_import(self, clean_db, this_loops_sessions, settings_file):
        from app.services.tasks.library_sync import _initial_import_pending

        assert await _initial_import_pending() is True
        assert settings_file.get().initial_import_complete is False, "decided once, and kept"

    async def test_a_library_that_already_has_tracks_changes_nothing(self, clean_db, this_loops_sessions, settings_file, library):
        """The upgrade path: an existing installation keeps reviewing everything new."""
        from app.services.tasks.library_sync import _initial_import_pending

        await LibraryScanner(clean_db, initial_import=False).scan(library)
        await clean_db.commit()
        assert await _initial_import_pending() is False
        assert settings_file.get().initial_import_complete is True

    async def test_an_interrupted_first_import_resumes_as_one(self, clean_db, this_loops_sessions, settings_file, library):
        """Some tracks exist, but the import never finished: the rest still arrive active."""
        from app.services.tasks.library_sync import _initial_import_pending

        settings_file.update(initial_import_complete=False)
        await LibraryScanner(clean_db, initial_import=True).scan(library)
        await clean_db.commit()
        assert await _initial_import_pending() is True

    async def test_it_finishes_only_once_a_scan_found_music(self, settings_file):
        from app.services.tasks.library_sync import _finish_initial_import

        settings_file.update(initial_import_complete=False)
        _finish_initial_import({"new": 0, "updated": 0, "unchanged": 0, "pending_review": 0})
        assert settings_file.get().initial_import_complete is False, "an empty folder imports nothing"
        _finish_initial_import({"new": 7, "pending_review": 1})
        assert settings_file.get().initial_import_complete is True
