"""Tests for the LLM service (llm/service.py).

Service.py is provider-agnostic: it resolves a provider via get_provider(),
delegates the conversation to it, and drains ToolExecutor state (queue /
ephemeral playlist / playback) after the stream ends. Provider-specific loop
behavior lives in test_llm_providers_*.py.
"""

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm.service import LLMService


class FakeProvider:
    """Stand-in for an LLMProvider. Yields a caller-supplied list of events."""

    def __init__(
        self,
        events: list[dict[str, Any]],
        *,
        configured: bool = True,
        name: str = "fake",
    ):
        self._events = events
        self._configured = configured
        self.name = name

    def is_configured(self) -> bool:
        return self._configured

    async def chat(self, **_kwargs) -> AsyncIterator[dict[str, Any]]:
        for e in self._events:
            yield e

    async def complete_utility(self, **_kwargs) -> str:
        return ""


def _make_service(events, *, configured=True):
    """Build an LLMService with a fake provider and a stubbed executor."""
    provider = FakeProvider(events, configured=configured)
    with patch("app.services.llm.service.get_provider", return_value=provider):
        service = LLMService()
    return service


class TestServiceConfigurationGate:
    @pytest.mark.asyncio
    async def test_yields_error_when_provider_not_configured(self):
        mock_db = AsyncMock()
        service = _make_service([], configured=False)
        events = [e async for e in service.chat("hello", [], mock_db)]
        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "not configured" in events[0]["content"]


class TestServiceEventPassthrough:
    @pytest.mark.asyncio
    async def test_passes_through_provider_events(self):
        mock_db = AsyncMock()
        provider_events = [
            {"type": "text", "content": "Hello!"},
            {"type": "tool_call", "id": "t1", "name": "search_library", "input": {"query": "jazz"}},
            {"type": "tool_result", "name": "search_library", "result": {"count": 1}},
        ]
        service = _make_service(provider_events)

        with patch("app.services.llm.service.ToolExecutor") as mock_executor_class:
            mock_executor = MagicMock()
            mock_executor.get_queued_tracks.return_value = ([], True)
            mock_executor.get_auto_saved_playlist.return_value = None
            mock_executor.get_playback_action.return_value = None
            mock_executor_class.return_value = mock_executor

            out = [e async for e in service.chat("hi", [], mock_db)]

        types = [e["type"] for e in out]
        assert types[:3] == ["text", "tool_call", "tool_result"]
        assert out[-1]["type"] == "done"

    @pytest.mark.asyncio
    async def test_stops_drain_if_provider_emits_error(self):
        """If the provider signals an error, skip the post-stream drain."""
        mock_db = AsyncMock()
        service = _make_service([{"type": "error", "content": "boom"}])

        with patch("app.services.llm.service.ToolExecutor") as mock_executor_class:
            mock_executor = MagicMock()
            # These shouldn't be inspected (drain skipped), but stub anyway.
            mock_executor.get_queued_tracks.return_value = ([{"id": "x"}], True)
            mock_executor_class.return_value = mock_executor

            out = [e async for e in service.chat("hi", [], mock_db)]

        assert [e["type"] for e in out] == ["error"]


class TestServicePostStreamDrain:
    @pytest.mark.asyncio
    async def test_emits_queue_event_when_tracks_queued(self):
        mock_db = AsyncMock()
        service = _make_service([{"type": "text", "content": "done"}])

        with patch("app.services.llm.service.ToolExecutor") as mock_executor_class:
            mock_executor = MagicMock()
            mock_executor.get_queued_tracks.return_value = (
                [{"id": "t1", "title": "Song"}],
                True,
            )
            mock_executor.get_auto_saved_playlist.return_value = None
            mock_executor.get_playback_action.return_value = None
            mock_executor_class.return_value = mock_executor

            out = [e async for e in service.chat("q", [], mock_db)]

        queue = [e for e in out if e["type"] == "queue"]
        assert len(queue) == 1
        assert queue[0]["tracks"] == [{"id": "t1", "title": "Song"}]
        assert queue[0]["clear"] is True
        assert out[-1]["type"] == "done"

    @pytest.mark.asyncio
    async def test_emits_ephemeral_playlist_event(self):
        mock_db = AsyncMock()
        service = _make_service([{"type": "text", "content": "done"}])

        with patch("app.services.llm.service.ToolExecutor") as mock_executor_class:
            mock_executor = MagicMock()
            mock_executor.get_queued_tracks.return_value = ([], True)
            mock_executor.get_auto_saved_playlist.return_value = {
                "ephemeral": True,
                "name": "Jazz Mix",
                "generation_prompt": "jazz",
                "track_ids": ["t1"],
                "tracks": [{"id": "t1"}],
                "suggested_tracks": [],
            }
            mock_executor.get_playback_action.return_value = None
            mock_executor_class.return_value = mock_executor

            out = [e async for e in service.chat("q", [], mock_db)]

        pl = [e for e in out if e["type"] == "ephemeral_playlist_created"]
        assert len(pl) == 1
        assert pl[0]["name"] == "Jazz Mix"

    @pytest.mark.asyncio
    async def test_emits_playback_action(self):
        mock_db = AsyncMock()
        service = _make_service([{"type": "text", "content": "done"}])

        with patch("app.services.llm.service.ToolExecutor") as mock_executor_class:
            mock_executor = MagicMock()
            mock_executor.get_queued_tracks.return_value = ([], True)
            mock_executor.get_auto_saved_playlist.return_value = None
            mock_executor.get_playback_action.return_value = "play"
            mock_executor_class.return_value = mock_executor

            out = [e async for e in service.chat("q", [], mock_db)]

        pb = [e for e in out if e["type"] == "playback"]
        assert len(pb) == 1
        assert pb[0]["action"] == "play"
