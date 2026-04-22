"""OpenAI-compatible provider.

Works with any server that speaks the OpenAI Chat Completions protocol —
api.openai.com, Groq, Together, OpenRouter, LocalAI, vLLM, llama.cpp server,
LM Studio, Ollama's /v1 endpoint, etc.

Tool definitions arrive in Anthropic `input_schema` shape (the canonical source
in tools.py) and are translated to OpenAI `{type: "function", function: {...}}`
shape at call time. JSON Schema structure is identical between the two.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
import openai

from app.services.app_settings import get_app_settings_service

from .executor import ToolExecutor

logger = logging.getLogger(__name__)

_CHAT_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=10.0)


def _to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate Anthropic-shape tool definitions to OpenAI function-tool shape."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


def _to_openai_messages(
    conversation_history: list[dict[str, Any]],
    user_message: str,
    system_prompt: str,
) -> list[dict[str, Any]]:
    """Build the initial OpenAI messages list from plain-text history."""
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for msg in conversation_history:
        role = msg.get("role")
        content = msg.get("content", "")
        if role in ("user", "assistant") and isinstance(content, str):
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})
    return messages


class OpenAIProvider:
    """LLM provider using the openai SDK against any OpenAI-compatible endpoint."""

    name = "openai"

    def __init__(self) -> None:
        self._settings_service = get_app_settings_service()

    def _api_key(self) -> str | None:
        return self._settings_service.get_effective("openai_api_key")

    def _base_url(self) -> str | None:
        return self._settings_service.get_effective("openai_base_url")

    def _chat_model(self) -> str | None:
        return self._settings_service.get_effective("openai_chat_model")

    def _utility_model(self) -> str | None:
        return self._settings_service.get_effective("openai_utility_model")

    def is_configured(self) -> bool:
        return self._settings_service.has_openai_config()

    def _client(self, timeout: httpx.Timeout) -> openai.OpenAI:
        return openai.OpenAI(
            api_key=self._api_key(),
            base_url=self._base_url() or None,
            timeout=timeout,
        )

    async def chat(
        self,
        *,
        user_message: str,
        conversation_history: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
        tool_executor: ToolExecutor,
        max_iterations: int = 8,
    ) -> AsyncIterator[dict[str, Any]]:
        if not self._api_key():
            yield {"type": "error", "content": "OpenAI API key not configured"}
            return
        model = self._chat_model()
        if not model:
            yield {
                "type": "error",
                "content": "OPENAI_CHAT_MODEL is not set. Set it to a model your endpoint serves.",
            }
            return

        client = self._client(_CHAT_TIMEOUT)
        openai_tools = _to_openai_tools(tools)
        messages = _to_openai_messages(conversation_history, user_message, system_prompt)

        first_turn = True
        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "max_tokens": 2048,
                    "tools": openai_tools,
                    "messages": messages,
                }
                if first_turn:
                    kwargs["tool_choice"] = "required"

                try:
                    response = client.chat.completions.create(**kwargs)
                except openai.BadRequestError as e:
                    # Some OpenAI-compatible servers (older Ollama, partial proxies)
                    # reject tool_choice="required". Retry once without it.
                    if first_turn and "tool_choice" in str(e).lower():
                        logger.info(
                            "Server rejected tool_choice=required; retrying without it"
                        )
                        kwargs.pop("tool_choice", None)
                        response = client.chat.completions.create(**kwargs)
                    else:
                        raise
                finally:
                    first_turn = False
            except openai.AuthenticationError as e:
                logger.error(f"OpenAI AuthenticationError: {e}")
                yield {
                    "type": "error",
                    "content": "Invalid API key. Check your OpenAI API key in Settings.",
                }
                return
            except openai.BadRequestError as e:
                logger.error(f"OpenAI BadRequestError: {e}")
                yield {"type": "error", "content": f"API error: {e}"}
                return
            except openai.APIError as e:
                logger.error(f"OpenAI APIError: {e}")
                yield {"type": "error", "content": f"API error: {e}"}
                return

            choice = response.choices[0]
            msg = choice.message

            assistant_text = msg.content or ""
            if assistant_text:
                yield {"type": "text", "content": assistant_text}

            tool_calls = msg.tool_calls or []

            if tool_calls:
                # Serialize the raw tool_calls for the next assistant turn in the transcript.
                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_text or None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in tool_calls
                        ],
                    }
                )

                for tc in tool_calls:
                    name = tc.function.name
                    try:
                        tool_input = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        logger.warning(
                            f"Model returned malformed JSON for {name}: "
                            f"{tc.function.arguments!r}"
                        )
                        yield {
                            "type": "error",
                            "content": (
                                f"Model returned malformed JSON for tool {name!r}. "
                                "Try a different model or rephrase."
                            ),
                        }
                        return

                    yield {
                        "type": "tool_call",
                        "id": tc.id,
                        "name": name,
                        "input": tool_input,
                    }

                    result = await tool_executor.execute(name, tool_input)
                    logger.info(
                        f"Tool {name} executed, result keys: "
                        f"{list(result.keys()) if isinstance(result, dict) else 'not-dict'}"
                    )

                    yield {"type": "tool_result", "name": name, "result": result}

                    if isinstance(result, dict) and "_navigate" in result:
                        yield {"type": "navigate", "view": result["_navigate"]}

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result),
                        }
                    )

            finish = choice.finish_reason
            if finish == "tool_calls":
                continue
            # "stop", "length", "content_filter", None — terminate in all cases.
            return

        logger.warning(f"OpenAI hit max iterations ({max_iterations}), forcing end")
        yield {"type": "text", "content": "I found some tracks for you."}

    async def complete_utility(
        self,
        *,
        prompt: str,
        max_tokens: int = 200,
        timeout_seconds: float = 30.0,
    ) -> str:
        if not self._api_key():
            raise ValueError("OpenAI API key not configured")
        model = self._utility_model()
        if not model:
            raise ValueError(
                "OPENAI_UTILITY_MODEL is not set. Set it to a model your endpoint serves."
            )

        timeout = httpx.Timeout(
            connect=min(5.0, timeout_seconds),
            read=timeout_seconds,
            write=min(10.0, timeout_seconds),
            pool=min(5.0, timeout_seconds),
        )
        client = self._client(timeout)
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        if not response.choices:
            return ""
        text = response.choices[0].message.content or ""
        return text.strip()
