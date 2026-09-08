#!/usr/bin/env python3
"""Fail when the API shape moves without anyone deciding what it means for clients (ADR-0113).

`dump_openapi.py --check` already catches a *stale* `openapi.json`. It cannot catch the thing that
actually breaks a shipped app: the schema and the committed artifact moving together, correctly,
while `API_CONTRACT_VERSION` stays where it was and no client ever learns the shape changed under
it. ADR-0078 records that failure once already — a four-path gap "invisible until a call fails at
runtime against a shape the backend stopped returning."

So this gate does not ask "is the file current?" It asks **"has anyone looked at this change?"**
`contract.lock.json` is the record of the last time somebody did.

Three keys are excluded from the fingerprint:

- ``info.version`` is `get_app_version()` — "dev" locally, "demo" on fly, a git tag on a release
  build. Including it would make the hash depend on which machine ran the script.
- ``info.x-contract-version`` and ``info.x-min-client-contract`` are the numbers this gate exists to
  police. Hashing them would mean bumping the version changed the hash, so a bump would demand
  another bump.

**This is a byte-hash of the rendered schema, not a docstring-stripped structural one.** Stripping
prose would stop a `Field(description=...)` edit tripping the gate, but it is recursive logic that
can bury a real `$ref` rename inside text it discarded. A false alarm costs one `make
contract-lock`; a missed breaking change costs a build in the field. If it starts firing constantly,
revisit — do not quietly weaken it.

Usage:
    python scripts/check_contract_bump.py            # re-lock: record the current shape
    python scripts/check_contract_bump.py --check    # exit 1 if the shape moved unacknowledged
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent.parent
# Both: the app package resolves from the backend root, `dump_openapi` from this directory. There
# is no `scripts/__init__.py`, so it is a plain module import rather than a package one.
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

LOCK_PATH = BACKEND_ROOT / "contract.lock.json"

#: Excluded from the fingerprint. See the module docstring for why each one.
VOLATILE_INFO_KEYS = ("version", "x-contract-version", "x-min-client-contract")


def fingerprint(rendered: str) -> str:
    """A stable hash of the schema's shape, ignoring the keys that legitimately vary."""
    schema: dict[str, Any] = json.loads(rendered)
    info = schema.get("info")
    if isinstance(info, dict):
        for key in VOLATILE_INFO_KEYS:
            info.pop(key, None)
    canonical = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def main() -> int:
    check_only = "--check" in sys.argv

    from dump_openapi import STATIC_DIR, render

    from app.config import API_CONTRACT_VERSION

    if STATIC_DIR.exists():
        print(
            f"Refusing to use {STATIC_DIR}: a built frontend adds SPA routes to the schema.",
            file=sys.stderr,
        )
        return 1

    try:
        current = fingerprint(render())
    except Exception as exc:  # pragma: no cover - import failure is the message
        print(f"Could not build the schema: {exc}", file=sys.stderr)
        return 1

    if check_only:
        if not LOCK_PATH.exists():
            print(f"{LOCK_PATH.name} is missing — run `make contract-lock`.", file=sys.stderr)
            return 1
        locked = json.loads(LOCK_PATH.read_text())
        if locked.get("schema_hash") == current:
            print(f"API shape matches contract version {API_CONTRACT_VERSION}.")
            return 0
        if locked.get("contract_version") != API_CONTRACT_VERSION:
            # The shape moved and the version moved with it. That is the bump working.
            print(
                f"API shape changed and API_CONTRACT_VERSION moved to {API_CONTRACT_VERSION} — "
                "run `make contract-lock` to record it."
            )
            return 1
        print(
            f"The API shape changed, but API_CONTRACT_VERSION is still "
            f"{API_CONTRACT_VERSION}.\n\n"
            "Decide which this is:\n\n"
            "  * Old clients are unaffected (a new endpoint, a new optional field):\n"
            "      make contract-lock\n\n"
            "  * It changes what an already-shipped client can assume (a removed or renamed\n"
            "    field, a narrowed type, a changed status code):\n"
            "      bump API_CONTRACT_VERSION in app/config.py, then make contract-lock\n\n"
            "Raising MIN_CLIENT_CONTRACT is a separate decision with its own rule — see ADR-0113.",
            file=sys.stderr,
        )
        return 1

    LOCK_PATH.write_text(
        json.dumps({"contract_version": API_CONTRACT_VERSION, "schema_hash": current}, indent=2)
        + "\n"
    )
    print(f"Locked contract version {API_CONTRACT_VERSION} at {current[:19]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
