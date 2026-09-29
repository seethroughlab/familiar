#!/usr/bin/env python3
"""Lint: server state is found through `settings.data_dir`, not the working directory (ADR-0132).

Thirteen places once built paths like `Path("data/settings.json")`, which resolve against whatever
directory the process started in. That was right only because the image's WORKDIR is `/app`. A
server started from anywhere else, as a native distribution is, would write its settings into the
wrong directory, or fail inside a sandbox, with nothing to say why.

The rule: outside `app/config.py`, no `Path(...)` under `app/` may take a literal that is `"data"`
or starts with `"data/"`. `app/config.py` is where `data_dir` and the paths derived from it are
defined, so it is the one file allowed to spell them.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"

ALLOWED = {"app/config.py"}
PATH_CALLS = {"Path", "PurePath", "PosixPath"}


def _is_data_literal(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and (node.value in ("data", "data/") or node.value.startswith("data/"))
    )


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def check(source: str, rel: str) -> list[str]:
    """Problems in one module, given its source and its path relative to `backend/`."""
    if rel in ALLOWED:
        return []
    problems: list[str] = []
    for node in ast.walk(ast.parse(source, filename=rel)):
        if (
            isinstance(node, ast.Call)
            and _call_name(node.func) in PATH_CALLS
            and node.args
            and _is_data_literal(node.args[0])
        ):
            literal = node.args[0].value  # type: ignore[attr-defined]
            problems.append(
                f'{rel}:{node.lineno}: Path("{literal}") resolves against the working directory — '
                "use settings.data_dir or a property derived from it in app/config.py"
            )
    return problems


def main() -> int:
    failures: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(APP.parent).as_posix()
        failures.extend(check(path.read_text(), rel))
    if failures:
        print("Working-directory data paths (ADR-0132 point 2):")
        for f in failures:
            print(f"  {f}")
        return 1
    print("Data paths all derive from settings.data_dir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
