"""Tests for the export/import service (export_import.py).

Tests cover track matching, export functionality, import preview,
import execution with merge mode, and external track handling.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.db.models import (
    ExternalTrack,
    Profile,
    ProfilePlayHistory,
    Track,
)
from app.services.export_import import (
    EXPORT_VERSION,
    ExportImportService,
    ImportService,
    TrackMatcher,
)


class TestTrackMatcher:
    """Tests for TrackMatcher - matching track refs to local library."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.scalar = AsyncMock()
        return db

    @pytest.fixture
    def matcher(self, mock_db):
        return TrackMatcher(mock_db)

    @pytest.mark.asyncio
    async def test_match_by_isrc(self, matcher, mock_db):
        """Should match track by ISRC with 100% confidence."""
        local_track = MagicMock(spec=Track)
        local_track.id = uuid4()
        local_track.isrc = "USRC12345678"
        local_track.musicbrainz_track_id = None
        local_track.title = "Test Song"
        local_track.artist = "Test Artist"

        # Build cache
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [local_track]
        mock_db.execute.return_value = mock_result

        track_ref = {"isrc": "USRC12345678", "title": "Test Song", "artist": "Test Artist"}

        track, method, confidence = await matcher.match_track_ref(track_ref)

        assert track == local_track
        assert method == "isrc"
        assert confidence == 1.0

    @pytest.mark.asyncio
    async def test_match_by_musicbrainz_id(self, matcher, mock_db):
        """Should match track by MusicBrainz ID."""
        local_track = MagicMock(spec=Track)
        local_track.id = uuid4()
        local_track.isrc = None
        local_track.musicbrainz_track_id = "mb-12345"
        local_track.title = "Test Song"
        local_track.artist = "Test Artist"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [local_track]
        mock_db.execute.return_value = mock_result

        track_ref = {"musicbrainz_id": "mb-12345", "title": "Test Song", "artist": "Test Artist"}

        track, method, confidence = await matcher.match_track_ref(track_ref)

        assert track == local_track
        assert method == "musicbrainz"
        assert confidence == 1.0

    @pytest.mark.asyncio
    async def test_match_by_exact_title_artist(self, matcher, mock_db):
        """Should match track by exact title+artist."""
        local_track = MagicMock(spec=Track)
        local_track.id = uuid4()
        local_track.isrc = None
        local_track.musicbrainz_track_id = None
        local_track.title = "Test Song"
        local_track.artist = "Test Artist"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [local_track]
        mock_db.execute.return_value = mock_result

        track_ref = {"title": "Test Song", "artist": "Test Artist"}

        track, method, confidence = await matcher.match_track_ref(track_ref)

        assert track == local_track
        assert method == "exact"
        assert confidence == 1.0

    @pytest.mark.asyncio
    async def test_match_returns_none_when_no_match(self, matcher, mock_db):
        """Should return None when no match found."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        track_ref = {"title": "Unknown Song", "artist": "Unknown Artist"}

        track, method, confidence = await matcher.match_track_ref(track_ref)

        assert track is None
        assert method is None
        assert confidence is None

    @pytest.mark.asyncio
    async def test_match_batch_processes_multiple_refs(self, matcher, mock_db):
        """Should match multiple track references in batch."""
        track1 = MagicMock(spec=Track)
        track1.id = uuid4()
        track1.isrc = "ISRC1"
        track1.musicbrainz_track_id = None
        track1.title = "Song 1"
        track1.artist = "Artist 1"

        track2 = MagicMock(spec=Track)
        track2.id = uuid4()
        track2.isrc = "ISRC2"
        track2.musicbrainz_track_id = None
        track2.title = "Song 2"
        track2.artist = "Artist 2"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [track1, track2]
        mock_db.execute.return_value = mock_result

        refs = [
            {"isrc": "ISRC1", "title": "Song 1", "artist": "Artist 1"},
            {"isrc": "ISRC2", "title": "Song 2", "artist": "Artist 2"},
            {"title": "Unknown", "artist": "Unknown"},
        ]

        results = await matcher.match_batch(refs)

        assert len(results) == 3
        assert results[0][1] == track1  # First matched
        assert results[1][1] == track2  # Second matched
        assert results[2][1] is None  # Third not matched


class TestExportImportService:
    """Tests for ExportImportService export functionality."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.scalar = AsyncMock()
        return db

    @pytest.fixture
    def service(self, mock_db):
        return ExportImportService(mock_db)

    def test_build_track_ref(self, service):
        """Should build track reference with all identifiers."""
        track = MagicMock(spec=Track)
        track.isrc = "USRC12345678"
        track.musicbrainz_track_id = "mb-12345"
        track.title = "Test Song"
        track.artist = "Test Artist"
        track.album = "Test Album"
        track.duration_seconds = 180.5

        ref = service._build_track_ref(track)

        assert ref["isrc"] == "USRC12345678"
        assert ref["musicbrainz_id"] == "mb-12345"
        assert ref["title"] == "Test Song"
        assert ref["artist"] == "Test Artist"
        assert ref["album"] == "Test Album"
        assert ref["duration_seconds"] == 180.5

    @pytest.mark.asyncio
    async def test_export_profile_includes_metadata(self, service, mock_db):
        """Export should include version and profile metadata."""
        profile = MagicMock(spec=Profile)
        profile.id = uuid4()
        profile.name = "Test Profile"
        profile.color = "#ff0000"
        profile.settings = {"theme": "dark"}

        # Mock empty results for all sections
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        with patch("app.services.export_import.get_app_version", return_value="1.0.0"):
            export = await service.export_profile(
                profile,
                include_play_history=False,
                include_favorites=False,
                include_playlists=False,
                include_smart_playlists=False,
                include_proposed_changes=False,
                include_external_tracks=False,
            )

        assert export["version"] == EXPORT_VERSION
        assert "exported_at" in export
        assert export["familiar_version"] == "1.0.0"
        assert export["profile"]["name"] == "Test Profile"
        assert export["profile"]["color"] == "#ff0000"

    @pytest.mark.asyncio
    async def test_export_includes_chat_history_passthrough(self, service, mock_db):
        """Export should pass through chat history."""
        profile = MagicMock(spec=Profile)
        profile.id = uuid4()
        profile.name = "Test"
        profile.color = None
        profile.settings = {}

        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute.return_value = mock_result

        chat_history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        with patch("app.services.export_import.get_app_version", return_value="1.0.0"):
            export = await service.export_profile(
                profile,
                include_play_history=False,
                include_favorites=False,
                include_playlists=False,
                include_smart_playlists=False,
                include_proposed_changes=False,
                include_external_tracks=False,
                chat_history=chat_history,
            )

        assert export["chat_history"] == chat_history


