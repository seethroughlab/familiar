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


class TestRefToKey:
    """Tests for ImportService._ref_to_key."""

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

    def test_lowercase_normalization(self, service):
        """Should lowercase all components."""
        ref = {"isrc": "USRC123", "title": "Test Song", "artist": "Artist"}
        key = service._ref_to_key(ref)
        assert key == "usrc123:test song:artist"

    def test_missing_fields(self, service):
        """Should handle missing fields gracefully."""
        ref = {"title": "Song"}
        key = service._ref_to_key(ref)
        assert key == ":song:"


class TestBuildExternalTrackRef:
    """Tests for ExportImportService._build_external_track_ref."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute = AsyncMock()
        return db

    @pytest.fixture
    def service(self, mock_db):
        return ExportImportService(mock_db)

    def test_maps_all_fields(self, service):
        """Should map all ExternalTrack fields correctly."""
        ext = MagicMock(spec=ExternalTrack)
        ext.title = "External Song"
        ext.artist = "External Artist"
        ext.album = "External Album"
        ext.duration_seconds = 200
        ext.track_number = 3
        ext.year = 2023
        ext.isrc = "ISRC123"
        ext.spotify_id = "sp_456"
        ext.musicbrainz_recording_id = "mb_789"
        ext.deezer_id = "dz_101"
        ext.preview_url = "https://preview.example.com"
        ext.preview_source = "spotify"
        ext.external_data = {"key": "value"}
        ext.source = MagicMock()
        ext.source.value = "spotify_playlist"

        ref = service._build_external_track_ref(ext)

        assert ref["title"] == "External Song"
        assert ref["spotify_id"] == "sp_456"
        assert ref["source"] == "spotify_playlist"
        assert ref["external_data"] == {"key": "value"}


class TestExportPlayHistory:
    """Tests for ExportImportService._export_play_history."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute = AsyncMock()
        return db

    @pytest.fixture
    def service(self, mock_db):
        return ExportImportService(mock_db)

    @pytest.mark.asyncio
    async def test_exports_play_history(self, service, mock_db):
        """Should format play history with track refs."""
        ph = MagicMock()
        ph.play_count = 15
        ph.last_played_at = datetime(2024, 6, 15, 10, 0, 0)
        ph.total_play_seconds = 2700

        track = MagicMock(spec=Track)
        track.isrc = "ISRC1"
        track.musicbrainz_track_id = None
        track.title = "Song"
        track.artist = "Artist"
        track.album = "Album"
        track.duration_seconds = 180

        mock_result = MagicMock()
        mock_result.all.return_value = [(ph, track)]
        mock_db.execute.return_value = mock_result

        result = await service._export_play_history(uuid4())

        assert len(result) == 1
        assert result[0]["play_count"] == 15
        assert result[0]["total_play_seconds"] == 2700
        assert "Z" in result[0]["last_played_at"]
        assert result[0]["track_ref"]["title"] == "Song"


