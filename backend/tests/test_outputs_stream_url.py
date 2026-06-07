"""Tests for the device-facing stream URL rewrite (network audio outputs).

Regression coverage for the bug where a WiiM (or any network output) was handed the browser's own
origin as the stream URL. When the browser reaches the app over a network the device can't (e.g.
Tailscale), the device must instead fetch from a LAN-reachable base URL.
"""

from uuid import UUID

from app.api.routes.outputs import _device_stream_url
from app.config import settings

TRACK_ID = UUID("11111111-1111-1111-1111-111111111111")
FRONTEND_URL = "https://familiar.tailnet.ts.net/api/v1/tracks/11111111-1111-1111-1111-111111111111/stream"


def test_rewrites_to_lan_base_when_configured(monkeypatch):
    # Env-var source (DEVICE_STREAM_BASE_URL) — resolved via get_effective's env fallback.
    monkeypatch.setattr(settings, "device_stream_base_url", "http://192.168.1.50:4400")
    assert (
        _device_stream_url(FRONTEND_URL, TRACK_ID)
        == "http://192.168.1.50:4400/api/v1/tracks/11111111-1111-1111-1111-111111111111/stream"
    )


def test_rewrites_using_app_settings_source(monkeypatch):
    # settings.json source (admin-configured) takes precedence over the frontend origin.
    import app.api.routes.outputs as outputs_mod

    class _StubService:
        def get_effective(self, key):
            return "http://10.0.0.130:4400" if key == "device_stream_base_url" else None

    monkeypatch.setattr(outputs_mod, "get_app_settings_service", lambda: _StubService())
    assert (
        _device_stream_url(FRONTEND_URL, TRACK_ID)
        == "http://10.0.0.130:4400/api/v1/tracks/11111111-1111-1111-1111-111111111111/stream"
    )


def test_strips_trailing_slash_on_base(monkeypatch):
    monkeypatch.setattr(settings, "device_stream_base_url", "http://192.168.1.50:4400/")
    assert (
        _device_stream_url(FRONTEND_URL, TRACK_ID)
        == "http://192.168.1.50:4400/api/v1/tracks/11111111-1111-1111-1111-111111111111/stream"
    )


def test_passthrough_when_base_unset(monkeypatch):
    monkeypatch.setattr(settings, "device_stream_base_url", None)
    assert _device_stream_url(FRONTEND_URL, TRACK_ID) == FRONTEND_URL


def test_passthrough_when_no_track_id(monkeypatch):
    # Without a track id we can't rebuild the path, so honor the provided URL.
    monkeypatch.setattr(settings, "device_stream_base_url", "http://192.168.1.50:4400")
    assert _device_stream_url(FRONTEND_URL, None) == FRONTEND_URL
