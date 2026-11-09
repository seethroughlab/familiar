"""Atomic file write utilities.

Writes go to a temporary file in the same directory, then are renamed into
place.  On POSIX systems ``os.rename`` is atomic within the same filesystem,
so readers never see a half-written file.  If anything goes wrong the
temporary file is cleaned up and the original is left untouched.

**A replaced file keeps its owner and mode.** `mkstemp` makes a 0600 file owned by whoever is
writing, so a rewrite used to take the file's ownership with it. In the Docker image the server
runs as `familiar`, but `docker exec` runs as root: `docker exec familiar-api python -m app.token
--create` left `settings.json` root-owned and unreadable to the server, which then ran on default
settings, without the token it had just been given (found by ADR-0171's upgrade drill).
"""

import os
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path


def _keep_ownership(tmp_path: str, target: Path) -> None:
    """Give the replacement the replaced file's mode, and its owner when we may (root).

    A file that does not exist yet takes its directory's owner instead, so root creating
    `settings.json` for the first time does not make it root's either.
    """
    as_root = hasattr(os, "geteuid") and os.geteuid() == 0
    try:
        st = os.stat(target)
    except FileNotFoundError:
        if as_root:
            parent = os.stat(target.parent)
            os.chown(tmp_path, parent.st_uid, parent.st_gid)
        return
    os.chmod(tmp_path, stat.S_IMODE(st.st_mode))
    if as_root:
        os.chown(tmp_path, st.st_uid, st.st_gid)


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
        _keep_ownership(tmp_path, target)
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
        _keep_ownership(tmp_path, target)
        os.rename(tmp_path, target)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