class TestExportFavorites:
    """Tests for ExportImportService._export_favorites."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute = AsyncMock()
        return db

    @pytest.fixture
    def service(self, mock_db):
        return ExportImportService(mock_db)

    @pytest.mark.asyncio
    async def test_exports_favorites(self, service, mock_db):
        """Should format favorites with track refs."""
        fav = MagicMock()
        fav.favorited_at = datetime(2024, 3, 1, 12, 0, 0)

        track = MagicMock(spec=Track)
        track.isrc = None
        track.musicbrainz_track_id = None
        track.title = "Fav Song"
        track.artist = "Fav Artist"
        track.album = "Fav Album"
        track.duration_seconds = 240

        mock_result = MagicMock()
        mock_result.all.return_value = [(fav, track)]
        mock_db.execute.return_value = mock_result

        result = await service._export_favorites(uuid4())

        assert len(result) == 1
        assert result[0]["track_ref"]["title"] == "Fav Song"
        assert "Z" in result[0]["favorited_at"]


class TestExportPlaylists:
    """Tests for ExportImportService._export_playlists."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute = AsyncMock()
        db.get = AsyncMock()
        return db

    @pytest.fixture
    def service(self, mock_db):
        return ExportImportService(mock_db)

    @pytest.mark.asyncio
    async def test_exports_local_tracks(self, service, mock_db):
        """Should export playlists with local track refs."""
        playlist = MagicMock()
        playlist.id = uuid4()
        playlist.name = "My Playlist"
        playlist.description = "desc"
        playlist.is_auto_generated = False
        playlist.is_wishlist = False
        playlist.generation_prompt = None
        playlist.created_at = datetime(2024, 1, 1)

        pt = MagicMock()
        pt.track_id = uuid4()
        pt.external_track_id = None
        pt.position = 0

        track = MagicMock(spec=Track)
        track.isrc = None
        track.musicbrainz_track_id = None
        track.title = "Track 1"
        track.artist = "Artist 1"
        track.album = "Album 1"
        track.duration_seconds = 180

        # First: playlists, second: playlist tracks
        mock_db.execute.side_effect = [
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[playlist])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[pt])))),
        ]
        mock_db.get.return_value = track

        result = await service._export_playlists(uuid4())

        assert len(result) == 1
        assert result[0]["name"] == "My Playlist"
        assert len(result[0]["tracks"]) == 1
        assert result[0]["tracks"][0]["type"] == "local"

    @pytest.mark.asyncio
    async def test_exports_external_tracks(self, service, mock_db):
        """Should export playlists with external track refs."""
        playlist = MagicMock()
        playlist.id = uuid4()
        playlist.name = "Mixed"
        playlist.description = None
        playlist.is_auto_generated = True
        playlist.is_wishlist = False
        playlist.generation_prompt = "test"
        playlist.created_at = None

        pt = MagicMock()
        pt.track_id = None
        pt.external_track_id = uuid4()
        pt.position = 0

        ext_track = MagicMock(spec=ExternalTrack)
        ext_track.title = "Ext Song"
        ext_track.artist = "Ext Artist"
        ext_track.album = None
        ext_track.duration_seconds = 200
        ext_track.track_number = None
        ext_track.year = None
        ext_track.isrc = None
        ext_track.spotify_id = "sp_1"
        ext_track.musicbrainz_recording_id = None
        ext_track.deezer_id = None
        ext_track.preview_url = None
        ext_track.preview_source = None
        ext_track.external_data = None
        ext_track.source = MagicMock()
        ext_track.source.value = "spotify_playlist"

        mock_db.execute.side_effect = [
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[playlist])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[pt])))),
        ]
        mock_db.get.return_value = ext_track

        result = await service._export_playlists(uuid4())

        assert result[0]["tracks"][0]["type"] == "external"


