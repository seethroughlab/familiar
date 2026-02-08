"""Tests for atomic file write utilities."""

import os
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
