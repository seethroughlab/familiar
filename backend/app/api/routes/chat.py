"""Chat endpoints for LLM-powered music discovery."""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentProfile, DbSession
from app.api.exceptions import LLMNotConfiguredError, sanitize_error_for_client
from app.api.ratelimit import CHAT_RATE_LIMIT, limiter
from app.services.app_settings import get_app_settings_service
from app.services.llm import LLMService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatStatusResponse(BaseModel):
    configured: bool
    provider: str | None = None


class ChatResponse(BaseModel):
    response: str
    tool_calls: list[dict[str, Any]]
    queued_tracks: list[dict[str, Any]]
    playback_action: dict[str, Any] | None = None


@router.get("/status", response_model=ChatStatusResponse)
async def get_chat_status() -> ChatStatusResponse:
    """Check if LLM is configured and available.

    Returns configuration status so the frontend can show
    appropriate warnings before the user tries to chat. Reports the *active*
    provider — selecting "openai" without openai credentials returns
    configured=False even if ANTHROPIC_API_KEY is set.
    """
    settings_service = get_app_settings_service()
    return ChatStatusResponse(
        configured=settings_service.is_active_provider_configured(),
        provider=settings_service.get_active_provider(),
    )


class ChatMessage(BaseModel):
    """A single chat message."""
    role: str = Field(..., pattern=r"^(user|assistant)$")
    content: str = Field(..., max_length=50000)


class ChatRequest(BaseModel):
    """Chat request body."""
    message: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="User message, max 10,000 characters"
    )
    history: list[ChatMessage] = Field(
        default=[],
        max_length=100,
        description="Chat history, max 100 messages"
    )
    visible_track_ids: list[str] = Field(
        default=[],
        max_length=100,
        description="Track IDs currently visible in the library view"
    )

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, v: str) -> str:
        """Ensure message is not just whitespace."""
        if not v.strip():
            raise ValueError("Message cannot be empty or whitespace only")
        return v


async def generate_sse_events(
    message: str,
    history: list[dict[str, Any]],
    db: AsyncSession,
    profile_id: UUID | None = None,
    visible_track_ids: list[str] | None = None,
) -> AsyncIterator[str]:
    """Generate Server-Sent Events for streaming chat response."""
    llm_service = LLMService()  # type: ignore[no-untyped-call]

    try:
        async for event in llm_service.chat(message, history, db, profile_id, visible_track_ids):  # type: ignore[no-untyped-call]
            # Format as SSE
            yield f"data: {json.dumps(event)}\n\n"
    except Exception as e:
        # Log the full error for debugging, but send sanitized message to client
        logger.exception("Error in chat stream")
        safe_message = sanitize_error_for_client(e)
        yield f"data: {json.dumps({'type': 'error', 'message': safe_message})}\n\n"

    yield "data: [DONE]\n\n"


@router.post(
    "/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "Server-sent events carrying chat deltas and tool calls.",
        }
    },
)
@limiter.limit(CHAT_RATE_LIMIT)
async def chat_stream(
    request: Request,
    chat_request: ChatRequest,
    db: DbSession,
    profile: CurrentProfile,
) -> StreamingResponse:
    """
    Stream a chat response with tool execution.

    Returns Server-Sent Events (SSE) with the following event types:
    - text: LLM text response chunk
    - tool_call: Tool being called (name, input)
    - tool_result: Result of tool execution
    - queue: Tracks to add to queue
    - playback: Playback control action
    - done: Stream complete
    - error: Error occurred
    """
    settings_service = get_app_settings_service()
    if not settings_service.is_active_provider_configured():
        raise LLMNotConfiguredError()

    # Convert history to format expected by LLM service
    history = [{"role": msg.role, "content": msg.content} for msg in chat_request.history]
    profile_id = profile.id if profile else None

    return StreamingResponse(
        generate_sse_events(
            chat_request.message,
            history,
            db,
            profile_id,
            chat_request.visible_track_ids or None,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.post("", response_model=ChatResponse)
@limiter.limit(CHAT_RATE_LIMIT)
async def chat(
    request: Request,
    chat_request: ChatRequest,
    db: DbSession,
    profile: CurrentProfile,
) -> ChatResponse:
    """
    Non-streaming chat endpoint.

    Returns the complete response after all tool calls are processed.
    Useful for simpler integrations that don't need streaming.
    """
    settings_service = get_app_settings_service()
    if not settings_service.is_active_provider_configured():
        raise LLMNotConfiguredError()

    llm_service = LLMService()  # type: ignore[no-untyped-call]
    history = [{"role": msg.role, "content": msg.content} for msg in chat_request.history]
    profile_id = profile.id if profile else None
    visible_track_ids = chat_request.visible_track_ids or None

    response_text = ""
    tool_calls = []
    queued_tracks = []
    playback_action = None

    async for event in llm_service.chat(chat_request.message, history, db, profile_id, visible_track_ids):  # type: ignore[no-untyped-call]
        if event["type"] == "text":
            response_text += event["content"]
        elif event["type"] == "tool_call":
            tool_calls.append({
                "name": event["name"],
                "input": event["input"]
            })
        elif event["type"] == "queue":
            queued_tracks = event["tracks"]
        elif event["type"] == "playback":
            playback_action = event["action"]

    return ChatResponse(
        response=response_text,
        tool_calls=tool_calls,
        queued_tracks=queued_tracks,
        playback_action=playback_action,
    )
