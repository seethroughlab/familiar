"""Pool workers exit when the server that started them is gone (2026-11-10).

An idle `multiprocessing` pool worker holds a write end of its own task queue, so it never sees
end-of-file when its parent dies; it leaves only if the pool sends it a stop message. The library
scan pool's worker outlives each sync, and four of them, orphaned to PID 1 by E2E servers that had
been stopped, held test databases open for a day and blocked recreating one. Here the parent is
killed with SIGKILL, which sends nothing at all, and the worker must still go.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent

HARNESS = {
    "scan pool": """
        from app.services.tasks.library_sync import _get_scan_executor
        executor = _get_scan_executor()
    """,
    "analysis pool initialiser": """
        import multiprocessing as mp
        from concurrent.futures import ProcessPoolExecutor
        from app.services.background.executors import _analysis_worker_init
        executor = ProcessPoolExecutor(1, mp_context=mp.get_context("spawn"), initializer=_analysis_worker_init)
    """,
}


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers kill(0) until reaped; only a process that is running counts.
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return bool(state.stdout.strip()) and not state.stdout.strip().startswith("Z")


@pytest.mark.parametrize("pool", list(HARNESS))
def test_an_idle_worker_exits_after_its_parent_is_killed(pool, tmp_path):
    pid_file = tmp_path / "worker.pid"
    script = textwrap.dedent(HARNESS[pool]) + textwrap.dedent(f"""
        import os, signal
        worker = executor.submit(os.getpid).result(timeout=60)
        open({str(pid_file)!r}, "w").write(str(worker))
        os.kill(os.getpid(), signal.SIGKILL)  # no atexit, no shutdown, no stop message
    """)
    # The PID goes through a file, and the harness's output nowhere: a worker that outlives it
    # inherits its stdout, and a pipe here would hold this test open until the worker died.
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND,
        env={**os.environ, "PYTHONPATH": str(BACKEND)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=120,
    )
    assert result.returncode == -9, "the harness did not reach its own SIGKILL"
    worker = int(pid_file.read_text())

    deadline = time.monotonic() + 10
    while _alive(worker) and time.monotonic() < deadline:
        time.sleep(0.2)
    alive = _alive(worker)
    if alive:
        os.kill(worker, 9)  # never leave the orphan this test exists to prevent
    assert not alive, f"worker {worker} outlived its killed parent ({pool})"
