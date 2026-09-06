#!/usr/bin/env python3
"""Contribute embeddings this installation already computed but never sent.

**Familiar contributes at analysis time and nowhere else.** The only call is in
`analysis_pipeline.py`, inside the branch that runs after computing an embedding
locally, so a track offers itself once and never again. An installation that
re-analysed its library while contribution was off — or that turns it on later —
holds vectors the commons will never see, and no amount of waiting changes that.

That is clapback's `ADR-0001` point 8 in miniature: passive accumulation does not
happen. This is the backfill that closes it.

Two things it is careful about, both of which would corrupt the corpus quietly:

**The fingerprint is hashed as stored, not decoded.** `track_analysis.acoustid`
holds a hex-escaped string (`\\x4151…`) rather than raw bytes, because the
fingerprint crosses a JSON boundary in the chromaprint subprocess. The corpus was
built by hashing that string. Measured against 500 local tracks: hashing the
string matched 232 rows in the corpus, hashing the decoded bytes matched 1. This
script therefore hands the stored value to `hash_fingerprint` untouched, which is
the same path the pipeline takes.

**It never re-sends what is already there.** A repeat POST of an existing vector
increments `contributor_count` and records a `submission_agreement` row — so a
naive re-run would manufacture evidence that one installation independently
agreed with itself, which is exactly the measurement clapback's `ADR-0008` is
built on. Every track is looked up before it is offered.

    python -m scripts.backfill_community_cache --dry-run
    python -m scripts.backfill_community_cache --limit 50
    python -m scripts.backfill_community_cache
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(0, ".")

from sqlalchemy import select  # noqa: E402

from app.config import EMBEDDING_VERSION  # noqa: E402
from app.db.models import TrackAnalysis  # noqa: E402
from app.db.session import async_session_maker  # noqa: E402
from app.services.app_settings import get_app_settings_service  # noqa: E402
from app.services.community_cache import get_community_cache_service  # noqa: E402

logger = logging.getLogger("backfill")


@dataclass
class Tally:
    considered: int = 0
    already_present: int = 0
    contributed: int = 0
    refused: int = 0
    skipped_no_fingerprint: int = 0
    errors: list[str] = field(default_factory=list)

    def report(self) -> str:
        return (
            f"considered {self.considered:,} · already in corpus {self.already_present:,} · "
            f"contributed {self.contributed:,} · refused {self.refused:,} · "
            f"no fingerprint {self.skipped_no_fingerprint:,} · errors {len(self.errors)}"
        )


async def backfill(*, dry_run: bool, limit: int | None, per_minute: int, url: str | None) -> Tally:
    settings = get_app_settings_service().get()
    if not settings.community_cache_contribute and not dry_run:
        raise SystemExit(
            "community_cache_contribute is off. This script will not contribute on your "
            "behalf against that setting — turn it on in Admin, or use --dry-run."
        )

    client_id = get_app_settings_service().ensure_community_cache_client_id()
    # An explicit target, because the commons moving hosts is exactly when a
    # backfill is needed and exactly when `community_cache_url` still points at
    # the old one. Mutating a setting in order to run a migration would leave the
    # installation pointed somewhere nobody chose if the run were interrupted.
    cache = get_community_cache_service(
        cache_url=url or settings.community_cache_url, client_id=client_id
    )
    logger.info("corpus: %s", cache.cache_url)
    logger.info("installation: %s", client_id)
    logger.info("embedding version: %s", EMBEDDING_VERSION)

    # Only the current pipeline. Older vectors are not comparable with what the
    # corpus is being asked to hold, and contributing them would be the mistake
    # clapback's ADR-0006 exists to prevent. Note that this filter is the closest
    # this script can get: it selects rows sharing a counter, not rows sharing a
    # pipeline, which is why the contribution below declares no pipeline at all.
    stmt = (
        select(TrackAnalysis.acoustid, TrackAnalysis.embedding)
        .where(TrackAnalysis.embedding_version == EMBEDDING_VERSION)
        .where(TrackAnalysis.embedding.is_not(None))
    )
    if limit:
        stmt = stmt.limit(limit)

    tally = Tally()
    # The server allows 30 contributions a minute. Pacing here rather than
    # discovering it as 429s keeps the run boring and the log readable.
    interval = 60.0 / max(per_minute, 1)
    started = time.monotonic()

    async with async_session_maker() as session:
        rows = (await session.execute(stmt)).all()

    logger.info("%s tracks at the current embedding version", f"{len(rows):,}")
    for i, (acoustid, embedding) in enumerate(rows, 1):
        tally.considered += 1
        if not acoustid:
            tally.skipped_no_fingerprint += 1
            continue

        try:
            existing = await cache.lookup(acoustid)
            if existing is not None:
                tally.already_present += 1
                continue

            if dry_run:
                tally.contributed += 1
            else:
                # **No `pipeline_version`, deliberately.** These vectors came out
                # of the database, computed at some earlier time by whatever
                # `clapback-embed` was installed then. `embedding_version == 7`
                # narrows that but does not pin it: the counter is this
                # application's own and moved once for a reason unrelated to the
                # encoder. Declaring the currently installed pipeline here would
                # assert, on tens of thousands of rows, a provenance nobody
                # verified — the exact failure clapback's `ADR-0006` is written to
                # prevent, and its point 5 says these rows are recomputed rather
                # than relabelled anyway.
                ok = await cache.contribute(acoustid, list(embedding))
                if ok:
                    tally.contributed += 1
                else:
                    tally.refused += 1
                await asyncio.sleep(interval)
        except Exception as exc:  # noqa: BLE001 - one bad row must not end the run
            tally.errors.append(f"{acoustid[:16]}: {exc}")
            if len(tally.errors) > 50:
                logger.error("more than 50 errors; stopping. last: %s", exc)
                break

        if i % 250 == 0:
            rate = i / max(time.monotonic() - started, 1) * 60
            logger.info("%s/%s · %.0f/min · %s", f"{i:,}", f"{len(rows):,}", rate, tally.report())

    await cache.close()
    return tally


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--dry-run", action="store_true",
                   help="report what would be sent, contact the corpus only to check presence")
    p.add_argument("--limit", type=int, help="stop after this many tracks — for a first run")
    p.add_argument("--rate", type=int, default=25,
                   help="contributions per minute (server allows 30; default leaves headroom)")
    p.add_argument("--url", help="contribute here instead of community_cache_url — for a host move")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    tally = asyncio.run(
        backfill(dry_run=args.dry_run, limit=args.limit, per_minute=args.rate, url=args.url)
    )

    print()
    print("dry run — nothing was sent" if args.dry_run else "backfill complete")
    print(tally.report())
    for e in tally.errors[:10]:
        print(f"  error: {e}")


if __name__ == "__main__":
    main()
