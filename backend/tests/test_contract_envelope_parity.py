"""Contract tests: envelope parity and SSE pre-stream error validation.

Verifies every error handler path in main.py produces the canonical envelope,
and that SSE endpoints return JSON envelopes (not SSE events) on pre-stream
validation failure.
"""

from fastapi.testclient import TestClient

from tests.conftest import assert_full_envelope, make_profile_headers

ZERO_UUID = "00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# Envelope parity — one test per exception handler path
# ---------------------------------------------------------------------------


def test_422_pydantic_validation_has_envelope(client: TestClient) -> None:
    """RequestValidationError handler → 422 envelope."""
    response = client.get("/api/v1/tracks/not-a-uuid/stream")
    payload = assert_full_envelope(response, status_code=422)
    assert "detail" in payload


def test_404_familiar_error_has_envelope(client: TestClient) -> None:
    """FamiliarError(404) handler → 404 envelope."""
    response = client.get(f"/api/v1/profiles/{ZERO_UUID}")
    assert_full_envelope(response, status_code=404)


def test_400_familiar_error_has_envelope(client: TestClient) -> None:
    """FamiliarError(400) handler → 400 envelope."""
    response = client.get("/api/v1/artwork/abc123/invalid-size")
    assert_full_envelope(response, status_code=400)


def test_401_auth_error_has_envelope(client: TestClient) -> None:
    """HTTPException(401) from require_profile → 401 envelope."""
    response = client.get("/api/v1/playlists")
    assert_full_envelope(response, status_code=401)


def test_503_service_unavailable_has_envelope(
    client: TestClient, test_profile: dict, monkeypatch
) -> None:
    """ServiceUnavailableError → 503 envelope.

    **Re-pointed from `/chat` when ADR-0043 retired it.** That route raised
    `LLMNotConfiguredError`, which is now defined and raised nowhere, so this shape had no reachable
    trigger left. Last.fm's auth endpoint raises the same base class when it has no credentials —
    which CI never configures — so the envelope stays covered rather than the test being deleted
    with the route that happened to exercise it.
    """
    # **Forced, not assumed absent.** The obvious version of this just calls the endpoint and
    # expects a 503 because CI configures no credentials — which passes in CI and fails on any
    # developer machine that has them, exactly like the chat-key tests this repository already
    # carries. Patching the check makes the assertion about the envelope rather than about the
    # machine.
    from app.services import lastfm as lastfm_module

    service = lastfm_module.get_lastfm_service()
    monkeypatch.setattr(service, "is_configured", lambda: False)

    response = client.get("/api/v1/lastfm/auth", headers=make_profile_headers(test_profile))
    assert_full_envelope(response, status_code=503)


def test_405_method_not_allowed_has_envelope(client: TestClient) -> None:
    """Starlette 405 handler → 405 response.

    Note: Starlette generates 405 at the ASGI routing level before FastAPI's
    exception handlers run, so it uses Starlette's default format.
    """
    response = client.delete("/api/v1/library/stats")
    assert response.status_code == 405


# ---------------------------------------------------------------------------
# SSE pre-stream error tests — **none remain, and that is a real gap.**
#
# These asserted that a route destined to become `text/event-stream` still returns a JSON envelope
# when it fails during setup, rather than a half-open stream carrying an error frame. Every one of
# them used `/chat/stream`, which ADR-0043 retired. The surviving SSE route, `/library/map/stream`,
# cannot replace them: it requires no profile and opens the stream unconditionally, so it has no
# pre-stream failure to provoke. Re-pointing them there would have asserted nothing while looking
# like coverage.
#
# Recorded rather than quietly dropped: if an SSE route ever gains a pre-stream error path, this is
# the section it belongs in.
# ---------------------------------------------------------------------------




def test_map_stream_invalid_entity_returns_422(client: TestClient) -> None:
    """GET /library/map/stream with bad entity_type → 422 validation envelope."""
    response = client.get("/api/v1/library/map/stream?entity_type=invalid")
    assert_full_envelope(response, status_code=422)


def test_map_3d_stream_invalid_entity_returns_422(client: TestClient) -> None:
    """GET /library/map/3d/stream with bad entity_type → 422 validation envelope."""
    response = client.get("/api/v1/library/map/3d/stream?entity_type=invalid")
    assert_full_envelope(response, status_code=422)