class TestExportSmartPlaylists:
    """Tests for ExportImportService._export_smart_playlists."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute = AsyncMock()
        return db

    @pytest.fixture
    def service(self, mock_db):
        return ExportImportService(mock_db)

    @pytest.mark.asyncio
    async def test_preserves_rules(self, service, mock_db):
        """Should export smart playlists with rules preserved."""
        sp = MagicMock()
        sp.name = "High Energy"
        sp.description = "Energetic tracks"
        sp.rules = [{"field": "energy", "operator": ">=", "value": 0.8}]
        sp.match_mode = "all"
        sp.order_by = "energy"
        sp.order_direction = "desc"
        sp.max_tracks = 50

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sp]
        mock_db.execute.return_value = mock_result

        result = await service._export_smart_playlists(uuid4())

        assert len(result) == 1
        assert result[0]["name"] == "High Energy"
        assert result[0]["rules"] == [{"field": "energy", "operator": ">=", "value": 0.8}]
        assert result[0]["max_tracks"] == 50


class TestImportFavorites:
    """Tests for ImportService._import_favorites."""

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
    async def test_creates_new_favorite(self, service, mock_db):
        """Should create new favorite when not existing."""
        profile_id = uuid4()
        track_id = uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        favorites = [
            {"track_ref": {"title": "Song", "artist": "Artist"}, "favorited_at": "2024-01-15T12:00:00Z"}
        ]
        track_id_lookup = {":song:artist": track_id}

        result = await service._import_favorites(profile_id, favorites, track_id_lookup, mode="merge")

        assert result["imported"] == 1
        assert result["skipped"] == 0
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_existing_favorite(self, service, mock_db):
        """Should skip existing favorites in merge mode."""
        profile_id = uuid4()
        track_id = uuid4()

        existing_fav = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_fav
        mock_db.execute.return_value = mock_result

        favorites = [
            {"track_ref": {"title": "Song", "artist": "Artist"}}
        ]
        track_id_lookup = {":song:artist": track_id}

        result = await service._import_favorites(profile_id, favorites, track_id_lookup, mode="merge")

        assert result["imported"] == 0
        assert result["skipped"] == 1


class TestImportPlaylists:
    """Tests for ImportService._import_playlists."""

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
    async def test_creates_with_tracks(self, service, mock_db):
        """Should create playlist with local tracks."""
        profile_id = uuid4()
        track_id = uuid4()

        # No existing playlist
        mock_db.execute.return_value = MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)
        )

        playlists = [{
            "name": "New Playlist",
            "description": "Test",
            "is_wishlist": False,
            "is_auto_generated": False,
            "tracks": [
                {
                    "type": "local",
                    "track_ref": {"title": "Song", "artist": "Artist"},
                    "position": 0,
                },
            ],
        }]
        track_id_lookup = {":song:artist": track_id}

        result = await service._import_playlists(profile_id, playlists, track_id_lookup, mode="merge")

        assert result["imported"] == 1
        # Should have added playlist + track
        assert mock_db.add.call_count >= 2

    @pytest.mark.asyncio
    async def test_merge_skips_existing(self, service, mock_db):
        """Should skip existing playlists in merge mode."""
        profile_id = uuid4()

        existing_playlist = MagicMock()
        mock_db.execute.return_value = MagicMock(
            scalar_one_or_none=MagicMock(return_value=existing_playlist)
        )

        playlists = [{"name": "Existing Playlist", "is_wishlist": False, "tracks": []}]

        result = await service._import_playlists(profile_id, playlists, {}, mode="merge")

        assert result["skipped"] == 1
        assert result["imported"] == 0

    @pytest.mark.asyncio
    async def test_wishlist_creates_if_not_exists(self, service, mock_db):
        """Should create wishlist if one doesn't exist."""
        profile_id = uuid4()

        mock_db.execute.return_value = MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)
        )

        playlists = [{"name": "Wishlist", "is_wishlist": True, "tracks": []}]

        result = await service._import_playlists(profile_id, playlists, {}, mode="merge")

        assert result["imported"] == 1


