#!/usr/bin/env python3
"""Write the OpenAPI schema to a file, for cross-repo client generation (ADR-0007 phase 2).

`familiar-apple` generates its Swift client from this schema, and it cannot obtain it the way
`lint_openapi.py` does — that imports the FastAPI app in-process, which needs the Python
toolchain and this repository. A committed artifact is the only thing a separate repo with a
different toolchain can consume.

Two properties make committing it safe, and both had to be established first:

**Determinism.** Two modules once declared `ImportPreviewResponse`, and which one FastAPI fully
qualified varied between runs — so the file would have churned on every regeneration and a
generated client would have had a type renamed under it. Fixed in phase 1.6 by renaming one.

**A defined environment.** A built frontend adds SPA catch-all routes and changes the schema, which
is why CI lints on a bare checkout (see the note above the lint step in `.github/workflows/ci.yml`).
This script therefore refuses to write if `backend/static/` exists, rather than silently producing
a schema with routes no client should see.

Usage:
    python scripts/dump_openapi.py            # write backend/openapi.json
    python scripts/dump_openapi.py --check    # exit 1 if the file is stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

SCHEMA_PATH = BACKEND_ROOT / "openapi.json"
STATIC_DIR = BACKEND_ROOT / "static"


def render() -> str:
    """The schema as it should appear on disk: sorted keys, trailing newline."""
    from app.main import app

    # sort_keys because dict ordering is not part of the contract, and an unsorted dump would
    # produce spurious diffs that make the --check gate untrustworthy.
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    check_only = "--check" in sys.argv

    if STATIC_DIR.exists():
        print(
            f"Refusing to use {STATIC_DIR}: a built frontend adds SPA routes to the schema.\n"
            "Remove backend/static/ (or run from a bare checkout) and try again.",
            file=sys.stderr,
        )
        return 1

    try:
        current = render()
    except Exception as exc:  # pragma: no cover - import failure is the message
        print(f"Could not build the schema: {exc}", file=sys.stderr)
        return 1

    if check_only:
        if not SCHEMA_PATH.exists():
            print(f"{SCHEMA_PATH.name} is missing — run `make openapi`.", file=sys.stderr)
            return 1
        if SCHEMA_PATH.read_text() != current:
            print(
                f"{SCHEMA_PATH.name} is stale — the API changed without regenerating it.\n"
                "Run `make openapi` and commit the result. Clients generate from this file, "
                "so a stale one means a client built against an API that no longer exists.",
                file=sys.stderr,
            )
            return 1
        print(f"{SCHEMA_PATH.name} is up to date.")
        return 0

    SCHEMA_PATH.write_text(current)
    print(f"Wrote {SCHEMA_PATH.relative_to(BACKEND_ROOT.parent)} ({len(current):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
