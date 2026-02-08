"""Tests for the Subsonic API compatibility layer."""

import hashlib
import xml.etree.ElementTree as ET
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.routes.subsonic import (
    _dict_to_xml,
    album_id,
    artist_id,
    parse_id,
    subsonic_error,
    subsonic_response,
    track_to_child,
)
from tests.conftest import make_profile_headers


# ---------------------------------------------------------------------------
# Unit tests for helpers (no DB needed)
# ---------------------------------------------------------------------------


class TestIDMapping:
    """Test deterministic ID generation and parsing."""

    def test_artist_id_deterministic(self):
        assert artist_id("Radiohead") == artist_id("Radiohead")
        assert artist_id("radiohead") == artist_id("Radiohead")
        assert artist_id("  Radiohead  ") == artist_id("Radiohead")

    def test_artist_id_different_artists(self):
        assert artist_id("Radiohead") != artist_id("Björk")

    def test_album_id_deterministic(self):
        a = album_id("Radiohead", "OK Computer")
        b = album_id("Radiohead", "OK Computer")
        assert a == b

    def test_album_id_case_insensitive(self):
        assert album_id("radiohead", "ok computer") == album_id("Radiohead", "OK Computer")

    def test_album_id_different_albums(self):
        assert album_id("Radiohead", "OK Computer") != album_id("Radiohead", "Kid A")

    def test_parse_id_artist(self):
        id_type, raw = parse_id("ar-abc123")
        assert id_type == "artist"
        assert raw == "ar-abc123"

    def test_parse_id_album(self):
        id_type, raw = parse_id("al-abc123")
        assert id_type == "album"
        assert raw == "al-abc123"

    def test_parse_id_track(self):
        uid = str(uuid4())
        id_type, raw = parse_id(uid)
        assert id_type == "track"
        assert raw == uid

    def test_id_prefixes(self):
        assert artist_id("Test").startswith("ar-")
        assert album_id("Test", "Album").startswith("al-")


class TestResponseFormatting:
    """Test XML and JSON response formatting."""

    def test_xml_success_response(self):
        resp = subsonic_response(None, "xml")
        assert resp.media_type == "text/xml; charset=utf-8"
        root = ET.fromstring(resp.body.decode())
        assert root.attrib["status"] == "ok"

    def test_json_success_response(self):
        import json
        resp = subsonic_response({"license": {"valid": "true"}}, "json")
        assert "application/json" in resp.media_type
        body = json.loads(resp.body)
        sr = body["subsonic-response"]
        assert sr["status"] == "ok"
        assert sr["license"]["valid"] == "true"

    def test_xml_error_response(self):
        resp = subsonic_error(40, "Wrong username", "xml")
        root = ET.fromstring(resp.body.decode())
        assert root.attrib["status"] == "failed"
        ns = {"sub": "http://subsonic.org/restapi"}
        err = root.find("sub:error", ns)
        if err is None:
            err = root.find("error")
        assert err is not None
        assert err.attrib["code"] == "40"
        assert err.attrib["message"] == "Wrong username"

    def test_json_error_response(self):
        import json
        resp = subsonic_error(40, "Wrong username", "json")
        body = json.loads(resp.body)
        sr = body["subsonic-response"]
        assert sr["status"] == "failed"
        assert sr["error"]["code"] == 40
        assert sr["error"]["message"] == "Wrong username"


class TestDictToXml:
    """Test XML serialization of Subsonic data structures."""

    def test_scalar_as_attribute(self):
        root = ET.Element("test")
        _dict_to_xml(root, {"name": "Radiohead", "id": "123"})
        assert root.attrib["name"] == "Radiohead"
        assert root.attrib["id"] == "123"

    def test_none_value_skipped(self):
        root = ET.Element("test")
        _dict_to_xml(root, {"name": "Radiohead", "year": None})
        assert root.attrib["name"] == "Radiohead"
        assert "year" not in root.attrib

    def test_list_as_children(self):
        root = ET.Element("artist")
        _dict_to_xml(root, {
            "name": "Radiohead",
            "album": [
                {"id": "1", "name": "OK Computer"},
                {"id": "2", "name": "Kid A"},
            ]
        })
        assert root.attrib["name"] == "Radiohead"
        albums = root.findall("album")
        assert len(albums) == 2
        assert albums[0].attrib["name"] == "OK Computer"

    def test_nested_dict(self):
        root = ET.Element("response")
        _dict_to_xml(root, {"license": {"valid": "true", "email": "test@test.com"}})
        license_el = root.find("license")
        assert license_el is not None
        assert license_el.attrib["valid"] == "true"

    def test_bool_lowercase(self):
        root = ET.Element("test")
        _dict_to_xml(root, {"isDir": False, "isVideo": True})
        assert root.attrib["isDir"] == "false"
        assert root.attrib["isVideo"] == "true"


