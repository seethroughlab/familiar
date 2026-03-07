"""Shared mock objects for external API services."""

from unittest.mock import AsyncMock, MagicMock


def mock_lastfm_service() -> MagicMock:
    """Create a mock LastfmService."""
    service = MagicMock()
    service.is_configured.return_value = True

    service.get_similar_artists = AsyncMock(return_value=[
        {"name": "Similar Artist 1", "match": "0.95", "url": "https://last.fm/artist1"},
        {"name": "Similar Artist 2", "match": "0.80", "url": "https://last.fm/artist2"},
    ])

    service.get_similar_tracks = AsyncMock(return_value=[
        {
            "name": "Similar Track 1",
            "artist": {"name": "Artist 1"},
            "match": "0.90",
            "url": "https://last.fm/track1",
        },
    ])

    service.scrobble = AsyncMock(return_value=True)
    service.update_now_playing = AsyncMock(return_value=True)

    return service


def mock_musicbrainz_response() -> dict:
    """Return a typical MusicBrainz recording search response."""
    return {
        "recording-list": [
            {
                "id": "mb-recording-123",
                "title": "Test Track",
                "artist-credit": [
                    {"artist": {"id": "mb-artist-123", "name": "Test Artist"}}
                ],
                "release-list": [
                    {
                        "id": "mb-release-123",
                        "title": "Test Album",
                        "status": "Official",
                        "date": "2024-01-01",
                        "release-group": {
                            "primary-type": "Album",
                        },
                    }
                ],
                "isrc-list": ["USRC12345678"],
                "length": "180000",
            }
        ],
        "recording-count": 1,
    }


def mock_bandcamp_search_html() -> str:
    """Return minimal Bandcamp search result HTML for parsing tests."""
    return """
    <div class="searchresult data-search album">
        <div class="heading"><a href="https://artist.bandcamp.com/album/test">Test Album</a></div>
        <div class="subhead">by Test Artist</div>
        <div class="genre">electronic</div>
        <div class="released">released January 1, 2024</div>
        <div class="art"><img src="https://example.com/art.jpg"></div>
    </div>
    """
