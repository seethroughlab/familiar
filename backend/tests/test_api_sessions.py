"""Tests for listening sessions service."""

from unittest.mock import MagicMock
from uuid import uuid4

from app.services.sessions import ListeningSession, Participant, PlaybackState, SessionRole


class TestSessionRole:
    def test_host_role(self):
        assert SessionRole.HOST.value == "host"

    def test_listener_role(self):
        assert SessionRole.LISTENER.value == "listener"

    def test_guest_role(self):
        assert SessionRole.GUEST.value == "guest"


class TestPlaybackState:
    def test_default_state(self):
        state = PlaybackState()
        assert state.track_id is None
        assert state.is_playing is False
        assert state.position_ms == 0

    def test_custom_state(self):
        track_id = uuid4()
        state = PlaybackState(track_id=track_id, is_playing=True, position_ms=5000)
        assert state.track_id == track_id
        assert state.is_playing is True
        assert state.position_ms == 5000


class TestListeningSession:
    def test_code_format(self):
        session = ListeningSession(
            id="session-1",
            code="ABC123",
            name="Test Session",
            host_id=uuid4(),
        )
        assert session.code == "ABC123"

    def test_initial_playback_state(self):
        session = ListeningSession(
            id="session-1",
            code="ABC123",
            name="Test Session",
            host_id=uuid4(),
        )
        assert session.playback_state.is_playing is False

    def test_to_dict_includes_basic_fields(self):
        host_id = uuid4()
        session = ListeningSession(
            id="session-1",
            code="ABC123",
            name="Test Session",
            host_id=host_id,
        )
        d = session.to_dict()
        assert d["id"] == "session-1"
        assert d["code"] == "ABC123"
        assert d["name"] == "Test Session"
        assert d["host_id"] == str(host_id)

    def test_to_dict_playback_state(self):
        session = ListeningSession(
            id="session-1",
            code="ABC123",
            name="Test Session",
            host_id=uuid4(),
        )
        d = session.to_dict()
        assert d["playback_state"]["is_playing"] is False
        assert d["playback_state"]["track_id"] is None

    def test_webrtc_enabled_default(self):
        session = ListeningSession(
            id="session-1",
            code="ABC123",
            name="Test Session",
            host_id=uuid4(),
        )
        assert session.webrtc_enabled is True


class TestParticipant:
    def test_create_participant(self):
        ws = MagicMock()
        p = Participant(
            user_id=uuid4(),
            username="User 1",
            websocket=ws,
            role=SessionRole.HOST,
        )
        assert p.username == "User 1"
        assert p.role == SessionRole.HOST
        assert p.webrtc_connected is False
