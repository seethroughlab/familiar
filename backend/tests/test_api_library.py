"""Tests for the library API endpoints.

Tests cover library stats, artist/album browsing, year distribution,
sync operations, and analysis status.
"""

from fastapi.testclient import TestClient


class TestLibraryStats:
    """Tests for /library/stats endpoint."""

    def test_get_library_stats(self, client: TestClient) -> None:
        """Test getting library statistics."""
        response = client.get("/api/v1/library/stats")
        assert response.status_code == 200

        data = response.json()
        assert "total_tracks" in data
        assert "total_albums" in data
        assert "total_artists" in data
        assert "albums" in data
        assert "compilations" in data
        assert "soundtracks" in data
        assert "analyzed_tracks" in data
        assert "pending_analysis" in data

    def test_stats_values_are_non_negative(self, client: TestClient) -> None:
        """All stats values should be non-negative."""
        response = client.get("/api/v1/library/stats")
        data = response.json()

        for key, value in data.items():
            assert value >= 0, f"{key} should be non-negative"


class TestListArtists:
    """Tests for /library/artists endpoint."""

    def test_list_artists_returns_list(self, client: TestClient) -> None:
        """Test listing artists returns paginated response."""
        response = client.get("/api/v1/library/artists")
        assert response.status_code == 200

        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert isinstance(data["items"], list)

    def test_list_artists_pagination(self, client: TestClient) -> None:
        """Test artist list pagination parameters."""
        response = client.get("/api/v1/library/artists?page=1&page_size=10")
        assert response.status_code == 200

        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 10

    def test_list_artists_sort_by_name(self, client: TestClient) -> None:
        """Test sorting artists by name."""
        response = client.get("/api/v1/library/artists?sort_by=name")
        assert response.status_code == 200

    def test_list_artists_sort_by_track_count(self, client: TestClient) -> None:
        """Test sorting artists by track count."""
        response = client.get("/api/v1/library/artists?sort_by=track_count")
        assert response.status_code == 200

    def test_list_artists_search(self, client: TestClient) -> None:
        """Test searching for artists."""
        response = client.get("/api/v1/library/artists?search=test")
        assert response.status_code == 200

    def test_artist_summary_has_required_fields(self, client: TestClient) -> None:
        """Artist items should have all required fields."""
        response = client.get("/api/v1/library/artists?page_size=1")
        data = response.json()

        if data["items"]:
            artist = data["items"][0]
            assert "name" in artist
            assert "track_count" in artist
            assert "album_count" in artist
            assert "first_track_id" in artist


class TestListAlbums:
    """Tests for /library/albums endpoint."""

    def test_list_albums_returns_list(self, client: TestClient) -> None:
        """Test listing albums returns paginated response."""
        response = client.get("/api/v1/library/albums")
        assert response.status_code == 200

        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data

    def test_list_albums_filter_by_artist(self, client: TestClient) -> None:
        """Test filtering albums by artist."""
        response = client.get("/api/v1/library/albums?artist=test")
        assert response.status_code == 200

    def test_list_albums_sort_by_year(self, client: TestClient) -> None:
        """Test sorting albums by year."""
        response = client.get("/api/v1/library/albums?sort_by=year")
        assert response.status_code == 200

    def test_album_summary_has_required_fields(self, client: TestClient) -> None:
        """Album items should have all required fields."""
        response = client.get("/api/v1/library/albums?page_size=1")
        data = response.json()

        if data["items"]:
            album = data["items"][0]
            assert "name" in album
            assert "artist" in album
            assert "track_count" in album
            assert "first_track_id" in album


class TestYearDistribution:
    """Tests for /library/years endpoint."""

    def test_get_year_distribution(self, client: TestClient) -> None:
        """Test getting year distribution."""
        response = client.get("/api/v1/library/years")
        assert response.status_code == 200

        data = response.json()
        assert "years" in data
        assert "total_with_year" in data
        assert "total_without_year" in data
        assert "min_year" in data
        assert "max_year" in data

    def test_year_distribution_years_are_valid(self, client: TestClient) -> None:
        """Year values should be realistic."""
        response = client.get("/api/v1/library/years")
        data = response.json()

        for year_data in data["years"]:
            assert year_data["year"] >= 1900
            assert year_data["year"] <= 2100
            assert year_data["track_count"] >= 0


class TestSyncStatus:
    """Tests for sync status endpoint."""

    def test_get_sync_status(self, client: TestClient) -> None:
        """Test getting sync status."""
        response = client.get("/api/v1/library/sync/status")
        assert response.status_code == 200

        data = response.json()
        assert "status" in data
        assert "message" in data
        assert data["status"] in ["idle", "running", "completed", "error"]


class TestSyncStart:
    """Tests for starting sync."""

    def test_start_sync_returns_status(self, client: TestClient) -> None:
        """Test starting sync returns valid status."""
        response = client.post("/api/v1/library/sync")
        # Accept various valid responses:
        # - 200: sync started or already_running
        # - 429: rate limited (too many requests)
        assert response.status_code in [200, 429]

        if response.status_code == 200:
            data = response.json()
            assert "status" in data
            assert data["status"] in ["started", "already_running"]


