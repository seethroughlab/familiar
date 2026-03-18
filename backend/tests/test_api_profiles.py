"""Tests for the profiles API endpoints.

Tests cover profile CRUD operations, avatar upload/download, and access control.
"""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import make_profile_headers


class TestListProfiles:
    """Tests for listing profiles."""

    def test_list_profiles_returns_list(self, client: TestClient) -> None:
        """Test listing profiles returns a list."""
        response = client.get("/api/v1/profiles")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_profiles_includes_created(self, client: TestClient, test_profile: dict) -> None:
        """Test that created profiles appear in list."""
        response = client.get("/api/v1/profiles")
        assert response.status_code == 200

        profile_ids = [p["id"] for p in response.json()]
        assert test_profile["id"] in profile_ids


class TestCreateProfile:
    """Tests for creating profiles."""

    def test_create_profile(self, client: TestClient) -> None:
        """Test creating a new profile."""
        response = client.post(
            "/api/v1/profiles",
            json={"name": "Test User"},
        )
        assert response.status_code == 201

        data = response.json()
        assert data["name"] == "Test User"
        assert "id" in data
        assert "created_at" in data
        assert data["has_lastfm"] is False

    def test_create_profile_with_color(self, client: TestClient) -> None:
        """Test creating a profile with a color."""
        response = client.post(
            "/api/v1/profiles",
            json={"name": "Colorful User", "color": "#FF5500"},
        )
        assert response.status_code == 201
        assert response.json()["color"] == "#FF5500"

    def test_create_profile_empty_name_fails(self, client: TestClient) -> None:
        """Test creating a profile with empty name fails."""
        response = client.post(
            "/api/v1/profiles",
            json={"name": ""},
        )
        assert response.status_code == 422

    def test_create_profile_invalid_color_fails(self, client: TestClient) -> None:
        """Test creating a profile with invalid color fails."""
        response = client.post(
            "/api/v1/profiles",
            json={"name": "Test", "color": "not-a-color"},
        )
        assert response.status_code == 422

    def test_create_profile_short_color_fails(self, client: TestClient) -> None:
        """Test creating a profile with 3-char color fails."""
        response = client.post(
            "/api/v1/profiles",
            json={"name": "Test", "color": "#F00"},
        )
        assert response.status_code == 422


class TestGetProfile:
    """Tests for getting profiles."""

    def test_get_profile_by_id(self, client: TestClient, test_profile: dict) -> None:
        """Test getting a profile by ID."""
        profile_id = test_profile["id"]
        response = client.get(f"/api/v1/profiles/{profile_id}")
        assert response.status_code == 200
        assert response.json()["id"] == profile_id

    def test_get_profile_not_found(self, client: TestClient) -> None:
        """Test getting a non-existent profile returns 404."""
        response = client.get(f"/api/v1/profiles/{uuid4()}")
        assert response.status_code == 404

    def test_get_profile_invalid_uuid(self, client: TestClient) -> None:
        """Test getting with invalid UUID fails."""
        response = client.get("/api/v1/profiles/not-a-uuid")
        assert response.status_code == 422


class TestGetCurrentProfile:
    """Tests for getting current profile via /me endpoint."""

    def test_get_me_requires_profile(self, client: TestClient) -> None:
        """Test /me requires X-Profile-ID header."""
        response = client.get("/api/v1/profiles/me")
        assert response.status_code == 401

    def test_get_me_returns_profile(self, client: TestClient, test_profile: dict) -> None:
        """Test /me returns the current profile."""
        headers = make_profile_headers(test_profile)
        response = client.get("/api/v1/profiles/me", headers=headers)
        assert response.status_code == 200
        assert response.json()["id"] == test_profile["id"]


