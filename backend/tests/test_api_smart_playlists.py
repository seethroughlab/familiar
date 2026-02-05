"""Tests for the smart playlists API endpoints.

Tests cover input validation and available fields endpoint.
Note: Due to async SQLAlchemy greenlet constraints in the test client,
CRUD operations that hit the database may fail. These are tested as
integration tests in the real environment.
"""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import make_profile_headers


class TestSmartPlaylistsList:
    """Tests for listing smart playlists."""

    def test_list_requires_profile(self, client: TestClient) -> None:
        """Test that listing smart playlists requires a profile."""
        response = client.get("/api/v1/smart-playlists")
        assert response.status_code == 401


class TestSmartPlaylistValidation:
    """Tests for smart playlist input validation."""

    def test_create_empty_name_fails(self, client: TestClient, test_profile: dict) -> None:
        """Test creating a smart playlist with empty name fails."""
        headers = make_profile_headers(test_profile)
        response = client.post(
            "/api/v1/smart-playlists",
            headers=headers,
            json={
                "name": "",
                "rules": [],
            },
        )
        assert response.status_code == 422  # Validation error

    def test_create_invalid_match_mode_fails(self, client: TestClient, test_profile: dict) -> None:
        """Test creating a smart playlist with invalid match mode fails."""
        headers = make_profile_headers(test_profile)
        response = client.post(
            "/api/v1/smart-playlists",
            headers=headers,
            json={
                "name": "Test",
                "rules": [],
                "match_mode": "invalid",
            },
        )
        assert response.status_code == 422

    def test_create_invalid_order_direction_fails(self, client: TestClient, test_profile: dict) -> None:
        """Test creating a smart playlist with invalid order direction fails."""
        headers = make_profile_headers(test_profile)
        response = client.post(
            "/api/v1/smart-playlists",
            headers=headers,
            json={
                "name": "Test",
                "rules": [],
                "order_direction": "invalid",
            },
        )
        assert response.status_code == 422

    def test_create_max_tracks_too_high_fails(self, client: TestClient, test_profile: dict) -> None:
        """Test creating a smart playlist with max_tracks > 10000 fails."""
        headers = make_profile_headers(test_profile)
        response = client.post(
            "/api/v1/smart-playlists",
            headers=headers,
            json={
                "name": "Test",
                "rules": [],
                "max_tracks": 50000,
            },
        )
        assert response.status_code == 422

    def test_create_max_tracks_zero_fails(self, client: TestClient, test_profile: dict) -> None:
        """Test creating a smart playlist with max_tracks = 0 fails."""
        headers = make_profile_headers(test_profile)
        response = client.post(
            "/api/v1/smart-playlists",
            headers=headers,
            json={
                "name": "Test",
                "rules": [],
                "max_tracks": 0,
            },
        )
        assert response.status_code == 422


class TestSmartPlaylistAccess:
    """Tests for smart playlist access control."""

    def test_get_not_found(self, client: TestClient, test_profile: dict) -> None:
        """Test getting a non-existent playlist returns 404."""
        headers = make_profile_headers(test_profile)
        response = client.get(f"/api/v1/smart-playlists/{uuid4()}", headers=headers)
        assert response.status_code == 404

    def test_get_invalid_uuid_fails(self, client: TestClient, test_profile: dict) -> None:
        """Test getting with invalid UUID fails."""
        headers = make_profile_headers(test_profile)
        response = client.get("/api/v1/smart-playlists/not-a-uuid", headers=headers)
        assert response.status_code == 422

    def test_update_not_found(self, client: TestClient, test_profile: dict) -> None:
        """Test updating a non-existent playlist returns 404."""
        headers = make_profile_headers(test_profile)
        response = client.put(
            f"/api/v1/smart-playlists/{uuid4()}",
            headers=headers,
            json={"name": "New Name"},
        )
        assert response.status_code == 404

    def test_delete_not_found(self, client: TestClient, test_profile: dict) -> None:
        """Test deleting a non-existent playlist returns 404."""
        headers = make_profile_headers(test_profile)
        response = client.delete(f"/api/v1/smart-playlists/{uuid4()}", headers=headers)
        assert response.status_code == 404

    def test_refresh_not_found(self, client: TestClient, test_profile: dict) -> None:
        """Test refreshing non-existent playlist returns 404."""
        headers = make_profile_headers(test_profile)
        response = client.post(f"/api/v1/smart-playlists/{uuid4()}/refresh", headers=headers)
        assert response.status_code == 404

    def test_get_tracks_not_found(self, client: TestClient, test_profile: dict) -> None:
        """Test getting tracks for non-existent playlist returns 404."""
        headers = make_profile_headers(test_profile)
        response = client.get(f"/api/v1/smart-playlists/{uuid4()}/tracks", headers=headers)
        assert response.status_code == 404


