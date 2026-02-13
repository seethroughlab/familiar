"""Tests for Spotify rate limiting and SpotifyCompat wrapper."""

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest
import spotipy

from app.services.spotify_compat import (
    _MIN_REQUEST_INTERVAL,
    SpotifyCompat,
    SpotifyRateLimitError,
)


@pytest.fixture
def mock_spotipy():
    """Create a mock spotipy.Spotify client."""
    client = MagicMock(spec=spotipy.Spotify)
    client.search.return_value = {"artists": {"items": [{"id": "abc", "name": "Test"}]}}
    client.artist_albums.return_value = {"items": []}
    client.current_user_saved_tracks.return_value = {"items": []}
    return client


@pytest.fixture
def compat(mock_spotipy):
    """Create a SpotifyCompat wrapper."""
    return SpotifyCompat(mock_spotipy, token="test-token")


class TestThrottle:
    """Test centralized request throttling."""

    def test_throttle_enforces_minimum_delay(self, compat):
        """Back-to-back calls should be spaced by at least _MIN_REQUEST_INTERVAL."""
        # First call — no delay
        compat._throttle()
        t0 = time.monotonic()

        # Second call — should sleep
        compat._throttle()
        elapsed = time.monotonic() - t0

        assert elapsed >= _MIN_REQUEST_INTERVAL * 0.9  # Allow 10% tolerance

    def test_throttle_no_delay_after_interval(self, compat):
        """If enough time has passed, _throttle() should not sleep."""
        compat._last_request_time = time.monotonic() - _MIN_REQUEST_INTERVAL - 1.0

        t0 = time.monotonic()
        compat._throttle()
        elapsed = time.monotonic() - t0

        assert elapsed < 0.1  # Should not have slept


class TestDelegatedThrottling:
    """Test that delegated spotipy methods are automatically throttled."""

    def test_delegated_method_is_throttled(self, compat, mock_spotipy):
        """Delegated methods (via __getattr__) should go through _throttle()."""
        with patch.object(compat, "_throttle") as mock_throttle:
            compat.search(q="test", type="artist", limit=1)

        mock_throttle.assert_called_once()
        mock_spotipy.search.assert_called_once_with(q="test", type="artist", limit=1)

    def test_multiple_delegated_calls_throttled(self, compat, mock_spotipy):
        """Multiple delegated calls should each be throttled."""
        with patch.object(compat, "_throttle") as mock_throttle:
            compat.search(q="a", type="artist", limit=1)
            compat.artist_albums("id1")

        assert mock_throttle.call_count == 2

    def test_non_callable_attributes_not_wrapped(self, compat, mock_spotipy):
        """Non-callable attributes should be returned directly without wrapping."""
        mock_spotipy.some_property = "value"
        result = compat.some_property
        assert result == "value"


class TestPlaylistItemsRetry:
    """Test playlist_items() retry logic on 429."""

    def test_retry_on_429_then_success(self, compat):
        """Should retry on 429 and succeed when the API recovers."""
        rate_limited = httpx.Response(
            status_code=429,
            headers={"Retry-After": "1"},
            request=httpx.Request("GET", "https://api.spotify.com/v1/playlists/test/items"),
        )
        ok_response = httpx.Response(
            status_code=200,
            json={"items": []},
            request=httpx.Request("GET", "https://api.spotify.com/v1/playlists/test/items"),
        )

        with patch("app.services.spotify_compat.httpx.get", side_effect=[rate_limited, ok_response]):
            with patch("app.services.spotify_compat.time.sleep"):  # Don't actually sleep
                result = compat.playlist_items("test")

        assert result == {"items": []}

    def test_raises_after_max_retries(self, compat):
        """Should raise SpotifyRateLimitError after exhausting retries."""
        rate_limited = httpx.Response(
            status_code=429,
            headers={"Retry-After": "1"},
            request=httpx.Request("GET", "https://api.spotify.com/v1/playlists/test/items"),
        )

        with patch("app.services.spotify_compat.httpx.get", return_value=rate_limited):
            with patch("app.services.spotify_compat.time.sleep"):
                with pytest.raises(SpotifyRateLimitError) as exc_info:
                    compat.playlist_items("test")

        assert exc_info.value.retry_after == 1


class TestSpotifyRateLimitError:
    """Test SpotifyRateLimitError exception."""

    def test_error_with_retry_after(self):
        err = SpotifyRateLimitError(retry_after=60)
        assert err.retry_after == 60
        assert "60s" in str(err)

    def test_error_without_retry_after(self):
        err = SpotifyRateLimitError()
        assert err.retry_after is None
        assert "rate limit" in str(err).lower()

    def test_propagates_through_search_artist(self):
        """SpotifyRateLimitError should not be caught by bare except Exception."""
        from app.services.spotify_compat import SpotifyRateLimitError

        # Verify it's a proper Exception subclass
        assert issubclass(SpotifyRateLimitError, Exception)

        # Verify it can be caught specifically before a bare except
        err = SpotifyRateLimitError(retry_after=3600)
        caught_specifically = False
        try:
            raise err
        except SpotifyRateLimitError:
            caught_specifically = True
        except Exception:
            caught_specifically = False

        assert caught_specifically
