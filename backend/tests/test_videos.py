"""Tests for the music video surface (ADR-0086).

Before this file the feature had exactly one test — an error-envelope assertion in
`test_contract_error_shapes.py` — which is why three of the findings in ADR-0086's `## Context`
survived since Phase 5: a stream that advertised `Accept-Ranges` and ignored `Range`, a table
nothing read or wrote, and no way to ask which tracks have a video.

The video file lives at `settings.videos_path / f"{track_id}.mp4"`, because that filename *is* the
persistence model the service uses to answer "is there a video". The poster frame beside it,
`{track_id}.jpg`, answers "is there a poster" the same way.
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
# Not a real JPEG; nothing here decodes it. Distinct from CONTENT so a test cannot pass by serving
# the video where the poster should be.
POSTER = b"\xff\xd8" + bytes(range(255, -1, -1)) * 4


async def _insert_video(async_db, *, title, poster):
    track = await insert_test_track(async_db, title=title, artist="Someone")
    await async_db.flush()

    settings.videos_path.mkdir(parents=True, exist_ok=True)
    path = settings.videos_path / f"{track.id}.mp4"
    path.write_bytes(CONTENT)
    poster_path = settings.videos_path / f"{track.id}.jpg"
    if poster:
        poster_path.write_bytes(POSTER)

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
    return track, path, poster_path


@pytest.fixture()
async def track_with_video(async_db):
    """A track with a real .mp4 on disk where the service looks for it, its poster, and its row."""
    track, path, poster_path = await _insert_video(async_db, title="Watchable", poster=True)
    yield track
    path.unlink(missing_ok=True)
    poster_path.unlink(missing_ok=True)


@pytest.fixture()
async def track_without_poster(async_db):
    """A video downloaded before posters were saved: the mp4 and the row, and nothing beside it."""
    track, path, poster_path = await _insert_video(async_db, title="Unposted", poster=False)
    yield track
    path.unlink(missing_ok=True)
    poster_path.unlink(missing_ok=True)


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


class TestPoster:
    """The poster frame is fetched with the video and served beside it.

    Answered from disk, like the video itself: a jpg beside the mp4 is the whole persistence model,
    which is what lets the list say `has_poster` without a column and lets a poster leave with its
    video without a second delete.
    """

    @pytest.mark.asyncio
    async def test_serves_the_jpeg_with_a_long_cache_life(self, track_with_video, client):
        r = client.get(f"/api/v1/videos/{track_with_video.id}/poster")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/jpeg")
        assert "max-age=31536000" in r.headers["cache-control"]
        assert r.content == POSTER

    @pytest.mark.asyncio
    async def test_404_when_there_is_no_poster(self, track_without_poster, client):
        r = client.get(f"/api/v1/videos/{track_without_poster.id}/poster")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_the_list_says_whether_a_poster_exists(
        self, track_with_video, track_without_poster, client
    ):
        """So a grid asks only for posters that exist, rather than finding out with a 404 apiece."""
        items = client.get("/api/v1/videos").json()["items"]
        by_id = {i["id"]: i for i in items}
        assert by_id[str(track_with_video.id)]["has_poster"] is True
        assert by_id[str(track_without_poster.id)]["has_poster"] is False

    @pytest.mark.asyncio
    async def test_delete_removes_the_poster_too(self, track_with_video, client):
        track_id = str(track_with_video.id)
        assert client.delete(f"/api/v1/videos/{track_id}").status_code == 200
        assert not (settings.videos_path / f"{track_id}.jpg").exists()


async def _no_record(*args, **kwargs):
    """Stand-in for `_record_download`: the row is point 1's concern, tested above."""


