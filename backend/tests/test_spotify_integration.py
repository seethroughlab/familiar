"""Tests for Spotify integration service (spotify.py).

Tests cover OAuth flow, token refresh, favorites sync, and track matching.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.db.models import SpotifyProfile, Track
from app.services.spotify import SpotifyService, SpotifySyncService


class TestSpotifyServiceConfig:
    """Tests for SpotifyService configuration and initialization."""

    def test_is_configured_with_both_credentials(self):
        """Should return True when both client_id and client_secret are set."""
        with patch.object(SpotifyService, "_get_credentials") as mock_get_creds:
            mock_get_creds.return_value = ("client_id_123", "client_secret_456")
            service = SpotifyService()
            assert service.is_configured() is True

    def test_is_configured_missing_client_id(self):
        """Should return False when client_id is missing."""
        with patch.object(SpotifyService, "_get_credentials") as mock_get_creds:
            mock_get_creds.return_value = (None, "client_secret_456")
            service = SpotifyService()
            assert service.is_configured() is False

    def test_is_configured_missing_client_secret(self):
        """Should return False when client_secret is missing."""
        with patch.object(SpotifyService, "_get_credentials") as mock_get_creds:
            mock_get_creds.return_value = ("client_id_123", None)
            service = SpotifyService()
            assert service.is_configured() is False


class TestSpotifyServiceOAuth:
    """Tests for OAuth flow methods."""

    @pytest.fixture
    def service(self):
        """Create SpotifyService with mocked credentials."""
        with patch.object(SpotifyService, "_get_credentials") as mock_get_creds:
            mock_get_creds.return_value = ("test_client_id", "test_client_secret")
            return SpotifyService()

    def test_get_auth_url_returns_url_and_state(self, service):
        """Should return auth URL and state token with profile ID."""
        with patch("app.services.spotify.SpotifyOAuth") as mock_oauth:
            mock_oauth_instance = MagicMock()
            mock_oauth_instance.get_authorize_url.return_value = "https://accounts.spotify.com/authorize?..."
            mock_oauth.return_value = mock_oauth_instance

            profile_id = uuid4()
            auth_url, state = service.get_auth_url(profile_id)

            assert "spotify.com" in auth_url
            assert str(profile_id) in state
            assert ":" in state  # State format: "{profile_id}:{random_token}"

    @pytest.mark.asyncio
    async def test_handle_callback_invalid_state(self, service):
        """Should raise ValueError for invalid OAuth state."""
        mock_db = AsyncMock()

        with pytest.raises(ValueError, match="Invalid OAuth state"):
            await service.handle_callback(mock_db, "auth_code", "invalid_state")

    @pytest.mark.asyncio
    async def test_handle_callback_creates_new_profile(self, service):
        """Should create SpotifyProfile for new connections."""
        mock_db = AsyncMock()
        profile_id = uuid4()
        state = f"{profile_id}:random_token"

        # Mock no existing profile
        mock_db.execute.return_value = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with patch("app.services.spotify.SpotifyOAuth") as mock_oauth:
            mock_oauth_instance = MagicMock()
            mock_oauth_instance.get_access_token.return_value = {
                "access_token": "access_123",
                "refresh_token": "refresh_456",
                "expires_in": 3600,
            }
            mock_oauth.return_value = mock_oauth_instance

            with patch("app.services.spotify.spotipy.Spotify") as mock_spotify:
                mock_sp = MagicMock()
                mock_sp.current_user.return_value = {"id": "spotify_user_id"}
                mock_spotify.return_value = mock_sp

                await service.handle_callback(mock_db, "auth_code", state)

                # Should add new profile
                mock_db.add.assert_called_once()
                added_profile = mock_db.add.call_args[0][0]
                assert added_profile.profile_id == profile_id
                assert added_profile.access_token == "access_123"
                assert added_profile.refresh_token == "refresh_456"

    @pytest.mark.asyncio
    async def test_handle_callback_updates_existing_profile(self, service):
        """Should update existing SpotifyProfile on reconnection."""
        mock_db = AsyncMock()
        profile_id = uuid4()
        state = f"{profile_id}:random_token"

        # Mock existing profile
        existing_profile = MagicMock()
        existing_profile.profile_id = profile_id
        mock_db.execute.return_value = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = existing_profile

        with patch("app.services.spotify.SpotifyOAuth") as mock_oauth:
            mock_oauth_instance = MagicMock()
            mock_oauth_instance.get_access_token.return_value = {
                "access_token": "new_access_token",
                "refresh_token": "new_refresh_token",
                "expires_in": 3600,
            }
            mock_oauth.return_value = mock_oauth_instance

            with patch("app.services.spotify.spotipy.Spotify") as mock_spotify:
                mock_sp = MagicMock()
                mock_sp.current_user.return_value = {"id": "spotify_user_id"}
                mock_spotify.return_value = mock_sp

                await service.handle_callback(mock_db, "auth_code", state)

                # Should update existing profile, not add
                mock_db.add.assert_not_called()
                assert existing_profile.access_token == "new_access_token"


class TestSpotifyServiceTokenRefresh:
    """Tests for token refresh functionality."""

    @pytest.fixture
    def service(self):
        with patch.object(SpotifyService, "_get_credentials") as mock_get_creds:
            mock_get_creds.return_value = ("test_client_id", "test_client_secret")
            return SpotifyService()

    @pytest.mark.asyncio
    async def test_get_client_refreshes_expired_token(self, service):
        """Should refresh token when expired."""
        mock_db = AsyncMock()
        profile_id = uuid4()

        # Mock expired profile
        expired_profile = MagicMock(spec=SpotifyProfile)
        expired_profile.profile_id = profile_id
        expired_profile.access_token = "old_token"
        expired_profile.refresh_token = "refresh_token"
        expired_profile.token_expires_at = datetime.utcnow() - timedelta(hours=1)  # Expired

        mock_db.execute.return_value = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = expired_profile

        with patch("app.services.spotify.SpotifyOAuth") as mock_oauth:
            mock_oauth_instance = MagicMock()
            mock_oauth_instance.refresh_access_token.return_value = {
                "access_token": "new_token",
                "refresh_token": "new_refresh",
                "expires_in": 3600,
            }
            mock_oauth.return_value = mock_oauth_instance

            with patch("app.services.spotify.spotipy.Spotify") as mock_spotify:
                await service.get_client(mock_db, profile_id)

                # Should have called refresh
                mock_oauth_instance.refresh_access_token.assert_called_once_with("refresh_token")
                # Should return client with new token
                mock_spotify.assert_called_with(auth="new_token", requests_timeout=30, retries=5, backoff_factor=2.0)

    @pytest.mark.asyncio
    async def test_get_client_returns_none_when_no_profile(self, service):
        """Should return None when no SpotifyProfile exists."""
        mock_db = AsyncMock()
        mock_db.execute.return_value = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        client = await service.get_client(mock_db, uuid4())
        assert client is None

    @pytest.mark.asyncio
    async def test_get_client_returns_none_on_refresh_failure(self, service):
        """Should return None if token refresh fails."""
        mock_db = AsyncMock()
        profile_id = uuid4()

        expired_profile = MagicMock(spec=SpotifyProfile)
        expired_profile.access_token = "old_token"
        expired_profile.refresh_token = "refresh_token"
        expired_profile.token_expires_at = datetime.utcnow() - timedelta(hours=1)

        mock_db.execute.return_value = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = expired_profile

        with patch("app.services.spotify.SpotifyOAuth") as mock_oauth:
            mock_oauth_instance = MagicMock()
            mock_oauth_instance.refresh_access_token.side_effect = Exception("Refresh failed")
            mock_oauth.return_value = mock_oauth_instance

            client = await service.get_client(mock_db, profile_id)
            assert client is None


class TestSpotifySyncService:
    """Tests for SpotifySyncService favorites sync."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        # async methods need AsyncMock
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.flush = AsyncMock()
        db.scalar = AsyncMock()
        # db.add is sync, so use regular MagicMock (already default)
        return db

    @pytest.fixture
    def sync_service(self, mock_db):
        with patch.object(SpotifyService, "_get_credentials") as mock_get_creds:
            mock_get_creds.return_value = ("test_client_id", "test_client_secret")
            return SpotifySyncService(mock_db)

    @pytest.mark.asyncio
    async def test_sync_favorites_no_client(self, sync_service, mock_db):
        """Should raise ValueError when Spotify is not connected."""
        with patch.object(sync_service.spotify_service, "get_client", return_value=None):
            with pytest.raises(ValueError, match="Spotify not connected"):
                await sync_service.sync_favorites(uuid4())

    @pytest.mark.asyncio
    async def test_sync_favorites_fetches_saved_tracks(self, sync_service, mock_db):
        """Should fetch and process saved tracks from Spotify."""
        profile_id = uuid4()
        mock_client = MagicMock()

        # Mock pagination: first call returns track, subsequent calls return empty
        call_count = 0
        def mock_saved_tracks(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "items": [
                        {
                            "added_at": "2024-01-15T10:00:00Z",
                            "track": {
                                "id": "spotify_track_1",
                                "name": "Test Song",
                                "artists": [{"name": "Test Artist", "id": "artist_1"}],
                                "album": {"name": "Test Album", "id": "album_1"},
                                "duration_ms": 180000,
                                "popularity": 75,
                                "external_ids": {"isrc": "USRC12345678"},
                                "external_urls": {"spotify": "https://open.spotify.com/track/..."},
                                "preview_url": None,
                            },
                        }
                    ]
                }
            return {"items": []}

        mock_client.current_user_saved_tracks.side_effect = mock_saved_tracks

        with patch.object(sync_service.spotify_service, "get_client", return_value=mock_client):
            # Mock no existing favorite - execute returns async result with sync .scalar_one_or_none
            mock_execute_result = MagicMock()
            mock_execute_result.scalar_one_or_none.return_value = None
            mock_db.execute = AsyncMock(return_value=mock_execute_result)

            # Mock no local match
            with patch.object(sync_service, "_match_to_local", AsyncMock(return_value=None)):
                stats = await sync_service.sync_favorites(profile_id)

                assert stats["fetched"] == 1
                assert stats["new"] == 1
                assert stats["unmatched"] == 1
                mock_db.add.assert_called()

    @pytest.mark.asyncio
    async def test_sync_favorites_matches_local_tracks(self, sync_service, mock_db):
        """Should match Spotify tracks to local library."""
        profile_id = uuid4()
        mock_client = MagicMock()

        # Mock pagination: first call returns track, subsequent calls return empty
        call_count = 0
        def mock_saved_tracks(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "items": [
                        {
                            "added_at": "2024-01-15T10:00:00Z",
                            "track": {
                                "id": "spotify_track_1",
                                "name": "Test Song",
                                "artists": [{"name": "Test Artist", "id": "artist_1"}],
                                "album": {"name": "Test Album", "id": "album_1"},
                                "duration_ms": 180000,
                                "external_ids": {},
                                "external_urls": {},
                                "preview_url": None,
                                "popularity": 50,
                            },
                        }
                    ]
                }
            return {"items": []}

        mock_client.current_user_saved_tracks.side_effect = mock_saved_tracks

        # Mock local track match
        local_track = MagicMock(spec=Track)
        local_track.id = uuid4()

        with patch.object(sync_service.spotify_service, "get_client", return_value=mock_client):
            mock_execute_result = MagicMock()
            mock_execute_result.scalar_one_or_none.return_value = None
            mock_db.execute = AsyncMock(return_value=mock_execute_result)

            with patch.object(sync_service, "_match_to_local", AsyncMock(return_value=local_track)):
                stats = await sync_service.sync_favorites(profile_id)

                assert stats["matched"] == 1
                # New favorite should have matched_track_id set
                added_favorite = mock_db.add.call_args[0][0]
                assert added_favorite.matched_track_id == local_track.id


