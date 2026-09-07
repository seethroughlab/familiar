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
    python -m scripts.backfill_community_cache --declare-pipeline
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


async def backfill(
    *,
    dry_run: bool,
    limit: int | None,
    per_minute: int,
    url: str | None,
    declare_pipeline: bool = False,
    lookup_per_minute: int = 250,
) -> Tally:
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
    # clapback's ADR-0006 exists to prevent. This filter selects rows sharing a
    # *counter* rather than rows sharing a pipeline — which is exactly why
    # `--declare-pipeline` is opt-in, and why it is only defensible for rows at the
    # current counter. See the comment above it.
    stmt = (
        select(TrackAnalysis.acoustid, TrackAnalysis.embedding)
        .where(TrackAnalysis.embedding_version == EMBEDDING_VERSION)
        .where(TrackAnalysis.embedding.is_not(None))
    )
    if limit:
        stmt = stmt.limit(limit)

    # **What `--declare-pipeline` asserts, and on what basis.**
    #
    # Off, this script declares nothing, and that is the right default. Its vectors
    # come out of the database, computed at some earlier time by whatever
    # `clapback-embed` was installed then; the counter is this application's own and
    # has moved for reasons unrelated to the encoder. Declaring the currently
    # installed pipeline over rows like that asserts a provenance nobody verified,
    # which is the exact failure clapback's `ADR-0006` is written to prevent.
    #
    # On, it declares — and the claim is narrower than it looks, because the query
    # below selects only `embedding_version == EMBEDDING_VERSION`. A row at the
    # *current* counter was written by code carrying that counter, which is the code
    # running now, which delegates to the `clapback-embed` installed now. So the
    # inference is "this vector was produced by the pipeline this machine has", and
    # its one weak point is an embedder upgraded between the recompute and this run —
    # nothing records which version wrote a row, so nothing here can check that.
    #
    # It exists because of a real loss. On 2026-09-06 a settings write reset
    # `community_cache_contribute` to false partway through the phase 3 re-analysis;
    # 8,772 tracks were recomputed, marked at the current version, and contributed
    # nothing. They will never be re-embedded — the pipeline only offers a track
    # after computing it — so the alternative to declaring here is bumping
    # `EMBEDDING_VERSION` again and spending another day of CPU re-deriving vectors
    # already measured identical to 5e-16.
    #
    # A flag rather than a default, and never inferred: the assertion should be
    # visible in the command somebody typed, not buried in a script's behaviour.
    declared: str | None = None
    if declare_pipeline:
        from app.services.analysis import embedding_pipeline_version

        declared = embedding_pipeline_version()
        if not declared:
            raise SystemExit(
                "--declare-pipeline needs an installed clapback-embed to read "
                "PIPELINE_VERSION from. Without one there is nothing to declare, and "
                "guessing is the failure ADR-0006 exists to prevent."
            )
        logger.info("declaring pipeline: %s", declared)
    else:
        logger.info("declaring no pipeline (pass --declare-pipeline to change that)")

    tally = Tally()
    # The server allows 30 contributions a minute. Pacing here rather than
    # discovering it as 429s keeps the run boring and the log readable.
    interval = 60.0 / max(per_minute, 1)
    # Every track costs a lookup whether or not it costs a contribution, and the
    # server's lookup allowance is separate from and larger than its contribution
    # allowance. Pacing only the writes leaves ~25,000 reads to go out as fast as the
    # loop can issue them, which earns 429s, and a 429 past its retries is precisely
    # the ambiguity `raise_on_error` above exists to catch. Cheaper not to provoke it.
    lookup_interval = 60.0 / max(lookup_per_minute, 1)
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
            # **`raise_on_error` is what keeps this script's promise.** Its
            # docstring says it never re-sends what is already there, and without
            # this it could not tell "the corpus does not have it" from "the corpus
            # did not answer". A rate-limited lookup returns None after its retries,
            # which would read as absent and contribute a duplicate — incrementing a
            # contributor count and filing a `submission_agreement` row that says one
            # installation independently agreed with itself. Raising instead lands in
            # the per-track handler below, which records an error and moves on.
            existing = await cache.lookup(acoustid, raise_on_error=True)
            await asyncio.sleep(lookup_interval)
            if existing is not None:
                tally.already_present += 1
                continue

            if dry_run:
                tally.contributed += 1
            else:
                ok = await cache.contribute(
                    acoustid, list(embedding), pipeline_version=declared
                )
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
    p.add_argument(
        "--lookup-rate",
        type=int,
        default=250,
        help=(
            "lookups per minute, paced under the server's allowance. Every track "
            "costs one whether or not it is contributed"
        ),
    )
    p.add_argument("--rate", type=int, default=25,
                   help="contributions per minute (server allows 30; default leaves headroom)")
    p.add_argument("--url", help="contribute here instead of community_cache_url — for a host move")
    p.add_argument(
        "--declare-pipeline",
        action="store_true",
        help=(
            "declare clapback_embed.PIPELINE_VERSION on each contribution. Only "
            "honest because this selects rows at the current EMBEDDING_VERSION, "
            "which the installed embedder produced — see the comment in backfill()"
        ),
    )
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    tally = asyncio.run(
        backfill(
            dry_run=args.dry_run,
            limit=args.limit,
            per_minute=args.rate,
            url=args.url,
            declare_pipeline=args.declare_pipeline,
            lookup_per_minute=args.lookup_rate,
        )
    )

    print()
    print("dry run — nothing was sent" if args.dry_run else "backfill complete")
    print(tally.report())
    for e in tally.errors[:10]:
        print(f"  error: {e}")


if __name__ == "__main__":
    main()
