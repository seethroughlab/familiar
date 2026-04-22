"""Shared fake response classes for LLM provider tests.

Mimics the shapes returned by `anthropic` and `openai` SDKs so provider chat
loops can be exercised without network calls.
"""

from __future__ import annotations

from uuid import uuid4


# ---------- Anthropic fakes ----------

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


class FakeAnthropicResponse:
    """Fake Claude API response (messages.create return value)."""

    def __init__(self, content: list, stop_reason: str = "end_turn"):
        self.content = content
        self.stop_reason = stop_reason


# ---------- OpenAI fakes ----------

class FakeOpenAIToolCallFunction:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class FakeOpenAIToolCall:
    def __init__(self, name: str, arguments: str, call_id: str | None = None):
        self.id = call_id or f"call_{uuid4().hex[:8]}"
        self.type = "function"
        self.function = FakeOpenAIToolCallFunction(name, arguments)


class FakeOpenAIMessage:
    def __init__(self, content: str | None = None, tool_calls: list | None = None):
        self.content = content
        self.tool_calls = tool_calls


class FakeOpenAIChoice:
    def __init__(self, message: FakeOpenAIMessage, finish_reason: str = "stop"):
        self.message = message
        self.finish_reason = finish_reason


class FakeOpenAIResponse:
    """Fake chat.completions.create return value."""

    def __init__(self, choices: list[FakeOpenAIChoice]):
        self.choices = choices
