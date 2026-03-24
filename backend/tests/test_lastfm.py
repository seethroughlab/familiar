"""Tests for Last.fm service - auth URL, signing, scrobbling."""

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.lastfm import LastfmService


@pytest.fixture
def mock_settings():
    """Patch app_settings to return test credentials."""
    mock = MagicMock()
    mock.get_effective.side_effect = lambda key: {
        "lastfm_api_key": "test_api_key",
        "lastfm_api_secret": "test_api_secret",
    }.get(key)

    with patch("app.services.lastfm.get_app_settings_service", return_value=mock):
        yield mock


@pytest.fixture
def service(mock_settings):
    return LastfmService()


class TestIsConfigured:
    def test_configured(self, service):
        assert service.is_configured() is True

    def test_not_configured(self):
        mock = MagicMock()
        mock.get_effective.return_value = None
        with patch("app.services.lastfm.get_app_settings_service", return_value=mock):
            svc = LastfmService()
            assert svc.is_configured() is False


class TestGetAuthUrl:
    def test_returns_url_with_api_key(self, service):
        url = service.get_auth_url("http://localhost/callback")
        assert "test_api_key" in url
        assert "http%3A%2F%2Flocalhost%2Fcallback" in url

    def test_raises_if_not_configured(self):
        mock = MagicMock()
        mock.get_effective.return_value = None
        with patch("app.services.lastfm.get_app_settings_service", return_value=mock):
            svc = LastfmService()
            with pytest.raises(ValueError, match="not configured"):
                svc.get_auth_url("http://localhost/callback")


class TestSignParams:
    def test_signature_is_md5(self, service):
        params = {"method": "test", "api_key": "test_api_key"}
        sig = service._sign_params(params)
        assert len(sig) == 32  # MD5 hex digest length

    def test_signature_is_deterministic(self, service):
        params = {"method": "test", "api_key": "test_api_key"}
        assert service._sign_params(params) == service._sign_params(params)

    def test_signature_changes_with_params(self, service):
        params1 = {"method": "test", "api_key": "test_api_key"}
        params2 = {"method": "other", "api_key": "test_api_key"}
        assert service._sign_params(params1) != service._sign_params(params2)

    def test_signature_includes_secret(self, service):
        params = {"a": "1"}
        sig = service._sign_params(params)
        expected = hashlib.md5(b"a1test_api_secret").hexdigest()
        assert sig == expected


class TestScrobble:
    @pytest.mark.asyncio
    async def test_returns_false_if_not_configured(self):
        mock = MagicMock()
        mock.get_effective.return_value = None
        with patch("app.services.lastfm.get_app_settings_service", return_value=mock):
            svc = LastfmService()
            result = await svc.scrobble("sk", "Artist", "Track")
            assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self, service):
        mock_response = MagicMock()
        mock_response.json.return_value = {"scrobbles": {"@attr": {"accepted": 1}}}
        service.client = AsyncMock()
        service.client.post.return_value = mock_response

        result = await service.scrobble("session_key", "Artist", "Track", timestamp=1234567890)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_error_response(self, service):
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": 9, "message": "Invalid session key"}
        service.client = AsyncMock()
        service.client.post.return_value = mock_response

        result = await service.scrobble("bad_key", "Artist", "Track")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self, service):
        service.client = AsyncMock()
        service.client.post.side_effect = Exception("Network error")

        result = await service.scrobble("sk", "Artist", "Track")
        assert result is False


class TestUpdateNowPlaying:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self, service):
        mock_response = MagicMock()
        mock_response.json.return_value = {"nowplaying": {}}
        service.client = AsyncMock()
        service.client.post.return_value = mock_response

        result = await service.update_now_playing("sk", "Artist", "Track")
        assert result is True

    @pytest.mark.asyncio
    async def test_includes_album_and_duration(self, service):
        mock_response = MagicMock()
        mock_response.json.return_value = {"nowplaying": {}}
        service.client = AsyncMock()
        service.client.post.return_value = mock_response

        await service.update_now_playing("sk", "Artist", "Track", album="Album", duration=180)
        call_kwargs = service.client.post.call_args
        data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
        assert data["album"] == "Album"
        assert data["duration"] == "180"


