"""Tests for atomic file write utilities."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.utils.atomic_write import atomic_write_bytes, atomic_write_text, atomic_write_via


class TestAtomicWriteBytes:
    """Tests for atomic_write_bytes."""

    def test_successful_write(self):
        """File should contain the written data after a successful call."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "output.bin"
            data = b"hello world"

            atomic_write_bytes(target, data)

            assert target.read_bytes() == data

    def test_creates_parent_directories(self):
        """Missing parent directories should be created automatically."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "a" / "b" / "c" / "output.bin"

            atomic_write_bytes(target, b"nested")

            assert target.read_bytes() == b"nested"

    def test_overwrites_existing_file(self):
        """Existing file should be replaced atomically."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "output.bin"
            target.write_bytes(b"old content")

            atomic_write_bytes(target, b"new content")

            assert target.read_bytes() == b"new content"

    def test_failure_preserves_original(self):
        """On write failure, the original file should remain intact."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "output.bin"
            target.write_bytes(b"original")

            with patch("app.utils.atomic_write.os.write", side_effect=OSError("disk full")):
                with pytest.raises(OSError, match="disk full"):
                    atomic_write_bytes(target, b"new data")

            # Original should be untouched
            assert target.read_bytes() == b"original"

    def test_no_leftover_temp_files(self):
        """No temporary files should remain after success or failure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "output.bin"

            # Success case
            atomic_write_bytes(target, b"data")
            files = list(Path(tmpdir).iterdir())
            assert files == [target], f"Unexpected files: {files}"

            # Failure case
            with patch("app.utils.atomic_write.os.write", side_effect=OSError("fail")):
                with pytest.raises(OSError):
                    atomic_write_bytes(target, b"bad")

            files = list(Path(tmpdir).iterdir())
            assert files == [target], f"Leftover temp files: {files}"


class TestAtomicWriteText:
    """Tests for atomic_write_text."""

    def test_writes_text_as_utf8(self):
        """Text should be written with UTF-8 encoding by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "output.txt"

            atomic_write_text(target, "héllo wörld")

            assert target.read_text(encoding="utf-8") == "héllo wörld"


class TestAtomicWriteVia:
    """Tests for atomic_write_via (callback-based writes)."""

    def test_successful_callback(self):
        """Callback should be able to write to the provided path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "output.dat"

            def write_fn(path: Path) -> None:
                path.write_bytes(b"from callback")

            atomic_write_via(target, write_fn)

            assert target.read_bytes() == b"from callback"

    def test_callback_failure_cleans_up(self):
        """If the callback raises, temp file should be removed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "output.dat"
            target.write_bytes(b"original")

            def bad_write(path: Path) -> None:
                raise RuntimeError("simulated failure")

            with pytest.raises(RuntimeError, match="simulated failure"):
                atomic_write_via(target, bad_write)

            # Original should remain
            assert target.read_bytes() == b"original"
            # No temp files
            files = list(Path(tmpdir).iterdir())
            assert files == [target]


class TestARewriteKeepsTheFile:
    """ADR-0171's drill: `docker exec` (root) rewrote settings.json as a root-owned 0600 file, and
    the server (`familiar`) then ran on defaults, without the token it had just been given."""

    def test_the_mode_survives_a_rewrite(self, tmp_path):
        import os
        import stat

        target = tmp_path / "settings.json"
        target.write_text("{}")
        os.chmod(target, 0o640)
        atomic_write_text(target, '{"a": 1}')
        assert stat.S_IMODE(os.stat(target).st_mode) == 0o640
        assert target.read_text() == '{"a": 1}'

    def test_root_gives_the_replacement_the_old_owner(self, tmp_path, monkeypatch):
        import os

        target = tmp_path / "settings.json"
        target.write_text("{}")
        st = os.stat(target)
        chowned: list[tuple[int, int]] = []
        monkeypatch.setattr(os, "geteuid", lambda: 0)
        monkeypatch.setattr(os, "chown", lambda path, uid, gid: chowned.append((uid, gid)))
        atomic_write_text(target, "{}")
        atomic_write_via(target, lambda p: p.write_text("{}"))
        assert chowned == [(st.st_uid, st.st_gid)] * 2

    def test_a_non_root_writer_does_not_try_to_chown(self, tmp_path, monkeypatch):
        import os

        target = tmp_path / "settings.json"
        target.write_text("{}")
        monkeypatch.setattr(os, "geteuid", lambda: 1000)

        def chown(*_):
            raise AssertionError("chown attempted without root")

        monkeypatch.setattr(os, "chown", chown)
        atomic_write_text(target, "{}")

    def test_root_creating_a_file_gives_it_the_directory_owner(self, tmp_path, monkeypatch):
        import os

        st = os.stat(tmp_path)
        chowned: list[tuple[int, int]] = []
        monkeypatch.setattr(os, "geteuid", lambda: 0)
        monkeypatch.setattr(os, "chown", lambda path, uid, gid: chowned.append((uid, gid)))
        atomic_write_text(tmp_path / "settings.json", "{}")
        assert chowned == [(st.st_uid, st.st_gid)]

    def test_a_new_file_is_unaffected(self, tmp_path):
        target = tmp_path / "new.json"
        atomic_write_text(target, "{}")
        assert target.read_text() == "{}"
