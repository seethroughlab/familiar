"""Tests for _external_track_to_response in tracks route."""

from types import SimpleNamespace
from uuid import uuid4

from app.api.routes.tracks import _external_track_to_response
from app.db.models import ExternalTrackSource


def _make_external_track(**overrides):
    """Create a mock ExternalTrack-like object with sensible defaults."""
    defaults = {
        "id": uuid4(),
        "title": "Test Song",
        "artist": "Test Artist",
        "album": "Test Album",
        "track_number": 3,
        "year": 2023,
        "duration_seconds": 240.5,
        "source": ExternalTrackSource.MANUAL,
        "spotify_id": None,
        "matched_track_id": None,
        "external_data": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestExternalTrackToResponse:
    """Tests for _external_track_to_response conversion function."""

    def test_basic_fields_mapped(self):
        ext = _make_external_track()
        resp = _external_track_to_response(ext)

        assert resp.id == ext.id
        assert resp.title == "Test Song"
        assert resp.artist == "Test Artist"
        assert resp.album == "Test Album"
        assert resp.track_number == 3
        assert resp.year == 2023
        assert resp.duration_seconds == 240.5

    def test_track_type_is_external(self):
        ext = _make_external_track()
        resp = _external_track_to_response(ext)
        assert resp.track_type == "external"

    def test_file_path_is_empty(self):
        """External tracks have no local file."""
        ext = _make_external_track()
        resp = _external_track_to_response(ext)
        assert resp.file_path == ""

    def test_analysis_version_zero(self):
        """External tracks have no analysis."""
        ext = _make_external_track()
        resp = _external_track_to_response(ext)
        assert resp.analysis_version == 0

    def test_album_type_defaults_to_album(self):
        ext = _make_external_track()
        resp = _external_track_to_response(ext)
        assert resp.album_type == "album"

    def test_nullable_fields_are_none(self):
        ext = _make_external_track()
        resp = _external_track_to_response(ext)
        assert resp.album_artist is None
        assert resp.disc_number is None
        assert resp.genre is None
        assert resp.format is None

    def test_source_enum_converted_to_string(self):
        ext = _make_external_track(source=ExternalTrackSource.SPOTIFY_FAVORITE)
        resp = _external_track_to_response(ext)
        assert resp.source == "spotify_favorite"

    def test_source_manual(self):
        ext = _make_external_track(source=ExternalTrackSource.MANUAL)
        resp = _external_track_to_response(ext)
        assert resp.source == "manual"

    def test_source_none(self):
        ext = _make_external_track(source=None)
        resp = _external_track_to_response(ext)
        assert resp.source is None

    def test_spotify_id_passed_through(self):
        ext = _make_external_track(spotify_id="abc123")
        resp = _external_track_to_response(ext)
        assert resp.spotify_id == "abc123"

    def test_spotify_id_none(self):
        ext = _make_external_track(spotify_id=None)
        resp = _external_track_to_response(ext)
        assert resp.spotify_id is None

    def test_matched_track_id_converted_to_string(self):
        matched_id = uuid4()
        ext = _make_external_track(matched_track_id=matched_id)
        resp = _external_track_to_response(ext)
        assert resp.matched_track_id == str(matched_id)

    def test_matched_track_id_none(self):
        ext = _make_external_track(matched_track_id=None)
        resp = _external_track_to_response(ext)
        assert resp.matched_track_id is None

    def test_external_data_none_becomes_empty(self):
        ext = _make_external_track(external_data=None)
        resp = _external_track_to_response(ext)
        assert resp.external_data == {}

    def test_external_data_preserved(self):
        data = {"album_art_url": "https://example.com/art.jpg", "spotify_uri": "spotify:track:abc"}
        ext = _make_external_track(external_data=data)
        resp = _external_track_to_response(ext)
        assert resp.external_data == data

    def test_preview_url_from_external_data(self):
        data = {"itunes_preview_url": "https://itunes.apple.com/preview/123"}
        ext = _make_external_track(external_data=data)
        resp = _external_track_to_response(ext)
        assert resp.preview_url == "https://itunes.apple.com/preview/123"

    def test_preview_url_none_when_not_in_data(self):
        ext = _make_external_track(external_data={"other_key": "value"})
        resp = _external_track_to_response(ext)
        assert resp.preview_url is None

    def test_preview_url_none_when_no_external_data(self):
        ext = _make_external_track(external_data=None)
        resp = _external_track_to_response(ext)
        assert resp.preview_url is None

    def test_album_none(self):
        ext = _make_external_track(album=None)
        resp = _external_track_to_response(ext)
        assert resp.album is None

    def test_duration_none(self):
        ext = _make_external_track(duration_seconds=None)
        resp = _external_track_to_response(ext)
        assert resp.duration_seconds is None

    def test_year_none(self):
        ext = _make_external_track(year=None)
        resp = _external_track_to_response(ext)
        assert resp.year is None
