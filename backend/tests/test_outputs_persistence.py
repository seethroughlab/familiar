"""Registered network outputs must survive a restart.

Regression: OutputManager held outputs only in memory, so a manually-registered
WiiM (UPnP) device vanished on every `docker restart`. These tests assert that
registrations persist to disk and reload into a fresh manager.
"""

from uuid import UUID

import pytest

from app.services import outputs as outputs_mod
from app.services.outputs import (
    BrowserOutput,
    OutputManager,
    UPnPOutput,
)


@pytest.fixture
def outputs_file(tmp_path, monkeypatch):
    """Redirect the persistence file to a temp location for each test."""
    path = tmp_path / "outputs.json"
    monkeypatch.setattr(outputs_mod, "_OUTPUTS_FILE", path)
    return path


def test_upnp_output_survives_fresh_manager(outputs_file):
    manager = OutputManager()
    wiim = UPnPOutput(name="WiiM", device_url="http://10.0.0.5:49152/description.xml")
    wiim_id = manager.register_output(wiim)

    assert outputs_file.exists()

    # Simulate a restart: a brand-new manager loads from the same file.
    reloaded = OutputManager()
    reloaded.load_persisted()

    assert wiim_id in reloaded.outputs
    restored = reloaded.outputs[wiim_id]
    assert isinstance(restored, UPnPOutput)
    assert restored.name == "WiiM"
    assert restored.device_url == "http://10.0.0.5:49152/description.xml"
    # The id is stable so a saved activeOutputId still matches after restart.
    assert isinstance(restored.id, UUID)
    assert restored.id == wiim_id


def test_browser_output_is_not_persisted(outputs_file):
    manager = OutputManager()
    manager.register_output(BrowserOutput(name="This Device"))

    # Browser outputs are ephemeral — the file should hold no entries for them.
    import json

    assert json.loads(outputs_file.read_text()) == []


def test_unregister_removes_from_disk(outputs_file):
    manager = OutputManager()
    wiim_id = manager.register_output(
        UPnPOutput(name="WiiM", device_url="http://10.0.0.5:49152/description.xml")
    )
    assert manager.unregister_output(wiim_id) is True

    reloaded = OutputManager()
    reloaded.load_persisted()
    assert wiim_id not in reloaded.outputs


def test_browser_register_does_not_clobber_saved_devices(outputs_file):
    """get_output_manager() loads saved devices, then registers the browser
    default whose _persist() must keep the loaded devices in the file."""
    seed = OutputManager()
    wiim_id = seed.register_output(
        UPnPOutput(name="WiiM", device_url="http://10.0.0.5:49152/description.xml")
    )

    # Mirror get_output_manager()'s order: load first, then register browser.
    manager = OutputManager()
    manager.load_persisted()
    manager.register_output(BrowserOutput(name="This Device"))

    # The browser register triggered a re-persist; the WiiM must still be there.
    after_restart = OutputManager()
    after_restart.load_persisted()
    assert wiim_id in after_restart.outputs


def test_load_persisted_is_resilient_to_bad_entries(outputs_file):
    outputs_file.write_text(
        '[{"type": "upnp", "id": "not-a-uuid", "device_url": "x"}, '
        '{"type": "upnp", "id": "11111111-1111-1111-1111-111111111111", '
        '"name": "Good", "device_url": "http://10.0.0.9:49152/description.xml"}]'
    )
    manager = OutputManager()
    manager.load_persisted()

    # The malformed entry is skipped; the valid one still loads.
    good_id = UUID("11111111-1111-1111-1111-111111111111")
    assert good_id in manager.outputs
    assert manager.outputs[good_id].name == "Good"
