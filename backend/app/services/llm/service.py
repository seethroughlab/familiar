"""LLM service for conversational music discovery."""
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, cast
from uuid import UUID

import anthropic
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.app_settings import get_app_settings_service

from .executor import ToolExecutor
from .tools import MUSIC_TOOLS, SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Timeout configuration for Anthropic API calls
# - connect: Time to establish connection (10s)
# - read: Time to wait for response data (120s - allows for long tool chains)
# - write: Time to send request data (120s)
# - pool: Time to acquire connection from pool (10s)
LLM_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=10.0)


class LLMService:
    """Service for conversational music discovery using Claude."""

    def __init__(self) -> None:
        api_key = self._get_api_key()
        self.claude_client = anthropic.Anthropic(api_key=api_key, timeout=LLM_TIMEOUT)

    def _get_api_key(self) -> str | None:
        """Get Anthropic API key with proper precedence."""
        return get_app_settings_service().get_effective("anthropic_api_key")

    async def chat(
        self,
        message: str,
        conversation_history: list[dict[str, Any]],
        db: AsyncSession,
        profile_id: UUID | None = None,
        visible_track_ids: list[str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Process a chat message and stream the response.

        Yields dicts with types:
        - {"type": "text", "content": "..."}
        - {"type": "tool_call", "name": "...", "input": {...}}
        - {"type": "tool_result", "name": "...", "result": {...}}
        - {"type": "queue", "tracks": [...], "clear": bool}
        - {"type": "playback", "action": "..."}
        - {"type": "done"}
        """
        async for event in self._chat_claude(message, conversation_history, db, profile_id, visible_track_ids):
            yield event

    async def _chat_claude(
        self,
        message: str,
        conversation_history: list[dict[str, Any]],
        db: AsyncSession,
        profile_id: UUID | None = None,
        visible_track_ids: list[str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Chat using Claude API."""
        if not self.claude_client:
            yield {"type": "error", "content": "Claude client not configured"}
            return

        tool_executor = ToolExecutor(db, profile_id, user_message=message, visible_track_ids=visible_track_ids)
        messages: list[dict[str, Any]] = conversation_history + [
            {"role": "user", "content": message}
        ]

        # Build dynamic system prompt with current settings
        settings = get_app_settings_service().get()
        discovery_mode = settings.playlist_discovery_mode
        system_prompt = SYSTEM_PROMPT + f"""

## Current User Settings

- **playlist_discovery_mode**: "{discovery_mode}"
{"  → You MUST include suggested_tracks in queue_tracks calls. Always suggest 3-5 relevant tracks the user might want to acquire that fit the request but aren't in their library." if discovery_mode == "suggest_missing" else "  → Only use local library tracks. Do not include suggested_tracks."}"""

        first_turn = True
        max_iterations = 8  # Prevent infinite tool loops
        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            try:
                # Force tool use on first turn to prevent hallucination
                create_kwargs: dict[str, Any] = {
                    "model": "claude-sonnet-4-5-20250929",
                    "max_tokens": 2048,
                    "system": system_prompt,
                    "tools": cast(Any, MUSIC_TOOLS),
                    "messages": cast(Any, messages),
                }
                if first_turn:
                    create_kwargs["tool_choice"] = {"type": "any"}
                    first_turn = False

                response = self.claude_client.messages.create(**create_kwargs)
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

            # Process response content
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

                    result = await tool_executor.execute(block.name, tool_input)
                    logger.info(f"Tool {block.name} executed, result keys: {list(result.keys()) if isinstance(result, dict) else 'not-dict'}")

                    yield {"type": "tool_result", "name": block.name, "result": result}

                    # Check for navigation hint in result
                    if isinstance(result, dict) and "_navigate" in result:
                        yield {"type": "navigate", "view": result["_navigate"]}

                    assistant_content.append(block)

                    messages.append({"role": "assistant", "content": assistant_content})
                    messages.append({
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result),
                            }
                        ],
                    })
                    assistant_content = []

            if response.stop_reason == "end_turn":
                queued, clear_queue = tool_executor.get_queued_tracks()
                if queued:
                    yield {"type": "queue", "tracks": queued, "clear": clear_queue}

                # Emit ephemeral playlist metadata for frontend to store temporarily
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
                break
            elif response.stop_reason == "tool_use":
                continue
            else:
                yield {"type": "done"}
                break
        else:
            # Hit max iterations - force end and queue any tracks found
            logger.warning(f"Hit max iterations ({max_iterations}), forcing end")
            queued, clear_queue = tool_executor.get_queued_tracks()
            if queued:
                yield {"type": "queue", "tracks": queued, "clear": clear_queue}
            yield {"type": "text", "content": "I found some tracks for you."}
            yield {"type": "done"}

