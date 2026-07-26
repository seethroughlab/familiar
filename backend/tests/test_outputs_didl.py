"""Tests for DIDL-Lite metadata sent to UPnP renderers.

Regression coverage for the bug where the ``res`` protocolInfo was hardcoded to ``audio/flac`` for
every track. Strict renderers (WiiM/LinkPlay) reject SetAVTransportURI when protocolInfo doesn't
match the real stream type, which broke playback for MP3s (and everything non-FLAC).
"""

from app.services.outputs import TrackMetadata, _build_didl_metadata

URL = "http://192.168.1.50:4400/api/v1/tracks/abc/stream"


def test_protocolinfo_matches_mp3_content_type():
    didl = _build_didl_metadata(URL, TrackMetadata(title="x", content_type="audio/mpeg"))
    assert "http-get:*:audio/mpeg:*" in didl
    assert "audio/flac" not in didl


def test_protocolinfo_matches_flac_content_type():
    didl = _build_didl_metadata(URL, TrackMetadata(title="x", content_type="audio/flac"))
    assert "http-get:*:audio/flac:*" in didl


def test_protocolinfo_defaults_to_mp3_when_unknown():
    # No content type available — default to the most common case rather than mislabeling.
    didl = _build_didl_metadata(URL, TrackMetadata(title="x"))
    assert "http-get:*:audio/mpeg:*" in didl