class TestUpdateProfile:
    """Tests for updating profiles."""

    def test_update_profile_name(self, client: TestClient, test_profile: dict) -> None:
        """Test updating a profile's name."""
        profile_id = test_profile["id"]
        response = client.put(
            f"/api/v1/profiles/{profile_id}",
            json={"name": "Updated Name"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Updated Name"

    def test_update_profile_color(self, client: TestClient, test_profile: dict) -> None:
        """Test updating a profile's color."""
        profile_id = test_profile["id"]
        response = client.put(
            f"/api/v1/profiles/{profile_id}",
            json={"color": "#00FF00"},
        )
        assert response.status_code == 200
        assert response.json()["color"] == "#00FF00"

    def test_update_profile_not_found(self, client: TestClient) -> None:
        """Test updating a non-existent profile returns 404."""
        response = client.put(
            f"/api/v1/profiles/{uuid4()}",
            json={"name": "New Name"},
        )
        assert response.status_code == 404

    def test_update_profile_invalid_color_fails(self, client: TestClient, test_profile: dict) -> None:
        """Test updating with invalid color fails."""
        profile_id = test_profile["id"]
        response = client.put(
            f"/api/v1/profiles/{profile_id}",
            json={"color": "invalid"},
        )
        assert response.status_code == 422


class TestDeleteProfile:
    """Tests for deleting profiles."""

    def test_delete_profile(self, client: TestClient) -> None:
        """Test deleting a profile."""
        # Create a profile to delete
        create_response = client.post(
            "/api/v1/profiles",
            json={"name": "To Delete"},
        )
        profile_id = create_response.json()["id"]

        # Delete it
        response = client.delete(f"/api/v1/profiles/{profile_id}")
        assert response.status_code == 204

        # Verify it's gone
        get_response = client.get(f"/api/v1/profiles/{profile_id}")
        assert get_response.status_code == 404

    def test_delete_profile_not_found(self, client: TestClient) -> None:
        """Test deleting a non-existent profile returns 404."""
        response = client.delete(f"/api/v1/profiles/{uuid4()}")
        assert response.status_code == 404


class TestProfileAvatar:
    """Tests for profile avatar endpoints."""

    def test_get_avatar_not_found_profile(self, client: TestClient) -> None:
        """Test getting avatar for non-existent profile."""
        response = client.get(f"/api/v1/profiles/{uuid4()}/avatar")
        assert response.status_code == 404

    def test_get_avatar_no_avatar(self, client: TestClient, test_profile: dict) -> None:
        """Test getting avatar when profile has none."""
        profile_id = test_profile["id"]
        response = client.get(f"/api/v1/profiles/{profile_id}/avatar")
        assert response.status_code == 404
        assert "no avatar" in response.json()["message"].lower()

    def test_delete_avatar_not_found_profile(self, client: TestClient) -> None:
        """Test deleting avatar for non-existent profile."""
        response = client.delete(f"/api/v1/profiles/{uuid4()}/avatar")
        assert response.status_code == 404

    def test_delete_avatar_no_avatar(self, client: TestClient, test_profile: dict) -> None:
        """Test deleting avatar when profile has none (should succeed)."""
        profile_id = test_profile["id"]
        response = client.delete(f"/api/v1/profiles/{profile_id}/avatar")
        # Should succeed even if no avatar exists
        assert response.status_code == 200

    def test_upload_avatar_not_found_profile(self, client: TestClient) -> None:
        """Test uploading avatar for non-existent profile."""
        response = client.post(
            f"/api/v1/profiles/{uuid4()}/avatar",
            files={"file": ("test.jpg", b"fake image data", "image/jpeg")},
        )
        assert response.status_code == 404


class TestProfileResponseStructure:
    """Tests for profile response structure."""

    def test_profile_has_required_fields(self, client: TestClient, test_profile: dict) -> None:
        """Test that profile responses have all required fields."""
        response = client.get(f"/api/v1/profiles/{test_profile['id']}")
        data = response.json()

        assert "id" in data
        assert "name" in data
        assert "color" in data
        assert "avatar_url" in data
        assert "created_at" in data
        assert "has_lastfm" in data

    def test_avatar_url_format(self, client: TestClient, test_profile: dict) -> None:
        """Test that avatar_url is None when no avatar."""
        response = client.get(f"/api/v1/profiles/{test_profile['id']}")
        data = response.json()

        # No avatar uploaded, should be None
        assert data["avatar_url"] is None


class TestProfileValidation:
    """Tests for profile input validation."""

    def test_name_too_long_fails(self, client: TestClient) -> None:
        """Test that name over 100 chars fails."""
        response = client.post(
            "/api/v1/profiles",
            json={"name": "x" * 101},
        )
        assert response.status_code == 422

    def test_name_max_length_succeeds(self, client: TestClient) -> None:
        """Test that name at 100 chars succeeds."""
        response = client.post(
            "/api/v1/profiles",
            json={"name": "x" * 100},
        )
        assert response.status_code == 201

    def test_color_lowercase_succeeds(self, client: TestClient) -> None:
        """Test that lowercase hex color works."""
        response = client.post(
            "/api/v1/profiles",
            json={"name": "Test", "color": "#aabbcc"},
        )
        assert response.status_code == 201

    def test_color_uppercase_succeeds(self, client: TestClient) -> None:
        """Test that uppercase hex color works."""
        response = client.post(
            "/api/v1/profiles",
            json={"name": "Test", "color": "#AABBCC"},
        )
        assert response.status_code == 201

    def test_color_mixed_case_succeeds(self, client: TestClient) -> None:
        """Test that mixed case hex color works."""
        response = client.post(
            "/api/v1/profiles",
            json={"name": "Test", "color": "#AaBbCc"},
        )
        assert response.status_code == 201

    def test_color_missing_hash_fails(self, client: TestClient) -> None:
        """Test that color without # fails."""
        response = client.post(
            "/api/v1/profiles",
            json={"name": "Test", "color": "AABBCC"},
        )
        assert response.status_code == 422
