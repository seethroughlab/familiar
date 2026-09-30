#!/usr/bin/env python3
"""Current-state docs name only things that exist (ADR-0127 point 9).

Scans the documents that describe the present — not the ADRs, which are records — for three kinds
of claim and checks each against the tree:

1. A backticked repository path (`backend/app/main.py`, `packages/frontend/src/api/`) exists.
   Paths are tried as written and under the roots people abbreviate to (`backend/`,
   `packages/frontend/src/`, `packages/web/`), because `app/api/deps.py` is how the backend is
   usually named.
2. `make <target>` resolves in the root or backend Makefile.
3. `pnpm <script>` / `pnpm run <script>` resolves in the root or a workspace `package.json`.

A path that carries a glob, a placeholder or a line number is checked without them. Anything
inside a fenced code block that is *output* (a `$` prompt line or a log) is skipped by fence; the
check is on prose and on commands the reader is told to type.

A `<!-- check-docs: ignore -->` HTML comment on the line before a claim exempts it, for the rare
statement about something that deliberately does not exist.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CURRENT_STATE_DOCS = [
    "README.md",
    "CONTRIBUTING.md",
    "AGENTS.md",
    "docs/START-HERE.md",
    "docs/ARCHITECTURE.md",
    "docs/HEALTH.md",
]

PATH_ROOTS = ["", "backend/", "backend/app/", "backend/app/services/", "backend/app/api/", "packages/frontend/src/", "packages/frontend/", "packages/web/", "packages/", "docker/", "scripts/"]

BACKTICK = re.compile(r"`([^`\n]+)`")
MAKE = re.compile(r"\bmake ([a-z][a-z0-9-]*)")
PNPM = re.compile(r"\bpnpm (?:run )?([a-z][a-z0-9:-]*)")
PNPM_SKIP = {"install", "dev", "add", "exec", "dlx", "-r", "--filter", "test", "build", "lint"}  # pnpm's own verbs / roots handled below


def looks_like_path(token: str) -> bool:
    # Not repository paths: URLs, flags, placeholders, package names, sibling repositories.
    if token.startswith(("http://", "https://", "<", "-", "$", "{", "@", "../", "~")):
        return False
    if re.search(r"[A-Z]{4,}|<[^>]+>", token):  # `YYYYMMDD_slug.py`, `<Artist>/<Album>`
        return False
    if re.search(r'[=" ]', token.strip()) and "/" in token:  # `path="/…"`, an attribute, not a file
        return False
    if " " in token.strip() and not token.strip().startswith(("packages/", "backend/", "docs/", "scripts/")):
        return False
    if "/" not in token and not re.search(r"\.(py|ts|tsx|md|json|yml|yaml|sh|toml|html|css|swift|mjs)$", token):
        return False
    if token.startswith("/") and not token.startswith("/api"):  # an absolute or URL path
        return False
    if token.startswith("/api"):
        return False  # a URL, not a file
    return True


def normalise(token: str) -> str:
    token = token.strip()
    token = re.sub(r":\d+(?:-\d+)?$", "", token)  # `file.py:123`
    token = re.sub(r"\{[^}]*\}", "", token)  # `{id}` placeholders
    return token.rstrip("/")


_basenames: set[str] | None = None


def known_basenames() -> set[str]:
    """Every file name in the tree, for a bare `conftest.py`-style mention. Built once."""
    global _basenames
    if _basenames is None:
        skip = {"node_modules", ".git", ".venv", "dist", "build", "__pycache__", ".pnpm"}
        _basenames = set()
        for path in ROOT.rglob("*"):
            if any(part in skip for part in path.parts):
                continue
            _basenames.add(path.name)
    return _basenames


def path_exists(token: str) -> bool:
    if "*" in token:
        # A glob: `test_contract_*.py` — something must match it, at a root or anywhere below one.
        for root in PATH_ROOTS:
            base = ROOT / root
            if base.exists() and (list(base.glob(token)) or list(base.glob(f"**/{token}"))):
                return True
        return False
    for root in PATH_ROOTS:
        if (ROOT / root / token).exists():
            return True
    if "/" not in token:
        return token in known_basenames()
    return False


def make_targets() -> set[str]:
    targets: set[str] = set()
    for mf in (ROOT / "Makefile", ROOT / "backend" / "Makefile"):
        if mf.exists():
            targets |= set(re.findall(r"^([a-z][a-z0-9-]*):", mf.read_text(), re.M))
    return targets


def pnpm_scripts() -> set[str]:
    scripts: set[str] = set()
    for pkg in [ROOT / "package.json", *ROOT.glob("packages/*/package.json"), *ROOT.glob("packages/visualizers/*/package.json")]:
        try:
            scripts |= set(json.loads(pkg.read_text()).get("scripts", {}).keys())
        except (OSError, ValueError):
            pass
    return scripts


def strip_output_fences(text: str) -> str:
    """Drop fenced blocks that are output rather than instructions (their first line starts with `$`
    output or a log shape); keep bash fences, whose commands the reader is told to type."""
    out: list[str] = []
    in_fence = False
    keep = True
    for line in text.split("\n"):
        if line.startswith("```"):
            if not in_fence:
                in_fence = True
                lang = line[3:].strip()
                keep = lang in ("", "bash", "sh", "shell", "zsh", "console", "make")
            else:
                in_fence = False
                was_kept, keep = keep, True
                if was_kept:
                    out.append("```")
                continue
            if keep:
                out.append("```")  # the marker stays, so `check()` knows it is inside a command fence
            continue
        if in_fence and not keep:
            continue
        out.append(line)
    return "\n".join(out)


def check(doc: Path, targets: set[str], scripts: set[str]) -> list[str]:
    problems: list[str] = []
    text = strip_output_fences(doc.read_text())
    lines = text.split("\n")
    in_fence = False
    for i, line in enumerate(lines, 1):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if i >= 2 and "check-docs: ignore" in lines[i - 2]:
            continue
        # Commands count only where the reader is told to type them: in backticks or a fence.
        command_text = [m.group(1) for m in BACKTICK.finditer(line)] + ([line] if in_fence else [])
        for raw in (m.group(1) for m in BACKTICK.finditer(line)):
            if not looks_like_path(raw):
                continue
            token = normalise(raw)
            if not token or not path_exists(token):
                problems.append(f"{doc.relative_to(ROOT)}:{i}: `{raw}` does not exist")
        for chunk in command_text:
            for m in MAKE.finditer(chunk):
                if m.group(1) not in targets:
                    problems.append(f"{doc.relative_to(ROOT)}:{i}: `make {m.group(1)}` is not a target")
            for m in PNPM.finditer(chunk):
                name = m.group(1)
                if name in PNPM_SKIP or name.startswith("-"):
                    continue
                if name not in scripts:
                    problems.append(f"{doc.relative_to(ROOT)}:{i}: `pnpm {name}` is not a script")
    return problems


def main() -> int:
    targets, scripts = make_targets(), pnpm_scripts()
    problems: list[str] = []
    for rel in CURRENT_STATE_DOCS:
        doc = ROOT / rel
        if not doc.exists():
            problems.append(f"{rel}: listed as a current-state document but missing")
            continue
        problems.extend(check(doc, targets, scripts))
    if problems:
        print("Current-state docs name things that do not exist (ADR-0127 point 9):")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"Docs check OK: {len(CURRENT_STATE_DOCS)} documents, every path, make target and pnpm script resolves.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
