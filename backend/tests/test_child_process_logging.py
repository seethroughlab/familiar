"""What a spawned child process writes to the log can be measured and believed.

Found 2026-10-02 reading Familiar Server's log: an analysis worker's lines carried no time, so a
track's minutes could not be divided into its steps, and `[MEMORY]` reported each worker at about
1.2 TB, because macOS gives `ru_maxrss` in bytes where Linux gives kilobytes.
"""

from __future__ import annotations

import logging
import re
import resource
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.logging_config import CHILD_LOG_FORMAT
from app.services.tasks import common

APP = Path(__file__).parent.parent / "app"


def test_every_child_entry_point_logs_when_and_which_process() -> None:
    """A bare `%(message)s` anywhere in the app is a child whose steps cannot be timed."""
    bare = [
        f"{path.relative_to(APP.parent)}:{n}"
        for path in APP.rglob("*.py")
        if "cli" not in path.parts
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if re.search(r"""format=["']%\(message\)s["']""", line)
    ]
    assert not bare, f"child processes logging without a time: {bare}"


def test_the_child_format_carries_time_and_pid() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "Extracting features", None, None)
    line = logging.Formatter(CHILD_LOG_FORMAT).format(record)
    assert re.match(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} INFO \[pid \d+\] Extracting features$", line
    )


@pytest.mark.parametrize(
    ("platform", "ru_maxrss"),
    [("darwin", 1_250_016 * 1024), ("linux", 1_250_016)],
    ids=["macOS gives bytes", "Linux gives kilobytes"],
)
def test_peak_memory_is_megabytes_on_both(monkeypatch, platform: str, ru_maxrss: int) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(resource, "getrusage", lambda _who: SimpleNamespace(ru_maxrss=ru_maxrss))
    assert common.get_memory_mb() == pytest.approx(1_250_016 / 1024)
