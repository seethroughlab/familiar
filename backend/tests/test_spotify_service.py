"""Tests for Spotify service - auth URL, configuration."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.services.spotify import SpotifyService


@pytest.fixture
def mock_settings():
    """Patch app_settings to return test credentials."""
    mock = MagicMock()
    mock.get_effective.side_effect = lambda key: {
        "spotify_client_id": "test_client_id",
        "spotify_client_secret": "test_client_secret",
    }.get(key)

    with patch("app.services.spotify.get_app_settings_service", return_value=mock):
        yield mock


@pytest.fixture
def service(mock_settings):
    return SpotifyService()


class TestIsConfigured:
    def test_configured(self, service):
        assert service.is_configured() is True

    def test_not_configured_missing_id(self):
        mock = MagicMock()
        mock.get_effective.return_value = None
        with patch("app.services.spotify.get_app_settings_service", return_value=mock):
            svc = SpotifyService()
            assert svc.is_configured() is False


class TestGetAuthUrl:
    @patch("app.services.spotify.SpotifyOAuth")
    def test_returns_url_and_state(self, mock_oauth_cls, service):
        mock_oauth = MagicMock()
        mock_oauth.get_authorize_url.return_value = "https://accounts.spotify.com/authorize?..."
        mock_oauth_cls.return_value = mock_oauth

        profile_id = uuid4()
        url, state = service.get_auth_url(profile_id)

        assert url.startswith("https://accounts.spotify.com/")
        assert str(profile_id) in state

    @patch("app.services.spotify.SpotifyOAuth")
    def test_state_contains_profile_id(self, mock_oauth_cls, service):
        mock_oauth = MagicMock()
        mock_oauth.get_authorize_url.return_value = "https://accounts.spotify.com/authorize"
        mock_oauth_cls.return_value = mock_oauth

        profile_id = uuid4()
        _, state = service.get_auth_url(profile_id)
        assert state.startswith(str(profile_id) + ":")


class TestHandleCallback:
    @pytest.mark.asyncio
    async def test_invalid_state_raises(self, service):
        from unittest.mock import AsyncMock
        db = AsyncMock()
        with pytest.raises(ValueError, match="Invalid OAuth state"):
            await service.handle_callback(db, "auth_code", "invalid-state")

    @pytest.mark.asyncio
    async def test_invalid_uuid_in_state_raises(self, service):
        from unittest.mock import AsyncMock
        db = AsyncMock()
        with pytest.raises(ValueError, match="Invalid OAuth state"):
            await service.handle_callback(db, "auth_code", "not-a-uuid:token")
