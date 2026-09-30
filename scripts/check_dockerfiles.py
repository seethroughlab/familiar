#!/usr/bin/env python3
"""Every workspace package the web build reaches is copied into every image that builds it.

Both `docker/Dockerfile` and `deploy/fly/Dockerfile` copy workspace packages by name, one `COPY`
per package in each of two layers (the manifest layer before `pnpm install`, the source layer
before `vite build`). A package that is a dependency of `@familiar/web` and is named in neither
is simply absent from the image, and the build fails with "Rollup failed to resolve import".

That happened twice for `packages/api-client` (ADR-0129): first in `docker/Dockerfile`, caught by
CI a round-trip later; then in `deploy/fly/Dockerfile`, where nothing caught it — the demo deploy
failed on every push to `main` for a day, and `familiar-demo.fly.dev` went on serving the
previous build. Two files that must agree, and no check that they did.

Walks `workspace:` dependencies from `packages/web/package.json`, then checks each Dockerfile
names every package in both layers. Stdlib only; run from anywhere.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILES = ("docker/Dockerfile", "deploy/fly/Dockerfile")
ENTRY = "packages/web"


def workspace_packages() -> dict[str, Path]:
    """Package name to directory, for every `packages/*` member with a manifest."""
    found: dict[str, Path] = {}
    for manifest in (ROOT / "packages").glob("*/package.json"):
        found[json.loads(manifest.read_text())["name"]] = manifest.parent
    return found


def reachable_from(entry: Path, packages: dict[str, Path]) -> list[Path]:
    """The entry and every workspace package it depends on, transitively."""
    by_dir = {path: name for name, path in packages.items()}
    seen: list[Path] = []
    stack = [entry]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.append(current)
        manifest = json.loads((current / "package.json").read_text())
        for section in ("dependencies", "devDependencies"):
            for name, spec in manifest.get(section, {}).items():
                if str(spec).startswith("workspace:") and name in packages:
                    stack.append(packages[name])
    del by_dir
    return sorted(seen)


def missing_from(dockerfile: Path, required: list[Path]) -> list[str]:
    text = dockerfile.read_text()
    problems = []
    for package in required:
        rel = package.relative_to(ROOT).as_posix()
        manifest_layer = re.search(rf"^COPY {re.escape(rel)}/package\.json ", text, re.M)
        source_layer = re.search(rf"^COPY {re.escape(rel)}/ ", text, re.M)
        if not manifest_layer:
            problems.append(f"{rel}/package.json is not copied before `pnpm install`")
        if not source_layer:
            problems.append(f"{rel}/ is not copied before the build")
    return problems


def main() -> int:
    packages = workspace_packages()
    required = reachable_from(ROOT / ENTRY, packages)
    failures = 0
    for name in DOCKERFILES:
        for problem in missing_from(ROOT / name, required):
            print(f"{name}: {problem}")
            failures += 1
    if failures:
        print(f"\n{failures} missing COPY line(s). The web build reaches "
              f"{', '.join(p.relative_to(ROOT).as_posix() for p in required)}; "
              "each must be copied in both layers of both Dockerfiles.")
        return 1
    print(f"Dockerfiles OK: {len(DOCKERFILES)} images copy all {len(required)} workspace packages the web build reaches.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
