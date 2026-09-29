"""A server runs outside the container (ADR-0132).

These cover the parts that used to hold only because the image's WORKDIR is `/app`: where state is
written, where the version comes from, and how a server starts without `docker/entrypoint.sh`.
No database: `app.serve`'s migration and uvicorn steps are passed in.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import app.config as config_module
from app.config import Settings, get_app_version
from app.serve import DEFAULT_HOST, DEFAULT_PORT, main


class TestDataDir:
    def test_the_default_is_the_relative_directory_the_image_already_uses(self, monkeypatch):
        monkeypatch.delenv("FAMILIAR_DATA_DIR", raising=False)
        s = Settings()
        assert s.data_dir == Path("data")
        assert s.settings_file == Path("data/settings.json")

    def test_familiar_data_dir_moves_every_derived_path(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FAMILIAR_DATA_DIR", str(tmp_path))
        for var in ("ART_PATH", "VIDEOS_PATH", "PROFILES_PATH", "MIXTAPES_PATH"):
            monkeypatch.delenv(var, raising=False)
        s = Settings()
        derived = [
            s.art_path,
            s.videos_path,
            s.profiles_path,
            s.mixtapes_path,
            s.settings_file,
            s.outputs_file,
            s.transcode_cache_dir,
            s.restore_safety_dir,
            s.analysis_data_dir,
            s.models_dir,
        ]
        assert all(p.is_relative_to(tmp_path) for p in derived), derived

    def test_an_explicit_path_variable_still_wins(self, monkeypatch, tmp_path):
        # The image puts art on its own volume at /data/art; that must survive a data_dir.
        monkeypatch.setenv("FAMILIAR_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("ART_PATH", "/data/art")
        assert Settings().art_path == Path("/data/art")

    def test_an_unprefixed_data_dir_is_not_read(self, monkeypatch):
        # DATA_DIR is a common enough name that some unrelated environment will have set it.
        monkeypatch.delenv("FAMILIAR_DATA_DIR", raising=False)
        monkeypatch.setenv("DATA_DIR", "/somewhere/else")
        assert Settings().data_dir == Path("data")


class TestVersion:
    def test_read_from_version_beside_the_backend(self, monkeypatch, tmp_path):
        (tmp_path / "VERSION").write_text("v0.2.0-beta8\n")
        monkeypatch.setattr(config_module, "BACKEND_ROOT", tmp_path)
        assert get_app_version() == "v0.2.0-beta8"

    def test_dev_when_nothing_stamped_it(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config_module, "BACKEND_ROOT", tmp_path)
        assert get_app_version() == "dev"

    def test_in_the_image_that_file_is_app_version(self):
        # The Dockerfile writes /app/VERSION with WORKDIR /app and the package at /app/app, so the
        # lookup moved without moving the file. Pin the layout it depends on.
        dockerfile = (Path(__file__).resolve().parents[2] / "docker" / "Dockerfile").read_text()
        assert 'RUN echo "${VERSION}" > /app/VERSION' in dockerfile
        assert "COPY --chown=familiar:familiar backend/app ./app" in dockerfile


class TestServe:
    def _run(self, argv):
        calls: list[object] = []
        main(argv, migrate=lambda: calls.append("migrate"), run=lambda h, p: calls.append((h, p)))
        return calls

    def test_migrates_before_it_serves(self):
        assert self._run([]) == ["migrate", (DEFAULT_HOST, DEFAULT_PORT)]

    def test_binds_loopback_unless_told_otherwise(self):
        assert DEFAULT_HOST == "127.0.0.1"

    def test_host_and_port_come_from_arguments(self):
        assert self._run(["--host", "0.0.0.0", "--port", "8000"])[-1] == ("0.0.0.0", 8000)

    def test_a_failed_migration_does_not_start_the_server(self):
        def fail():
            raise RuntimeError("migration failed")

        started = []
        with pytest.raises(RuntimeError):
            main([], migrate=fail, run=lambda h, p: started.append(1))
        assert started == []
