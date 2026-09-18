#!/usr/bin/env python3
"""Lint: the route, operation and adapter boundaries hold (ADR-0130 point 9).

Three rules, checked over every `import` in `app/` — including the ones inside functions,
which is where a boundary is usually crossed "just this once":

1. `app/operations/` and `app/container.py` know nothing of HTTP: no `fastapi`, no `starlette`,
   nothing from `app.api`, `app.main` or `app.mcp`. An operation is what a route *calls*.
2. `app/services/` does not reach into `app.api.routes` or `app.api.deps`. A service that calls
   a route function is a route wearing a service's name.
3. Nothing under `app/` imports `app.main`. The assembled application is for uvicorn and tests.

`KNOWN` lists the files that break rule 2 today, each with the domain whose migration removes
it. The list ratchets: an entry that no longer violates fails this lint, so it can only shrink.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"

HTTP_FREE = ("app/operations/", "app/container.py")
HTTP_FREE_FORBIDDEN = ("fastapi", "starlette", "app.api", "app.main", "app.mcp")

SERVICES_FORBIDDEN = ("app.api.routes", "app.api.deps")

#: rule 2 violations that exist today, and what removes them.
KNOWN: dict[str, str] = {
    "app/services/llm/handlers/playlists.py": (
        "calls route functions in app.api.routes.playlists and .favorites directly; "
        "moves to operations when the playlists domain migrates"
    ),
}


def imported_names(tree: ast.AST) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append((node.lineno, node.module))
    return out


def _hits(name: str, forbidden: tuple[str, ...]) -> bool:
    return any(name == f or name.startswith(f + ".") for f in forbidden)


def check(source: str, rel: str) -> list[str]:
    """Problems in one module, given its source and its path relative to `backend/`."""
    tree = ast.parse(source, filename=rel)
    problems: list[str] = []
    for lineno, name in imported_names(tree):
        if rel.startswith(HTTP_FREE) and _hits(name, HTTP_FREE_FORBIDDEN):
            problems.append(f"{rel}:{lineno}: imports {name} — operations and the container are HTTP-free")
        if rel.startswith("app/services/") and _hits(name, SERVICES_FORBIDDEN):
            problems.append(f"{rel}:{lineno}: imports {name} — a service does not reach into routes")
        if name == "app.main" or name.startswith("app.main."):
            problems.append(f"{rel}:{lineno}: imports app.main — only uvicorn and tests assemble the app")
    return problems


def main() -> int:
    failures: list[str] = []
    still_needed: set[str] = set()
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(APP.parent).as_posix()
        problems = check(path.read_text(), rel)
        if rel in KNOWN:
            if problems:
                still_needed.add(rel)
            continue
        failures.extend(problems)
    for rel, why in KNOWN.items():
        if rel not in still_needed:
            failures.append(f"{rel}: listed in KNOWN but no longer violates — remove the entry ({why})")
    if failures:
        print("Boundary violations (ADR-0130 point 9):")
        for f in failures:
            print(f"  {f}")
        return 1
    print(f"Boundaries hold ({len(KNOWN)} known exception(s) still needed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
