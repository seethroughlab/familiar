"""`app.cli.match_music_videos` — who is asked about, and what the loop does with the answers.

Search and download are injected, so nothing here reaches YouTube or runs yt-dlp.
"""

import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.cli.match_music_videos import Candidate, candidates, run
from app.config import settings
from app.db.models import ProfileFavorite, ProfilePlayHistory, TrackVideo
from app.services.video import VideoDownloadStatus, VideoSearchResult, VideoSearchUnavailable
from app.utils.time import utcnow
from tests.factories import insert_test_profile, insert_test_track


def result(title, channel="ArtistVEVO", duration=180, video_id="v1"):
    return VideoSearchResult(
        video_id=video_id, title=title, channel=channel, duration=duration,
        thumbnail_url="", url=f"https://www.youtube.com/watch?v={video_id}",
    )


def candidate(track_id="00000000-0000-0000-0000-000000000001", title="Evil", artist="Interpol"):
    from uuid import UUID

    return Candidate(
        track_id=UUID(track_id), title=title, artist=artist, duration_seconds=220.0,
        plays=5, favourite=True,
    )


@pytest.fixture()
async def session_maker():
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


class TestCandidates:
    @pytest.mark.asyncio
    async def test_favourites_and_played_tracks_without_a_video_most_played_first(
        self, async_db, session_maker
    ):
        profile = await insert_test_profile(async_db, name="Batch")
        favourite = await insert_test_track(async_db, title="Kept", artist="A")
        played = await insert_test_track(async_db, title="Worn out", artist="B")
        barely = await insert_test_track(async_db, title="Once", artist="C")
        has_video = await insert_test_track(async_db, title="Seen", artist="D")
        nobody = await insert_test_track(async_db, title="Unloved", artist="E")
        await async_db.flush()
        async_db.add_all([
            ProfileFavorite(profile_id=profile.id, track_id=favourite.id),
            ProfileFavorite(profile_id=profile.id, track_id=has_video.id),
            ProfilePlayHistory(profile_id=profile.id, track_id=played.id, play_count=9),
            ProfilePlayHistory(profile_id=profile.id, track_id=barely.id, play_count=1),
            ProfilePlayHistory(profile_id=profile.id, track_id=favourite.id, play_count=2),
            TrackVideo(track_id=has_video.id, source="youtube", source_id="x", file_path="/v.mp4",
                       downloaded_at=utcnow()),
        ])
        await async_db.commit()

        picks = await candidates(session_maker, profile.id, min_plays=3, limit=50)
        ids = [c.track_id for c in picks]

        assert ids[:2] == [played.id, favourite.id]  # 9 plays, then 2
        assert barely.id not in ids  # one play and not a favourite
        assert has_video.id not in ids  # already has one
        assert nobody.id not in ids
        assert picks[1].favourite and picks[1].plays == 2


class TestRun:
    @pytest.mark.asyncio
    async def test_a_confident_match_is_downloaded_and_logged(self, tmp_path):
        downloads = []

        async def search(query):
            assert query == "Interpol Evil official music video"
            return [result("Interpol - Evil (Official Video)", duration=221, video_id="abc")]

        async def download(track_id, url):
            downloads.append((track_id, url))
            return VideoDownloadStatus(track_id=track_id, video_id="abc", status="complete", progress=100)

        log = tmp_path / "match-log.jsonl"
        tally = await run([candidate()], search=search, download=download, log_path=log)

        assert tally.matched == 1
        assert downloads == [("00000000-0000-0000-0000-000000000001", "https://www.youtube.com/watch?v=abc")]
        entry = json.loads(log.read_text().strip())
        assert entry["decision"] == "matched" and entry["video_id"] == "abc"

    @pytest.mark.asyncio
    async def test_a_doubtful_result_is_skipped_with_its_reason(self, tmp_path):
        async def search(query):
            return [result("Interpol - Evil (Live at Reading)", duration=221)]

        async def download(track_id, url):
            raise AssertionError("must not download a skipped track")

        log = tmp_path / "match-log.jsonl"
        tally = await run([candidate()], search=search, download=download, log_path=log)

        assert tally.skipped == 1
        entry = json.loads(log.read_text().strip())
        assert entry["decision"] == "skipped" and "live" in entry["reason"]

    @pytest.mark.asyncio
    async def test_dry_run_decides_but_downloads_and_logs_nothing(self, tmp_path):
        """Skips included: the first dry run on the NAS logged its skips, and the real run that
        followed would have passed over every track it had already looked at."""
        async def search(query):
            if "Evil" in query:
                return [result("Interpol - Evil (Official Video)", duration=221)]
            return [result("Interpol - PDA (Live)", duration=221)]

        async def download(track_id, url):
            raise AssertionError("dry run must not download")

        log = tmp_path / "match-log.jsonl"
        picks = [candidate(), candidate(track_id="00000000-0000-0000-0000-000000000002", title="PDA")]
        tally = await run(picks, search=search, download=download, log_path=log, dry_run=True)

        assert (tally.matched, tally.skipped) == (1, 1)
        assert not log.exists()

    @pytest.mark.asyncio
    async def test_a_logged_track_is_not_asked_about_again(self, tmp_path):
        log = tmp_path / "match-log.jsonl"
        log.write_text(json.dumps({"track_id": "00000000-0000-0000-0000-000000000001",
                                   "decision": "skipped"}) + "\n")

        async def search(query):
            raise AssertionError("already in the log")

        async def download(track_id, url):
            raise AssertionError("already in the log")

        tally = await run([candidate()], search=search, download=download, log_path=log)
        assert tally.already_logged == 1

        # `--retry` asks again.
        asked = []

        async def search_again(query):
            asked.append(query)
            return []

        await run([candidate()], search=search_again, download=download, log_path=log, retry=True)
        assert asked == ["Interpol Evil official music video"]

    @pytest.mark.asyncio
    async def test_three_search_failures_in_a_row_stop_the_run(self, tmp_path):
        asked = []

        async def search(query):
            asked.append(query)
            raise VideoSearchUnavailable("blocked")

        async def download(track_id, url):
            raise AssertionError("nothing to download")

        picks = [candidate(track_id=f"00000000-0000-0000-0000-00000000000{i}") for i in range(1, 6)]
        tally = await run(picks, search=search, download=download, log_path=tmp_path / "log")

        assert len(asked) == 3
        assert tally.failed == 3

    @pytest.mark.asyncio
    async def test_a_failed_download_is_logged_as_failed(self, tmp_path):
        async def search(query):
            return [result("Interpol - Evil (Official Video)", duration=221, video_id="abc")]

        async def download(track_id, url):
            return VideoDownloadStatus(track_id=track_id, video_id="abc", status="error",
                                       progress=0, error="Requested format is not available")

        log = tmp_path / "match-log.jsonl"
        tally = await run([candidate()], search=search, download=download, log_path=log)

        assert tally.failed == 1
        entry = json.loads(log.read_text().strip())
        assert entry["decision"] == "failed" and "format" in entry["reason"]