class TestSpotifyTrackMatching:
    """Tests for track matching logic."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.flush = AsyncMock()
        db.scalar = AsyncMock()
        return db

    @pytest.fixture
    def sync_service(self, mock_db):
        with patch.object(SpotifyService, "_get_credentials") as mock_get_creds:
            mock_get_creds.return_value = ("test_client_id", "test_client_secret")
            return SpotifySyncService(mock_db)

    @pytest.mark.asyncio
    async def test_match_by_isrc(self, sync_service, mock_db):
        """Should match track by ISRC."""
        local_track = MagicMock(spec=Track)
        local_track.id = uuid4()

        # Mock ISRC query returns track
        mock_db.execute.return_value = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = local_track

        spotify_track = {
            "name": "Test Song",
            "artists": [{"name": "Test Artist"}],
            "external_ids": {"isrc": "USRC12345678"},
        }

        result = await sync_service._match_to_local(spotify_track)
        assert result == local_track

    @pytest.mark.asyncio
    async def test_match_by_exact_title_artist(self, sync_service, mock_db):
        """Should match by exact title and artist when ISRC fails."""
        local_track = MagicMock(spec=Track)
        local_track.id = uuid4()

        # When external_ids has no ISRC, the code skips ISRC check entirely
        # and goes straight to title/artist exact match.
        # So the FIRST db.execute call is for title/artist match.
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = local_track
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        spotify_track = {
            "name": "Test Song",
            "artists": [{"name": "Test Artist"}],
            "external_ids": {},
        }

        result = await sync_service._match_to_local(spotify_track)
        assert result == local_track

    @pytest.mark.asyncio
    async def test_match_returns_none_when_no_match(self, sync_service, mock_db):
        """Should return None when no match found."""
        # All queries return None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.first.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        spotify_track = {
            "name": "Unknown Song",
            "artists": [{"name": "Unknown Artist"}],
            "external_ids": {},
        }

        result = await sync_service._match_to_local(spotify_track)
        assert result is None


class TestSpotifyDataExtraction:
    """Tests for extracting data from Spotify track objects."""

    @pytest.fixture
    def sync_service(self):
        mock_db = AsyncMock()
        with patch.object(SpotifyService, "_get_credentials") as mock_get_creds:
            mock_get_creds.return_value = ("test_client_id", "test_client_secret")
            return SpotifySyncService(mock_db)

    def test_extract_track_data_full(self, sync_service):
        """Should extract all available data from Spotify track."""
        spotify_track = {
            "name": "Test Song",
            "artists": [{"name": "Test Artist", "id": "artist_123"}],
            "album": {"name": "Test Album", "id": "album_456"},
            "external_ids": {"isrc": "USRC12345678"},
            "duration_ms": 180000,
            "popularity": 75,
            "preview_url": "https://p.scdn.co/mp3-preview/...",
            "external_urls": {"spotify": "https://open.spotify.com/track/123"},
        }

        result = sync_service._extract_track_data(spotify_track)

        assert result["name"] == "Test Song"
        assert result["artist"] == "Test Artist"
        assert result["artist_id"] == "artist_123"
        assert result["album"] == "Test Album"
        assert result["album_id"] == "album_456"
        assert result["duration_ms"] == 180000
        assert "spotify.com" in result["external_url"]

    def test_extract_track_data_minimal(self, sync_service):
        """Should handle tracks with minimal data."""
        spotify_track = {
            "name": "Test Song",
            "artists": [],
            "album": {},
            "external_ids": {},
            "duration_ms": None,
            "popularity": None,
            "preview_url": None,
            "external_urls": {},
        }

        result = sync_service._extract_track_data(spotify_track)

        assert result["name"] == "Test Song"
        assert result["artist"] is None
        assert result["album"] is None