def _fake_yt_dlp(monkeypatch, videos_dir, *, writes: list[str], seen: list[list[str]]):
    """A yt-dlp that exits 0 after writing the named temp files, recording the command it got."""

    class FakeProcess:
        returncode = 0
        stdout = None

        async def wait(self):
            for name in writes:
                (videos_dir / name).write_bytes(POSTER if name.endswith(".jpg") else CONTENT)
            return 0

    async def fake_exec(*args, **kwargs):
        seen.append(list(args))
        return FakeProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)


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

        # yt-dlp's side of the contract: the temp file exists when it exits 0.
        _fake_yt_dlp(monkeypatch, service.videos_dir, writes=[f"{track_id}.temp.mp4"], seen=[])
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
    async def test_asks_for_a_jpg_poster_under_the_temp_name(self, monkeypatch, tmp_path):
        """The flags, and the extension-less thumbnail template that makes the output name fixed.

        `-o {id}.temp.mp4` alone names the thumbnail `{id}.temp.jpg` for a merged mp4 but
        `{id}.temp.mp4.jpg` when the format fallback lands on webm — yt-dlp only replaces an
        extension that equals the video's. `thumbnail:{id}.temp` is what keeps it predictable.
        """
        from app.services.video import VideoService

        service = VideoService(videos_dir=tmp_path)
        seen: list[list[str]] = []
        _fake_yt_dlp(monkeypatch, tmp_path, writes=["t1.temp.mp4", "t1.temp.jpg"], seen=seen)
        monkeypatch.setattr(service, "_record_download", _no_record)

        await service.download("t1", "https://www.youtube.com/watch?v=abc12345678")

        (cmd,) = seen
        assert "--write-thumbnail" in cmd
        assert cmd[cmd.index("--convert-thumbnails") + 1] == "jpg"
        assert f"thumbnail:{tmp_path / 't1.temp'}" in cmd

    @pytest.mark.asyncio
    async def test_asks_for_h264_before_anything_else(self, monkeypatch, tmp_path):
        """`ext=mp4` let VP9 and AV1 through and the Mac played them as audio."""
        from app.services.video import VideoService

        service = VideoService(videos_dir=tmp_path)
        seen: list[list[str]] = []
        _fake_yt_dlp(monkeypatch, tmp_path, writes=["t1.temp.mp4"], seen=seen)
        monkeypatch.setattr(service, "_record_download", _no_record)

        await service.download("t1", "https://www.youtube.com/watch?v=abc12345678")

        (cmd,) = seen
        selector = cmd[cmd.index("-f") + 1]
        assert selector.startswith("bestvideo[height<=1080][vcodec^=avc1]")
        assert "[ext=mp4]" not in selector.split("/")[0]

    @pytest.mark.asyncio
    async def test_the_poster_is_kept_beside_the_video(self, monkeypatch, tmp_path):
        from app.services.video import VideoService

        service = VideoService(videos_dir=tmp_path)
        _fake_yt_dlp(monkeypatch, tmp_path, writes=["t1.temp.mp4", "t1.temp.jpg"], seen=[])
        monkeypatch.setattr(service, "_record_download", _no_record)

        status = await service.download("t1", "https://www.youtube.com/watch?v=abc12345678")

        assert status.status == "complete"
        assert service.has_poster("t1")
        assert (tmp_path / "t1.jpg").read_bytes() == POSTER
        assert list(tmp_path.glob("t1.temp.*")) == []

    @pytest.mark.asyncio
    async def test_a_missing_poster_never_fails_a_download(self, monkeypatch, tmp_path):
        """And a poster from an earlier download of this track does not survive to describe it."""
        from app.services.video import VideoService

        service = VideoService(videos_dir=tmp_path)
        (tmp_path / "t1.jpg").write_bytes(b"stale")
        # An unconverted webp is what a failed `--convert-thumbnails` leaves behind.
        _fake_yt_dlp(monkeypatch, tmp_path, writes=["t1.temp.mp4", "t1.temp.webp"], seen=[])
        monkeypatch.setattr(service, "_record_download", _no_record)

        status = await service.download("t1", "https://www.youtube.com/watch?v=abc12345678")

        assert status.status == "complete"
        assert service.has_video("t1")
        assert not service.has_poster("t1")
        assert list(tmp_path.glob("t1.temp.*")) == []

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