class TestImportSmartPlaylists:
    """Tests for ImportService._import_smart_playlists."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        return db

    @pytest.fixture
    def service(self, mock_db):
        return ImportService(mock_db)

    @pytest.mark.asyncio
    async def test_creates_new(self, service, mock_db):
        """Should create new smart playlist."""
        profile_id = uuid4()

        mock_db.execute.return_value = MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)
        )

        smart_playlists = [{
            "name": "High Energy",
            "description": "Energetic tracks",
            "rules": [{"field": "energy", "operator": ">=", "value": 0.8}],
            "match_mode": "all",
            "order_by": "energy",
            "order_direction": "desc",
            "max_tracks": 50,
        }]

        result = await service._import_smart_playlists(profile_id, smart_playlists, mode="merge")

        assert result["imported"] == 1
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_merge_skips_existing(self, service, mock_db):
        """Should skip existing smart playlists in merge mode."""
        profile_id = uuid4()

        existing_sp = MagicMock()
        mock_db.execute.return_value = MagicMock(
            scalar_one_or_none=MagicMock(return_value=existing_sp)
        )

        smart_playlists = [{"name": "Existing", "rules": []}]

        result = await service._import_smart_playlists(profile_id, smart_playlists, mode="merge")

        assert result["skipped"] == 1
        assert result["imported"] == 0


class TestLibraryExportBuildTrackExport:
    """Tests for LibraryExportService._build_track_export."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute = AsyncMock()
        return db

    @pytest.fixture
    def service(self, mock_db):
        from app.services.export_import import LibraryExportService
        return LibraryExportService(mock_db)

    def test_basic_track(self, service):
        """Should export basic track metadata."""
        track = MagicMock(spec=Track)
        track.file_hash = "abc123"
        track.isrc = "ISRC1"
        track.musicbrainz_track_id = "mb1"
        track.title = "Song"
        track.artist = "Artist"
        track.album = "Album"
        track.duration_seconds = 200
        track.album_artist = "Artist"
        track.track_number = 1
        track.disc_number = 1
        track.year = 2020
        track.genre = "Rock"
        track.musicbrainz_artist_id = None
        track.musicbrainz_album_id = None
        track.composer = None
        track.conductor = None
        track.lyricist = None
        track.user_overrides = None

        result = service._build_track_export(track, None, include_embeddings=True, include_acoustid=True)

        assert result["file_hash"] == "abc123"
        assert result["title"] == "Song"
        assert result["metadata"]["year"] == 2020
        assert "analysis" not in result

    def test_with_analysis(self, service):
        """Should include analysis features when available."""
        track = MagicMock(spec=Track)
        track.file_hash = None
        track.isrc = None
        track.musicbrainz_track_id = None
        track.title = "Song"
        track.artist = "Artist"
        track.album = "Album"
        track.duration_seconds = 200
        track.album_artist = None
        track.track_number = None
        track.disc_number = None
        track.year = None
        track.genre = None
        track.musicbrainz_artist_id = None
        track.musicbrainz_album_id = None
        track.composer = None
        track.conductor = None
        track.lyricist = None
        track.user_overrides = None

        analysis = MagicMock()
        analysis.version = 5
        analysis.features = {"bpm": 120}
        analysis.embedding = None
        analysis.acoustid = "fingerprint_data_abc"
        analysis.acoustid_lookup = {"recording_id": "mb123"}

        result = service._build_track_export(track, analysis, include_embeddings=True, include_acoustid=True)

        assert result["analysis"]["version"] == 5
        assert result["analysis"]["features"] == {"bpm": 120}
        assert result["analysis"]["acoustid"] == "fingerprint_data_abc"

    def test_with_embedding(self, service):
        """Should include embedding when requested."""
        track = MagicMock(spec=Track)
        track.file_hash = None
        track.isrc = None
        track.musicbrainz_track_id = None
        track.title = "Song"
        track.artist = "Artist"
        track.album = "Album"
        track.duration_seconds = 200
        track.album_artist = None
        track.track_number = None
        track.disc_number = None
        track.year = None
        track.genre = None
        track.musicbrainz_artist_id = None
        track.musicbrainz_album_id = None
        track.composer = None
        track.conductor = None
        track.lyricist = None
        track.user_overrides = None

        analysis = MagicMock()
        analysis.version = 5
        analysis.features = {}
        analysis.embedding = MagicMock()
        analysis.embedding.tolist.return_value = [0.1, 0.2, 0.3]
        analysis.acoustid = None
        analysis.acoustid_lookup = None

        result = service._build_track_export(track, analysis, include_embeddings=True, include_acoustid=False)

        assert result["analysis"]["embedding"] == [0.1, 0.2, 0.3]


