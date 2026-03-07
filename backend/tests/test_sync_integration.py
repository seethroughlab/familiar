"""Tests for library sync integration (tasks/).

Tests cover the SyncProgressReporter, sync flow, progress reporting, and failure handling.
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tasks import (
    MAX_FAILURES_STORED,
    SYNC_PROGRESS_KEY,
    TASK_FAILURES_KEY,
    SyncProgressReporter,
    _record_task_failure,
    clear_task_failures,
    get_recent_failures,
)


class TestSyncProgressReporter:
    """Tests for SyncProgressReporter class."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        mock = MagicMock()
        return mock

    @pytest.fixture
    def reporter(self, mock_redis):
        """Create SyncProgressReporter with mocked Redis."""
        with patch("app.services.tasks.library_sync.get_redis", return_value=mock_redis):
            return SyncProgressReporter()

    def test_init_sets_initial_progress(self, reporter, mock_redis):
        """Reporter should set initial progress state on init."""
        mock_redis.set.assert_called()
        call_args = mock_redis.set.call_args
        progress_data = json.loads(call_args[0][1])

        assert progress_data["status"] == "running"
        assert progress_data["phase"] == "starting"
        assert progress_data["files_discovered"] == 0
        assert progress_data["started_at"] is not None

    def test_set_discovering_updates_phase(self, reporter, mock_redis):
        """set_discovering should update to discovery phase."""
        reporter.set_discovering(dirs_scanned=10, files_found=500)

        call_args = mock_redis.set.call_args
        progress_data = json.loads(call_args[0][1])

        assert progress_data["phase"] == "discovering"
        assert progress_data["files_discovered"] == 500
        assert "10 dirs" in progress_data["phase_message"]

    def test_set_reading_updates_phase(self, reporter, mock_redis):
        """set_reading should update to reading phase with stats."""
        reporter.set_reading(
            processed=100,
            total=500,
            new=80,
            updated=15,
            unchanged=5,
            current="/path/to/song.mp3",
        )

        call_args = mock_redis.set.call_args
        progress_data = json.loads(call_args[0][1])

        assert progress_data["phase"] == "reading"
        assert progress_data["files_processed"] == 100
        assert progress_data["files_total"] == 500
        assert progress_data["new_tracks"] == 80
        assert progress_data["updated_tracks"] == 15
        assert progress_data["unchanged_tracks"] == 5
        assert progress_data["current_item"] == "/path/to/song.mp3"

    def test_set_reading_calculates_percentage(self, reporter, mock_redis):
        """set_reading should calculate progress percentage."""
        reporter.set_reading(processed=250, total=500, new=0, updated=0, unchanged=250)

        call_args = mock_redis.set.call_args
        progress_data = json.loads(call_args[0][1])

        assert "50%" in progress_data["phase_message"]

    def test_progress_includes_heartbeat(self, reporter, mock_redis):
        """All updates should include heartbeat timestamp."""
        reporter.set_discovering(dirs_scanned=1, files_found=10)

        call_args = mock_redis.set.call_args
        progress_data = json.loads(call_args[0][1])

        assert "last_heartbeat" in progress_data
        # Heartbeat should be recent (parseable as ISO datetime)
        datetime.fromisoformat(progress_data["last_heartbeat"])

    def test_progress_includes_errors(self, reporter, mock_redis):
        """Progress should include accumulated errors."""
        reporter.errors = ["Error 1", "Error 2"]
        reporter.set_reading(processed=10, total=100, new=0, updated=0, unchanged=0)

        call_args = mock_redis.set.call_args
        progress_data = json.loads(call_args[0][1])

        assert progress_data["errors"] == ["Error 1", "Error 2"]

    def test_progress_has_expiry(self, reporter, mock_redis):
        """Progress should have Redis expiry set."""
        call_args = mock_redis.set.call_args
        # Check that ex= parameter was passed
        assert "ex" in call_args[1] or call_args[0][2]  # Either kwargs or positional


