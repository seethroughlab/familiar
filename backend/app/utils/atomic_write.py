"""Atomic file write utilities.

Writes go to a temporary file in the same directory, then are renamed into
place.  On POSIX systems ``os.rename`` is atomic within the same filesystem,
so readers never see a half-written file.  If anything goes wrong the
temporary file is cleaned up and the original is left untouched.
"""

import os
import tempfile
from collections.abc import Callable
from pathlib import Path


def atomic_write_bytes(target: Path, data: bytes) -> None:
    """Atomically write *data* to *target*.

    Creates a temp file in the same directory, writes, then renames.
    """
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        os.write(fd, data)
        os.fsync(fd)
        os.close(fd)
        fd = -1  # Mark as closed
        os.rename(tmp_path, target)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        # Clean up temp file on any failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_text(target: Path, text: str, encoding: str = "utf-8") -> None:
    """Atomically write *text* to *target*."""
    atomic_write_bytes(target, text.encode(encoding))


def atomic_write_via(target: Path, write_fn: Callable[[Path], None]) -> None:
    """Atomically write to *target* using a callback that needs a file path.

    Useful for libraries like Pillow that write to a path rather than bytes:

        atomic_write_via(output, lambda p: img.save(p, "JPEG", quality=85))
    """
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    os.close(fd)  # Let the callback open it
    try:
        write_fn(Path(tmp_path))
        os.rename(tmp_path, target)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
