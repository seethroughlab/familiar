"""Tests for the LLM service (llm/service.py).

Tests cover Claude API integration, streaming chat flow, tool execution loop,
error handling, and max_iterations cutoff.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.llm.service import LLMService


class FakeTextBlock:
    """Fake Claude text block."""

    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class FakeToolUseBlock:
    """Fake Claude tool_use block."""

    def __init__(self, name: str, tool_input: dict, tool_id: str | None = None):
        self.type = "tool_use"
        self.id = tool_id or f"tool_{uuid4().hex[:8]}"
        self.name = name
        self.input = tool_input


class FakeResponse:
    """Fake Claude API response."""

    def __init__(self, content: list, stop_reason: str = "end_turn"):
        self.content = content
        self.stop_reason = stop_reason


class TestLLMServiceInit:
    """Tests for LLMService initialization."""

    @patch("app.services.llm.service.get_app_settings_service")
    @patch("app.services.llm.service.anthropic.Anthropic")
    def test_init_loads_api_key(self, mock_anthropic, mock_settings):
        """Service should load API key from settings on init."""
        mock_settings_instance = MagicMock()
        mock_settings_instance.get_effective.return_value = "sk-test-key"
        mock_settings.return_value = mock_settings_instance

        LLMService()

        mock_settings_instance.get_effective.assert_called_once_with("anthropic_api_key")
        mock_anthropic.assert_called_once()
        call_kwargs = mock_anthropic.call_args.kwargs
        assert call_kwargs["api_key"] == "sk-test-key"
        # Should also have timeout configured
        assert "timeout" in call_kwargs

    @patch("app.services.llm.service.get_app_settings_service")
    @patch("app.services.llm.service.anthropic.Anthropic")
    def test_init_with_no_api_key(self, mock_anthropic, mock_settings):
        """Service should still initialize with None API key."""
        mock_settings_instance = MagicMock()
        mock_settings_instance.get_effective.return_value = None
        mock_settings.return_value = mock_settings_instance

        LLMService()

        mock_anthropic.assert_called_once()
        call_kwargs = mock_anthropic.call_args.kwargs
        assert call_kwargs["api_key"] is None


class TestLLMServiceChat:
    """Tests for the chat method and Claude API integration."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return AsyncMock()

    @pytest.fixture
    def mock_claude_client(self):
        """Create a mock Claude client."""
        return MagicMock()

    @pytest.fixture
    def service(self, mock_claude_client):
        """Create LLMService with mocked Claude client."""
        with patch("app.services.llm.service.get_app_settings_service") as mock_settings:
            mock_settings_instance = MagicMock()
            mock_settings_instance.get_effective.return_value = "sk-test-key"
            mock_settings.return_value = mock_settings_instance

            with patch("app.services.llm.service.anthropic.Anthropic") as mock_anthropic:
                mock_anthropic.return_value = mock_claude_client
                service = LLMService()
                return service

    @pytest.mark.asyncio
    async def test_chat_yields_error_when_no_client(self, mock_db):
        """Should yield error event if claude_client is None."""
        with patch("app.services.llm.service.get_app_settings_service") as mock_settings:
            mock_settings_instance = MagicMock()
            mock_settings_instance.get_effective.return_value = None
            mock_settings.return_value = mock_settings_instance

            with patch("app.services.llm.service.anthropic.Anthropic") as mock_anthropic:
                mock_anthropic.return_value = None
                service = LLMService()
                service.claude_client = None

                events = []
                async for event in service.chat("hello", [], mock_db):
                    events.append(event)

                assert len(events) == 1
                assert events[0]["type"] == "error"
                assert "not configured" in events[0]["content"]

    @pytest.mark.asyncio
    async def test_chat_simple_text_response(self, service, mock_claude_client, mock_db):
        """Simple text response should yield text and done events."""
        mock_claude_client.messages.create.return_value = FakeResponse(
            content=[FakeTextBlock("Hello! How can I help you with music today?")],
            stop_reason="end_turn",
        )

        events = []
        async for event in service.chat("hello", [], mock_db):
            events.append(event)

        # Should have text event and done event
        assert any(e["type"] == "text" for e in events)
        assert events[-1]["type"] == "done"

        text_event = next(e for e in events if e["type"] == "text")
        assert "Hello" in text_event["content"]

    @pytest.mark.asyncio
    async def test_chat_tool_use_flow(self, service, mock_claude_client, mock_db):
        """Tool use should yield tool_call and tool_result events."""
        # First response: tool use
        tool_response = FakeResponse(
            content=[FakeToolUseBlock("search_library", {"query": "jazz"})],
            stop_reason="tool_use",
        )
        # Second response: final text
        final_response = FakeResponse(
            content=[FakeTextBlock("I found some jazz tracks for you!")],
            stop_reason="end_turn",
        )
        mock_claude_client.messages.create.side_effect = [tool_response, final_response]

        with patch("app.services.llm.service.ToolExecutor") as mock_executor_class:
            mock_executor = MagicMock()
            # execute is async, so use AsyncMock for just that method
            mock_executor.execute = AsyncMock(return_value={"tracks": [], "count": 0})
            # These are sync methods
            mock_executor.get_queued_tracks.return_value = ([], True)
            mock_executor.get_auto_saved_playlist.return_value = None
            mock_executor.get_playback_action.return_value = None
            mock_executor.get_navigate_hint.return_value = None
            mock_executor_class.return_value = mock_executor

            events = []
            async for event in service.chat("play some jazz", [], mock_db):
                events.append(event)

            # Should have tool_call, tool_result, text, and done events
            event_types = [e["type"] for e in events]
            assert "tool_call" in event_types
            assert "tool_result" in event_types
            assert "text" in event_types
            assert "done" in event_types

    @pytest.mark.asyncio
    async def test_chat_queued_tracks_yield_queue_event(self, service, mock_claude_client, mock_db):
        """When tool executor has queued tracks, should yield queue event."""
        mock_claude_client.messages.create.return_value = FakeResponse(
            content=[FakeTextBlock("Here's your music!")],
            stop_reason="end_turn",
        )

        with patch("app.services.llm.service.ToolExecutor") as mock_executor_class:
            mock_executor = MagicMock()
            mock_executor.get_queued_tracks.return_value = (
                [{"id": "track-1", "title": "Song"}],
                True,
            )
            mock_executor.get_auto_saved_playlist.return_value = None
            mock_executor.get_playback_action.return_value = None
            mock_executor_class.return_value = mock_executor

            events = []
            async for event in service.chat("play something", [], mock_db):
                events.append(event)

            queue_events = [e for e in events if e["type"] == "queue"]
            assert len(queue_events) == 1
            assert queue_events[0]["tracks"] == [{"id": "track-1", "title": "Song"}]
            assert queue_events[0]["clear"] is True

    @pytest.mark.asyncio
    async def test_chat_ephemeral_playlist_created_yields_event(self, service, mock_claude_client, mock_db):
        """When tool executor creates a playlist, should yield ephemeral_playlist_created event."""
        mock_claude_client.messages.create.return_value = FakeResponse(
            content=[FakeTextBlock("I created a playlist for you!")],
            stop_reason="end_turn",
        )

        with patch("app.services.llm.service.ToolExecutor") as mock_executor_class:
            mock_executor = MagicMock()
            mock_executor.get_queued_tracks.return_value = ([], True)
            mock_executor.get_auto_saved_playlist.return_value = {
                "ephemeral": True,
                "name": "Jazz Mix",
                "generation_prompt": "create a jazz playlist",
                "track_ids": ["track-1", "track-2"],
                "tracks": [{"id": "track-1"}, {"id": "track-2"}],
                "suggested_tracks": [],
            }
            mock_executor.get_playback_action.return_value = None
            mock_executor_class.return_value = mock_executor

            events = []
            async for event in service.chat("create a jazz playlist", [], mock_db):
                events.append(event)

            playlist_events = [e for e in events if e["type"] == "ephemeral_playlist_created"]
            assert len(playlist_events) == 1
            assert playlist_events[0]["name"] == "Jazz Mix"
            assert playlist_events[0]["track_ids"] == ["track-1", "track-2"]

    @pytest.mark.asyncio
    async def test_chat_playback_action_yields_event(self, service, mock_claude_client, mock_db):
        """When tool executor has playback action, should yield playback event."""
        mock_claude_client.messages.create.return_value = FakeResponse(
            content=[FakeTextBlock("Playing now!")],
            stop_reason="end_turn",
        )

        with patch("app.services.llm.service.ToolExecutor") as mock_executor_class:
            mock_executor = MagicMock()
            mock_executor.get_queued_tracks.return_value = ([], True)
            mock_executor.get_auto_saved_playlist.return_value = None
            mock_executor.get_playback_action.return_value = "play"
            mock_executor_class.return_value = mock_executor

            events = []
            async for event in service.chat("play music", [], mock_db):
                events.append(event)

            playback_events = [e for e in events if e["type"] == "playback"]
            assert len(playback_events) == 1
            assert playback_events[0]["action"] == "play"