class TestTaskFailureRecording:
    """Tests for task failure recording functionality."""

    @pytest.fixture
    def mock_redis(self):
        return MagicMock()

    def test_record_task_failure_pushes_to_list(self, mock_redis):
        """Should push failure to Redis list."""
        with patch("app.services.tasks.common.get_redis", return_value=mock_redis):
            _record_task_failure("analysis", "Audio file corrupted", "track_123")

            mock_redis.lpush.assert_called_once()
            call_args = mock_redis.lpush.call_args[0]
            assert call_args[0] == TASK_FAILURES_KEY

            failure_data = json.loads(call_args[1])
            assert failure_data["task"] == "analysis"
            assert failure_data["error"] == "Audio file corrupted"
            assert failure_data["track"] == "track_123"
            assert "timestamp" in failure_data

    def test_record_task_failure_trims_list(self, mock_redis):
        """Should trim failure list to max size."""
        with patch("app.services.tasks.common.get_redis", return_value=mock_redis):
            _record_task_failure("analysis", "Error")

            mock_redis.ltrim.assert_called_once_with(
                TASK_FAILURES_KEY, 0, MAX_FAILURES_STORED - 1
            )

    def test_record_task_failure_sets_expiry(self, mock_redis):
        """Should set 24-hour expiry on failures list."""
        with patch("app.services.tasks.common.get_redis", return_value=mock_redis):
            _record_task_failure("analysis", "Error")

            mock_redis.expire.assert_called_once_with(TASK_FAILURES_KEY, 86400)

    def test_record_task_failure_handles_redis_error(self, mock_redis):
        """Should handle Redis errors gracefully."""
        mock_redis.lpush.side_effect = Exception("Redis connection failed")

        with patch("app.services.tasks.common.get_redis", return_value=mock_redis):
            # Should not raise
            _record_task_failure("analysis", "Error")


class TestGetRecentFailures:
    """Tests for retrieving recent failures."""

    @pytest.fixture
    def mock_redis(self):
        return MagicMock()

    def test_get_recent_failures_returns_list(self, mock_redis):
        """Should return list of recent failures."""
        mock_redis.lrange.return_value = [
            json.dumps({"task": "analysis", "error": "Error 1"}).encode(),
            json.dumps({"task": "scan", "error": "Error 2"}).encode(),
        ]

        with patch("app.services.tasks.common.get_redis", return_value=mock_redis):
            failures = get_recent_failures(limit=10)

            assert len(failures) == 2
            assert failures[0]["task"] == "analysis"
            assert failures[1]["task"] == "scan"

    def test_get_recent_failures_respects_limit(self, mock_redis):
        """Should request limited number of failures."""
        mock_redis.lrange.return_value = []

        with patch("app.services.tasks.common.get_redis", return_value=mock_redis):
            get_recent_failures(limit=5)

            mock_redis.lrange.assert_called_once_with(TASK_FAILURES_KEY, 0, 4)

    def test_get_recent_failures_handles_redis_error(self, mock_redis):
        """Should return empty list on Redis error."""
        mock_redis.lrange.side_effect = Exception("Redis error")

        with patch("app.services.tasks.common.get_redis", return_value=mock_redis):
            failures = get_recent_failures()
            assert failures == []


class TestClearTaskFailures:
    """Tests for clearing task failures."""

    def test_clear_task_failures_deletes_key(self):
        """Should delete the failures key from Redis."""
        mock_redis = MagicMock()

        with patch("app.services.tasks.common.get_redis", return_value=mock_redis):
            clear_task_failures()

            mock_redis.delete.assert_called_once_with(TASK_FAILURES_KEY)

    def test_clear_task_failures_handles_error(self):
        """Should handle Redis errors gracefully."""
        mock_redis = MagicMock()
        mock_redis.delete.side_effect = Exception("Redis error")

        with patch("app.services.tasks.common.get_redis", return_value=mock_redis):
            # Should not raise
            clear_task_failures()


class TestSyncProgressPhases:
    """Tests for all sync progress phases."""

    @pytest.fixture
    def mock_redis(self):
        return MagicMock()

    @pytest.fixture
    def reporter(self, mock_redis):
        with patch("app.services.tasks.library_sync.get_redis", return_value=mock_redis):
            return SyncProgressReporter()

    def test_phase_transitions(self, reporter, mock_redis):
        """Should transition through all phases correctly."""
        # Phase 1: Discovering
        reporter.set_discovering(dirs_scanned=5, files_found=100)
        progress = json.loads(mock_redis.set.call_args[0][1])
        assert progress["phase"] == "discovering"

        # Phase 2: Reading
        reporter.set_reading(processed=50, total=100, new=40, updated=5, unchanged=5)
        progress = json.loads(mock_redis.set.call_args[0][1])
        assert progress["phase"] == "reading"

    def test_set_reading_with_recovered_tracks(self, reporter, mock_redis):
        """Should track recovered tracks."""
        reporter.set_reading(
            processed=100,
            total=100,
            new=50,
            updated=30,
            unchanged=15,
            recovered=5,
        )

        progress = json.loads(mock_redis.set.call_args[0][1])
        assert progress["recovered"] == 5


