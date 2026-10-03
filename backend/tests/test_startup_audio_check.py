"""The startup check for audio in the library answers within its budget, however large the library.

Found 2026-10-02: one full `rglob` per extension with no match, over a NAS share on SMB at ~32 s
per 300 folders, kept Familiar Server's server in startup past the app's three-minute limit, so it
was restarted, forever.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

import app.main as main
from app.main import library_has_audio


def test_finds_audio_in_any_supported_format(tmp_path: Path) -> None:
    (tmp_path / "Artist" / "Album").mkdir(parents=True)
    (tmp_path / "Artist" / "Album" / "01 Track.FLAC").write_bytes(b"")
    assert library_has_audio(tmp_path) is True


def test_says_false_only_after_looking_everywhere(tmp_path: Path) -> None:
    (tmp_path / "Artist").mkdir()
    (tmp_path / "Artist" / "cover.jpg").write_bytes(b"")
    assert library_has_audio(tmp_path) is False


def test_gives_up_rather_than_walking_a_large_library(tmp_path: Path) -> None:
    for i in range(20):
        (tmp_path / f"folder {i}").mkdir()
    (tmp_path / "folder 19" / "track.mp3").write_bytes(b"")
    assert library_has_audio(tmp_path, budget_seconds=-1) is None


def test_not_knowing_is_not_a_warning(tmp_path: Path, monkeypatch, caplog) -> None:
    monkeypatch.setattr(main, "MUSIC_LIBRARY_PATH", tmp_path)
    monkeypatch.setattr(main, "library_has_audio", lambda _path: None)
    monkeypatch.setattr(main.app_config, "allow_writable_library", True)
    with caplog.at_level(logging.WARNING):
        main.validate_library_path()
    assert not any("appears empty" in r.getMessage() for r in caplog.records)


def test_an_unreadable_library_is_still_reported(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        library_has_audio(tmp_path / "not there")
