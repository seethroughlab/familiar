"""Contract tests: auth/profile requirement matrix.

Parametrized tests verify that all RequiredProfile endpoints return the
correct 401/400 error envelope when the profile header is missing or invalid.
"""

import pytest
from fastapi.testclient import TestClient

from tests.conftest import assert_error_shape

ZERO_UUID = "00000000-0000-0000-0000-000000000000"

REQUIRED_PROFILE_ENDPOINTS = [
    ("GET", "/api/v1/playlists"),
    ("GET", "/api/v1/smart-playlists"),
    ("GET", "/api/v1/favorites"),
    ("GET", "/api/v1/profiles/me"),
    ("GET", "/api/v1/bandcamp/search?q=test"),
    ("POST", "/api/v1/export-import/export"),
    ("GET", f"/api/v1/download/playlist/{ZERO_UUID}"),
    ("POST", f"/api/v1/tracks/{ZERO_UUID}/played"),
    ("POST", f"/api/v1/tracks/{ZERO_UUID}/skipped"),
    ("POST", f"/api/v1/tracks/{ZERO_UUID}/rejected"),
    # Radio suggestions weigh this profile's taste and skip history, so unlike the
    # ambient routes they cannot run profile-less (ADR-0005).
    ("POST", "/api/v1/queue/suggestions"),
]


def _endpoint_id(param):
    """Generate readable test IDs from (method, path) tuples."""
    method, path = param
    # Strip prefix and query params for a compact ID
    short = path.replace("/api/v1/", "").split("?")[0]
    return f"{method}-{short}"


@pytest.mark.parametrize(
    ("method", "path"),
    REQUIRED_PROFILE_ENDPOINTS,
    ids=[_endpoint_id(e) for e in REQUIRED_PROFILE_ENDPOINTS],
)
def test_required_profile_missing_returns_401(client: TestClient, method: str, path: str) -> None:
    """Endpoints using RequiredProfile must return 401 when no X-Profile-ID header is sent."""
    response = getattr(client, method.lower())(path)
    assert_error_shape(response, status_code=401)
    assert "Profile ID required" in response.json()["message"]


@pytest.mark.parametrize(
    ("method", "path"),
    REQUIRED_PROFILE_ENDPOINTS,
    ids=[_endpoint_id(e) for e in REQUIRED_PROFILE_ENDPOINTS],
)
def test_required_profile_invalid_format_returns_400(client: TestClient, method: str, path: str) -> None:
    """Endpoints using RequiredProfile must return 400 for a malformed X-Profile-ID."""
    response = getattr(client, method.lower())(path, headers={"X-Profile-ID": "not-a-uuid"})
    assert_error_shape(response, status_code=400)
    assert response.json()["message"] == "Invalid profile ID format"
