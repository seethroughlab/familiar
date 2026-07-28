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
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

SCHEMA_PATH = BACKEND_ROOT / "openapi.json"
STATIC_DIR = BACKEND_ROOT / "static"


NULL_SCHEMA = {"type": "null"}


def _normalise_nullable(node: Any, required: list[str] | None = None, key: str | None = None) -> Any:
    """Rewrite Pydantic's nullable spelling into the one generators understand.

    Pydantic v2 emits `X | None` as ``anyOf: [{...X}, {"type": "null"}]``. That is valid OpenAPI
    3.1 and semantically identical to ``type: [X, "null"]`` — but swift-openapi-generator rejects a
    bare ``{"type": "null"}`` member and **silently drops the whole property**. Measured before
    this existed: 487 of 1,374 properties, 35% of the schema, including `title`, `artist` and
    `duration_seconds` on the favourites response. A client generated from that is not merely
    incomplete, it looks complete.

    Two shapes, handled differently:

    - a typed member (``{"type": "string", "format": "date-time"}``) collapses into
      ``{"type": ["string", "null"], "format": "date-time"}`` — lossless, and the canonical 3.1
      form;
    - a ``$ref`` member cannot go in a type array, so the reference is hoisted and the property is
      dropped from ``required``. That is faithful rather than lossy: a Swift optional means
      "absent or null", which is exactly what the field permits.
    """
    if isinstance(node, list):
        return [_normalise_nullable(v) for v in node]
    if not isinstance(node, dict):
        return node

    members = node.get("anyOf")
    if isinstance(members, list) and NULL_SCHEMA in members:
        others = [m for m in members if m != NULL_SCHEMA]
        if len(others) == 1:
            other = others[0]
            rest = {k: v for k, v in node.items() if k != "anyOf"}
            if "type" in other:
                node = {**rest, **other, "type": [other["type"], "null"]}
            elif "$ref" in other:
                node = {**rest, **other}
                if required is not None and key is not None and key in required:
                    required.remove(key)

    properties = node.get("properties")
    if isinstance(properties, dict):
        own_required = node.get("required")
        own_required = own_required if isinstance(own_required, list) else None
        node["properties"] = {
            name: _normalise_nullable(value, own_required, name)
            for name, value in properties.items()
        }
        if own_required is not None:
            # An emptied `required` is noise in a generated client; drop the key entirely.
            if own_required:
                node["required"] = own_required
            else:
                node.pop("required", None)
        return node

    return {
        k: (_normalise_nullable(v) if k != "properties" else v)
        for k, v in node.items()
    }


def render() -> str:
    """The schema as it should appear on disk: sorted keys, trailing newline."""
    from app.main import app

    schema = _normalise_nullable(app.openapi())

    # sort_keys because dict ordering is not part of the contract, and an unsorted dump would
    # produce spurious diffs that make the --check gate untrustworthy.
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


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
