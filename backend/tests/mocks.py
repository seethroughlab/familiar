"""Shared mock objects for external API services.

Usage:
    from tests.mocks import mock_spotify_client, mock_lastfm_responses

    @patch("app.services.spotify.spotipy.Spotify")
    def test_something(mock_sp_cls):
        mock_sp_cls.return_value = mock_spotify_client()
"""

from unittest.mock import AsyncMock, MagicMock


def mock_spotify_client(**overrides: object) -> MagicMock:
    """Create a mock spotipy.Spotify client with common responses."""
    client = MagicMock()

    client.current_user.return_value = {
        "id": "testuser123",
        "display_name": "Test User",
        "email": "test@example.com",
    }

    client.current_user_saved_tracks.return_value = {
        "items": [
            {
                "added_at": "2024-01-01T00:00:00Z",
                "track": {
                    "id": "spotify_track_1",
                    "name": "Test Track",
                    "artists": [{"name": "Test Artist", "id": "artist_1"}],
                    "album": {
                        "name": "Test Album",
                        "id": "album_1",
                        "images": [{"url": "https://example.com/art.jpg", "width": 300}],
                    },
                    "duration_ms": 180000,
                    "external_ids": {"isrc": "USRC12345678"},
                    "track_number": 1,
                },
            }
        ],
        "next": None,
        "total": 1,
    }

    client.current_user_playlists.return_value = {
        "items": [
            {
                "id": "playlist_1",
                "name": "My Playlist",
                "tracks": {"total": 5},
                "owner": {"id": "testuser123"},
            }
        ],
        "next": None,
    }

    for key, val in overrides.items():
        setattr(client, key, val)

    return client


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
