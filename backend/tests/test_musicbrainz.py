"""Tests for MusicBrainz service - release selection, enrichment, and search."""

from unittest.mock import patch

import musicbrainzngs

from app.services.metadata.musicbrainz import (
    _normalize_for_comparison,
    _select_best_release,
    enrich_track,
    get_artist_by_id,
    get_artist_releases_recent,
    get_recording_by_id,
    get_release_by_id,
    search_artist,
    search_recording,
)


class TestNormalizeForComparison:
    def test_basic(self):
        assert _normalize_for_comparison("Hello World") == "hello world"

    def test_strips_whitespace(self):
        assert _normalize_for_comparison("  Hello  ") == "hello"

    def test_none_returns_empty(self):
        assert _normalize_for_comparison(None) == ""

    def test_empty_string(self):
        assert _normalize_for_comparison("") == ""


class TestSelectBestRelease:
    def test_empty_list_returns_none(self):
        assert _select_best_release([]) is None

    def test_single_release_returned(self):
        releases = [{"title": "Album", "status": "Official"}]
        assert _select_best_release(releases) == releases[0]

    def test_exact_album_match_preferred(self):
        releases = [
            {"title": "Greatest Hits", "status": "Official", "release-group": {"primary-type": "Album", "secondary-type-list": ["Compilation"]}},
            {"title": "Original Album", "status": "Official", "release-group": {"primary-type": "Album"}},
        ]
        result = _select_best_release(releases, local_album="Original Album")
        assert result["title"] == "Original Album"

    def test_album_preferred_over_compilation(self):
        releases = [
            {"title": "Compilation", "status": "Official", "release-group": {"primary-type": "Album", "secondary-type-list": ["Compilation"]}},
            {"title": "Studio Album", "status": "Official", "date": "2020-01-01", "release-group": {"primary-type": "Album"}},
        ]
        result = _select_best_release(releases)
        assert result["title"] == "Studio Album"

    def test_official_preferred_over_bootleg(self):
        releases = [
            {"title": "Album", "status": "Bootleg", "date": "2020-01-01", "release-group": {"primary-type": "Album"}},
            {"title": "Album", "status": "Official", "date": "2020-06-01", "release-group": {"primary-type": "Album"}},
        ]
        result = _select_best_release(releases)
        assert result["status"] == "Official"

    def test_album_type_scoring(self):
        releases = [
            {"title": "Single", "status": "Official", "date": "2020-01-01", "release-group": {"primary-type": "Single"}},
            {"title": "Album", "status": "Official", "date": "2020-01-01", "release-group": {"primary-type": "Album"}},
        ]
        result = _select_best_release(releases)
        assert result["title"] == "Album"

    def test_earlier_date_preferred_as_tiebreaker(self):
        releases = [
            {"title": "Album", "status": "Official", "date": "2022-01-01", "release-group": {"primary-type": "Album"}},
            {"title": "Album", "status": "Official", "date": "2020-01-01", "release-group": {"primary-type": "Album"}},
        ]
        result = _select_best_release(releases)
        assert result["date"] == "2020-01-01"

    def test_soundtrack_penalized(self):
        releases = [
            {"title": "Soundtrack", "status": "Official", "date": "2020-01-01", "release-group": {"primary-type": "Album", "secondary-type-list": ["Soundtrack"]}},
            {"title": "EP", "status": "Official", "date": "2020-01-01", "release-group": {"primary-type": "EP"}},
        ]
        result = _select_best_release(releases)
        assert result["title"] == "EP"


class TestEnrichTrack:
    @patch("app.services.metadata.musicbrainz.get_recording_by_id")
    def test_uses_recording_id_first(self, mock_get):
        mock_get.return_value = {"title": "Track", "artist": "Artist"}
        result = enrich_track(
            title="Track", artist="Artist",
            musicbrainz_recording_id="abc-123",
        )
        assert result is not None
        mock_get.assert_called_once_with("abc-123", local_album=None)

    @patch("app.services.metadata.musicbrainz.search_recording")
    @patch("app.services.metadata.musicbrainz.get_recording_by_id")
    def test_falls_back_to_search(self, mock_get, mock_search):
        mock_get.return_value = None
        mock_search.return_value = {"title": "Track", "artist": "Artist"}
        result = enrich_track(
            title="Track", artist="Artist",
            musicbrainz_recording_id="abc-123",
        )
        assert result is not None
        mock_search.assert_called_once()

    @patch("app.services.metadata.musicbrainz.search_recording")
    @patch("app.services.metadata.musicbrainz.get_recording_by_id")
    def test_returns_none_when_nothing_found(self, mock_get, mock_search):
        mock_get.return_value = None
        mock_search.return_value = None
        result = enrich_track(title="Unknown", artist="Unknown")
        assert result is None

    @patch("app.services.metadata.musicbrainz.search_recording")
    def test_search_only_with_title(self, mock_search):
        mock_search.return_value = {"title": "Track"}
        result = enrich_track(title="Track")
        assert result is not None

    def test_returns_none_with_no_info(self):
        result = enrich_track()
        assert result is None


