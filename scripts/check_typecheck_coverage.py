#!/usr/bin/env python3
"""Every workspace package with TypeScript in it is type-checked (ADR-0170 points 1 and 5).

`pnpm -r typecheck` runs the script in every package that has one and silently skips every package
that does not, which is how `@familiar/frontend` went unchecked while a green build implied
otherwise: Vite strips types without looking at them. This makes the skip loud.

A package passes when it has a `typecheck` script, or declares in its package.json that it has no
TypeScript source — `"familiar": {"noTypeScript": "<why>"}` — and really has none.

Reads `pnpm-workspace.yaml` for the package globs, so a new workspace folder is covered without
editing this file.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"node_modules", "dist", "build", "generated", "test-results", "playwright-report"}


def workspace_globs() -> list[str]:
    text = (ROOT / "pnpm-workspace.yaml").read_text()
    section = text.split("packages:", 1)[1]
    globs = []
    for line in section.splitlines():
        if line and not line.startswith((" ", "\t", "#")):
            break  # the next top-level key
        match = re.match(r"\s*-\s*['\"]?([^'\"#\s]+)", line)
        if match:
            globs.append(match.group(1))
    return globs


def has_typescript(package: Path, nested: set[Path]) -> bool:
    for path in package.rglob("*"):
        parts = set(path.relative_to(package).parts)
        if parts & SKIP_DIRS:
            continue
        # A nested workspace package answers for its own files.
        if any(path.is_relative_to(other) for other in nested if other != package):
            continue
        if path.suffix in {".ts", ".tsx", ".mts", ".cts"} and not path.name.endswith(".d.ts"):
            return True
    return False


def main() -> int:
    packages = sorted(
        {p.parent for pattern in workspace_globs() for p in ROOT.glob(f"{pattern}/package.json")}
    )
    if not packages:
        print("check_typecheck_coverage: no workspace packages found; pnpm-workspace.yaml unread?")
        return 1
    nested = set(packages)
    failures = []
    for package in packages:
        manifest = json.loads((package / "package.json").read_text())
        name = manifest.get("name", package.relative_to(ROOT).as_posix())
        has_script = "typecheck" in manifest.get("scripts", {})
        declared = (manifest.get("familiar") or {}).get("noTypeScript")
        typed = has_typescript(package, nested)
        if has_script:
            status = "typecheck"
        elif declared and not typed:
            status = f"no TypeScript ({declared})"
        elif declared and typed:
            failures.append(f"{name} declares noTypeScript but contains TypeScript")
            continue
        else:
            failures.append(
                f"{name} has no `typecheck` script"
                + (" and contains TypeScript" if typed else "; add one, or declare familiar.noTypeScript")
            )
            continue
        print(f"  ok  {name}: {status}")
    for failure in failures:
        print(f"FAIL  {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
