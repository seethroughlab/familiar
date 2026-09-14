"""Stills: a picture for the length of the track is not a video.

The score is pure and tested on synthetic frames; the sampling is tested with a fake ffmpeg;
the batch and the CLI are tested with the score injected.
"""

import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.cli.find_still_videos import find
from app.cli.match_music_videos import Candidate, run
from app.config import settings
from app.services.video import (
    MOTION_SAMPLE_FRAMES,
    MOTION_SAMPLE_SIDE,
    STILL_IMAGE_THRESHOLD,
    VideoDownloadStatus,
    VideoSearchResult,
    VideoService,
    get_video_service,
    max_frame_difference,
)
from tests.test_videos import track_with_video, track_without_poster  # noqa: F401, F811 — fixtures

N = MOTION_SAMPLE_SIDE * MOTION_SAMPLE_SIDE


def flat(value):
    return bytes([value]) * N


class TestMaxFrameDifference:
    def test_identical_frames_score_zero(self):
        assert max_frame_difference([flat(40)] * 8) == 0.0

    def test_pixel_noise_stays_under_the_threshold(self):
        frames = [bytes((40 + (i % 2)) for _ in range(N)) for i in range(8)]
        assert max_frame_difference(frames) < STILL_IMAGE_THRESHOLD

    def test_one_changed_frame_anywhere_is_enough(self):
        """A slideshow that changes once still moves."""
        frames = [flat(40)] * 7 + [flat(200)]
        assert max_frame_difference(frames) == 160.0

    def test_fewer_than_two_frames_is_no_answer(self):
        assert max_frame_difference([]) is None
        assert max_frame_difference([flat(1)]) is None
        assert max_frame_difference([flat(1), b""]) is None

    def test_mismatched_frames_are_no_answer(self):
        assert max_frame_difference([flat(1), b"\x01" * 10]) is None


class TestSampling:
    @pytest.mark.asyncio
    async def test_frames_are_taken_evenly_and_never_at_zero(self, monkeypatch, tmp_path):
        """Uploads open on black or a title card; sample 0 would differ from all the rest."""
        calls = []

        class Proc:
            def __init__(self, out):
                self.out = out

            async def communicate(self):
                return self.out, b""

        async def fake_exec(*args, **kwargs):
            calls.append(list(args))
            if args[0] == "ffprobe":
                return Proc(b"90.0\n")
            return Proc(flat(7))

        monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
        service = VideoService(videos_dir=tmp_path)

        score = await service.motion_score(tmp_path / "v.mp4")

        assert score == 0.0
        seeks = [float(c[c.index("-ss") + 1]) for c in calls if c[0] == "ffmpeg"]
        assert len(seeks) == MOTION_SAMPLE_FRAMES
        assert seeks[0] == 10.0 and seeks[-1] == 80.0  # 90s / 9
        assert all(c.index("-ss") < c.index("-i") for c in calls if c[0] == "ffmpeg")  # input seek

    @pytest.mark.asyncio
    async def test_is_still_image_applies_the_threshold(self, monkeypatch, tmp_path):
        service = VideoService(videos_dir=tmp_path)

        async def still(path):
            return 0.4

        async def moving(path):
            return 42.0

        monkeypatch.setattr(service, "motion_score", still)
        assert await service.is_still_image(tmp_path / "a.mp4") is True
        monkeypatch.setattr(service, "motion_score", moving)
        assert await service.is_still_image(tmp_path / "a.mp4") is False


def candidate(track_id="00000000-0000-0000-0000-000000000001"):
    from uuid import UUID

    return Candidate(track_id=UUID(track_id), title="Evil", artist="Interpol",
                     duration_seconds=220.0, plays=5, favourite=True)


class TestBatchRefusesStills:
    @pytest.mark.asyncio
    async def test_a_downloaded_still_is_removed_and_logged_as_such(self, tmp_path):
        removed = []

        async def search(query):
            return [VideoSearchResult(video_id="abc", title="Interpol - Evil (Official Video)",
                                      channel="InterpolVEVO", duration=221, thumbnail_url="",
                                      url="https://www.youtube.com/watch?v=abc")]

        async def download(track_id, url):
            return VideoDownloadStatus(track_id=track_id, video_id="abc", status="complete", progress=100)

        async def is_still(track_id):
            return True

        async def remove(track_id):
            removed.append(track_id)

        log = tmp_path / "match-log.jsonl"
        tally = await run([candidate()], search=search, download=download, log_path=log,
                          is_still=is_still, remove=remove)

        assert (tally.matched, tally.stills) == (0, 1)
        assert removed == ["00000000-0000-0000-0000-000000000001"]
        entry = json.loads(log.read_text().strip())
        assert entry["decision"] == "still"


@pytest.fixture()
async def session_maker():
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


class TestFindStills:
    @pytest.mark.asyncio
    async def test_reports_and_deletes_on_request(
        self, track_with_video, track_without_poster, session_maker, monkeypatch  # noqa: F811
    ):
        service = get_video_service()
        still_id = str(track_with_video.id)

        async def score(path):
            return 0.2 if path.stem == still_id else 60.0

        monkeypatch.setattr(service, "motion_score", score)

        stills, low, videos = await find(service, session_maker=session_maker)
        assert stills >= 1 and videos >= 1
        assert service.has_video(still_id)

        await find(service, delete=True, session_maker=session_maker)
        assert not service.has_video(still_id)
        assert service.has_video(str(track_without_poster.id))
