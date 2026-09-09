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

`MIN_CLIENT_CONTRACT` gets a second, stricter gate. ADR-0113 point 10 states the rule — never raise
the floor until the client build satisfying it is installed everywhere — and states it as prose,
because no mechanism can verify that a build is on a device. What a mechanism *can* do is refuse to
let the floor move as a silent one-line diff. Raising it requires naming the build that satisfies
it, in the lock file, where a reviewer sees it:

    make contract-lock SATISFIED_BY="iOS/macOS build 41"

Not proof. But the failure mode this guards against is nobody noticing, and an unnamed build cannot
pass.

Usage:
    python scripts/check_contract_bump.py            # re-lock: record the current shape
    python scripts/check_contract_bump.py --check    # exit 1 if the shape moved unacknowledged
    python scripts/check_contract_bump.py --satisfied-by "build 41"   # required to raise the floor
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
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


def _satisfied_by(argv: list[str]) -> str | None:
    """The client build a floor raise is justified by, if one was given."""
    if "--satisfied-by" not in argv:
        return None
    index = argv.index("--satisfied-by")
    if index + 1 >= len(argv):
        return None
    return argv[index + 1].strip() or None


def main() -> int:
    check_only = "--check" in sys.argv
    satisfied_by = _satisfied_by(sys.argv)

    from dump_openapi import STATIC_DIR, render

    from app.config import API_CONTRACT_VERSION, MIN_CLIENT_CONTRACT

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

        # The floor is checked before the shape, because it is the one that can break something
        # already installed. A shape change is a build failure; a floor raise is a device that
        # stops working in the field.
        locked_floor = locked.get("min_client_contract")
        if locked_floor != MIN_CLIENT_CONTRACT:
            history = locked.get("client_floor_history") or []
            named = history[-1].get("satisfied_by") if history else None
            print(
                f"MIN_CLIENT_CONTRACT is {MIN_CLIENT_CONTRACT} but the lock records "
                f"{locked_floor}.\n\n"
                "Raising the floor refuses every client below it — including builds already on\n"
                "devices, and whatever is live on the App Store, since merging to main redeploys\n"
                "familiar-demo. ADR-0113 point 10.\n\n"
                "Name the client build that satisfies it:\n"
                '    make contract-lock SATISFIED_BY="iOS/macOS build NN"\n\n'
                f"(the last recorded raise names: {named or 'nothing'})",
                file=sys.stderr,
            )
            return 1

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

    previous = json.loads(LOCK_PATH.read_text()) if LOCK_PATH.exists() else {}
    history = list(previous.get("client_floor_history") or [])
    previous_floor = previous.get("min_client_contract")

    if previous_floor is not None and MIN_CLIENT_CONTRACT > previous_floor:
        if not satisfied_by:
            print(
                f"Refusing to raise the client floor from {previous_floor} to "
                f"{MIN_CLIENT_CONTRACT} without naming what satisfies it.\n\n"
                "This is the one change here that can break an app already on a device, and no\n"
                "check can confirm a build is installed — so the record is the control:\n\n"
                '    make contract-lock SATISFIED_BY="iOS/macOS build NN"\n\n'
                "Confirm against App Store Connect, not just TestFlight: merging to main\n"
                "redeploys familiar-demo, which is the server App Review connects to.",
                file=sys.stderr,
            )
            return 1
        history.append(
            {
                "floor": MIN_CLIENT_CONTRACT,
                "satisfied_by": satisfied_by,
                "date": date.today().isoformat(),
            }
        )
    elif previous_floor is None:
        history = [
            {
                "floor": MIN_CLIENT_CONTRACT,
                "satisfied_by": satisfied_by or "initial floor — refuses nothing",
                "date": date.today().isoformat(),
            }
        ]
    elif MIN_CLIENT_CONTRACT < previous_floor:
        # Lowering is always safe: it admits clients that were refused.
        history.append(
            {
                "floor": MIN_CLIENT_CONTRACT,
                "satisfied_by": satisfied_by or "lowered — admits more clients",
                "date": date.today().isoformat(),
            }
        )

    LOCK_PATH.write_text(
        json.dumps(
            {
                "contract_version": API_CONTRACT_VERSION,
                "min_client_contract": MIN_CLIENT_CONTRACT,
                "schema_hash": current,
                "client_floor_history": history,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        f"Locked contract version {API_CONTRACT_VERSION}, client floor "
        f"{MIN_CLIENT_CONTRACT}, at {current[:19]}…"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
