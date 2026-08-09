"""Listening sessions: WebRTC signalling on the listener's own server (ADR-0036).

Revived from `ceeb926`, which shelved it for scope on 2026-03-06. The client half was rebuilt
afterwards against `https://familiar-sessions.fly.dev` — so every released build has signalled
through a box the listener does not run, and every development build has 404ed against the route
this file restores. ADR-0036 point 2 is the argument for bringing it back rather than keeping the
relay, and it is a values decision: the relay works.

**The split here is ADR-0036 point 5.** The REST half is typed to ADR-0007's rules so the Apple
clients generate it; the WebSocket is hand-written on every client, because the generator has
nothing to generate for a socket. That is the same exclusion ADR-0007 point 8 already makes for the
two SSE map variants.

**The server signals and never carries audio** (point 4). Every message below is an offer, an
answer, an ICE candidate or a piece of session bookkeeping. Peers connect directly; a listening
party must not turn a NAS into a streaming host.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.api.exceptions import NotFoundError
from app.api.schemas.common import error_responses
from app.config import settings
from app.services.sessions import SessionRole, get_session_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ── Response schemas ────────────────────────────────────────────────────────
#
# Typed rather than `dict[str, Any]` because ADR-0036 point 5 puts this tag on the generated
# surface. The service's `to_dict()` predates that and still returns a dict; these models are
# built from it rather than replacing it, so the WebSocket — which sends the same payloads and is
# not generated — keeps one source of truth for the shape.


class SessionPlaybackState(BaseModel):
    """What the host is playing, as guests last heard it."""

    track_id: str | None = None
    is_playing: bool = False
    position_ms: int = 0


class SessionParticipant(BaseModel):
    user_id: str
    username: str
    role: str
    joined_at: str
    webrtc_connected: bool = False


class SessionResponse(BaseModel):
    """A listening session, as looked up by its join code."""

    id: str
    code: str
    name: str
    host_id: str
    created_at: str
    participant_count: int
    webrtc_enabled: bool
    playback_state: SessionPlaybackState
    participants: list[SessionParticipant] = Field(default_factory=list)


class IceServer(BaseModel):
    """One entry of an `RTCConfiguration.iceServers` array, in the browser's own shape."""

    urls: str
    username: str | None = None
    credential: str | None = None


class IceServersResponse(BaseModel):
    ice_servers: list[IceServer]
    #: False when only STUN is configured, which is the default. Clients show this rather than
    #: discovering it by failing — ADR-0036 point 7.
    has_turn: bool


def get_ice_servers() -> list[dict[str, Any]]:
    """ICE configuration: Google STUN by default, TURN by configuration (ADR-0036 point 6).

    Familiar does not run a TURN server and does not promise one. Behind symmetric NAT with no TURN
    configured, a session will fail for reasons no amount of retrying fixes — which is why
    `has_turn` is reported rather than left to be inferred.
    """
    servers: list[dict[str, Any]] = [
        {"urls": "stun:stun.l.google.com:19302"},
        {"urls": "stun:stun1.l.google.com:19302"},
    ]

    if settings.turn_server_url:
        turn_config: dict[str, Any] = {"urls": settings.turn_server_url}
        if settings.turn_server_username:
            turn_config["username"] = settings.turn_server_username
        if settings.turn_server_credential:
            turn_config["credential"] = settings.turn_server_credential
        servers.append(turn_config)

    return servers


def has_turn_configured() -> bool:
    return bool(settings.turn_server_url)


@router.get(
    "/ice-servers",
    operation_id="sessions_get_ice_servers",
    response_model=IceServersResponse,
)
async def read_ice_servers() -> IceServersResponse:
    """The ICE configuration a client should use when establishing a session peer connection.

    A REST route rather than only the join payload, because the Apple clients need it before they
    have joined anything (ADR-0037), and because a client that wants to warn about symmetric NAT
    up front should not have to open a socket to find out.
    """
    return IceServersResponse(
        ice_servers=[IceServer(**server) for server in get_ice_servers()],
        has_turn=has_turn_configured(),
    )


@router.get(
    "/by-code/{code}",
    operation_id="sessions_get_by_code",
    response_model=SessionResponse,
    responses=error_responses(404),
)
async def get_session_by_code(code: str) -> SessionResponse:
    """Look up a session by its six-character join code.

    Case-insensitive, because the code is something one person reads aloud to another.
    """
    manager = get_session_manager()
    session = manager.get_session_by_code(code.upper())

    if not session:
        raise NotFoundError("Session not found")

    return SessionResponse.model_validate(session.to_dict())


