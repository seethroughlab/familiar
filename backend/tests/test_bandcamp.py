"""Tests for Bandcamp service - search result parsing."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.bandcamp import BandcampResult, BandcampService


class TestBandcampSearch:
    @pytest.fixture
    def service(self):
        return BandcampService()

    @pytest.mark.asyncio
    async def test_returns_empty_on_http_error(self, service):
        import httpx
        service.client = AsyncMock()
        service.client.get.side_effect = httpx.ConnectError("Connection error")
        results = await service.search("test query")
        assert results == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_results(self, service):
        mock_response = MagicMock()
        mock_response.text = "<html><body>No results</body></html>"
        mock_response.raise_for_status = MagicMock()
        service.client = AsyncMock()
        service.client.get.return_value = mock_response

        results = await service.search("very obscure query")
        assert results == []


class TestBandcampResult:
    def test_dataclass_creation(self):
        result = BandcampResult(
            result_type="album",
            name="Test Album",
            artist="Test Artist",
            album=None,
            url="https://artist.bandcamp.com/album/test",
            image_url="https://example.com/art.jpg",
            genre="electronic",
            release_date="January 1, 2024",
        )
        assert result.result_type == "album"
        assert result.name == "Test Album"
        assert result.artist == "Test Artist"
