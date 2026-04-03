"""Shared Anthropic model selection for backend LLM callsites."""

from typing import Literal

AnthropicModelRole = Literal["chat", "utility"]

_ACTIVE_ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"


def get_anthropic_model(role: AnthropicModelRole) -> str:
    """Return the configured Anthropic model for a usage role."""
    if role not in ("chat", "utility"):
        raise ValueError(f"Unknown Anthropic model role: {role}")
    return _ACTIVE_ANTHROPIC_MODEL
