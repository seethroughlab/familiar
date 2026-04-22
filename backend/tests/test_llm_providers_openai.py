"""Tests for the OpenAI-compatible provider (providers_openai.py)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm.providers_openai import (
    OpenAIProvider,
    _to_openai_messages,
    _to_openai_tools,
)
from tests.llm_fakes import (
    FakeOpenAIChoice,
    FakeOpenAIMessage,
    FakeOpenAIResponse,
    FakeOpenAIToolCall,
)


def _mk_provider(
    *,
    api_key: str | None = "sk-test",
    base_url: str | None = None,
    chat_model: str | None = "gpt-4o",
    utility_model: str | None = "gpt-4o-mini",
) -> OpenAIProvider:
    with patch(
        "app.services.llm.providers_openai.get_app_settings_service"
    ) as mock_settings:
        inst = MagicMock()

        def fake_get_effective(key: str):
            return {
                "openai_api_key": api_key,
                "openai_base_url": base_url,
                "openai_chat_model": chat_model,
                "openai_utility_model": utility_model,
            }.get(key)

        inst.get_effective.side_effect = fake_get_effective
        inst.has_openai_config.return_value = bool(api_key and chat_model and utility_model)
        mock_settings.return_value = inst
        return OpenAIProvider()


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


class TestToolSchemaTranslation:
    def test_translates_input_schema_to_parameters(self):
        anthropic_tool = {
            "name": "search_library",
            "description": "Search",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }
        result = _to_openai_tools([anthropic_tool])
        assert result == [
            {
                "type": "function",
                "function": {
                    "name": "search_library",
                    "description": "Search",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        ]


class TestMessageTranslation:
    def test_prepends_system_and_appends_user(self):
        out = _to_openai_messages(
            conversation_history=[
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ],
            user_message="new question",
            system_prompt="You are helpful.",
        )
        assert out[0] == {"role": "system", "content": "You are helpful."}
        assert out[-1] == {"role": "user", "content": "new question"}
        assert {"role": "assistant", "content": "hi"} in out


class TestConfiguration:
    def test_is_configured_requires_all_fields(self):
        assert _mk_provider().is_configured()
        # has_openai_config is what we delegate to; stub it to simulate
        # missing one field:
        p = _mk_provider(chat_model=None)
        assert not p.is_configured()


class TestChatFlow:
    @pytest.mark.asyncio
    async def test_text_response(self):
        provider = _mk_provider()
        with patch(
            "app.services.llm.providers_openai.openai.OpenAI"
        ) as mock_openai:
            client = MagicMock()
            client.chat.completions.create.return_value = FakeOpenAIResponse(
                choices=[
                    FakeOpenAIChoice(FakeOpenAIMessage(content="Hello!"), "stop")
                ]
            )
            mock_openai.return_value = client
            events = await _drain(provider, tool_executor=MagicMock())

        assert any(e["type"] == "text" and e["content"] == "Hello!" for e in events)
        assert client.chat.completions.create.call_args.kwargs["model"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_tool_call_happy_path(self):
        provider = _mk_provider()
        with patch(
            "app.services.llm.providers_openai.openai.OpenAI"
        ) as mock_openai:
            client = MagicMock()
            client.chat.completions.create.side_effect = [
                FakeOpenAIResponse(
                    choices=[
                        FakeOpenAIChoice(
                            FakeOpenAIMessage(
                                content=None,
                                tool_calls=[
                                    FakeOpenAIToolCall(
                                        "search_library",
                                        json.dumps({"query": "jazz"}),
                                        call_id="call_abc",
                                    )
                                ],
                            ),
                            finish_reason="tool_calls",
                        )
                    ]
                ),
                FakeOpenAIResponse(
                    choices=[
                        FakeOpenAIChoice(
                            FakeOpenAIMessage(content="Found some."),
                            finish_reason="stop",
                        )
                    ]
                ),
            ]
            mock_openai.return_value = client

            executor = MagicMock()
            executor.execute = AsyncMock(return_value={"count": 1})
            events = await _drain(provider, tool_executor=executor)

        types = [e["type"] for e in events]
        assert "tool_call" in types
        assert "tool_result" in types
        assert "text" in types

        # First call forces tools; second doesn't.
        first = client.chat.completions.create.call_args_list[0].kwargs
        second = client.chat.completions.create.call_args_list[1].kwargs
        assert first.get("tool_choice") == "required"
        assert "tool_choice" not in second

    @pytest.mark.asyncio
    async def test_malformed_json_in_arguments_yields_error(self):
        provider = _mk_provider()
        with patch(
            "app.services.llm.providers_openai.openai.OpenAI"
        ) as mock_openai:
            client = MagicMock()
            client.chat.completions.create.return_value = FakeOpenAIResponse(
                choices=[
                    FakeOpenAIChoice(
                        FakeOpenAIMessage(
                            content=None,
                            tool_calls=[
                                FakeOpenAIToolCall(
                                    "search_library",
                                    "{not valid json",
                                )
                            ],
                        ),
                        finish_reason="tool_calls",
                    )
                ]
            )
            mock_openai.return_value = client
            events = await _drain(provider, tool_executor=MagicMock())

        errors = [e for e in events if e["type"] == "error"]
        assert len(errors) == 1
        assert "malformed JSON" in errors[0]["content"]

    @pytest.mark.asyncio
    async def test_tool_choice_required_retry(self):
        """Some OpenAI-compat servers reject tool_choice=required; we retry without it."""
        import openai as openai_mod

        provider = _mk_provider()
        with patch(
            "app.services.llm.providers_openai.openai.OpenAI"
        ) as mock_openai:
            client = MagicMock()
            # First call raises, retry succeeds.
            client.chat.completions.create.side_effect = [
                openai_mod.BadRequestError(
                    message="tool_choice not supported",
                    response=MagicMock(status_code=400),
                    body={"error": {"message": "tool_choice not supported"}},
                ),
                FakeOpenAIResponse(
                    choices=[
                        FakeOpenAIChoice(
                            FakeOpenAIMessage(content="ok"), finish_reason="stop"
                        )
                    ]
                ),
            ]
            mock_openai.return_value = client

            events = await _drain(provider, tool_executor=MagicMock())

        assert client.chat.completions.create.call_count == 2
        retry_kwargs = client.chat.completions.create.call_args_list[1].kwargs
        assert "tool_choice" not in retry_kwargs
        assert any(e["type"] == "text" for e in events)

    @pytest.mark.asyncio
    async def test_base_url_passed_through_when_set(self):
        provider = _mk_provider(base_url="https://api.groq.com/openai/v1")
        with patch(
            "app.services.llm.providers_openai.openai.OpenAI"
        ) as mock_openai:
            client = MagicMock()
            client.chat.completions.create.return_value = FakeOpenAIResponse(
                choices=[FakeOpenAIChoice(FakeOpenAIMessage(content="hi"), "stop")]
            )
            mock_openai.return_value = client
            await _drain(provider, tool_executor=MagicMock())

        ctor_kwargs = mock_openai.call_args.kwargs
        assert ctor_kwargs["base_url"] == "https://api.groq.com/openai/v1"

    @pytest.mark.asyncio
    async def test_base_url_none_when_unset(self):
        provider = _mk_provider(base_url=None)
        with patch(
            "app.services.llm.providers_openai.openai.OpenAI"
        ) as mock_openai:
            client = MagicMock()
            client.chat.completions.create.return_value = FakeOpenAIResponse(
                choices=[FakeOpenAIChoice(FakeOpenAIMessage(content="hi"), "stop")]
            )
            mock_openai.return_value = client
            await _drain(provider, tool_executor=MagicMock())

        ctor_kwargs = mock_openai.call_args.kwargs
        assert ctor_kwargs["base_url"] is None

    @pytest.mark.asyncio
    async def test_missing_chat_model_yields_error_without_call(self):
        provider = _mk_provider(chat_model=None)
        with patch(
            "app.services.llm.providers_openai.openai.OpenAI"
        ) as mock_openai:
            events = await _drain(provider, tool_executor=MagicMock())
        assert any(e["type"] == "error" for e in events)
        assert not mock_openai.called


class TestUtility:
    @pytest.mark.asyncio
    async def test_complete_utility_returns_trimmed_text(self):
        provider = _mk_provider()
        with patch(
            "app.services.llm.providers_openai.openai.OpenAI"
        ) as mock_openai:
            client = MagicMock()
            client.chat.completions.create.return_value = FakeOpenAIResponse(
                choices=[
                    FakeOpenAIChoice(
                        FakeOpenAIMessage(content="  Midnight Drive  "),
                        finish_reason="stop",
                    )
                ]
            )
            mock_openai.return_value = client
            result = await provider.complete_utility(prompt="name this")
        assert result == "Midnight Drive"

    @pytest.mark.asyncio
    async def test_complete_utility_raises_without_model(self):
        provider = _mk_provider(utility_model=None)
        with pytest.raises(ValueError):
            await provider.complete_utility(prompt="x")
