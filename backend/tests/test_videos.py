"""Tests for the music video surface (ADR-0086).

Before this file the feature had exactly one test — an error-envelope assertion in
`test_contract_error_shapes.py` — which is why three of the findings in ADR-0086's `## Context`
survived since Phase 5: a stream that advertised `Accept-Ranges` and ignored `Range`, a table
nothing read or wrote, and no way to ask which tracks have a video.

The video file lives at `settings.videos_path / f"{track_id}.mp4"`, because that filename *is* the
persistence model the service uses to answer "is there a video".
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db.models.tracks import TrackVideo
from app.services.video import get_video_service
from app.utils.time import utcnow
from tests.factories import insert_test_track

# Deterministic, and large enough that ranges are meaningful.
CONTENT = bytes(range(256)) * 64  # 16 KiB
CONTENT_LEN = len(CONTENT)


@pytest.fixture()
async def track_with_video(async_db):
    """A track with a real .mp4 on disk where the service looks for it, and its row."""
    track = await insert_test_track(async_db, title="Watchable", artist="Someone")
    await async_db.flush()

    settings.videos_path.mkdir(parents=True, exist_ok=True)
    path = settings.videos_path / f"{track.id}.mp4"
    path.write_bytes(CONTENT)

    async_db.add(
        TrackVideo(
            track_id=track.id,
            source="youtube",
            source_id="dQw4w9WgXcQ",
            source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            file_path=str(path),
            is_audio_only=False,
            file_size_bytes=CONTENT_LEN,
            downloaded_at=utcnow(),
        )
    )
    await async_db.commit()

    yield track
    path.unlink(missing_ok=True)


class TestRanges:
    """ADR-0086 point 4. The handler this replaced served the whole file from byte 0 every time."""

    @pytest.mark.asyncio
    async def test_whole_file_without_a_range_header(self, track_with_video, client):
        r = client.get(f"/api/v1/videos/{track_with_video.id}/stream")
        assert r.status_code == 200
        assert r.content == CONTENT
        assert int(r.headers["content-length"]) == CONTENT_LEN

    @pytest.mark.asyncio
    async def test_closed_range(self, track_with_video, client):
        r = client.get(f"/api/v1/videos/{track_with_video.id}/stream",
                       headers={"Range": "bytes=0-99"})
        assert r.status_code == 206
        assert r.content == CONTENT[0:100]
        assert r.headers["content-range"] == f"bytes 0-99/{CONTENT_LEN}"

    @pytest.mark.asyncio
    async def test_mid_file_range(self, track_with_video, client):
        r = client.get(f"/api/v1/videos/{track_with_video.id}/stream",
                       headers={"Range": "bytes=1000-1999"})
        assert r.status_code == 206
        assert r.content == CONTENT[1000:2000]

    @pytest.mark.asyncio
    async def test_open_ended_range_runs_to_eof(self, track_with_video, client):
        start = CONTENT_LEN - 500
        r = client.get(f"/api/v1/videos/{track_with_video.id}/stream",
                       headers={"Range": f"bytes={start}-"})
        assert r.status_code == 206
        assert r.content == CONTENT[start:]

    @pytest.mark.asyncio
    async def test_suffix_range_returns_the_last_bytes(self, track_with_video, client):
        """`bytes=-100` is the final 100 bytes (RFC 9110 §14.1.2), not the first 100."""
        r = client.get(f"/api/v1/videos/{track_with_video.id}/stream",
                       headers={"Range": "bytes=-100"})
        assert r.status_code == 206
        assert r.content == CONTENT[-100:]

    @pytest.mark.asyncio
    async def test_unsatisfiable_range_is_416(self, track_with_video, client):
        r = client.get(f"/api/v1/videos/{track_with_video.id}/stream",
                       headers={"Range": f"bytes={CONTENT_LEN + 5000}-"})
        assert r.status_code == 416

    @pytest.mark.asyncio
    async def test_malformed_range_does_not_500(self, track_with_video, client):
        r = client.get(f"/api/v1/videos/{track_with_video.id}/stream",
                       headers={"Range": "bytes=abc-def"})
        assert r.status_code != 500

    @pytest.mark.asyncio
    async def test_ranges_reassemble_into_the_original(self, track_with_video, client):
        """Fetch it the way `AVPlayer` does, and rebuild it."""
        chunk = 4096
        rebuilt = b""
        for start in range(0, CONTENT_LEN, chunk):
            end = min(start + chunk - 1, CONTENT_LEN - 1)
            r = client.get(f"/api/v1/videos/{track_with_video.id}/stream",
                           headers={"Range": f"bytes={start}-{end}"})
            assert r.status_code == 206
            rebuilt += r.content
        assert rebuilt == CONTENT

    @pytest.mark.asyncio
    async def test_declares_a_video_media_type(self, track_with_video, client):
        """The schema used to claim `application/json`, which is what kept it un-generatable."""
        r = client.get(f"/api/v1/videos/{track_with_video.id}/stream")
        assert r.headers["content-type"].startswith("video/")


class TestListEndpoint:
    """ADR-0086 point 3 — the operation the Mac's Videos destination is built on."""

    @pytest.mark.asyncio
    async def test_lists_the_track_and_which_video_it_is(self, track_with_video, client):
        r = client.get("/api/v1/videos")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] >= 1
        row = next(i for i in body["items"] if i["id"] == str(track_with_video.id))
        assert row["title"] == "Watchable"
        assert row["artist"] == "Someone"
        assert row["source"] == "youtube"
        assert row["source_id"] == "dQw4w9WgXcQ"
        assert row["downloaded_at"] is not None

    @pytest.mark.asyncio
    async def test_a_track_without_a_video_is_absent(self, async_db, client):
        track = await insert_test_track(async_db, title="No video here")
        await async_db.commit()
        r = client.get("/api/v1/videos")
        assert r.status_code == 200
        assert all(i["id"] != str(track.id) for i in r.json()["items"])

    @pytest.mark.asyncio
    async def test_paging_envelope(self, track_with_video, client):
        r = client.get("/api/v1/videos", params={"page": 1, "page_size": 1})
        assert r.status_code == 200
        body = r.json()
        assert body["page"] == 1 and body["page_size"] == 1
        assert len(body["items"]) <= 1

    @pytest.mark.asyncio
    async def test_page_size_is_bounded(self, client):
        assert client.get("/api/v1/videos", params={"page_size": 5000}).status_code == 422
        assert client.get("/api/v1/videos", params={"page": 0}).status_code == 422


