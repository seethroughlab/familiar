"""A server has an identity, advertises it, and hands a pairing client what it needs (ADR-0134)."""

from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest

import app.services.app_settings as app_settings_module
from app.api.auth import TOKEN_HEADER
from app.services.app_settings import AppSettingsService
from app.services.server_identity import get_server_identity, lan_addresses


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """A settings service of this test's own, installed where every caller looks it up."""
    service = AppSettingsService(settings_path=tmp_path / "settings.json")
    monkeypatch.setattr(app_settings_module, "_app_settings_service", service)
    return service


class TestIdentity:
    def test_an_id_is_minted_once_and_kept(self, settings_file):
        first = get_server_identity().server_id
        assert first
        assert get_server_identity().server_id == first
        # Persisted, so a restart keeps it: a paired phone remembers this, not an address.
        reloaded = AppSettingsService(settings_path=settings_file.settings_path)
        assert reloaded.get().server_id == first

    def test_the_name_defaults_to_the_host_without_its_mdns_suffix(self, settings_file, monkeypatch):
        monkeypatch.setattr(socket, "gethostname", lambda: "Studio-MacBook.local")
        assert get_server_identity().server_name == "Studio-MacBook"

    def test_a_chosen_name_wins(self, settings_file):
        settings_file.update(server_name="Living Room")
        assert get_server_identity().server_name == "Living Room"


def test_lan_addresses_leave_out_what_a_phone_cannot_reach(monkeypatch):
    import psutil

    def addr(ip):
        return SimpleNamespace(family=socket.AF_INET, address=ip)

    monkeypatch.setattr(
        psutil,
        "net_if_addrs",
        lambda: {
            "lo0": [addr("127.0.0.1")],
            "en0": [addr("192.168.1.20"), SimpleNamespace(family=socket.AF_INET6, address="fe80::1")],
            "awdl": [addr("169.254.3.4")],
            "utun": [addr("100.101.102.103")],
        },
    )
    # Private LAN first; loopback and link-local never.
    assert lan_addresses() == ["192.168.1.20", "100.101.102.103"]


def test_the_advertisement_never_carries_the_token():
    from app.services.advertise import txt_record

    record = txt_record("id-1", "Studio")
    assert set(record) == {"id", "name", "contract"}


class TestContract:
    def test_the_handshake_says_which_server_this_is(self, client, settings_file):
        body = client.get("/api/v1/contract").json()
        assert body["server_id"] == get_server_identity().server_id
        assert body["server_name"]


class TestPairingEndpoint:
    def test_a_server_without_a_token_has_nothing_to_pair_with(self, client, settings_file):
        response = client.get("/api/v1/auth/pairing")
        assert response.status_code == 409

    def test_it_requires_the_token(self, client, settings_file):
        settings_file.update(access_token="secret-token")
        assert client.get("/api/v1/auth/pairing").status_code == 401

    def test_it_returns_what_a_pairing_link_needs(self, client, settings_file, monkeypatch):
        settings_file.update(access_token="secret-token")
        monkeypatch.setattr(
            "app.services.server_identity.lan_addresses", lambda: ["192.168.1.20"]
        )
        body = client.get("/api/v1/auth/pairing", headers={TOKEN_HEADER: "secret-token"}).json()
        assert body["token"] == "secret-token"
        assert body["server_id"] == get_server_identity().server_id
        assert body["addresses"] == ["192.168.1.20"]
        assert body["header"] == TOKEN_HEADER