class TestSearchRecording:
    @patch("app.services.metadata.musicbrainz.get_recording_by_id")
    @patch("app.services.metadata.musicbrainz.musicbrainzngs.search_recordings")
    def test_returns_enriched_recording(self, mock_search, mock_get):
        mock_search.return_value = {
            "recording-list": [{"id": "rec-123", "title": "Track"}]
        }
        mock_get.return_value = {"title": "Track", "artist": "Artist"}

        result = search_recording("Track", "Artist")
        assert result is not None
        mock_get.assert_called_once_with("rec-123", local_album=None)

    @patch("app.services.metadata.musicbrainz.musicbrainzngs.search_recordings")
    def test_returns_none_for_no_results(self, mock_search):
        mock_search.return_value = {"recording-list": []}
        result = search_recording("Unknown Track")
        assert result is None

    @patch("app.services.metadata.musicbrainz.musicbrainzngs.search_recordings")
    def test_handles_api_error(self, mock_search):
        import musicbrainzngs
        mock_search.side_effect = musicbrainzngs.WebServiceError("Error")
        result = search_recording("Track")
        assert result is None

    @patch("app.services.metadata.musicbrainz.get_recording_by_id")
    @patch("app.services.metadata.musicbrainz.musicbrainzngs.search_recordings")
    def test_passes_local_album(self, mock_search, mock_get):
        mock_search.return_value = {
            "recording-list": [{"id": "rec-456", "title": "Track"}]
        }
        mock_get.return_value = {"title": "Track", "album": "My Album"}

        result = search_recording("Track", "Artist", local_album="My Album")
        assert result is not None
        mock_get.assert_called_once_with("rec-456", local_album="My Album")

    @patch("app.services.metadata.musicbrainz.musicbrainzngs.search_recordings")
    def test_handles_generic_exception(self, mock_search):
        mock_search.side_effect = RuntimeError("unexpected")
        result = search_recording("Track")
        assert result is None


class TestGetRecordingById:
    @patch("app.services.metadata.musicbrainz.musicbrainzngs.get_recording_by_id")
    def test_returns_full_metadata(self, mock_get):
        mock_get.return_value = {
            "recording": {
                "id": "rec-123",
                "title": "Test Track",
                "length": "240000",
                "artist-credit": [
                    {"artist": {"name": "Test Artist", "id": "art-123"}},
                ],
                "release-list": [
                    {
                        "id": "rel-123",
                        "title": "Test Album",
                        "date": "2023-01-01",
                        "status": "Official",
                        "release-group": {"id": "rg-123", "primary-type": "Album"},
                    },
                ],
                "tag-list": [
                    {"name": "rock", "count": "10"},
                    {"name": "alternative", "count": "5"},
                ],
                "rating": {"value": "4.2", "votes-count": "100"},
            }
        }
        result = get_recording_by_id("rec-123")
        assert result is not None
        assert result["musicbrainz_recording_id"] == "rec-123"
        assert result["title"] == "Test Track"
        assert result["artist"] == "Test Artist"
        assert result["album"] == "Test Album"
        assert result["tags"] == ["rock", "alternative"]
        assert result["rating"] == 4.2
        assert result["rating_count"] == 100

    @patch("app.services.metadata.musicbrainz.musicbrainzngs.get_recording_by_id")
    def test_returns_none_on_empty_recording(self, mock_get):
        mock_get.return_value = {"recording": {}}
        assert get_recording_by_id("bad-id") is None

    @patch("app.services.metadata.musicbrainz.musicbrainzngs.get_recording_by_id")
    def test_handles_api_error(self, mock_get):
        mock_get.side_effect = musicbrainzngs.WebServiceError("Error")
        assert get_recording_by_id("bad-id") is None


class TestEnrichTrackFull:
    @patch("app.services.metadata.musicbrainz.search_recording")
    @patch("app.services.metadata.musicbrainz.get_recording_by_id")
    def test_enrich_with_isrc_path(self, mock_get_by_id, mock_search):
        """enrich_track with a recording_id should try get_recording_by_id first."""
        mock_get_by_id.return_value = {
            "title": "Song",
            "artist": "Band",
            "musicbrainz_recording_id": "rec-999",
        }
        result = enrich_track(
            title="Song", artist="Band",
            musicbrainz_recording_id="rec-999",
        )
        assert result is not None
        assert result["musicbrainz_recording_id"] == "rec-999"
        mock_search.assert_not_called()  # Should NOT fall back

    @patch("app.services.metadata.musicbrainz.search_recording")
    def test_enrich_passes_album_to_search(self, mock_search):
        mock_search.return_value = {"title": "Song", "album": "My Album"}
        result = enrich_track(title="Song", artist="Band", album="My Album")
        assert result is not None
        mock_search.assert_called_once_with("Song", "Band", local_album="My Album")


