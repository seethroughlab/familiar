"""Tests for the Anthropic provider loop (providers_anthropic.py).

Previously lived in test_llm_service.py while the loop was inline in service.py.
Behavior expectations are unchanged.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm.models import get_anthropic_model
from app.services.llm.providers_anthropic import AnthropicProvider
from tests.llm_fakes import FakeAnthropicResponse, FakeTextBlock, FakeToolUseBlock


def _mk_provider(api_key: str | None = "sk-test-key") -> AnthropicProvider:
    with patch(
        "app.services.llm.providers_anthropic.get_app_settings_service"
    ) as mock_settings:
        inst = MagicMock()
        inst.get_effective.return_value = api_key
        mock_settings.return_value = inst
        return AnthropicProvider()


async def _drain(provider, *, tool_executor, **kwargs):
    events = []
    async for e in provider.chat(
        user_message=kwargs.pop("user_message", "hi"),
        conversation_history=kwargs.pop("conversation_history", []),
        system_prompt=kwargs.pop("system_prompt", "sp"),
        tools=kwargs.pop("tools", []),
        tool_executor=tool_executor,
        **kwargs,
    ):
        events.append(e)
    return events


class TestAnthropicProviderConfig:
    def test_is_configured_true_with_key(self):
        assert _mk_provider("sk-test-key").is_configured()

    def test_is_configured_false_without_key(self):
        assert not _mk_provider(None).is_configured()


class TestAnthropicChatFlow:
    @pytest.mark.asyncio
    async def test_yields_error_when_no_key(self):
        provider = _mk_provider(None)
        events = await _drain(provider, tool_executor=MagicMock())
        assert events == [
            {"type": "error", "content": "Anthropic API key not configured"}
        ]

    @pytest.mark.asyncio
    async def test_simple_text_response(self):
        provider = _mk_provider()
        with patch(
            "app.services.llm.providers_anthropic.anthropic.Anthropic"
        ) as mock_anth:
            client = MagicMock()
            client.messages.create.return_value = FakeAnthropicResponse(
                content=[FakeTextBlock("Hello! How can I help?")],
                stop_reason="end_turn",
            )
            mock_anth.return_value = client

            events = await _drain(provider, tool_executor=MagicMock())

        assert any(e["type"] == "text" for e in events)
        assert client.messages.create.call_args.kwargs["model"] == get_anthropic_model("chat")

    @pytest.mark.asyncio
    async def test_tool_use_flow(self):
        provider = _mk_provider()
        with patch(
            "app.services.llm.providers_anthropic.anthropic.Anthropic"
        ) as mock_anth:
            client = MagicMock()
            client.messages.create.side_effect = [
                FakeAnthropicResponse(
                    content=[FakeToolUseBlock("search_library", {"query": "jazz"})],
                    stop_reason="tool_use",
                ),
                FakeAnthropicResponse(
                    content=[FakeTextBlock("I found some jazz tracks!")],
                    stop_reason="end_turn",
                ),
            ]
            mock_anth.return_value = client

            executor = MagicMock()
            executor.execute = AsyncMock(return_value={"tracks": [], "count": 0})
            events = await _drain(provider, tool_executor=executor)

        types = [e["type"] for e in events]
        assert "tool_call" in types
        assert "tool_result" in types
        assert "text" in types

    @pytest.mark.asyncio
    async def test_navigate_hint_yields_navigate_event(self):
        provider = _mk_provider()
        with patch(
            "app.services.llm.providers_anthropic.anthropic.Anthropic"
        ) as mock_anth:
            client = MagicMock()
            client.messages.create.side_effect = [
                FakeAnthropicResponse(
                    content=[FakeToolUseBlock("show_settings", {})],
                    stop_reason="tool_use",
                ),
                FakeAnthropicResponse(
                    content=[FakeTextBlock("Opening settings.")],
                    stop_reason="end_turn",
                ),
            ]
            mock_anth.return_value = client

            executor = MagicMock()
            executor.execute = AsyncMock(
                return_value={"_navigate": "settings", "status": "ok"}
            )
            events = await _drain(provider, tool_executor=executor)

        nav = [e for e in events if e["type"] == "navigate"]
        assert nav == [{"type": "navigate", "view": "settings"}]


class TestAnthropicErrors:
    @pytest.mark.asyncio
    async def test_bad_request(self):
        import anthropic

        provider = _mk_provider()
        with patch(
            "app.services.llm.providers_anthropic.anthropic.Anthropic"
        ) as mock_anth:
            client = MagicMock()
            client.messages.create.side_effect = anthropic.BadRequestError(
                message="Invalid",
                response=MagicMock(status_code=400),
                body={"error": {"message": "Invalid"}},
            )
            mock_anth.return_value = client
            events = await _drain(provider, tool_executor=MagicMock())
        assert events == [{"type": "error", "content": "API error: Invalid"}]

    @pytest.mark.asyncio
    async def test_auth_error(self):
        import anthropic

        provider = _mk_provider()
        with patch(
            "app.services.llm.providers_anthropic.anthropic.Anthropic"
        ) as mock_anth:
            client = MagicMock()
            client.messages.create.side_effect = anthropic.AuthenticationError(
                message="Bad key",
                response=MagicMock(status_code=401),
                body={"error": {"message": "Bad key"}},
            )
            mock_anth.return_value = client
            events = await _drain(provider, tool_executor=MagicMock())
        assert events[0]["type"] == "error"
        assert "Invalid API key" in events[0]["content"]


class TestAnthropicMaxIterations:
    @pytest.mark.asyncio
    async def test_max_iterations_emits_fallback_text(self):
        provider = _mk_provider()
        with patch(
            "app.services.llm.providers_anthropic.anthropic.Anthropic"
        ) as mock_anth:
            client = MagicMock()
            client.messages.create.return_value = FakeAnthropicResponse(
                content=[FakeToolUseBlock("search_library", {"query": "x"})],
                stop_reason="tool_use",
            )
            mock_anth.return_value = client

            executor = MagicMock()
            executor.execute = AsyncMock(return_value={"tracks": [], "count": 0})
            events = await _drain(provider, tool_executor=executor)

            assert client.messages.create.call_count == 8
            text_events = [e for e in events if e["type"] == "text"]
            assert any("found some tracks" in t["content"].lower() for t in text_events)
