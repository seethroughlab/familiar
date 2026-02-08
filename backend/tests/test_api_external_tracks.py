"""Tests for external tracks API routes."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import make_profile_headers
from tests.factories import create_test_external_track_data


class TestExternalTracksAPI:
    """Tests for /api/v1/external-tracks endpoints."""

    def test_list_external_tracks_empty(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        response = client.get("/api/v1/external-tracks", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list) or (isinstance(data, dict) and "items" in data)

    def test_create_external_track(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        track_data = create_test_external_track_data(
            title="Missing Song",
            artist="Some Artist",
            source="manual",
        )
        response = client.post("/api/v1/external-tracks", json=track_data, headers=headers)
        assert response.status_code in (200, 201)
        data = response.json()
        assert data["title"] == "Missing Song"
        assert data["artist"] == "Some Artist"

    def test_create_external_track_with_spotify_id(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        track_data = create_test_external_track_data(
            title="Spotify Track",
            artist="Spotify Artist",
            spotify_id=f"spotify_{uuid4().hex[:12]}",
            source="manual",
        )
        response = client.post("/api/v1/external-tracks", json=track_data, headers=headers)
        assert response.status_code in (200, 201)

    def test_get_external_track_not_found(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        fake_id = str(uuid4())
        response = client.get(f"/api/v1/external-tracks/{fake_id}", headers=headers)
        assert response.status_code == 404

    def test_delete_external_track_not_found(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        fake_id = str(uuid4())
        response = client.delete(f"/api/v1/external-tracks/{fake_id}", headers=headers)
        assert response.status_code == 404

    def test_manual_match_nonexistent_track(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        fake_ext_id = str(uuid4())
        fake_track_id = str(uuid4())
        response = client.post(
            f"/api/v1/external-tracks/{fake_ext_id}/match",
            json={"track_id": fake_track_id},
            headers=headers,
        )
        assert response.status_code in (404, 500)

    def test_create_and_retrieve_external_track(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        track_data = create_test_external_track_data(
            title="Retrieve Me",
            artist="Test Artist",
            source="manual",
        )
        create_resp = client.post("/api/v1/external-tracks", json=track_data, headers=headers)
        assert create_resp.status_code in (200, 201)
        created = create_resp.json()

        get_resp = client.get(f"/api/v1/external-tracks/{created['id']}", headers=headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["title"] == "Retrieve Me"

    def test_create_and_delete_external_track(self, client: TestClient, test_profile: dict):
        headers = make_profile_headers(test_profile)
        track_data = create_test_external_track_data(
            title="Delete Me",
            artist="Test Artist",
            source="manual",
        )
        create_resp = client.post("/api/v1/external-tracks", json=track_data, headers=headers)
        created = create_resp.json()

        del_resp = client.delete(f"/api/v1/external-tracks/{created['id']}", headers=headers)
        assert del_resp.status_code in (200, 204)
