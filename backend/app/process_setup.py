"""How this server's processes adapt to the platform they run on.

ADR-0131 point 4 allows the server to adapt to where it runs, provided no feature depends on macOS.
Three adaptations live here, each a no-op unless its condition holds:

- **Semaphore names (ADR-0136 point 3).** Inside the macOS App Sandbox, a POSIX semaphore may be
  created only under a name that begins with the app's group identifier and a slash. Every
  `multiprocessing` lock is one (`sem_open`), so without this the analysis and scan pools fail at
  their first `Lock` with `PermissionError: Operation not permitted`. That was measured in
  ADR-0136's spike, and so was the fix: Familiar Server sets `FAMILIAR_SEMAPHORE_PREFIX`, and
  Python builds every semaphore name from `semprefix`. Applied in the parent at import and again
  in every pool worker, because a worker that creates its own lock builds its own name.
- **MIME tables (ADR-0136 point 2).** `mimetypes` reads the system's tables, such as
  `/etc/apache2/mime.types`, the first time anything asks for a type, and the App Sandbox refuses
  that read. Python's `mimetypes.init` does not catch the `PermissionError`, so the first static
  file the server sent, the web admin's own page, answered 500. Found on the first install against a
  real library, 2026-10-01; the integration check never fetched a page, only the API.
- **Workers die with the server.** A `multiprocessing` pool worker waits on its task queue, and it
  holds a write end of that queue itself, so when the server goes it never sees end-of-file. It
  leaves only if the pool sends it a stop message on the way out, which a crash or SIGKILL never
  does, and which on 2026-11-10 a clean SIGTERM did not deliver to the scan pool's idle worker
  either. Those orphans, re-parented to PID 1, held database connections for a day. macOS has no
  `PR_SET_PDEATHSIG`, so `exit_with_parent` polls instead.
- **Background priority (ADR-0138 point 3).** `nice(10)` decides who gets the CPU. On Darwin the
  background QoS clamp (`PRIO_DARWIN_BG`) also moves the work onto efficiency cores and throttles
  its I/O, which is what keeps a laptop cool while it analyses a library.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import sys
import threading
import time

SEMAPHORE_PREFIX_ENV = "FAMILIAR_SEMAPHORE_PREFIX"

# <sys/resource.h>
_PRIO_DARWIN_PROCESS = 4
_PRIO_DARWIN_BG = 0x1000

logger = logging.getLogger(__name__)


def apply_semaphore_prefix() -> str | None:
    """Name this process's semaphores under `FAMILIAR_SEMAPHORE_PREFIX`, if it is set."""
    prefix = os.environ.get(SEMAPHORE_PREFIX_ENV)
    if prefix:
        multiprocessing.current_process()._config["semprefix"] = prefix  # type: ignore[attr-defined]
    return prefix


def init_mimetypes() -> list[str]:
    """Load `mimetypes` from the system tables this process may read, and only those.

    Called once at startup, so the lazy initialisation inside the first `guess_type` never runs and
    never meets a table it is not allowed to open. Returns the tables used.
    """
    import mimetypes

    readable = []
    for path in mimetypes.knownfiles:
        try:
            with open(path, encoding="utf-8"):
                readable.append(path)
        except OSError:
            continue
    # `init(files=…)` on a first call reads `knownfiles` *and* the files given, so the list itself
    # has to be replaced, not supplemented.
    mimetypes.knownfiles = readable
    mimetypes.init()
    return readable


def lower_priority() -> None:
    """Run this process at background priority: `nice(10)`, and on Darwin the background clamp."""
    try:
        os.nice(10)
    except Exception as e:  # noqa: BLE001 - raises on Windows; priority is a courtesy, not a need
        logging.warning(f"Could not set nice priority: {e}")
    if sys.platform == "darwin":
        try:
            import ctypes

            libc = ctypes.CDLL(None, use_errno=True)
            if libc.setpriority(_PRIO_DARWIN_PROCESS, 0, _PRIO_DARWIN_BG) != 0:
                logging.warning(f"Could not apply the background clamp: errno {ctypes.get_errno()}")
        except Exception as e:  # noqa: BLE001
            logging.warning(f"Could not apply the background clamp: {e}")


def darwin_background_clamped() -> bool:
    """Whether this process runs under `PRIO_DARWIN_BG`. Always False off Darwin."""
    if sys.platform != "darwin":
        return False
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    # `getpriority` answers 1 when the clamp is on, not the `PRIO_DARWIN_BG` flag that set it.
    return libc.getpriority(_PRIO_DARWIN_PROCESS, 0) > 0


#: How often a pool worker checks that the server is still its parent.
PARENT_POLL_S = 1.0


def exit_with_parent(poll_s: float = PARENT_POLL_S) -> threading.Thread:
    """End this process soon after its parent is gone, however the parent went.

    A daemon thread compares `os.getppid()` with the parent at start; when the parent dies the
    process is re-parented (to 1, or to a subreaper) and the thread calls `os._exit`. `_exit`, not
    `sys.exit`: the worker may be blocked in a pipe read or a native call, and nothing it holds is
    worth a clean shutdown once the server that asked for the work is gone. An open transaction
    rolls back when PostgreSQL sees the connection close.
    """
    parent = os.getppid()

    def watch() -> None:
        while True:
            time.sleep(poll_s)
            if os.getppid() != parent:
                os._exit(0)

    thread = threading.Thread(target=watch, name="exit-with-parent", daemon=True)
    thread.start()
    return thread


def scan_worker_init() -> None:
    """Initialiser for the library-scan pool: the platform's semaphore names; exit with the server."""
    apply_semaphore_prefix()
    exit_with_parent()


def analysis_worker_init() -> None:
    """Initialiser for the analysis pools: semaphore names, exit with the server, background priority."""
    apply_semaphore_prefix()
    exit_with_parent()
    lower_priority()
    logging.info(f"Analysis worker started at background priority (PID {os.getpid()})")
