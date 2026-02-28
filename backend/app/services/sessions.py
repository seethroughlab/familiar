"""Listening sessions service for synchronized playback with WebRTC."""

import secrets
from dataclasses import dataclass, field
from datetime import datetime
from app.utils.time import utcnow
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from fastapi import WebSocket


class SessionRole(str, Enum):
    """User's role in a session."""
    HOST = "host"
    LISTENER = "listener"
    GUEST = "guest"  # Anonymous listener via WebRTC


@dataclass
class Participant:
    """A participant in a listening session."""
    user_id: UUID
    username: str
    websocket: WebSocket
    role: SessionRole
    joined_at: datetime = field(default_factory=datetime.utcnow)
    # WebRTC connection state
    webrtc_connected: bool = False
    peer_id: str | None = None  # For WebRTC peer identification


@dataclass
class PlaybackState:
    """Current playback state for a session."""
    track_id: UUID | None = None
    is_playing: bool = False
    position_ms: int = 0
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ListeningSession:
    """A listening session where users can listen together."""
    id: str
    code: str  # 6-char join code
    name: str
    host_id: UUID
    created_at: datetime = field(default_factory=datetime.utcnow)
    participants: dict[UUID, Participant] = field(default_factory=dict)
    playback_state: PlaybackState = field(default_factory=PlaybackState)
    # WebRTC streaming settings
    webrtc_enabled: bool = True  # Whether to offer WebRTC audio streaming

    def to_dict(self, include_participants: bool = True) -> dict[str, Any]:
        """Convert to API response format."""
        result = {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "host_id": str(self.host_id),
            "created_at": self.created_at.isoformat(),
            "participant_count": len(self.participants),
            "webrtc_enabled": self.webrtc_enabled,
            "playback_state": {
                "track_id": str(self.playback_state.track_id) if self.playback_state.track_id else None,
                "is_playing": self.playback_state.is_playing,
                "position_ms": self.playback_state.position_ms,
            },
        }
        if include_participants:
            result["participants"] = [
                {
                    "user_id": str(p.user_id),
                    "username": p.username,
                    "role": p.role.value,
                    "joined_at": p.joined_at.isoformat(),
                    "webrtc_connected": p.webrtc_connected,
                }
                for p in self.participants.values()
            ]
        return result


