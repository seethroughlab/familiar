"""LLM service for conversational music discovery.

Provider-agnostic: the active provider (Anthropic or OpenAI-compatible) is resolved
via get_provider() and owns its own conversation-and-tool loop. This module just
builds the system prompt, delegates to the provider, passes events through, and
drains ToolExecutor state (queue/ephemeral playlist/playback) after the stream ends.
"""

import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.app_settings import get_app_settings_service

from .executor import ToolExecutor
from .providers import get_provider
from .tools import MUSIC_TOOLS, SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class LLMService:
    """Service for conversational music discovery."""

    def __init__(self) -> None:
        self.provider = get_provider()

    def _build_system_prompt(self) -> str:
        settings = get_app_settings_service().get()
        discovery_mode = settings.playlist_discovery_mode
        suffix = (
            "  → You MUST include suggested_tracks in queue_tracks calls. "
            "Always suggest 3-5 relevant tracks the user might want to acquire "
            "that fit the request but aren't in their library."
            if discovery_mode == "suggest_missing"
            else "  → Only use local library tracks. Do not include suggested_tracks."
        )
        return (
            SYSTEM_PROMPT
            + f"""

## Current User Settings

- **playlist_discovery_mode**: "{discovery_mode}"
{suffix}"""
        )

    async def chat(
        self,
        message: str,
        conversation_history: list[dict[str, Any]],
        db: AsyncSession,
        profile_id: UUID | None = None,
        visible_track_ids: list[str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Process a chat message and stream the response.

        Yields dicts with types:
        - {"type": "text", "content": "..."}
        - {"type": "tool_call", "name": "...", "input": {...}}
        - {"type": "tool_result", "name": "...", "result": {...}}
        - {"type": "navigate", "view": "..."}
        - {"type": "queue", "tracks": [...], "clear": bool}
        - {"type": "ephemeral_playlist_created", ...}
        - {"type": "playback", "action": "..."}
        - {"type": "error", "content": "..."}
        - {"type": "done"}
        """
        if not self.provider.is_configured():
            yield {
                "type": "error",
                "content": f"{self.provider.name} provider not configured",
            }
            return

        tool_executor = ToolExecutor(
            db, profile_id, user_message=message, visible_track_ids=visible_track_ids
        )
        system_prompt = self._build_system_prompt()

        saw_error = False
        async for event in self.provider.chat(
            user_message=message,
            conversation_history=conversation_history,
            system_prompt=system_prompt,
            tools=MUSIC_TOOLS,
            tool_executor=tool_executor,
        ):
            if event.get("type") == "error":
                saw_error = True
            yield event

        if saw_error:
            return

        queued, clear_queue = tool_executor.get_queued_tracks()
        if queued:
            yield {"type": "queue", "tracks": queued, "clear": clear_queue}

        auto_playlist = tool_executor.get_auto_saved_playlist()
        if auto_playlist and auto_playlist.get("ephemeral"):
            yield {
                "type": "ephemeral_playlist_created",
                "name": auto_playlist.get("name"),
                "generation_prompt": auto_playlist.get("generation_prompt"),
                "track_ids": auto_playlist.get("track_ids"),
                "tracks": auto_playlist.get("tracks"),
                "suggested_tracks": auto_playlist.get("suggested_tracks", []),
            }

        action = tool_executor.get_playback_action()
        if action:
            yield {"type": "playback", "action": action}

        yield {"type": "done"}
