"""`app.cli.backfill_video_posters` — posters for the videos downloaded before familiar#305.

The fetch is injected, so nothing here reaches YouTube; what is tested is which URLs are asked
for, in what order, and what lands on disk.
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.cli.backfill_video_posters import backfill, poster_url
from app.config import settings
from app.db.models.tracks import TrackVideo
from app.utils.time import utcnow
from tests.factories import insert_test_track

POSTER = b"\xff\xd8poster"
BETTER = b"\xff\xd8maxres"


async def _row(async_db, *, title, source_id):
    track = await insert_test_track(async_db, title=title, artist="Someone")
    await async_db.flush()
    async_db.add(
        TrackVideo(
            track_id=track.id,
            source="youtube",
            source_id=source_id,
            source_url=None if source_id == "adopted" else f"https://www.youtube.com/watch?v={source_id}",
            file_path=f"/videos/{track.id}.mp4",
            is_audio_only=False,
            file_size_bytes=1,
            downloaded_at=utcnow(),
        )
    )
    return track


@pytest.fixture()
async def rows(async_db, tmp_path):
    """Three videos: one with an id, one adopted, one with an id and a poster already on disk."""
    with_id = await _row(async_db, title="Needs one", source_id="abc12345678")
    adopted = await _row(async_db, title="Adopted", source_id="adopted")
    has_one = await _row(async_db, title="Has one", source_id="def12345678")
    await async_db.commit()
    (tmp_path / f"{has_one.id}.jpg").write_bytes(b"kept")
    return with_id, adopted, has_one


@pytest.fixture()
async def session_maker():
    # The CLI opens its own session, as the download path does; bind it to this test's engine
    # for the reason `test_videos.py` gives — the app's global engine is on another loop.
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


class TestBackfill:
    @pytest.mark.asyncio
    async def test_writes_a_poster_for_a_row_that_knows_its_id(
        self, rows, session_maker, tmp_path
    ):
        with_id, adopted, has_one = rows
        asked: list[str] = []

        async def fetch(url):
            asked.append(url)
            # No maxresdefault for this upload; hqdefault always exists.
            return None if url.endswith("maxresdefault.jpg") else POSTER

        result = await backfill(fetch, session_maker=session_maker, videos_dir=tmp_path)

        assert result == (1, 1, 1, 0)
        assert (tmp_path / f"{with_id.id}.jpg").read_bytes() == POSTER
        assert asked == [
            poster_url("abc12345678", "maxresdefault.jpg"),
            poster_url("abc12345678", "hqdefault.jpg"),
        ]
        # The adopted row has no id to ask for; the one with a poster was not asked about.
        assert not (tmp_path / f"{adopted.id}.jpg").exists()
        assert (tmp_path / f"{has_one.id}.jpg").read_bytes() == b"kept"
        assert list(tmp_path.glob("*.temp.*")) == []

    @pytest.mark.asyncio
    async def test_prefers_the_16_by_9_frame_when_youtube_has_it(
        self, rows, session_maker, tmp_path
    ):
        with_id, _, _ = rows

        async def fetch(url):
            return BETTER if url.endswith("maxresdefault.jpg") else POSTER

        await backfill(fetch, session_maker=session_maker, videos_dir=tmp_path)

        assert (tmp_path / f"{with_id.id}.jpg").read_bytes() == BETTER

    @pytest.mark.asyncio
    async def test_a_video_youtube_has_forgotten_is_counted_not_faked(
        self, rows, session_maker, tmp_path
    ):
        with_id, _, _ = rows

        async def fetch(url):
            return None

        result = await backfill(fetch, session_maker=session_maker, videos_dir=tmp_path)

        assert result[3] == 1
        assert not (tmp_path / f"{with_id.id}.jpg").exists()

    @pytest.mark.asyncio
    async def test_dry_run_fetches_but_writes_nothing(self, rows, session_maker, tmp_path):
        with_id, _, _ = rows

        async def fetch(url):
            return POSTER

        result = await backfill(fetch, dry_run=True, session_maker=session_maker, videos_dir=tmp_path)

        assert result[0] == 1
        assert not (tmp_path / f"{with_id.id}.jpg").exists()

    @pytest.mark.asyncio
    async def test_force_replaces_an_existing_poster(self, rows, session_maker, tmp_path):
        _, _, has_one = rows

        async def fetch(url):
            return POSTER

        await backfill(fetch, force=True, session_maker=session_maker, videos_dir=tmp_path)

        assert (tmp_path / f"{has_one.id}.jpg").read_bytes() == POSTER
