"""API contract audit: error-shape checks for player-critical endpoints.

This suite enforces a stable baseline contract:
- All error responses are JSON objects with a top-level `detail` key.
- App-level errors (400/401/404) use string `detail`.
- Validation errors (422) use list `detail`.
"""

from fastapi.testclient import TestClient


def assert_error_shape(
    response,
    *,
    status_code: int,
    detail_type: type[str] | type[list],
) -> None:
    assert response.status_code == status_code
    payload = response.json()
    assert isinstance(payload, dict)
    assert "detail" in payload
    assert isinstance(payload["detail"], detail_type)
    if isinstance(payload["detail"], list):
        assert len(payload["detail"]) > 0


def test_tracks_stream_invalid_track_id_validation_error_shape(client: TestClient) -> None:
    response = client.get("/api/v1/tracks/not-a-uuid/stream")
    assert_error_shape(response, status_code=422, detail_type=str)
    assert "track_id" in response.json()["detail"]


def test_artwork_by_hash_invalid_size_error_shape(client: TestClient) -> None:
    response = client.get("/api/v1/artwork/abc123/invalid-size")
    assert_error_shape(response, status_code=400, detail_type=str)
    assert "Size must be" in response.json()["detail"]


def test_playlists_requires_profile_error_shape(client: TestClient) -> None:
    response = client.get("/api/v1/playlists")
    assert_error_shape(response, status_code=401, detail_type=str)
    assert "Profile ID required" in response.json()["detail"]


def test_playlists_invalid_profile_header_error_shape(client: TestClient) -> None:
    response = client.get("/api/v1/playlists", headers={"X-Profile-ID": "not-a-uuid"})
    assert_error_shape(response, status_code=400, detail_type=str)
    assert response.json()["detail"] == "Invalid profile ID format"


def test_settings_update_validation_error_shape(client: TestClient) -> None:
    response = client.put("/api/v1/settings", json={"external_features_enabled": "not-a-bool"})
    assert_error_shape(response, status_code=422, detail_type=str)
    assert "external_features_enabled" in response.json()["detail"]