class TestGetSimilarArtists:
    @pytest.mark.asyncio
    async def test_returns_artists_list(self, service):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "similarartists": {
                "artist": [
                    {"name": "Similar Artist", "match": "0.9"},
                ]
            }
        }
        service.client = AsyncMock()
        service.client.get.return_value = mock_response

        result = await service.get_similar_artists("Test Artist")
        assert len(result) == 1
        assert result[0]["name"] == "Similar Artist"

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, service):
        service.client = AsyncMock()
        service.client.get.side_effect = Exception("Network error")

        result = await service.get_similar_artists("Test Artist")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_if_not_configured(self):
        mock = MagicMock()
        mock.get_effective.return_value = None
        with patch("app.services.lastfm.get_app_settings_service", return_value=mock):
            svc = LastfmService()
            result = await svc.get_similar_artists("Test Artist")
            assert result == []

    @pytest.mark.asyncio
    async def test_handles_non_dict_response(self, service):
        """When Last.fm returns a string instead of dict for similarartists."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "similarartists": "No artists found"
        }
        service.client = AsyncMock()
        service.client.get.return_value = mock_response

        result = await service.get_similar_artists("Unknown Artist")
        assert result == []


class TestGetSimilarTracks:
    @pytest.mark.asyncio
    async def test_returns_tracks_list(self, service):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "similartracks": {
                "track": [
                    {
                        "name": "Similar Track",
                        "artist": {"name": "Other Artist"},
                        "match": "0.75",
                        "url": "http://lastfm.com/track",
                    },
                ]
            }
        }
        service.client = AsyncMock()
        service.client.get.return_value = mock_response

        result = await service.get_similar_tracks("Artist", "Track")
        assert len(result) == 1
        assert result[0]["name"] == "Similar Track"

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, service):
        service.client = AsyncMock()
        service.client.get.side_effect = Exception("Network error")

        result = await service.get_similar_tracks("Artist", "Track")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_if_not_configured(self):
        mock = MagicMock()
        mock.get_effective.return_value = None
        with patch("app.services.lastfm.get_app_settings_service", return_value=mock):
            svc = LastfmService()
            result = await svc.get_similar_tracks("Artist", "Track")
            assert result == []

    @pytest.mark.asyncio
    async def test_handles_non_dict_response(self, service):
        mock_response = MagicMock()
        mock_response.json.return_value = {"similartracks": "not found"}
        service.client = AsyncMock()
        service.client.get.return_value = mock_response

        result = await service.get_similar_tracks("Artist", "Track")
        assert result == []


class TestExchangeToken:
    @pytest.mark.asyncio
    async def test_returns_session(self, service):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "session": {"key": "session_key_123", "name": "testuser"}
        }
        mock_response.raise_for_status = MagicMock()
        service.client = AsyncMock()
        service.client.get.return_value = mock_response

        result = await service.exchange_token("auth_token_456")
        assert result.session_key == "session_key_123"
        assert result.username == "testuser"

    @pytest.mark.asyncio
    async def test_raises_on_error_response(self, service):
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": 4, "message": "Invalid token"}
        mock_response.raise_for_status = MagicMock()
        service.client = AsyncMock()
        service.client.get.return_value = mock_response

        with pytest.raises(ValueError, match="Last.fm error"):
            await service.exchange_token("bad_token")

    @pytest.mark.asyncio
    async def test_raises_if_not_configured(self):
        mock = MagicMock()
        mock.get_effective.return_value = None
        with patch("app.services.lastfm.get_app_settings_service", return_value=mock):
            svc = LastfmService()
            with pytest.raises(ValueError, match="not configured"):
                await svc.exchange_token("token")


class TestGetArtistInfo:
    @pytest.mark.asyncio
    async def test_returns_artist_info(self, service):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "artist": {
                "name": "Radiohead",
                "mbid": "a74b1b7f-71a5-4011-9441-d0b5e4122711",
                "url": "http://lastfm.com/music/Radiohead",
            }
        }
        service.client = AsyncMock()
        service.client.get.return_value = mock_response

        result = await service.get_artist_info("Radiohead")
        assert result is not None
        assert result["name"] == "Radiohead"

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self, service):
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": 6, "message": "Artist not found"}
        service.client = AsyncMock()
        service.client.get.return_value = mock_response

        result = await service.get_artist_info("Nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self, service):
        service.client = AsyncMock()
        service.client.get.side_effect = Exception("timeout")

        result = await service.get_artist_info("Radiohead")
        assert result is None


class TestGetUserInfo:
    @pytest.mark.asyncio
    async def test_returns_user_data(self, service):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "user": {"name": "testuser", "playcount": "12345"}
        }
        service.client = AsyncMock()
        service.client.get.return_value = mock_response

        result = await service.get_user_info("session_key")
        assert result is not None
        assert result["name"] == "testuser"

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self, service):
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": 9, "message": "Invalid session"}
        service.client = AsyncMock()
        service.client.get.return_value = mock_response

        result = await service.get_user_info("bad_key")
        assert result is None
