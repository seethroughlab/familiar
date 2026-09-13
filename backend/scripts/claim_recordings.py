#!/usr/bin/env python3
"""Tell the corpus which recordings the embeddings we already contributed are.

`ADR-0102` chose the MusicBrainz recording id as the key that lets an
installation ask "what does recording X sound like" without holding X. clapback's
`ADR-0012` built the other side of that, as a *claim* per installation rather than
a column: `POST /v1/recordings/claims`, which attaches an id to a row the corpus
already holds and touches nothing else.

This script sends one claim per track that has both an `acoustid` and a
`musicbrainz_track_id`. It does not compute anything, resolve anything, or
re-send a vector. It is the cheap half of `ADR-0102` point 5 — the ids this
installation already has, which as of 2026-09-13 is 1,791 of 26,518 (6.8%) — and
it is worth running on its own because every one of those turns a hash in
somebody else's similarity results into a title.

The expensive half, resolving the other 93% through AcoustID at three a second,
is still `ADR-0102` point 5 and is not this script.

    python -m scripts.claim_recordings --dry-run
    python -m scripts.claim_recordings --limit 20
    python -m scripts.claim_recordings
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass

sys.path.insert(0, ".")

from sqlalchemy import select  # noqa: E402

from app.db.models import Track, TrackAnalysis  # noqa: E402
from app.db.session import async_session_maker  # noqa: E402
from app.services.app_settings import get_app_settings_service  # noqa: E402
from app.services.community_cache import get_community_cache_service  # noqa: E402

logger = logging.getLogger("claim_recordings")


@dataclass
class Tally:
    considered: int = 0
    claimed: int = 0
    refused: int = 0

    def report(self) -> str:
        return (
            f"considered {self.considered:,} · claimed {self.claimed:,} · "
            f"refused or absent {self.refused:,}"
        )


async def claim(*, dry_run: bool, limit: int | None, per_minute: int, url: str | None) -> Tally:
    settings = get_app_settings_service().get()
    # A claim discloses which recording this installation holds. That is the
    # same consent `community_cache_contribute` asks for, so it is the same gate.
    if not settings.community_cache_contribute and not dry_run:
        raise SystemExit(
            "community_cache_contribute is off. A recording claim tells the corpus which "
            "recordings this installation holds, and this script will not do that against "
            "that setting — turn it on in Admin, or use --dry-run."
        )
    client_id = get_app_settings_service().ensure_community_cache_client_id()
    cache = get_community_cache_service(
        cache_url=url or settings.community_cache_url, client_id=client_id
    )
    logger.info("corpus: %s", cache.cache_url)
    logger.info("installation: %s", client_id)

    stmt = (
        select(TrackAnalysis.acoustid, Track.musicbrainz_track_id)
        .join(Track, Track.id == TrackAnalysis.track_id)
        .where(TrackAnalysis.acoustid.is_not(None))
        .where(Track.musicbrainz_track_id.is_not(None))
    )
    if limit:
        stmt = stmt.limit(limit)

    tally = Tally()
    interval = 60.0 / max(per_minute, 1)
    async with async_session_maker() as session:
        rows = (await session.execute(stmt)).all()

    logger.info("%d tracks carry both a fingerprint and a recording id", len(rows))
    started = time.monotonic()
    try:
        for acoustid, mbid in rows:
            tally.considered += 1
            if dry_run:
                tally.claimed += 1
                continue
            if await cache.claim_recording(acoustid, mbid):
                tally.claimed += 1
            else:
                tally.refused += 1
            await asyncio.sleep(interval)
            if tally.considered % 100 == 0:
                logger.info("%s (%.0fs)", tally.report(), time.monotonic() - started)
    finally:
        await cache.close()
    return tally


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--dry-run", action="store_true", help="count, send nothing")
    p.add_argument("--limit", type=int, default=None, help="stop after this many tracks")
    p.add_argument(
        "--per-minute",
        type=int,
        default=200,
        help="claims per minute, paced under the corpus's contribution allowance",
    )
    p.add_argument("--url", help="claim here instead of community_cache_url")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    tally = asyncio.run(
        claim(dry_run=args.dry_run, limit=args.limit, per_minute=args.per_minute, url=args.url)
    )
    print()
    print("dry run — nothing was sent" if args.dry_run else "claims complete")
    print(tally.report())


if __name__ == "__main__":
    main()