class TestTrackToChild:
    """Test track serialization to Subsonic format."""

    def _make_track(self, **kwargs):
        """Create a mock Track object."""
        from unittest.mock import MagicMock
        from datetime import datetime

        track = MagicMock()
        track.id = kwargs.get("id", uuid4())
        track.title = kwargs.get("title", "Test Song")
        track.artist = kwargs.get("artist", "Test Artist")
        track.album = kwargs.get("album", "Test Album")
        track.album_artist = kwargs.get("album_artist", "")
        track.track_number = kwargs.get("track_number", 1)
        track.year = kwargs.get("year", 2024)
        track.genre = kwargs.get("genre", "Rock")
        track.file_size = kwargs.get("file_size", 5000000)
        track.file_path = kwargs.get("file_path", "/music/test.mp3")
        track.duration_seconds = kwargs.get("duration_seconds", 240.5)
        track.bitrate = kwargs.get("bitrate", 320000)
        track.created_at = kwargs.get("created_at", datetime(2024, 1, 1))
        return track

    def test_basic_fields(self):
        track = self._make_track()
        child = track_to_child(track)
        assert child["title"] == "Test Song"
        assert child["artist"] == "Test Artist"
        assert child["album"] == "Test Album"
        assert child["isDir"] == "false"
        assert child["type"] == "music"

    def test_duration_is_int(self):
        track = self._make_track(duration_seconds=240.7)
        child = track_to_child(track)
        assert child["duration"] == "240"

    def test_bitrate_in_kbps(self):
        track = self._make_track(bitrate=320000)
        child = track_to_child(track)
        assert child["bitRate"] == "320"

    def test_suffix_extraction(self):
        track = self._make_track(file_path="/music/test.flac")
        child = track_to_child(track)
        assert child["suffix"] == "flac"

    def test_cover_art_is_album_id(self):
        track = self._make_track()
        child = track_to_child(track)
        expected_al_id = album_id("Test Artist", "Test Album")
        assert child["coverArt"] == expected_al_id

    def test_no_album_no_cover_art(self):
        track = self._make_track(album=None)
        child = track_to_child(track)
        assert "coverArt" not in child

    def test_optional_fields_omitted(self):
        track = self._make_track(genre=None, year=None, track_number=None)
        child = track_to_child(track)
        assert "genre" not in child
        assert "year" not in child
        assert "track" not in child

    def test_parent_override(self):
        track = self._make_track()
        child = track_to_child(track, parent_id="custom-parent")
        assert child["parent"] == "custom-parent"


# ---------------------------------------------------------------------------
# Integration tests (require DB + test client)
# ---------------------------------------------------------------------------


def _subsonic_params(profile_data: dict, extra: dict | None = None) -> dict:
    """Build Subsonic auth params for test requests.

    Creates credentials for the profile and returns params dict for queries.
    """
    params = {"u": "testuser", "p": "testpass", "c": "pytest", "v": "1.16.1"}
    if extra:
        params.update(extra)
    return params


