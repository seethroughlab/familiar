"""ADR-0178 points 2 and 3: the update check is on by default, and a stored "disabled" is migrated once.

`_save` writes every field with its default, so a "disabled" in an existing `settings.json` is not
evidence that anyone chose it. These tests pin the one-time migration and, as importantly, that a
choice made afterwards is never undone.
"""

from __future__ import annotations

import json
import logging

from app.services.app_settings import DEFAULT_UPDATE_CHANNEL, AppSettingsService


def _service(tmp_path, stored: dict | None):
    path = tmp_path / "settings.json"
    if stored is not None:
        path.write_text(json.dumps(stored))
    return AppSettingsService(settings_path=path), path


def test_the_default_channel_is_one_that_sees_the_releases_that_exist():
    # Every release so far is a beta, and the "stable" channel skips betas: a stable default
    # would be the old silence by another name.
    assert DEFAULT_UPDATE_CHANNEL == "beta"


def test_a_new_install_checks_for_updates(tmp_path):
    service, _ = _service(tmp_path, None)
    assert service.get().update_channel == "beta"


def test_a_stored_disabled_nobody_chose_is_turned_on_once_and_said_so(tmp_path, caplog):
    service, path = _service(tmp_path, {"update_channel": "disabled", "music_library_paths": []})
    with caplog.at_level(logging.WARNING, logger="app.services.app_settings"):
        assert service.get().update_channel == "beta"
    stored = json.loads(path.read_text())
    assert stored["update_channel"] == "beta" and stored["update_channel_migrated"] is True
    assert sum("Update checks are now on" in r.getMessage() for r in caplog.records) == 1

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app.services.app_settings"):
        service.get()
    assert not any("Update checks are now on" in r.getMessage() for r in caplog.records)


def test_a_file_from_before_the_setting_existed_is_migrated_too(tmp_path):
    service, _ = _service(tmp_path, {"music_library_paths": []})
    assert service.get().update_channel == "beta"


def test_turning_it_off_after_the_migration_stays_off(tmp_path):
    service, _ = _service(tmp_path, {"update_channel": "disabled"})
    service.get()
    service.update(update_channel="disabled")
    assert service.get().update_channel == "disabled"
    assert (
        AppSettingsService(settings_path=tmp_path / "settings.json").get().update_channel
        == "disabled"
    )


def test_a_new_install_that_turns_it_off_stays_off(tmp_path):
    service, _ = _service(tmp_path, None)
    service.update(update_channel="disabled")
    assert service.get().update_channel == "disabled"


def test_a_channel_someone_picked_is_kept(tmp_path):
    service, path = _service(tmp_path, {"update_channel": "alpha"})
    assert service.get().update_channel == "alpha"
    assert json.loads(path.read_text())["update_channel_migrated"] is True


def test_the_migration_marker_is_not_in_the_settings_view(tmp_path):
    service, _ = _service(tmp_path, {"update_channel": "disabled"})
    assert "update_channel_migrated" not in service.get_masked()