class TestLLMServiceErrorHandling:
    """Tests for error handling in the chat method."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def service(self):
        with patch("app.services.llm.service.get_app_settings_service") as mock_settings:
            mock_settings_instance = MagicMock()
            mock_settings_instance.get_effective.return_value = "sk-test-key"
            mock_settings.return_value = mock_settings_instance

            with patch("app.services.llm.service.anthropic.Anthropic"):
                service = LLMService()
                return service

    @pytest.mark.asyncio
    async def test_chat_handles_bad_request_error(self, service, mock_db):
        """BadRequestError should yield error event with message."""
        import anthropic

        service.claude_client.messages.create.side_effect = anthropic.BadRequestError(
            message="Invalid request",
            response=MagicMock(status_code=400),
            body={"error": {"message": "Invalid request"}},
        )

        events = []
        async for event in service.chat("test", [], mock_db):
            events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "API error" in events[0]["content"]

    @pytest.mark.asyncio
    async def test_chat_handles_auth_error(self, service, mock_db):
        """AuthenticationError should yield error event about API key."""
        import anthropic

        service.claude_client.messages.create.side_effect = anthropic.AuthenticationError(
            message="Invalid API key",
            response=MagicMock(status_code=401),
            body={"error": {"message": "Invalid API key"}},
        )

        events = []
        async for event in service.chat("test", [], mock_db):
            events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "Invalid API key" in events[0]["content"]

    @pytest.mark.asyncio
    async def test_chat_handles_generic_api_error(self, service, mock_db):
        """Generic APIError should yield error event."""
        import anthropic

        service.claude_client.messages.create.side_effect = anthropic.APIError(
            message="Rate limit exceeded",
            request=MagicMock(),
            body={"error": {"message": "Rate limit exceeded"}},
        )

        events = []
        async for event in service.chat("test", [], mock_db):
            events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "API error" in events[0]["content"]


class TestLLMServiceMaxIterations:
    """Tests for max_iterations cutoff to prevent infinite loops."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def service(self):
        with patch("app.services.llm.service.get_app_settings_service") as mock_settings:
            mock_settings_instance = MagicMock()
            mock_settings_instance.get_effective.return_value = "sk-test-key"
            mock_settings.return_value = mock_settings_instance

            with patch("app.services.llm.service.anthropic.Anthropic"):
                service = LLMService()
                return service

    @pytest.mark.asyncio
    async def test_chat_respects_max_iterations(self, service, mock_db):
        """Should stop after max_iterations and yield any queued tracks."""
        # Always return tool_use to force iteration
        service.claude_client.messages.create.return_value = FakeResponse(
            content=[FakeToolUseBlock("search_library", {"query": "test"})],
            stop_reason="tool_use",
        )

        with patch("app.services.llm.service.ToolExecutor") as mock_executor_class:
            mock_executor = MagicMock()
            # execute is async
            mock_executor.execute = AsyncMock(return_value={"tracks": [{"id": "t1"}], "count": 1})
            # These are sync
            mock_executor.get_queued_tracks.return_value = (
                [{"id": "t1", "title": "Test"}],
                True,
            )
            mock_executor.get_auto_saved_playlist.return_value = None
            mock_executor.get_playback_action.return_value = None
            mock_executor_class.return_value = mock_executor

            events = []
            async for event in service.chat("find all tracks", [], mock_db):
                events.append(event)

            # Should have hit max iterations (8)
            call_count = service.claude_client.messages.create.call_count
            assert call_count == 8

            # Should end with queue event (if tracks found), text, and done
            assert events[-1]["type"] == "done"
            # Check for queue event before done
            queue_events = [e for e in events if e["type"] == "queue"]
            assert len(queue_events) > 0

    @pytest.mark.asyncio
    async def test_chat_yields_found_tracks_message_at_max_iterations(self, service, mock_db):
        """At max iterations, should yield helpful message about found tracks."""
        service.claude_client.messages.create.return_value = FakeResponse(
            content=[FakeToolUseBlock("search_library", {"query": "test"})],
            stop_reason="tool_use",
        )

        with patch("app.services.llm.service.ToolExecutor") as mock_executor_class:
            mock_executor = MagicMock()
            mock_executor.execute = AsyncMock(return_value={"tracks": [], "count": 0})
            mock_executor.get_queued_tracks.return_value = (
                [{"id": "t1", "title": "Test"}],
                True,
            )
            mock_executor.get_auto_saved_playlist.return_value = None
            mock_executor.get_playback_action.return_value = None
            mock_executor_class.return_value = mock_executor

            events = []
            async for event in service.chat("find tracks", [], mock_db):
                events.append(event)

            # Should have text event with "found some tracks" message
            text_events = [e for e in events if e["type"] == "text"]
            found_message = any("found some tracks" in e["content"].lower() for e in text_events)
            assert found_message


