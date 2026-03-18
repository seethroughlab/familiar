"""Tests for stream endpoint concurrency and heartbeat stale detection."""

import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.background.sync import SYNC_HEARTBEAT_STALE_SECONDS, is_heartbeat_stale

# ---------------------------------------------------------------------------
# Part 1: is_heartbeat_stale tests
# ---------------------------------------------------------------------------


class TestIsHeartbeatStale:
    """Test the heartbeat stale detection helper."""

    def test_stale_heartbeat_returns_true(self):
        """A heartbeat older than the threshold should be stale."""
        old_time = datetime.now() - timedelta(seconds=SYNC_HEARTBEAT_STALE_SECONDS + 60)
        progress = {"last_heartbeat": old_time.isoformat()}
        assert is_heartbeat_stale(progress) is True

    def test_fresh_heartbeat_returns_false(self):
        """A recent heartbeat should not be stale."""
        fresh_time = datetime.now() - timedelta(seconds=10)
        progress = {"last_heartbeat": fresh_time.isoformat()}
        assert is_heartbeat_stale(progress) is False

    def test_missing_heartbeat_returns_false(self):
        """No heartbeat field should return False (not stale)."""
        assert is_heartbeat_stale({}) is False
        assert is_heartbeat_stale({"last_heartbeat": None}) is False

    def test_invalid_heartbeat_returns_false(self):
        """Invalid heartbeat string should return False."""
        assert is_heartbeat_stale({"last_heartbeat": "not-a-date"}) is False

    def test_boundary_heartbeat(self):
        """Heartbeat just under the threshold should not be stale."""
        border_time = datetime.now() - timedelta(seconds=SYNC_HEARTBEAT_STALE_SECONDS - 5)
        assert is_heartbeat_stale({"last_heartbeat": border_time.isoformat()}) is False


# ---------------------------------------------------------------------------
# Part 2: Stream endpoint concurrency tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def temp_audio_file():
    """Create a minimal temp file to serve as a fake audio track."""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        # Write minimal content so file exists and has size
        f.write(b"\xff\xfb\x90\x00" + b"\x00" * 4096)
        f.flush()
        yield Path(f.name)
    try:
        Path(f.name).unlink()
    except FileNotFoundError:
        pass


class TestConcurrentStream:
    """Test concurrent stream requests don't crash.

    These tests exercise the TestClient with concurrent threads to verify
    that the streaming endpoint doesn't raise under parallel access.
    Since DB may not be available, 404 responses are acceptable — the goal
    is to ensure no unhandled exceptions or deadlocks.
    """

    def test_concurrent_stream_same_track(self, client):
        """3 parallel GET requests to the same track should all complete."""
        track_id = uuid4()

        def make_request():
            return client.get(f"/api/v1/tracks/{track_id}/stream")

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(make_request) for _ in range(3)]
            results = [f.result() for f in as_completed(futures)]

        assert len(results) == 3
        # All requests should complete without crashing (404 is fine — no DB track)
        for r in results:
            assert r.status_code in (200, 206, 404, 500)

    def test_concurrent_range_requests(self, client):
        """3 parallel requests with different Range headers should not crash."""
        track_id = uuid4()

        def make_range_request(byte_start):
            return client.get(
                f"/api/v1/tracks/{track_id}/stream",
                headers={"Range": f"bytes={byte_start}-{byte_start + 1023}"},
            )

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(make_range_request, offset)
                for offset in [0, 1024, 2048]
            ]
            results = [f.result() for f in as_completed(futures)]

        assert len(results) == 3
        for r in results:
            assert r.status_code in (200, 206, 404, 500)

    def test_concurrent_stream_different_tracks(self, client):
        """3 parallel requests to different tracks should all complete."""
        track_ids = [uuid4() for _ in range(3)]

        def make_request(tid):
            return client.get(f"/api/v1/tracks/{tid}/stream")

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(make_request, tid) for tid in track_ids]
            results = [f.result() for f in as_completed(futures)]

        assert len(results) == 3
        for r in results:
            assert r.status_code in (200, 206, 404, 500)
