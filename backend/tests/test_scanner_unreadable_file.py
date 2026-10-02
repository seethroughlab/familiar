"""A file the listing returns but that cannot be opened is skipped, not the end of the scan.

Found 2026-10-02 on Familiar Server reading a NAS share over SMB: macOS listed a file whose name
held a decomposed é, and stat and open failed under every normal form. The scanner's
FileNotFoundError ended the scan worker, so the first sync of 19,124 tracks never reached analysis.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.db.models import ArtistAlias, Track, TrackStatus
from app.services import scanner as scanner_module
from app.services.scanner import LibraryScanner

FIXTURES = Path(__file__).parent / "fixtures" / "audio"


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


def _refuse(monkeypatch: pytest.MonkeyPatch, bad: Path) -> None:
    """Make one listed file fail to open, as the SMB share's did."""
    real = scanner_module._get_file_info_sync

    def get_file_info(file_path, *args, **kwargs):
        if Path(file_path) == bad:
            raise FileNotFoundError(2, "No such file or directory", str(bad))
        return real(file_path, *args, **kwargs)

    monkeypatch.setattr(scanner_module, "_get_file_info_sync", get_file_info)


@pytest.mark.asyncio(loop_scope="function")
class TestAnUnreadableFile:
    async def test_the_rest_of_the_library_is_still_imported(self, clean_db, tmp_path, monkeypatch):
        library = tmp_path / "music"
        shutil.copytree(FIXTURES, library)
        await LibraryScanner(clean_db, initial_import=True).scan(library)
        await clean_db.commit()
        everything = {p for (p,) in (await clean_db.execute(select(Track.file_path))).all()}
        await clean_db.execute(delete(Track))
        await clean_db.commit()
        bad = Path(sorted(p for p in everything if "/artist1/" in p)[0])
        _refuse(monkeypatch, bad)

        result = await LibraryScanner(clean_db, initial_import=True).scan(library)
        await clean_db.commit()
        imported = {p for (p,) in (await clean_db.execute(select(Track.file_path))).all()}

        assert result["skipped_unreadable"] == 1
        assert imported == everything - {str(bad)}, (
            "one unreadable file stopped the rest being imported"
        )

    async def test_a_track_already_held_is_not_marked_missing(
        self, clean_db, tmp_path, monkeypatch
    ):
        """It was listed, so it is there; one failed read is not evidence it has gone."""
        library = tmp_path / "music"
        shutil.copytree(FIXTURES, library)
        await LibraryScanner(clean_db, initial_import=True).scan(library)
        await clean_db.commit()
        held = (await clean_db.execute(select(Track.file_path).limit(1))).scalar_one()
        _refuse(monkeypatch, Path(held))

        result = await LibraryScanner(clean_db, initial_import=False).scan(library)
        await clean_db.commit()
        status = (
            await clean_db.execute(select(Track.status).where(Track.file_path == held))
        ).scalar_one()

        assert result["skipped_unreadable"] == 1
        assert result["marked_missing"] == 0
        assert status == TrackStatus.ACTIVE