class TestLLMServiceNavigationHint:
    """Tests for navigation hint handling from tool results."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def service(self):
        with patch("app.services.llm.service.get_app_settings_service") as mock_settings:
            mock_settings_instance = MagicMock()
            mock_settings_instance.get_effective.return_value = "sk-test-key"
            mock_settings.return_value = mock_settings_instance

            with patch("app.services.llm.service.anthropic.Anthropic"):
                service = LLMService()
                return service

    @pytest.mark.asyncio
    async def test_chat_yields_navigate_event_from_tool_result(self, service, mock_db):
        """Tool result with _navigate key should yield navigate event."""
        service.claude_client.messages.create.side_effect = [
            FakeResponse(
                content=[FakeToolUseBlock("show_settings", {})],
                stop_reason="tool_use",
            ),
            FakeResponse(
                content=[FakeTextBlock("Opening settings.")],
                stop_reason="end_turn",
            ),
        ]

        with patch("app.services.llm.service.ToolExecutor") as mock_executor_class:
            mock_executor = MagicMock()
            mock_executor.execute = AsyncMock(return_value={"_navigate": "settings", "status": "ok"})
            mock_executor.get_queued_tracks.return_value = ([], True)
            mock_executor.get_auto_saved_playlist.return_value = None
            mock_executor.get_playback_action.return_value = None
            mock_executor_class.return_value = mock_executor

            events = []
            async for event in service.chat("open settings", [], mock_db):
                events.append(event)

            navigate_events = [e for e in events if e["type"] == "navigate"]
            assert len(navigate_events) == 1
            assert navigate_events[0]["view"] == "settings"