def _create_subsonic_creds(client: TestClient, profile: dict) -> dict:
    """Create Subsonic credentials and return {username, password}."""
    resp = client.post(
        "/api/v1/subsonic/credentials",
        headers=make_profile_headers(profile),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    return {"username": data["username"], "password": data["password"]}


class TestSubsonicCredentialManagement:
    """Test credential CRUD via the management API."""

    def test_no_credentials_initially(self, client: TestClient, test_profile: dict):
        resp = client.get(
            "/api/v1/subsonic/credentials",
            headers=make_profile_headers(test_profile),
        )
        assert resp.status_code == 200
        assert resp.json()["configured"] is False

    def test_create_credentials(self, client: TestClient, test_profile: dict):
        creds = _create_subsonic_creds(client, test_profile)
        assert creds["username"]
        assert creds["password"]
        assert len(creds["password"]) > 8

    def test_status_after_create(self, client: TestClient, test_profile: dict):
        _create_subsonic_creds(client, test_profile)
        resp = client.get(
            "/api/v1/subsonic/credentials",
            headers=make_profile_headers(test_profile),
        )
        data = resp.json()
        assert data["configured"] is True
        assert "password" not in data  # Password not returned on status check

    def test_delete_credentials(self, client: TestClient, test_profile: dict):
        _create_subsonic_creds(client, test_profile)
        resp = client.delete(
            "/api/v1/subsonic/credentials",
            headers=make_profile_headers(test_profile),
        )
        assert resp.json()["configured"] is False

        # Verify gone
        resp = client.get(
            "/api/v1/subsonic/credentials",
            headers=make_profile_headers(test_profile),
        )
        assert resp.json()["configured"] is False

    def test_regenerate_replaces(self, client: TestClient, test_profile: dict):
        creds1 = _create_subsonic_creds(client, test_profile)
        creds2 = _create_subsonic_creds(client, test_profile)
        # Username stays the same (based on profile name)
        assert creds1["username"] == creds2["username"]
        # Password changes
        assert creds1["password"] != creds2["password"]


class TestSubsonicAuth:
    """Test Subsonic authentication mechanisms."""

    def test_ping_with_password(self, client: TestClient, test_profile: dict):
        creds = _create_subsonic_creds(client, test_profile)
        resp = client.get("/rest/ping.view", params={
            "u": creds["username"],
            "p": creds["password"],
            "c": "pytest",
            "v": "1.16.1",
        })
        assert resp.status_code == 200
        root = ET.fromstring(resp.text)
        assert root.attrib["status"] == "ok"

    def test_ping_with_token(self, client: TestClient, test_profile: dict):
        creds = _create_subsonic_creds(client, test_profile)
        salt = "randomsalt123"
        token = hashlib.md5((creds["password"] + salt).encode()).hexdigest()
        resp = client.get("/rest/ping.view", params={
            "u": creds["username"],
            "t": token,
            "s": salt,
            "c": "pytest",
            "v": "1.16.1",
        })
        assert resp.status_code == 200
        root = ET.fromstring(resp.text)
        assert root.attrib["status"] == "ok"

    def test_ping_with_enc_password(self, client: TestClient, test_profile: dict):
        creds = _create_subsonic_creds(client, test_profile)
        enc_pass = "enc:" + creds["password"].encode().hex()
        resp = client.get("/rest/ping.view", params={
            "u": creds["username"],
            "p": enc_pass,
            "c": "pytest",
            "v": "1.16.1",
        })
        assert resp.status_code == 200
        root = ET.fromstring(resp.text)
        assert root.attrib["status"] == "ok"

    def test_wrong_password_fails(self, client: TestClient, test_profile: dict):
        creds = _create_subsonic_creds(client, test_profile)
        resp = client.get("/rest/ping.view", params={
            "u": creds["username"],
            "p": "wrongpassword",
            "c": "pytest",
            "v": "1.16.1",
        })
        assert resp.status_code == 200  # Subsonic returns 200 with error in body
        root = ET.fromstring(resp.text)
        assert root.attrib["status"] == "failed"

    def test_wrong_token_fails(self, client: TestClient, test_profile: dict):
        creds = _create_subsonic_creds(client, test_profile)
        resp = client.get("/rest/ping.view", params={
            "u": creds["username"],
            "t": "badtoken",
            "s": "salt",
            "c": "pytest",
            "v": "1.16.1",
        })
        assert resp.status_code == 200
        root = ET.fromstring(resp.text)
        assert root.attrib["status"] == "failed"

    def test_missing_username_fails(self, client: TestClient):
        resp = client.get("/rest/ping.view", params={
            "p": "test",
            "c": "pytest",
            "v": "1.16.1",
        })
        assert resp.status_code == 200
        root = ET.fromstring(resp.text)
        assert root.attrib["status"] == "failed"

    def test_json_format(self, client: TestClient, test_profile: dict):
        creds = _create_subsonic_creds(client, test_profile)
        resp = client.get("/rest/ping.view", params={
            "u": creds["username"],
            "p": creds["password"],
            "f": "json",
            "c": "pytest",
            "v": "1.16.1",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["subsonic-response"]["status"] == "ok"


class TestSubsonicEndpoints:
    """Test Subsonic browsing/search/stub endpoints."""

    def _auth_params(self, creds: dict) -> dict:
        return {
            "u": creds["username"],
            "p": creds["password"],
            "c": "pytest",
            "v": "1.16.1",
        }

    def test_get_license(self, client: TestClient, test_profile: dict):
        creds = _create_subsonic_creds(client, test_profile)
        resp = client.get("/rest/getLicense.view", params=self._auth_params(creds))
        root = ET.fromstring(resp.text)
        assert root.attrib["status"] == "ok"
        license_el = root.find("{http://subsonic.org/restapi}license")
        assert license_el is not None
        assert license_el.attrib["valid"] == "true"

    def test_get_music_folders(self, client: TestClient, test_profile: dict):
        creds = _create_subsonic_creds(client, test_profile)
        resp = client.get("/rest/getMusicFolders.view", params=self._auth_params(creds))
        root = ET.fromstring(resp.text)
        assert root.attrib["status"] == "ok"

    def test_get_artists(self, client: TestClient, test_profile: dict):
        creds = _create_subsonic_creds(client, test_profile)
        resp = client.get("/rest/getArtists.view", params=self._auth_params(creds))
        root = ET.fromstring(resp.text)
        assert root.attrib["status"] == "ok"

    def test_search3_empty_query(self, client: TestClient, test_profile: dict):
        creds = _create_subsonic_creds(client, test_profile)
        params = {**self._auth_params(creds), "query": "nonexistent_xyz"}
        resp = client.get("/rest/search3.view", params=params)
        root = ET.fromstring(resp.text)
        assert root.attrib["status"] == "ok"

    def test_get_starred_empty(self, client: TestClient, test_profile: dict):
        creds = _create_subsonic_creds(client, test_profile)
        resp = client.get("/rest/getStarred2.view", params=self._auth_params(creds))
        root = ET.fromstring(resp.text)
        assert root.attrib["status"] == "ok"

    def test_get_playlists_empty(self, client: TestClient, test_profile: dict):
        creds = _create_subsonic_creds(client, test_profile)
        resp = client.get("/rest/getPlaylists.view", params=self._auth_params(creds))
        root = ET.fromstring(resp.text)
        assert root.attrib["status"] == "ok"

    def test_get_genres(self, client: TestClient, test_profile: dict):
        creds = _create_subsonic_creds(client, test_profile)
        resp = client.get("/rest/getGenres.view", params=self._auth_params(creds))
        root = ET.fromstring(resp.text)
        assert root.attrib["status"] == "ok"

    def test_get_user(self, client: TestClient, test_profile: dict):
        creds = _create_subsonic_creds(client, test_profile)
        params = {**self._auth_params(creds), "username": creds["username"]}
        resp = client.get("/rest/getUser.view", params=params)
        root = ET.fromstring(resp.text)
        assert root.attrib["status"] == "ok"

    def test_json_format_browsing(self, client: TestClient, test_profile: dict):
        creds = _create_subsonic_creds(client, test_profile)
        params = {**self._auth_params(creds), "f": "json"}
        resp = client.get("/rest/getArtists.view", params=params)
        data = resp.json()
        assert data["subsonic-response"]["status"] == "ok"

    def test_get_song_not_found(self, client: TestClient, test_profile: dict):
        creds = _create_subsonic_creds(client, test_profile)
        params = {**self._auth_params(creds), "id": str(uuid4())}
        resp = client.get("/rest/getSong.view", params=params)
        root = ET.fromstring(resp.text)
        assert root.attrib["status"] == "failed"

    def test_get_random_songs(self, client: TestClient, test_profile: dict):
        creds = _create_subsonic_creds(client, test_profile)
        params = {**self._auth_params(creds), "size": "5"}
        resp = client.get("/rest/getRandomSongs.view", params=params)
        root = ET.fromstring(resp.text)
        assert root.attrib["status"] == "ok"

    def test_get_album_list2(self, client: TestClient, test_profile: dict):
        creds = _create_subsonic_creds(client, test_profile)
        params = {**self._auth_params(creds), "type": "newest", "size": "5"}
        resp = client.get("/rest/getAlbumList2.view", params=params)
        root = ET.fromstring(resp.text)
        assert root.attrib["status"] == "ok"