class TestAvailableFields:
    """Tests for available fields endpoint."""

    def test_get_available_fields(self, client: TestClient) -> None:
        """Test getting available fields for building rules."""
        response = client.get("/api/v1/smart-playlists/fields/available")
        assert response.status_code == 200

        data = response.json()
        assert "track_fields" in data
        assert "analysis_fields" in data
        assert "operators" in data

    def test_track_fields_structure(self, client: TestClient) -> None:
        """Test that track fields have expected structure."""
        response = client.get("/api/v1/smart-playlists/fields/available")
        data = response.json()

        for field in data["track_fields"]:
            assert "name" in field
            assert "type" in field
            assert "description" in field

        # Check specific expected fields
        field_names = {f["name"] for f in data["track_fields"]}
        assert "title" in field_names
        assert "artist" in field_names
        assert "album" in field_names
        assert "genre" in field_names
        assert "year" in field_names

    def test_analysis_fields_structure(self, client: TestClient) -> None:
        """Test that analysis fields have expected structure."""
        response = client.get("/api/v1/smart-playlists/fields/available")
        data = response.json()

        for field in data["analysis_fields"]:
            assert "name" in field
            assert "type" in field
            assert "description" in field

        # Check specific expected fields
        field_names = {f["name"] for f in data["analysis_fields"]}
        assert "bpm" in field_names
        assert "energy" in field_names
        assert "valence" in field_names
        assert "danceability" in field_names

    def test_operators_by_type(self, client: TestClient) -> None:
        """Test that operators are grouped by type."""
        response = client.get("/api/v1/smart-playlists/fields/available")
        data = response.json()

        operators = data["operators"]
        assert "string" in operators
        assert "number" in operators
        assert "date" in operators
        assert "boolean" in operators

        # String operators
        assert "contains" in operators["string"]
        assert "equals" in operators["string"]
        assert "not_contains" in operators["string"]

        # Number operators
        assert "greater_than" in operators["number"]
        assert "less_than" in operators["number"]
        assert "between" in operators["number"]

        # Date operators
        assert "within_days" in operators["date"]
        assert "not_within_days" in operators["date"]

        # Boolean operators
        assert "equals" in operators["boolean"]

    def test_play_history_fields_structure(self, client: TestClient) -> None:
        """Test that play history fields have expected structure."""
        response = client.get("/api/v1/smart-playlists/fields/available")
        data = response.json()

        assert "play_history_fields" in data

        for field in data["play_history_fields"]:
            assert "name" in field
            assert "type" in field
            assert "description" in field

        # Check specific expected fields
        field_names = {f["name"] for f in data["play_history_fields"]}
        assert "last_played_at" in field_names
        assert "play_count" in field_names
        assert "total_play_seconds" in field_names
        assert "never_played" in field_names

    def test_play_history_field_types(self, client: TestClient) -> None:
        """Test that play history fields have correct types."""
        response = client.get("/api/v1/smart-playlists/fields/available")
        data = response.json()

        field_types = {f["name"]: f["type"] for f in data["play_history_fields"]}
        assert field_types["last_played_at"] == "date"
        assert field_types["play_count"] == "number"
        assert field_types["total_play_seconds"] == "number"
        assert field_types["never_played"] == "boolean"

    def test_analysis_fields_have_ranges(self, client: TestClient) -> None:
        """Test that numeric analysis fields have range hints."""
        response = client.get("/api/v1/smart-playlists/fields/available")
        data = response.json()

        # Energy should have a range of [0, 1]
        energy_field = next(
            (f for f in data["analysis_fields"] if f["name"] == "energy"),
            None
        )
        assert energy_field is not None
        assert "range" in energy_field
        assert energy_field["range"] == [0, 1]

        # BPM should have a different range
        bpm_field = next(
            (f for f in data["analysis_fields"] if f["name"] == "bpm"),
            None
        )
        assert bpm_field is not None
        assert "range" in bpm_field

    def test_new_track_fields_present(self, client: TestClient) -> None:
        """Test that new metadata fields are present."""
        response = client.get("/api/v1/smart-playlists/fields/available")
        data = response.json()

        field_names = {f["name"] for f in data["track_fields"]}
        assert "composer" in field_names
        assert "comment" in field_names
        assert "grouping" in field_names
        assert "file_path" in field_names

    def test_new_track_fields_types(self, client: TestClient) -> None:
        """Test that new metadata fields have correct types."""
        response = client.get("/api/v1/smart-playlists/fields/available")
        data = response.json()

        field_types = {f["name"]: f["type"] for f in data["track_fields"]}
        assert field_types["composer"] == "string"
        assert field_types["comment"] == "string"
        assert field_types["grouping"] == "string"
        assert field_types["file_path"] == "string"

    def test_new_date_operators_present(self, client: TestClient) -> None:
        """Test that new date operators are present."""
        response = client.get("/api/v1/smart-playlists/fields/available")
        data = response.json()

        date_operators = data["operators"]["date"]
        # Legacy operators still present
        assert "within_days" in date_operators
        assert "not_within_days" in date_operators
        # New absolute date operators
        assert "after" in date_operators
        assert "before" in date_operators
        assert "on" in date_operators
        # New relative date operators
        assert "in_the_last" in date_operators
        assert "not_in_the_last" in date_operators

    def test_date_keywords_present(self, client: TestClient) -> None:
        """Test that date keywords are returned."""
        response = client.get("/api/v1/smart-playlists/fields/available")
        data = response.json()

        assert "date_keywords" in data
        keywords = data["date_keywords"]
        assert "today" in keywords
        assert "yesterday" in keywords
        assert "this_week" in keywords
        assert "last_week" in keywords
        assert "this_month" in keywords
        assert "last_month" in keywords
        assert "this_year" in keywords
        assert "last_year" in keywords

    def test_relative_units_present(self, client: TestClient) -> None:
        """Test that relative time units are returned."""
        response = client.get("/api/v1/smart-playlists/fields/available")
        data = response.json()

        assert "relative_units" in data
        units = data["relative_units"]
        assert "days" in units
        assert "weeks" in units
        assert "months" in units
        assert "years" in units