class TestSearchArtist:
    @patch("app.services.metadata.musicbrainz.musicbrainzngs.search_artists")
    def test_returns_best_match(self, mock_search):
        mock_search.return_value = {
            "artist-list": [
                {
                    "id": "art-123",
                    "name": "Radiohead",
                    "sort-name": "Radiohead",
                    "type": "Group",
                    "country": "GB",
                    "ext:score": "100",
                },
            ]
        }
        result = search_artist("Radiohead")
        assert result is not None
        assert result["name"] == "Radiohead"
        assert result["musicbrainz_artist_id"] == "art-123"
        assert result["score"] == 100

    @patch("app.services.metadata.musicbrainz.musicbrainzngs.search_artists")
    def test_returns_none_for_no_results(self, mock_search):
        mock_search.return_value = {"artist-list": []}
        assert search_artist("Nonexistent") is None

    @patch("app.services.metadata.musicbrainz.musicbrainzngs.search_artists")
    def test_handles_api_error(self, mock_search):
        mock_search.side_effect = musicbrainzngs.WebServiceError("Error")
        assert search_artist("Radiohead") is None


class TestGetArtistById:
    @patch("app.services.metadata.musicbrainz.musicbrainzngs.get_artist_by_id")
    def test_returns_artist_metadata(self, mock_get):
        mock_get.return_value = {
            "artist": {
                "id": "art-123",
                "name": "Radiohead",
                "sort-name": "Radiohead",
                "type": "Group",
                "country": "GB",
                "life-span": {"begin": "1985", "end": None, "ended": False},
                "tag-list": [{"name": "rock", "count": "50"}],
                "url-relation-list": [
                    {"type": "official homepage", "target": "http://radiohead.com"},
                ],
            }
        }
        result = get_artist_by_id("art-123")
        assert result is not None
        assert result["name"] == "Radiohead"
        assert result["begin_date"] == "1985"
        assert result["tags"] == ["rock"]
        assert len(result["urls"]) == 1

    @patch("app.services.metadata.musicbrainz.musicbrainzngs.get_artist_by_id")
    def test_handles_empty_artist(self, mock_get):
        mock_get.return_value = {"artist": {}}
        assert get_artist_by_id("bad-id") is None

    @patch("app.services.metadata.musicbrainz.musicbrainzngs.get_artist_by_id")
    def test_handles_api_error(self, mock_get):
        mock_get.side_effect = musicbrainzngs.WebServiceError("Error")
        assert get_artist_by_id("bad-id") is None


class TestGetReleaseById:
    @patch("app.services.metadata.musicbrainz.musicbrainzngs.get_release_by_id")
    def test_returns_release_metadata(self, mock_get):
        mock_get.return_value = {
            "release": {
                "id": "rel-123",
                "title": "OK Computer",
                "date": "1997-05-21",
                "status": "Official",
                "artist-credit": [{"artist": {"name": "Radiohead"}}],
                "label-info-list": [
                    {"label": {"name": "Parlophone"}, "catalog-number": "CDNDATA02"},
                ],
                "release-group": {"id": "rg-123", "type": "Album"},
                "medium-list": [{"track-count": "12"}],
            }
        }
        result = get_release_by_id("rel-123")
        assert result is not None
        assert result["title"] == "OK Computer"
        assert result["artist"] == "Radiohead"
        assert result["label"] == "Parlophone"
        assert result["track_count"] == 12

    @patch("app.services.metadata.musicbrainz.musicbrainzngs.get_release_by_id")
    def test_handles_api_error(self, mock_get):
        mock_get.side_effect = musicbrainzngs.WebServiceError("Error")
        assert get_release_by_id("bad-id") is None


class TestGetArtistReleasesRecent:
    @patch("app.services.metadata.musicbrainz.musicbrainzngs.browse_release_groups")
    def test_returns_recent_releases(self, mock_browse):
        mock_browse.return_value = {
            "release-group-list": [
                {
                    "id": "rg-1",
                    "title": "New Album",
                    "type": "Album",
                    "first-release-date": "2026-01-15",
                },
                {
                    "id": "rg-2",
                    "title": "Old Album",
                    "type": "Album",
                    "first-release-date": "2020-01-01",
                },
            ],
            "release-group-count": 2,
        }
        result = get_artist_releases_recent("art-123", days_back=365)
        # "New Album" should be included (within 365 days of today)
        assert any(r["title"] == "New Album" for r in result)

    @patch("app.services.metadata.musicbrainz.musicbrainzngs.browse_release_groups")
    def test_handles_partial_dates(self, mock_browse):
        mock_browse.return_value = {
            "release-group-list": [
                {
                    "id": "rg-1",
                    "title": "Year Only",
                    "type": "Album",
                    "first-release-date": "2026",
                },
            ],
            "release-group-count": 1,
        }
        result = get_artist_releases_recent("art-123", days_back=365)
        assert any(r["title"] == "Year Only" for r in result)

    @patch("app.services.metadata.musicbrainz.musicbrainzngs.browse_release_groups")
    def test_handles_api_error(self, mock_browse):
        mock_browse.side_effect = musicbrainzngs.WebServiceError("Error")
        result = get_artist_releases_recent("art-123")
        assert result == []

    @patch("app.services.metadata.musicbrainz.musicbrainzngs.browse_release_groups")
    def test_handles_empty_result(self, mock_browse):
        mock_browse.return_value = {"release-group-list": [], "release-group-count": 0}
        result = get_artist_releases_recent("art-123")
        assert result == []