class TestSearchFailureIsNotAnEmptyResult:
    """A broken search must not look like a search that found nothing.

    This is the defect ADR-0077 records for `search_bandcamp` — it "answered 'no results' for every
    query, for however long it had been" — and video search had it too: every `yt-dlp` failure was
    caught and returned as `[]`. It was found the same way, by asking for a video that certainly
    exists and being told there were none.
    """

    @pytest.mark.asyncio
    async def test_a_failed_search_raises_rather_than_returning_empty(self, monkeypatch):
        from app.services.video import VideoSearchUnavailable, VideoService

        async def fake_exec(*args, **kwargs):
            class Proc:
                returncode = 1

                async def communicate(self):
                    return b"", b"ERROR: Requested format is not available"

                def kill(self):
                    pass

                async def wait(self):
                    pass

            return Proc()

        monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
        with pytest.raises(VideoSearchUnavailable):
            await VideoService().search("anything")

    @pytest.mark.asyncio
    async def test_one_failed_entry_does_not_lose_the_others(self, monkeypatch):
        """An age-gated result makes yt-dlp exit 1 after printing the rest."""
        from app.services.video import VideoService

        good = (b'{"id": "abc", "title": "Interpol - Evil", "channel": null, "uploader": null, '
                b'"duration": 221, "thumbnail": "t"}\n')

        async def fake_exec(*args, **kwargs):
            class Proc:
                returncode = 1

                async def communicate(self):
                    return good, b"ERROR: [youtube] xyz: Sign in to confirm your age."

                def kill(self):
                    pass

                async def wait(self):
                    pass

            return Proc()

        monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
        results = await VideoService().search("interpol evil")
        assert [r.video_id for r in results] == ["abc"]
        assert results[0].channel == ""  # null, not None: every reader treats it as text

    @pytest.mark.asyncio
    async def test_a_genuinely_empty_search_still_returns_empty(self, monkeypatch):
        """The other half: success with no matches is an empty list, not an error."""
        from app.services.video import VideoService

        async def fake_exec(*args, **kwargs):
            class Proc:
                returncode = 0

                async def communicate(self):
                    return b"", b""

                def kill(self):
                    pass

                async def wait(self):
                    pass

            return Proc()

        monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
        assert await VideoService().search("nothing matches this") == []

    def test_no_player_client_is_pinned(self):
        """yt-dlp chooses its own client.

        Pinning `player_client=web` is what broke every search: YouTube answered it with
        storyboard images only. `docker/entrypoint.sh` updates yt-dlp on every boot precisely so
        it can track these changes — a pin here makes that update useless.
        """
        from app.services.video import VideoService

        assert VideoService._base_ytdlp_args() == []


class TestRefetchUnplayable:
    """Videos the Mac cannot decode are downloaded again under the H.264 selector."""

    @pytest.mark.asyncio
    async def test_a_vp9_file_is_fetched_again_and_an_h264_one_left_alone(
        self, async_db, track_with_video, track_without_poster, monkeypatch
    ):
        from app.cli.refetch_unplayable_videos import refetch

        service = get_video_service()
        vp9_id = str(track_with_video.id)

        async def fake_codec(path):
            return "vp9" if path.stem == vp9_id else "h264"

        fetched = []

        async def fake_download(track_id, url):
            fetched.append((track_id, url))
            from app.services.video import VideoDownloadStatus
            return VideoDownloadStatus(track_id=track_id, video_id="x", status="complete", progress=100)

        monkeypatch.setattr(service, "video_codec", fake_codec)
        monkeypatch.setattr(service, "download", fake_download)

        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        try:
            result = await refetch(
                service, pause=0, session_maker=async_sessionmaker(engine, expire_on_commit=False)
            )
        finally:
            await engine.dispose()

        assert fetched == [(vp9_id, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")]
        assert result[0] == 1 and result[1] >= 1

    @pytest.mark.asyncio
    async def test_dry_run_downloads_nothing(self, track_with_video, monkeypatch):
        from app.cli.refetch_unplayable_videos import refetch

        service = get_video_service()

        async def fake_codec(path):
            return "av1"

        async def fake_download(track_id, url):
            raise AssertionError("dry run must not download")

        monkeypatch.setattr(service, "video_codec", fake_codec)
        monkeypatch.setattr(service, "download", fake_download)

        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        try:
            result = await refetch(
                service, dry_run=True, pause=0,
                session_maker=async_sessionmaker(engine, expire_on_commit=False),
            )
        finally:
            await engine.dispose()
        assert result[0] >= 1

    @pytest.mark.asyncio
    async def test_ffprobe_is_asked_for_the_video_codec(self, monkeypatch, tmp_path):
        from app.services.video import VideoService

        seen = []

        class Proc:
            async def communicate(self):
                return b"vp9\n", b""

        async def fake_exec(*args, **kwargs):
            seen.append(list(args))
            return Proc()

        monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
        codec = await VideoService(videos_dir=tmp_path).video_codec(tmp_path / "t.mp4")

        assert codec == "vp9"
        assert seen[0][0] == "ffprobe" and str(tmp_path / "t.mp4") in seen[0]
