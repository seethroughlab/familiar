"""Anthropic provider — wraps the native Anthropic SDK.

The chat loop and error handling here are a straight move of what previously
lived in service.py::_chat_claude. Behavior is unchanged for existing installs.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any, cast

import anthropic
import httpx

from app.services.app_settings import get_app_settings_service

from .executor import ToolExecutor
from .models import get_anthropic_model

logger = logging.getLogger(__name__)

# connect: establish connection; read: wait for response data; write: send;
# pool: acquire connection from pool. read=120s allows for long tool chains.
_CHAT_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=10.0)
_UTILITY_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)


class AnthropicProvider:
    """LLM provider using Anthropic's native SDK."""

    name = "anthropic"

    def __init__(self) -> None:
        self._settings_service = get_app_settings_service()

    def _api_key(self) -> str | None:
        return self._settings_service.get_effective("anthropic_api_key")

    def is_configured(self) -> bool:
        return bool(self._api_key())

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
        api_key = self._api_key()
        if not api_key:
            yield {"type": "error", "content": "Anthropic API key not configured"}
            return

        client = anthropic.Anthropic(api_key=api_key, timeout=_CHAT_TIMEOUT)

        messages: list[dict[str, Any]] = conversation_history + [
            {"role": "user", "content": user_message}
        ]

        first_turn = True
        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            try:
                create_kwargs: dict[str, Any] = {
                    "model": get_anthropic_model("chat"),
                    "max_tokens": 2048,
                    "system": system_prompt,
                    "tools": cast(Any, tools),
                    "messages": cast(Any, messages),
                }
                if first_turn:
                    create_kwargs["tool_choice"] = {"type": "any"}
                    first_turn = False

                response = client.messages.create(**create_kwargs)
            except anthropic.BadRequestError as e:
                logger.error(f"Anthropic BadRequestError: {e}")
                yield {"type": "error", "content": f"API error: {e.message}"}
                return
            except anthropic.AuthenticationError as e:
                logger.error(f"Anthropic AuthenticationError: {e}")
                yield {
                    "type": "error",
                    "content": "Invalid API key. Check your Anthropic API key in Settings.",
                }
                return
            except anthropic.APIError as e:
                logger.error(f"Anthropic APIError: {e}")
                yield {"type": "error", "content": f"API error: {e.message}"}
                return

            assistant_content: list[Any] = []
            for block in response.content:
                if block.type == "text":
                    yield {"type": "text", "content": block.text}
                    assistant_content.append(block)
                elif block.type == "tool_use":
                    tool_input = cast(dict[str, Any], block.input)
                    yield {
                        "type": "tool_call",
                        "id": block.id,
                        "name": block.name,
                        "input": tool_input,
                    }

                    # Log inputs (truncated) to aid debugging
                    input_summary = {k: (str(v)[:80] if isinstance(v, (list, str)) and len(str(v)) > 80 else v) for k, v in tool_input.items()}
                    logger.info(f"Tool {block.name} input: {input_summary}")
                    result = await tool_executor.execute(block.name, tool_input)
                    result_count = result.get("count", result.get("queued", result.get("tracks_saved", "?"))) if isinstance(result, dict) else "?"
                    logger.info(
                        f"Tool {block.name} executed, result keys: "
                        f"{list(result.keys()) if isinstance(result, dict) else 'not-dict'}, count={result_count}"
                    )

                    yield {"type": "tool_result", "name": block.name, "result": result}

                    if isinstance(result, dict) and "_navigate" in result:
                        yield {"type": "navigate", "view": result["_navigate"]}

                    assistant_content.append(block)

                    messages.append({"role": "assistant", "content": assistant_content})
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": json.dumps(result),
                                }
                            ],
                        }
                    )
                    assistant_content = []

            if response.stop_reason == "end_turn":
                return
            if response.stop_reason == "tool_use":
                continue
            return

        logger.warning(f"Anthropic hit max iterations ({max_iterations}), forcing end")
        yield {"type": "text", "content": "I found some tracks for you."}

    async def complete_utility(
        self,
        *,
        prompt: str,
        max_tokens: int = 200,
        timeout_seconds: float = 30.0,
    ) -> str:
        api_key = self._api_key()
        if not api_key:
            raise ValueError("Anthropic API key not configured")

        timeout = httpx.Timeout(
            connect=min(5.0, timeout_seconds),
            read=timeout_seconds,
            write=min(10.0, timeout_seconds),
            pool=min(5.0, timeout_seconds),
        )
        client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        message = client.messages.create(
            model=get_anthropic_model("utility"),
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        if not message.content:
            return ""
        first_block = message.content[0]
        if hasattr(first_block, "text"):
            return first_block.text.strip()
        return ""