@router.websocket("/ws")
async def session_websocket(websocket: WebSocket) -> None:
    """Signalling for listening sessions.

    Deliberately not part of the generated surface (ADR-0036 point 5). Messages:

    - `create`: `{"type": "create", "name": ..., "user_id": ..., "username": ...}`
    - `join`: `{"type": "join", "code": "ABC123", "user_id": ..., "username": ...}`
    - `join_guest`: `{"type": "join_guest", "code": "ABC123", "guest_name": ...}`
    - `playback`: `{"type": "playback", "track_id": ..., "is_playing": ..., "position_ms": ...}`
    - `sync_request`, `chat`, `leave`

    WebRTC signalling: `webrtc_request`, `webrtc_offer`, `webrtc_answer`, `webrtc_ice`,
    `webrtc_connected`.

    **This is the only WebSocket route in the backend.** `services/outputs.py` has a docstring
    describing signalling "to the frontend via WebSocket" for browser outputs, and carries a
    `websocket_id` field — but no such route exists and never has. So this is not a socket beside
    others; it is the one, and whatever a long-lived connection implies for deployment arrives
    with it.
    """
    await websocket.accept()
    manager = get_session_manager()
    current_user_id: UUID | None = None

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "create":
                user_id = UUID(data["user_id"])
                username = data.get("username", "Anonymous")
                name = data.get("name", "Listening Session")

                session = manager.create_session(
                    host_id=user_id,
                    host_username=username,
                    name=name,
                    websocket=websocket,
                )
                current_user_id = user_id

                await websocket.send_json({
                    "type": "session_created",
                    "session": session.to_dict(),
                    # Sent at creation as well as at join: a host behind symmetric NAT with no TURN
                    # should learn that before inviting anyone, not after they fail to connect.
                    "ice_servers": get_ice_servers(),
                    "has_turn": has_turn_configured(),
                })

            elif msg_type == "join":
                code = data.get("code", "").upper()
                user_id = UUID(data["user_id"])
                username = data.get("username", "Anonymous")

                session = manager.get_session_by_code(code)
                if session is None:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Session not found",
                    })
                    continue

                participant = manager.join_session(
                    session=session,
                    user_id=user_id,
                    username=username,
                    websocket=websocket,
                )
                current_user_id = user_id

                await websocket.send_json({
                    "type": "session_joined",
                    "session": session.to_dict(),
                    "ice_servers": get_ice_servers(),
                    "has_turn": has_turn_configured(),
                })

                await manager.broadcast(
                    session,
                    {
                        "type": "user_joined",
                        "user": {
                            "user_id": str(user_id),
                            "username": username,
                            "role": participant.role.value,
                        },
                        "participant_count": len(session.participants),
                    },
                    exclude_user=user_id,
                )

            elif msg_type == "playback":
                if not current_user_id:
                    continue

                session = manager.get_user_session(current_user_id)
                if session is None:
                    continue

                if session.host_id != current_user_id:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Only the host can control playback",
                    })
                    continue

                track_id = UUID(data["track_id"]) if data.get("track_id") else None
                is_playing = data.get("is_playing")
                position_ms = data.get("position_ms")

                manager.update_playback(
                    session,
                    track_id=track_id,
                    is_playing=is_playing,
                    position_ms=position_ms,
                )

                await manager.broadcast(
                    session,
                    {
                        "type": "playback_update",
                        "track_id": str(track_id) if track_id else None,
                        "is_playing": is_playing,
                        "position_ms": position_ms,
                    },
                    exclude_user=current_user_id,
                )

            elif msg_type == "sync_request":
                if not current_user_id:
                    continue

                session = manager.get_user_session(current_user_id)
                if session is None:
                    continue

                await websocket.send_json({
                    "type": "sync_response",
                    "track_id": (
                        str(session.playback_state.track_id)
                        if session.playback_state.track_id
                        else None
                    ),
                    "is_playing": session.playback_state.is_playing,
                    "position_ms": session.playback_state.position_ms,
                })

            elif msg_type == "chat":
                if not current_user_id:
                    continue

                session = manager.get_user_session(current_user_id)
                if session is None:
                    continue

                participant = session.participants.get(current_user_id)
                if participant is None:
                    continue

                await manager.broadcast(
                    session,
                    {
                        "type": "chat",
                        "user_id": str(current_user_id),
                        "username": participant.username,
                        "message": data.get("message", ""),
                    },
                )

            elif msg_type == "join_guest":
                code = data.get("code", "").upper()
                guest_name = data.get("guest_name", "Guest")

                session = manager.get_session_by_code(code)
                if session is None:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Session not found",
                    })
                    continue

                if not session.webrtc_enabled:
                    await websocket.send_json({
                        "type": "error",
                        "message": "This session does not allow guest listeners",
                    })
                    continue

                participant = manager.join_as_guest(
                    session=session,
                    guest_name=guest_name,
                    websocket=websocket,
                )
                current_user_id = participant.user_id

                await websocket.send_json({
                    "type": "session_joined",
                    "session": session.to_dict(),
                    "your_user_id": str(current_user_id),
                    "your_peer_id": participant.peer_id,
                    "ice_servers": get_ice_servers(),
                    "has_turn": has_turn_configured(),
                })

                await manager.send_to_host(
                    session,
                    {
                        "type": "guest_joined",
                        "user_id": str(current_user_id),
                        "username": guest_name,
                        "peer_id": participant.peer_id,
                        "participant_count": len(session.participants),
                    },
                )

                await manager.broadcast(
                    session,
                    {
                        "type": "user_joined",
                        "user": {
                            "user_id": str(current_user_id),
                            "username": guest_name,
                            "role": SessionRole.GUEST.value,
                        },
                        "participant_count": len(session.participants),
                    },
                    exclude_user=current_user_id,
                )

            elif msg_type == "webrtc_request":
                if not current_user_id:
                    continue

                session = manager.get_user_session(current_user_id)
                if session is None:
                    continue

                participant = session.participants.get(current_user_id)
                if participant is None:
                    continue

                await manager.send_to_host(
                    session,
                    {
                        "type": "webrtc_create_offer",
                        "target_user_id": str(current_user_id),
                        "peer_id": participant.peer_id,
                    },
                )

            elif msg_type == "webrtc_offer":
                if not current_user_id:
                    continue

                session = manager.get_user_session(current_user_id)
                if session is None or session.host_id != current_user_id:
                    continue

                await manager.send_to_user(
                    session,
                    UUID(data.get("target_user_id")),
                    {
                        "type": "webrtc_offer",
                        "sdp": data.get("sdp"),
                        "from_user_id": str(current_user_id),
                    },
                )

            elif msg_type == "webrtc_answer":
                if not current_user_id:
                    continue

                session = manager.get_user_session(current_user_id)
                if session is None:
                    continue

                await manager.send_to_host(
                    session,
                    {
                        "type": "webrtc_answer",
                        "sdp": data.get("sdp"),
                        "from_user_id": str(current_user_id),
                    },
                )

            elif msg_type == "webrtc_ice":
                if not current_user_id:
                    continue

                session = manager.get_user_session(current_user_id)
                if session is None:
                    continue

                target_user_id = data.get("target_user_id")
                if target_user_id:
                    await manager.send_to_user(
                        session,
                        UUID(target_user_id),
                        {
                            "type": "webrtc_ice",
                            "candidate": data.get("candidate"),
                            "from_user_id": str(current_user_id),
                        },
                    )
                else:
                    await manager.send_to_host(
                        session,
                        {
                            "type": "webrtc_ice",
                            "candidate": data.get("candidate"),
                            "from_user_id": str(current_user_id),
                        },
                    )

            elif msg_type == "webrtc_connected":
                if not current_user_id:
                    continue

                connected = data.get("connected", False)
                manager.update_webrtc_state(current_user_id, connected)

                session = manager.get_user_session(current_user_id)
                if session is not None:
                    await manager.broadcast(
                        session,
                        {
                            "type": "webrtc_state_changed",
                            "user_id": str(current_user_id),
                            "connected": connected,
                        },
                        exclude_user=current_user_id,
                    )

            elif msg_type == "leave":
                if current_user_id:
                    session = manager.remove_user(current_user_id)
                    if session is not None and session.participants:
                        await manager.broadcast(
                            session,
                            {
                                "type": "user_left",
                                "user_id": str(current_user_id),
                                "participant_count": len(session.participants),
                            },
                        )
                    current_user_id = None

                await websocket.send_json({"type": "left"})

    except WebSocketDisconnect:
        if current_user_id:
            session = manager.remove_user(current_user_id)
            if session is not None and session.participants:
                await manager.broadcast(
                    session,
                    {
                        "type": "user_left",
                        "user_id": str(current_user_id),
                        "participant_count": len(session.participants),
                        "reason": "disconnected",
                    },
                )
