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


# ── The REST half, revived and typed (ADR-0036 point 5) ─────────────────────
#
# Added on revival. The shelved file tested the service's dataclasses and nothing that goes over the
# wire — which is the half that now has to satisfy ADR-0007, and the half the Apple clients generate
# from.

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.routes import sessions as sessions_routes
from app.main import app
from app.services.sessions import get_session_manager


@pytest.fixture
def manager():
    """The process-wide manager, emptied between tests.

    Sessions are in-process by decision (ADR-0036 point 8), so the singleton persists across tests
    in a way a database fixture would not — an earlier test's session is visible to a later one.
    """
    mgr = get_session_manager()
    mgr._sessions.clear()
    mgr._code_to_session.clear()
    mgr._user_sessions.clear()
    return mgr


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


class TestIceServers:
    def test_stun_only_by_default(self, monkeypatch):
        monkeypatch.setattr(sessions_routes.settings, "turn_server_url", None)
        servers = sessions_routes.get_ice_servers()
        assert len(servers) == 2
        assert all(s["urls"].startswith("stun:") for s in servers)
        assert sessions_routes.has_turn_configured() is False

    def test_turn_appended_when_configured(self, monkeypatch):
        monkeypatch.setattr(sessions_routes.settings, "turn_server_url", "turn:relay.example:3478")
        monkeypatch.setattr(sessions_routes.settings, "turn_server_username", "user")
        monkeypatch.setattr(sessions_routes.settings, "turn_server_credential", "secret")

        servers = sessions_routes.get_ice_servers()
        assert servers[-1] == {
            "urls": "turn:relay.example:3478",
            "username": "user",
            "credential": "secret",
        }
        assert sessions_routes.has_turn_configured() is True

    def test_turn_without_credentials_is_still_offered(self, monkeypatch):
        # An open TURN server is unusual but legal, and dropping it because there is no username
        # would leave the client with STUN and no explanation.
        monkeypatch.setattr(sessions_routes.settings, "turn_server_url", "turn:open.example:3478")
        monkeypatch.setattr(sessions_routes.settings, "turn_server_username", None)
        monkeypatch.setattr(sessions_routes.settings, "turn_server_credential", None)

        assert sessions_routes.get_ice_servers()[-1] == {"urls": "turn:open.example:3478"}

    @pytest.mark.anyio
    async def test_endpoint_reports_whether_turn_exists(self, client, monkeypatch):
        # ADR-0036 point 7: behind symmetric NAT with no TURN this fails for reasons retrying does
        # not fix, so the client is told rather than left to discover it as a hang.
        monkeypatch.setattr(sessions_routes.settings, "turn_server_url", None)

        response = await client.get("/api/v1/sessions/ice-servers")

        assert response.status_code == 200
        body = response.json()
        assert body["has_turn"] is False
        assert len(body["ice_servers"]) == 2


class TestSessionLookup:
    @pytest.mark.anyio
    async def test_unknown_code_is_404_not_an_empty_session(self, client, manager):
        response = await client.get("/api/v1/sessions/by-code/NOPE12")
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_lookup_returns_the_typed_shape(self, client, manager):
        session = manager.create_session(
            host_id=uuid4(),
            host_username="Jeff",
            name="Friday Night",
            websocket=MagicMock(),
        )

        response = await client.get(f"/api/v1/sessions/by-code/{session.code}")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == session.code
        assert body["name"] == "Friday Night"
        assert body["participant_count"] == 1
        # Nested, and typed rather than a bare dict — this is what the generated client models.
        assert body["playback_state"] == {"track_id": None, "is_playing": False, "position_ms": 0}
        assert body["participants"][0]["role"] == "host"

    @pytest.mark.anyio
    async def test_lookup_is_case_insensitive(self, client, manager):
        # The code is something one person reads aloud to another.
        session = manager.create_session(
            host_id=uuid4(), host_username="Jeff", name="S", websocket=MagicMock()
        )

        response = await client.get(f"/api/v1/sessions/by-code/{session.code.lower()}")

        assert response.status_code == 200
        assert response.json()["code"] == session.code