class SessionManager:
    """Manages active listening sessions in memory."""

    def __init__(self) -> None:
        self._sessions: dict[str, ListeningSession] = {}
        self._user_sessions: dict[UUID, str] = {}  # user_id -> session_id
        self._code_to_session: dict[str, str] = {}  # code -> session_id

    def _generate_code(self) -> str:
        """Generate a unique 6-character join code."""
        while True:
            code = secrets.token_hex(3).upper()
            if code not in self._code_to_session:
                return code

    def create_session(
        self,
        host_id: UUID,
        host_username: str,
        name: str,
        websocket: WebSocket,
    ) -> ListeningSession:
        """Create a new listening session."""
        # Remove user from any existing session
        self.remove_user(host_id)

        session_id = secrets.token_urlsafe(16)
        code = self._generate_code()

        session = ListeningSession(
            id=session_id,
            code=code,
            name=name,
            host_id=host_id,
        )

        # Add host as first participant
        host = Participant(
            user_id=host_id,
            username=host_username,
            websocket=websocket,
            role=SessionRole.HOST,
        )
        session.participants[host_id] = host

        self._sessions[session_id] = session
        self._user_sessions[host_id] = session_id
        self._code_to_session[code] = session_id

        return session

    def get_session(self, session_id: str) -> ListeningSession | None:
        """Get session by ID."""
        return self._sessions.get(session_id)

    def get_session_by_code(self, code: str) -> ListeningSession | None:
        """Get session by join code."""
        session_id = self._code_to_session.get(code.upper())
        if session_id:
            return self._sessions.get(session_id)
        return None

    def get_user_session(self, user_id: UUID) -> ListeningSession | None:
        """Get the session a user is currently in."""
        session_id = self._user_sessions.get(user_id)
        if session_id:
            return self._sessions.get(session_id)
        return None

    def join_session(
        self,
        session: ListeningSession,
        user_id: UUID,
        username: str,
        websocket: WebSocket,
        role: SessionRole = SessionRole.LISTENER,
    ) -> Participant:
        """Add a user to an existing session."""
        # Remove from any existing session
        self.remove_user(user_id)

        # Generate peer_id for WebRTC
        peer_id = secrets.token_urlsafe(8)

        participant = Participant(
            user_id=user_id,
            username=username,
            websocket=websocket,
            role=role,
            peer_id=peer_id,
        )

        session.participants[user_id] = participant
        self._user_sessions[user_id] = session.id

        return participant

    def join_as_guest(
        self,
        session: ListeningSession,
        guest_name: str,
        websocket: WebSocket,
    ) -> Participant:
        """Add an anonymous guest to a session for WebRTC streaming."""
        # Generate a random UUID for the guest
        guest_id = uuid4()

        return self.join_session(
            session=session,
            user_id=guest_id,
            username=guest_name,
            websocket=websocket,
            role=SessionRole.GUEST,
        )

    def get_host(self, session: ListeningSession) -> Participant | None:
        """Get the host participant for a session."""
        return session.participants.get(session.host_id)

    async def send_to_user(
        self,
        session: ListeningSession,
        user_id: UUID,
        message: dict[str, Any],
    ) -> bool:  # type: ignore[return]
        """Send a message to a specific user in a session."""
        participant = session.participants.get(user_id)
        if not participant:
            return False

        try:
            await participant.websocket.send_json(message)
            return True
        except Exception:
            self.remove_user(user_id)
            return False

    async def send_to_host(
        self,
        session: ListeningSession,
        message: dict[str, Any],
    ) -> bool:  # type: ignore[no-untyped-call]
        """Send a message to the session host."""
        return await self.send_to_user(session, session.host_id, message)

    def update_webrtc_state(
        self,
        user_id: UUID,
        connected: bool,
    ) -> None:  # type: ignore[return]
        """Update a participant's WebRTC connection state."""
        session = self.get_user_session(user_id)
        if session:
            participant = session.participants.get(user_id)
            if participant:
                participant.webrtc_connected = connected

    def remove_user(self, user_id: UUID) -> ListeningSession | None:
        """Remove a user from their current session."""
        session_id = self._user_sessions.pop(user_id, None)
        if not session_id:
            return None

        session = self._sessions.get(session_id)
        if not session:
            return None

        session.participants.pop(user_id, None)

        # If host left or no participants, end session
        if user_id == session.host_id or not session.participants:
            self._end_session(session)

        return session

    def _end_session(self, session: ListeningSession) -> None:  # type: ignore[return]
        """Clean up and remove a session."""
        self._code_to_session.pop(session.code, None)
        self._sessions.pop(session.id, None)

        # Remove all user mappings
        for user_id in list(session.participants.keys()):
            self._user_sessions.pop(user_id, None)

    def update_playback(
        self,
        session: ListeningSession,
        track_id: UUID | None = None,
        is_playing: bool | None = None,
        position_ms: int | None = None,
    ) -> None:  # type: ignore[return]
        """Update the playback state for a session."""
        if track_id is not None:
            session.playback_state.track_id = track_id
        if is_playing is not None:
            session.playback_state.is_playing = is_playing
        if position_ms is not None:
            session.playback_state.position_ms = position_ms
        session.playback_state.updated_at = utcnow()

    async def broadcast(
        self,
        session: ListeningSession,
        message: dict[str, Any],
        exclude_user: UUID | None = None,
    ) -> None:  # type: ignore[return]
        """Broadcast a message to all participants in a session."""
        disconnected = []

        for user_id, participant in session.participants.items():
            if user_id == exclude_user:
                continue

            try:
                await participant.websocket.send_json(message)
            except Exception:
                disconnected.append(user_id)

        # Clean up disconnected users
        for user_id in disconnected:
            self.remove_user(user_id)


# Global session manager instance
_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:  # type: ignore[return]
    """Get the global session manager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