class TestLibraryImportBuildLocalIndexes:
    """Tests for LibraryImportService._build_local_indexes."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute = AsyncMock()
        return db

    @pytest.fixture
    def service(self, mock_db):
        from app.services.export_import import LibraryImportService
        return LibraryImportService(mock_db)

    @pytest.mark.asyncio
    async def test_builds_all_indexes(self, service, mock_db):
        """Should build file_hash, isrc, musicbrainz, exact, and acoustid indexes."""
        track_id = uuid4()

        track_row = MagicMock()
        track_row.id = track_id
        track_row.file_hash = "hash123"
        track_row.isrc = "ISRC1"
        track_row.musicbrainz_track_id = "mb1"
        track_row.title = "Song"
        track_row.artist = "Artist"
        track_row.duration_seconds = 200.5

        analysis_row = MagicMock()
        analysis_row.track_id = track_id
        analysis_row.acoustid = "a" * 150  # Long fingerprint

        mock_db.execute.side_effect = [
            MagicMock(all=MagicMock(return_value=[track_row])),
            MagicMock(all=MagicMock(return_value=[analysis_row])),
        ]

        indexes = await service._build_local_indexes()

        assert indexes["file_hash"]["hash123"] == track_id
        assert indexes["isrc"]["ISRC1"] == track_id
        assert indexes["musicbrainz"]["mb1"] == track_id
        assert indexes["exact"]["song:artist:200"] == track_id
        assert indexes["acoustid"]["a" * 100] == track_id


class TestLibraryImportMatchTrack:
    """Tests for LibraryImportService._match_track."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute = AsyncMock()
        return db

    @pytest.fixture
    def service(self, mock_db):
        from app.services.export_import import LibraryImportService
        return LibraryImportService(mock_db)

    @pytest.fixture
    def indexes(self):
        track_id = uuid4()
        # acoustid key is first 100 chars of fingerprint
        acoustid_fp = "a" * 100
        return {
            "file_hash": {"hash123": track_id},
            "acoustid": {acoustid_fp: track_id},
            "isrc": {"ISRC1": track_id},
            "musicbrainz": {"mb1": track_id},
            "exact": {"song:artist:200": track_id},
            "_track_id": track_id,  # helper for assertions
            "_acoustid_fp": acoustid_fp,
        }

    @pytest.mark.asyncio
    async def test_match_by_file_hash(self, service, indexes):
        """Should match by file_hash with confidence 1.0."""
        export_track = {"file_hash": "hash123", "title": "Song", "artist": "Artist"}
        tid, method, conf = await service._match_track(export_track, indexes)
        assert tid == indexes["_track_id"]
        assert method == "file_hash"
        assert conf == 1.0

    @pytest.mark.asyncio
    async def test_match_by_acoustid(self, service, indexes):
        """Should match by acoustid with confidence 0.95."""
        # Full fingerprint is longer, but _match_track takes first 100 chars
        full_fp = indexes["_acoustid_fp"] + "extra_data_beyond_100"
        export_track = {"analysis": {"acoustid": full_fp}, "title": "Song", "artist": "Artist"}
        tid, method, conf = await service._match_track(export_track, indexes)
        assert tid == indexes["_track_id"]
        assert method == "acoustid"
        assert conf == 0.95

    @pytest.mark.asyncio
    async def test_match_by_isrc(self, service, indexes):
        """Should match by ISRC with confidence 0.95."""
        export_track = {"isrc": "ISRC1", "title": "Song", "artist": "Artist"}
        tid, method, conf = await service._match_track(export_track, indexes)
        assert tid == indexes["_track_id"]
        assert method == "isrc"
        assert conf == 0.95

    @pytest.mark.asyncio
    async def test_match_by_musicbrainz(self, service, indexes):
        """Should match by MusicBrainz ID with confidence 0.95."""
        export_track = {"musicbrainz_track_id": "mb1", "title": "Song", "artist": "Artist"}
        tid, method, conf = await service._match_track(export_track, indexes)
        assert tid == indexes["_track_id"]
        assert method == "musicbrainz"
        assert conf == 0.95

    @pytest.mark.asyncio
    async def test_match_by_exact_with_duration(self, service, indexes):
        """Should match by title+artist+duration with confidence 0.90."""
        export_track = {"title": "Song", "artist": "Artist", "duration_seconds": 200}
        tid, method, conf = await service._match_track(export_track, indexes)
        assert tid == indexes["_track_id"]
        assert method == "exact_with_duration"
        assert conf == 0.90

    @pytest.mark.asyncio
    async def test_no_match(self, service, indexes):
        """Should return None when no match found."""
        export_track = {"title": "Unknown", "artist": "Unknown"}
        # Mock fuzzy match returning nothing
        mock_result = MagicMock()
        mock_result.all.return_value = []
        service.db.execute.return_value = mock_result

        tid, method, conf = await service._match_track(export_track, indexes)
        assert tid is None
        assert method is None