class TestProgressPersistence:
    """Tests for progress persistence via Redis."""

    def test_progress_stored_at_correct_key(self):
        """Progress should be stored at SYNC_PROGRESS_KEY."""
        mock_redis = MagicMock()

        with patch("app.services.tasks.library_sync.get_redis", return_value=mock_redis):
            SyncProgressReporter()

            call_args = mock_redis.set.call_args[0]
            assert call_args[0] == SYNC_PROGRESS_KEY

    def test_progress_is_json_serializable(self):
        """All progress updates should be valid JSON."""
        mock_redis = MagicMock()

        with patch("app.services.tasks.library_sync.get_redis", return_value=mock_redis):
            reporter = SyncProgressReporter()
            reporter.set_discovering(10, 500)
            reporter.set_reading(100, 500, 80, 15, 5)

            # All calls should have valid JSON
            for call in mock_redis.set.call_args_list:
                json_str = call[0][1]
                # Should not raise
                data = json.loads(json_str)
                assert isinstance(data, dict)


class TestSpotifySyncProgressReporter:
    """Tests for SpotifySyncProgressReporter class."""

    @pytest.fixture
    def mock_redis(self):
        return MagicMock()

    @pytest.fixture
    def reporter(self, mock_redis):
        with patch("app.services.tasks.spotify_sync.get_redis", return_value=mock_redis):
            from app.services.tasks import SpotifySyncProgressReporter
            return SpotifySyncProgressReporter(profile_id="test-profile-123")

    def test_init_sets_connecting_phase(self, reporter, mock_redis):
        """Should set initial connecting phase on init."""
        mock_redis.set.assert_called()
        call_args = mock_redis.set.call_args
        progress_data = json.loads(call_args[0][1])

        assert progress_data["status"] == "running"
        assert progress_data["phase"] == "connecting"
        assert progress_data["profile_id"] == "test-profile-123"
        assert progress_data["tracks_fetched"] == 0

    def test_set_fetching(self, reporter, mock_redis):
        """Should update to fetching phase."""
        reporter.set_fetching(fetched=50, message="Fetching...")

        progress_data = json.loads(mock_redis.set.call_args[0][1])

        assert progress_data["phase"] == "fetching"
        assert progress_data["tracks_fetched"] == 50
        assert progress_data["message"] == "Fetching..."

    def test_set_matching(self, reporter, mock_redis):
        """Should update matching progress with percentage."""
        reporter.set_matching(processed=50, total=100, new=10, matched=40, unmatched=10, current="Some Track")

        progress_data = json.loads(mock_redis.set.call_args[0][1])

        assert progress_data["phase"] == "matching"
        assert progress_data["tracks_processed"] == 50
        assert progress_data["matched"] == 40
        assert "50%" in progress_data["message"]
        assert progress_data["current_track"] == "Some Track"

    def test_complete(self, reporter, mock_redis):
        """Should mark sync as complete."""
        reporter.complete(fetched=200, new=50, matched=150, unmatched=50)

        progress_data = json.loads(mock_redis.set.call_args[0][1])

        assert progress_data["status"] == "completed"
        assert progress_data["phase"] == "complete"
        assert progress_data["matched"] == 150

    def test_error(self, reporter, mock_redis):
        """Should set error status."""
        # Mock _get_current to return initial state
        mock_redis.get.return_value = json.dumps({
            "status": "running",
            "phase": "fetching",
            "errors": [],
        }).encode()

        reporter.error("Connection failed")

        progress_data = json.loads(mock_redis.set.call_args[0][1])

        assert progress_data["status"] == "error"
        assert "Connection failed" in progress_data["errors"]

    def test_error_preserves_existing_data(self, reporter, mock_redis):
        """Error should preserve existing progress data."""
        mock_redis.get.return_value = json.dumps({
            "status": "running",
            "phase": "matching",
            "matched": 50,
            "errors": ["previous error"],
        }).encode()

        reporter.error("New error")

        progress_data = json.loads(mock_redis.set.call_args[0][1])

        assert progress_data["matched"] == 50
        assert len(progress_data["errors"]) == 2