class TestAnalysisStatus:
    """Tests for analysis status endpoint."""

    def test_get_analysis_status(self, client: TestClient) -> None:
        """Test getting analysis status."""
        response = client.get("/api/v1/library/analysis/status")
        assert response.status_code == 200

        data = response.json()
        assert "status" in data
        assert "total" in data
        assert "analyzed" in data
        assert "pending" in data
        assert "percent" in data
        assert "embeddings_enabled" in data

    def test_analysis_status_values_consistent(self, client: TestClient) -> None:
        """Analysis stats should be internally consistent."""
        response = client.get("/api/v1/library/analysis/status")
        data = response.json()

        # analyzed + pending + failed should roughly equal total
        # (may not be exact due to timing)
        assert data["analyzed"] <= data["total"]
        assert data["pending"] <= data["total"]

    def test_analysis_percent_in_range(self, client: TestClient) -> None:
        """Analysis percent should be 0-100."""
        response = client.get("/api/v1/library/analysis/status")
        data = response.json()

        assert 0 <= data["percent"] <= 100


class TestExecutorStatus:
    """Tests for executor circuit breaker status."""

    def test_get_executor_status(self, client: TestClient) -> None:
        """Test getting executor status."""
        response = client.get("/api/v1/library/analysis/executor")
        assert response.status_code == 200

        data = response.json()
        assert "disabled" in data
        assert "consecutive_failures" in data
        assert "max_failures" in data
        assert "crashed_track_ids" in data

    def test_executor_reset(self, client: TestClient) -> None:
        """Test resetting executor circuit breaker."""
        response = client.post("/api/v1/library/analysis/executor/reset")
        assert response.status_code == 200

        data = response.json()
        assert "status" in data
        assert data["status"] == "reset"


class TestMissingTracks:
    """Tests for missing tracks management."""

    def test_get_missing_tracks(self, client: TestClient) -> None:
        """Test getting list of missing tracks."""
        response = client.get("/api/v1/library/missing")
        assert response.status_code == 200

        data = response.json()
        assert "tracks" in data
        assert "total_missing" in data
        assert "total_pending_deletion" in data
        assert isinstance(data["tracks"], list)

    def test_missing_track_has_required_fields(self, client: TestClient) -> None:
        """Missing track entries should have all required fields."""
        response = client.get("/api/v1/library/missing")
        data = response.json()

        for track in data["tracks"]:
            assert "id" in track
            assert "file_path" in track
            assert "status" in track
            assert "days_missing" in track


class TestRecentImports:
    """Tests for import history."""

    def test_get_recent_imports(self, client: TestClient) -> None:
        """Test getting recent imports list.

        Note: Returns 500 if no library path is configured (CI environment).
        """
        response = client.get("/api/v1/library/imports/recent")
        # Accept 200 (success) or 500 (no library configured in CI)
        assert response.status_code in (200, 500)

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)


class TestMoodDistribution:
    """Tests for mood distribution endpoint."""

    def test_get_mood_distribution(self, client: TestClient) -> None:
        """Test getting mood distribution."""
        response = client.get("/api/v1/library/mood-distribution")
        assert response.status_code == 200

        data = response.json()
        assert "cells" in data
        assert "grid_size" in data
        assert "total_with_mood" in data
        assert "total_without_mood" in data

    def test_mood_distribution_grid_size_param(self, client: TestClient) -> None:
        """Test mood distribution with custom grid size."""
        response = client.get("/api/v1/library/mood-distribution?grid_size=5")
        assert response.status_code == 200

        data = response.json()
        assert data["grid_size"] == 5

    def test_mood_cell_values_in_range(self, client: TestClient) -> None:
        """Mood cell boundaries should be in 0-1 range."""
        response = client.get("/api/v1/library/mood-distribution?grid_size=5")
        data = response.json()

        for cell in data["cells"]:
            assert 0 <= cell["energy_min"] <= 1
            assert 0 <= cell["energy_max"] <= 1
            assert 0 <= cell["valence_min"] <= 1
            assert 0 <= cell["valence_max"] <= 1
            assert cell["track_count"] >= 0


class TestCancelOperations:
    """Tests for cancel endpoints."""

    def test_cancel_analysis(self, client: TestClient) -> None:
        """Test cancelling analysis tasks."""
        response = client.post("/api/v1/library/analysis/cancel")
        assert response.status_code == 200

        data = response.json()
        assert "status" in data
        assert data["status"] == "cancelled"
        assert "requested" in data
        assert "in_process_tasks_cancelled" in data
        assert "subprocess_may_continue" in data

    def test_cancel_sync(self, client: TestClient) -> None:
        """Test cancelling sync operation."""
        response = client.post("/api/v1/library/sync/cancel")
        assert response.status_code == 200

        data = response.json()
        assert "status" in data
        assert data["status"] == "cancelled"
        assert "requested" in data
        assert "in_process_tasks_cancelled" in data
        assert "subprocess_may_continue" in data


class TestArtistDetail:
    """Tests for artist detail endpoint."""

    def test_get_artist_detail_not_found(self, client: TestClient) -> None:
        """Test getting non-existent artist returns 404."""
        response = client.get("/api/v1/library/artists/NonExistentArtist12345")
        assert response.status_code == 404

    def test_get_artist_detail_url_encoding(self, client: TestClient) -> None:
        """Test artist names with special characters."""
        # URL encoded "Test & Artist"
        response = client.get("/api/v1/library/artists/Test%20%26%20Artist")
        # Will return 404 if artist doesn't exist, but shouldn't error
        assert response.status_code in [200, 404]