class TestImportService:
    """Tests for ImportService import functionality."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.scalar = AsyncMock()
        return db

    @pytest.fixture
    def service(self, mock_db):
        return ImportService(mock_db)

    @pytest.mark.asyncio
    async def test_preview_import_returns_session_id(self, service, mock_db):
        """Preview should return session ID for later execution."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        import_data = {
            "version": EXPORT_VERSION,
            "exported_at": "2024-01-15T10:00:00Z",
            "profile": {"name": "Test"},
            "play_history": [],
            "favorites": [],
            "playlists": [],
        }

        session_id, preview = await service.preview_import(import_data)

        assert session_id is not None
        assert len(session_id) == 36  # UUID format
        assert preview["session_id"] == session_id

    @pytest.mark.asyncio
    async def test_preview_import_counts_items(self, service, mock_db):
        """Preview should count items in each section."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        import_data = {
            "version": EXPORT_VERSION,
            "exported_at": "2024-01-15T10:00:00Z",
            "profile": {"name": "Test"},
            "play_history": [
                {"track_ref": {"title": "Song 1", "artist": "Artist 1"}, "play_count": 5},
                {"track_ref": {"title": "Song 2", "artist": "Artist 2"}, "play_count": 3},
            ],
            "favorites": [
                {"track_ref": {"title": "Song 1", "artist": "Artist 1"}},
            ],
            "playlists": [
                {"name": "Playlist 1", "tracks": []},
                {"name": "Playlist 2", "tracks": []},
            ],
            "smart_playlists": [
                {"name": "Smart 1", "rules": []},
            ],
        }

        session_id, preview = await service.preview_import(import_data)

        assert preview["summary"]["play_history_count"] == 2
        assert preview["summary"]["favorites_count"] == 1
        assert preview["summary"]["playlists_count"] == 2
        assert preview["summary"]["smart_playlists_count"] == 1

    @pytest.mark.asyncio
    async def test_preview_import_reports_matching_stats(self, service, mock_db):
        """Preview should report matching statistics."""
        # Mock one track match
        local_track = MagicMock(spec=Track)
        local_track.id = uuid4()
        local_track.isrc = "ISRC1"
        local_track.musicbrainz_track_id = None
        local_track.title = "Song 1"
        local_track.artist = "Artist 1"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [local_track]
        mock_db.execute.return_value = mock_result

        import_data = {
            "version": EXPORT_VERSION,
            "exported_at": "2024-01-15T10:00:00Z",
            "profile": {"name": "Test"},
            "play_history": [
                {"track_ref": {"isrc": "ISRC1", "title": "Song 1", "artist": "Artist 1"}},
                {"track_ref": {"title": "Unknown", "artist": "Unknown"}},
            ],
            "favorites": [],
            "playlists": [],
        }

        session_id, preview = await service.preview_import(import_data)

        assert preview["matching"]["total"] == 2
        assert preview["matching"]["matched"] == 1
        assert preview["matching"]["unmatched"] == 1

    @pytest.mark.asyncio
    async def test_preview_import_warns_about_newer_version(self, service, mock_db):
        """Preview should warn about newer export version."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        import_data = {
            "version": EXPORT_VERSION + 1,  # Newer version
            "exported_at": "2024-01-15T10:00:00Z",
            "profile": {"name": "Test"},
        }

        session_id, preview = await service.preview_import(import_data)

        assert len(preview["warnings"]) > 0
        assert any("newer" in w.lower() for w in preview["warnings"])

    @pytest.mark.asyncio
    async def test_execute_import_invalid_session_raises(self, service, mock_db):
        """Execute should raise error for invalid session ID."""
        profile = MagicMock(spec=Profile)
        profile.id = uuid4()

        with pytest.raises(ValueError, match="not found"):
            await service.execute_import("invalid-session-id", profile)