class TestGetSyncProgress:
    """Tests for get_sync_progress function."""

    def test_returns_data(self):
        """Should return parsed progress data."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps({"status": "running", "phase": "reading"}).encode()

        with patch("app.services.tasks.library_sync.get_redis", return_value=mock_redis):
            from app.services.tasks import get_sync_progress
            result = get_sync_progress()

        assert result is not None
        assert result["status"] == "running"

    def test_handles_redis_error(self):
        """Should return None on Redis error."""
        mock_redis = MagicMock()
        mock_redis.get.side_effect = Exception("Redis down")

        with patch("app.services.tasks.library_sync.get_redis", return_value=mock_redis):
            from app.services.tasks import get_sync_progress
            result = get_sync_progress()

        assert result is None


class TestGetSpotifySyncProgress:
    """Tests for get_spotify_sync_progress function."""

    def test_returns_data(self):
        """Should return parsed Spotify sync progress."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps({"status": "running", "matched": 50}).encode()

        with patch("app.services.tasks.spotify_sync.get_redis", return_value=mock_redis):
            from app.services.tasks import get_spotify_sync_progress
            result = get_spotify_sync_progress()

        assert result is not None
        assert result["matched"] == 50


class TestGetMemoryMb:
    """Tests for get_memory_mb function."""

    def test_returns_float(self):
        """Should return memory as float."""
        from app.services.tasks import get_memory_mb
        result = get_memory_mb()
        assert isinstance(result, float)
        assert result >= 0

    def test_returns_positive_on_success(self):
        """Should return memory as positive value on macOS/Linux."""
        from app.services.tasks import get_memory_mb
        result = get_memory_mb()
        # On any real system running tests, memory should be > 0
        assert result > 0


class TestLogMemory:
    """Tests for log_memory function."""

    def test_calls_get_memory_and_logs(self):
        """Should log memory usage with label."""
        with patch("app.services.tasks.common.get_memory_mb", return_value=256.5), \
             patch("app.services.tasks.common.logger") as mock_logger:
            from app.services.tasks import log_memory
            log_memory("test phase")

            mock_logger.info.assert_called_once()
            call_msg = mock_logger.info.call_args[0][0]
            assert "256.5" in call_msg
            assert "test phase" in call_msg


class TestQueueTracksForFeatures:
    """Tests for queue_tracks_for_features function."""

    @pytest.mark.asyncio
    async def test_queues_tracks(self):
        """Should queue tracks needing feature extraction."""
        track_id = "12345678-1234-1234-1234-123456789abc"

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(track_id,)]
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_manager = MagicMock()
        mock_manager.run_analysis = AsyncMock()

        with patch("app.db.session.async_session_maker", return_value=mock_session), \
             patch("app.services.background.get_background_manager", return_value=mock_manager):
            from app.services.tasks import queue_tracks_for_features
            queued = await queue_tracks_for_features(limit=10)

        assert queued == 1
        mock_manager.run_analysis.assert_called_once_with(track_id, phase="features")

    @pytest.mark.asyncio
    async def test_empty_queue(self):
        """Should return 0 when no tracks need analysis."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.session.async_session_maker", return_value=mock_session):
            from app.services.tasks import queue_tracks_for_features
            queued = await queue_tracks_for_features()

        assert queued == 0


class TestQueueTracksForEmbeddings:
    """Tests for queue_tracks_for_embeddings function."""

    @pytest.mark.asyncio
    async def test_queues_tracks(self):
        """Should queue tracks needing embeddings."""
        track_id = "12345678-1234-1234-1234-123456789abc"

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(track_id,)]
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_manager = MagicMock()
        mock_manager.run_analysis = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.is_clap_embeddings_enabled.return_value = (True, "enabled")

        with patch("app.db.session.async_session_maker", return_value=mock_session), \
             patch("app.services.background.get_background_manager", return_value=mock_manager), \
             patch("app.services.app_settings.get_app_settings_service", return_value=mock_settings):
            from app.services.tasks import queue_tracks_for_embeddings
            queued = await queue_tracks_for_embeddings(limit=10)

        assert queued == 1
        mock_manager.run_analysis.assert_called_once_with(track_id, phase="embedding")

    @pytest.mark.asyncio
    async def test_disabled_clap(self):
        """Should return 0 when CLAP is disabled."""
        mock_settings = MagicMock()
        mock_settings.is_clap_embeddings_enabled.return_value = (False, "disabled")

        with patch("app.services.app_settings.get_app_settings_service", return_value=mock_settings):
            from app.services.tasks import queue_tracks_for_embeddings
            queued = await queue_tracks_for_embeddings()

        assert queued == 0
