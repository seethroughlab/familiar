#!/usr/bin/env python3
"""Run ADR-0115's backfill by hand: one bounded tick, under a person's eye.

The same two phase functions the scheduler calls every ten minutes, with a limit
and a tally, so the first real run can be compared against the probes before the
flag is left on. ``--dry-run`` asks AcoustID and decides, writes nothing and
claims nothing — it is the measurement, not the change.

    python -m scripts.backfill_recording_ids --limit 200 --dry-run
    python -m scripts.backfill_recording_ids --limit 200
    python -m scripts.backfill_recording_ids --phase claim --limit 500

The resolve phase honours `recording_backfill_enabled` and the claim phase
`community_cache_contribute`, exactly as the job does; `--dry-run` runs the
resolve phase regardless of the flag, since it sends fingerprints to AcoustID the
way the identification feature already does and writes nothing back.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

sys.path.insert(0, ".")

from app.services.tasks.recording_backfill import (  # noqa: E402
    run_claim_phase,
    run_resolve_phase,
)


async def _run(phase: str, limit: int, dry_run: bool) -> dict:
    out: dict = {}
    if phase in ("resolve", "both"):
        if dry_run:
            # The job's own gate is the flag; a dry run is a measurement and bypasses it
            # by pretending the flag is on for this process only.
            from app.services.app_settings import get_app_settings_service

            svc = get_app_settings_service()
            original = svc.get
            svc.get = lambda: original().model_copy(update={"recording_backfill_enabled": True})  # type: ignore[method-assign]
        out["resolve"] = await run_resolve_phase(limit=limit, dry_run=dry_run)
    if phase in ("claim", "both"):
        out["claim"] = await run_claim_phase(limit=limit, dry_run=dry_run)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--phase", choices=["resolve", "claim", "both"], default="both")
    p.add_argument("--limit", type=int, default=150, help="tracks per phase")
    p.add_argument("--dry-run", action="store_true", help="decide, write nothing, claim nothing")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    result = asyncio.run(_run(args.phase, args.limit, args.dry_run))
    print()
    print("dry run — nothing was written or sent" if args.dry_run else "tick complete")
    print(json.dumps(result, indent=1, default=str))


if __name__ == "__main__":
    main()