class TestImportMergeMode:
    """Tests for import merge mode behavior."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.scalar = AsyncMock()
        return db

    @pytest.fixture
    def service(self, mock_db):
        return ImportService(mock_db)

    @pytest.mark.asyncio
    async def test_merge_play_history_adds_counts(self, service, mock_db):
        """Merge mode should add play counts together."""
        # This tests the internal _import_play_history method

        profile_id = uuid4()
        track_id = uuid4()

        # Mock existing play history record with timezone-aware datetime
        existing_record = MagicMock(spec=ProfilePlayHistory)
        existing_record.play_count = 5
        existing_record.total_play_seconds = 900
        existing_record.last_played_at = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

        # AsyncMock.execute returns a coroutine, so we need its result to be
        # something that has .scalar_one_or_none() as a sync method
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_record
        mock_db.execute = AsyncMock(return_value=mock_result)

        play_history = [
            {
                "track_ref": {"title": "Song", "artist": "Artist"},
                "play_count": 3,
                "total_play_seconds": 540,
                "last_played_at": "2024-01-15T12:00:00Z",
            }
        ]

        # Key format is "isrc:title:artist" lowercased
        track_id_lookup = {":song:artist": track_id}

        result = await service._import_play_history(
            profile_id, play_history, track_id_lookup, mode="merge"
        )

        # Play counts should be merged (5 + 3 = 8)
        assert existing_record.play_count == 8
        assert existing_record.total_play_seconds == 1440
        assert result["imported"] == 1


class TestImportExternalTracks:
    """Tests for external track import."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.scalar = AsyncMock()
        return db

    @pytest.fixture
    def service(self, mock_db):
        return ImportService(mock_db)

    @pytest.mark.asyncio
    async def test_get_or_create_external_track_creates_new(self, service, mock_db):
        """Should create new external track if not exists."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        ext_data = {
            "title": "Test Song",
            "artist": "Test Artist",
            "album": "Test Album",
            "spotify_id": "spotify_123",
            "source": "spotify_playlist",
        }

        await service._get_or_create_external_track(ext_data)

        mock_db.add.assert_called_once()
        added_track = mock_db.add.call_args[0][0]
        assert added_track.title == "Test Song"
        assert added_track.artist == "Test Artist"
        assert added_track.spotify_id == "spotify_123"

    @pytest.mark.asyncio
    async def test_get_or_create_external_track_returns_existing(self, service, mock_db):
        """Should return existing external track by spotify_id."""
        existing_track = MagicMock(spec=ExternalTrack)
        existing_track.id = uuid4()
        existing_track.spotify_id = "spotify_123"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_track
        mock_db.execute.return_value = mock_result

        ext_data = {
            "title": "Test Song",
            "artist": "Test Artist",
            "spotify_id": "spotify_123",
            "source": "spotify_playlist",
        }

        result = await service._get_or_create_external_track(ext_data)

        assert result == existing_track
        mock_db.add.assert_not_called()
