"""Unit tests for background event timeline storage."""

from unittest.mock import MagicMock, patch

from app.services.background.events import (
    BACKGROUND_EVENTS_KEY,
    get_recent_background_events,
    record_background_event,
)


class TestBackgroundEvents:
    def test_record_background_event_writes_to_redis(self):
        mock_redis = MagicMock()
        with patch("app.services.background.events.get_redis", return_value=mock_redis):
            record_background_event("sync_start", {"foo": "bar"})

        mock_redis.lpush.assert_called_once()
        args = mock_redis.lpush.call_args[0]
        assert args[0] == BACKGROUND_EVENTS_KEY
        assert "sync_start" in args[1]
        mock_redis.ltrim.assert_called_once()
        mock_redis.expire.assert_called_once()

    def test_get_recent_background_events_returns_parsed_json(self):
        mock_redis = MagicMock()
        mock_redis.lrange.return_value = [
            b'{"event":"sync_start","details":{"a":1},"timestamp":"2026-01-01T00:00:00"}'
        ]
        with patch("app.services.background.events.get_redis", return_value=mock_redis):
            result = get_recent_background_events(limit=5)

        assert len(result) == 1
        assert result[0]["event"] == "sync_start"
        assert result[0]["details"]["a"] == 1
