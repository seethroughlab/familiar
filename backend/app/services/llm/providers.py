"""LLM provider abstraction.

Each provider owns its own conversation-and-tool loop. The service layer passes in
a system prompt, user message, conversation history, canonical tool definitions
(Anthropic `input_schema` shape), and a `ToolExecutor`. The provider yields a
normalized event stream that the service layer handles uniformly.

Normalized events:
    {"type": "text", "content": str}
    {"type": "tool_call", "id": str, "name": str, "input": dict}
    {"type": "tool_result", "name": str, "result": dict}
    {"type": "navigate", "view": str}
    {"type": "error", "content": str}

The provider does NOT emit queue/ephemeral_playlist_created/playback/done —
those are drained from ToolExecutor state by the service layer after the stream ends.
"""

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from app.services.app_settings import get_app_settings_service

from .executor import ToolExecutor


@runtime_checkable
class LLMProvider(Protocol):
    """Interface for chat + utility LLM calls. Providers own their SDK loop."""

    name: str  # "anthropic" | "openai"

    def is_configured(self) -> bool:
        """Does this provider have the credentials/config it needs to make calls?"""
        ...

    def chat(
        self,
        *,
        user_message: str,
        conversation_history: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
        tool_executor: ToolExecutor,
        max_iterations: int = 8,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run a chat turn with tool-use. Yields normalized events.

        Conversation history is a list of {role: "user"|"assistant", content: str}
        — plain text only, as emitted by the frontend. Each provider translates it
        into its own message shape internally.
        """
        ...

    async def complete_utility(
        self,
        *,
        prompt: str,
        max_tokens: int = 200,
        timeout_seconds: float = 30.0,
    ) -> str:
        """Single-turn, no-tools completion. Returns plain text."""
        ...


def get_provider() -> LLMProvider:
    """Resolve the active provider based on the user's selection.

    Defaults to AnthropicProvider. Import is deferred so the openai package is
    only required when the OpenAI provider is actually selected.
    """
    name = get_app_settings_service().get_active_provider()
    if name == "openai":
        from .providers_openai import OpenAIProvider

        return OpenAIProvider()

    from .providers_anthropic import AnthropicProvider

    return AnthropicProvider()
