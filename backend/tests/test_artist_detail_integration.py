"""Integration tests for the artist detail endpoint (GET /library/artists/{name}).

Tests the Last.fm similar-artists match-score flow:
- get_similar_artists (dedicated API) provides proper match scores
- Fallback to get_artist_info similar data when get_similar_artists fails
- Cache staleness detection when cached entries lack the 'match' key
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import delete

from app.api.routes.library import get_artist_detail
from app.db.models import ArtistInfo
from tests.factories import insert_test_track


@pytest.fixture
def mock_lastfm():
    """Mock Last.fm service with get_artist_info and get_similar_artists."""
    mock = MagicMock()
    mock.is_configured.return_value = True

    mock.get_artist_info = AsyncMock(return_value={
        "name": "Test Artist",
        "mbid": "test-mbid",
        "url": "https://www.last.fm/music/Test+Artist",
        "bio": {"summary": "A test artist.", "content": "Full bio."},
        "stats": {"listeners": "12345", "playcount": "67890"},
        "image": [],
        "similar": {"artist": [
            {"name": "Fallback Artist", "url": "https://last.fm/fallback"},
        ]},
        "tags": {"tag": [{"name": "electronic"}]},
    })

    mock.get_similar_artists = AsyncMock(return_value=[
        {"name": "Similar Artist 1", "match": "0.95", "url": "https://last.fm/artist1"},
        {"name": "Similar Artist 2", "match": "0.80", "url": "https://last.fm/artist2"},
    ])

    return mock


@pytest.fixture(autouse=True)
async def cleanup_artist_info(async_db):
    """Clean ArtistInfo before and after each test (not in conftest cleanup list)."""
    await async_db.execute(delete(ArtistInfo))
    await async_db.commit()
    yield
    await async_db.execute(delete(ArtistInfo))
    await async_db.commit()


class TestSimilarArtistsMatchScores:
    """Core regression test: get_similar_artists provides real match scores."""

    @pytest.mark.asyncio
    async def test_similar_artists_have_match_scores(self, async_db, mock_lastfm):
        await insert_test_track(async_db, artist="Test Artist")
        await async_db.commit()

        with patch("app.services.lastfm.get_lastfm_service", return_value=mock_lastfm):
            result = await get_artist_detail(db=async_db, artist_name="Test Artist")

        assert len(result.similar_artists) == 2
        assert result.similar_artists[0].name == "Similar Artist 1"
        assert result.similar_artists[0].match_score == 0.95
        assert result.similar_artists[1].name == "Similar Artist 2"
        assert result.similar_artists[1].match_score == 0.80


class TestSimilarArtistsFallback:
    """When get_similar_artists returns empty, falls back to get_artist_info data."""

    @pytest.mark.asyncio
    async def test_similar_artists_fallback_when_get_similar_fails(self, async_db, mock_lastfm):
        await insert_test_track(async_db, artist="Test Artist")
        await async_db.commit()

        # get_similar_artists returns nothing — should fall back to artist_info similar
        mock_lastfm.get_similar_artists = AsyncMock(return_value=[])

        with patch("app.services.lastfm.get_lastfm_service", return_value=mock_lastfm):
            result = await get_artist_detail(db=async_db, artist_name="Test Artist")

        # Fallback data from get_artist_info has no match key → score 0.0
        assert len(result.similar_artists) == 1
        assert result.similar_artists[0].name == "Fallback Artist"
        assert result.similar_artists[0].match_score == 0.0


class TestCacheStaleness:
    """Cache entries without 'match' key trigger a re-fetch."""

    @pytest.mark.asyncio
    async def test_cache_staleness_detects_missing_match_key(self, async_db, mock_lastfm):
        await insert_test_track(async_db, artist="Test Artist")

        # Pre-populate stale cache (no 'match' key in similar_artists)
        stale_cache = ArtistInfo(
            artist_name_normalized="test artist",
            artist_name="Test Artist",
            similar_artists=[{"name": "Stale Artist"}],
            tags=["rock"],
            fetched_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
        )
        async_db.add(stale_cache)
        await async_db.commit()

        with patch("app.services.lastfm.get_lastfm_service", return_value=mock_lastfm):
            result = await get_artist_detail(db=async_db, artist_name="Test Artist")

        # Cache was bypassed — fresh data fetched with real match scores
        mock_lastfm.get_artist_info.assert_awaited_once()
        mock_lastfm.get_similar_artists.assert_awaited_once()
        assert len(result.similar_artists) == 2
        assert result.similar_artists[0].match_score == 0.95