class TestDownloadWritesItsRow:
    """ADR-0086 point 1. yt-dlp is a subprocess, so the binary is never needed here."""

    @pytest.mark.asyncio
    async def test_a_completed_download_is_recorded(self, async_db, monkeypatch):
        track = await insert_test_track(async_db, title="Fresh")
        await async_db.commit()
        track_id = str(track.id)

        service = get_video_service()
        output_path = service.videos_dir / f"{track_id}.mp4"
        temp_path = service.videos_dir / f"{track_id}.temp.mp4"

        class FakeProcess:
            returncode = 0
            stdout = None

            async def wait(self):
                # yt-dlp's side of the contract: the temp file exists when it exits 0.
                temp_path.write_bytes(CONTENT)
                return 0

        async def fake_exec(*args, **kwargs):
            return FakeProcess()

        monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
        # `_record_download` opens its own session, because in production it runs under
        # `BackgroundTasks` after the request's session is gone. Point it at this test's engine —
        # the app's global engine binds its pool to the session-scoped client's event loop.
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        monkeypatch.setattr(
            "app.services.video.async_session_maker",
            async_sessionmaker(engine, expire_on_commit=False),
        )

        try:
            status = await service.download(
                track_id, "https://www.youtube.com/watch?v=abc12345678"
            )
            assert status.status == "complete"

            record = await service.get_video_record(async_db, track_id)
            assert record is not None
            assert record.source == "youtube"
            assert record.source_id == "abc12345678"
            assert record.file_size_bytes == CONTENT_LEN
            assert record.downloaded_at is not None
        finally:
            service._downloads.pop(track_id, None)
            output_path.unlink(missing_ok=True)
            temp_path.unlink(missing_ok=True)
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_status_survives_a_lost_progress_cache(self, async_db, track_with_video):
        """A restart empties `_downloads`; the row is what makes the video still discoverable."""
        service = get_video_service()
        track_id = str(track_with_video.id)
        service._downloads.pop(track_id, None)

        status = await service.get_download_status(async_db, track_id)
        assert status is not None
        assert status.status == "complete"
        assert status.video_id == "dQw4w9WgXcQ"

    @pytest.mark.asyncio
    async def test_a_row_whose_file_is_gone_is_reconciled_away(self, async_db, track_with_video):
        """ADR-0086 point 2: the file wins for existence, so a row describing nothing is deleted."""
        service = get_video_service()
        track_id = str(track_with_video.id)
        (settings.videos_path / f"{track_id}.mp4").unlink()

        assert await service.get_video_record(async_db, track_id) is None


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_removes_the_file_and_the_row(self, track_with_video, client):
        track_id = str(track_with_video.id)
        r = client.delete(f"/api/v1/videos/{track_id}")
        assert r.status_code == 200

        assert not (settings.videos_path / f"{track_id}.mp4").exists()
        listed = client.get("/api/v1/videos").json()["items"]
        assert all(i["id"] != track_id for i in listed)
