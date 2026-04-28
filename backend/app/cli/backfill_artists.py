"""One-shot backfill: populate ``artists`` + ``artist_aliases`` from existing tracks.

Run via ``python -m app.cli.backfill_artists`` (or ``make backfill-artists``
from ``backend/``). Idempotent — safe to re-run after a partial failure.

Algorithm
---------
1. Pull distinct ``(lower(trim(artist)), max(musicbrainz_artist_id))``
   pairs from ``tracks`` where the row is active and artist is not null.
2. For each pair, call ``resolve_canonical_artist`` with
   ``do_mb_lookup`` controlled by ``--no-mb``. The resolver merges by
   MBID where possible and registers an alias.
3. Migrate ``artist_info`` rows: for every alias whose normalized form
   matches an ``artist_info.artist_name_normalized``, copy the cached
   ``image_url``, bio, similar-artists, etc. onto the matched
   ``Artist``.
4. ``UPDATE tracks SET canonical_artist_id = aa.artist_id FROM
   artist_aliases aa WHERE aa.alias_normalized = lower(trim(t.artist))
   AND t.canonical_artist_id IS NULL`` — set the FK on every active
   track in one shot.

Pass 1 stops here; Pass 2 cuts over the read endpoints.

Expected runtime on the production library (~3.5k distinct artists,
~1.5k without tag-side MBIDs): ~25–45 minutes when ``do_mb_lookup``
is on. With ``--no-mb`` the backfill is purely local (seconds).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.models import Artist, ArtistAlias, ArtistInfo, Track, TrackStatus
from app.services.artist_resolver import resolve_canonical_artist
from app.services.external_albums_helpers import normalize_artist_name

logger = logging.getLogger("backfill_artists")


async def _distinct_artist_strings(
    db: AsyncSession,
) -> list[tuple[str, str | None]]:
    """Return list of ``(tag_string, max_mbid)`` for every distinct active artist."""
    stmt = (
        select(
            func.max(Track.artist).label("display"),
            func.max(Track.musicbrainz_artist_id).label("mbid"),
        )
        .where(
            Track.artist.isnot(None),
            Track.artist != "",
            Track.status == TrackStatus.ACTIVE,
        )
        .group_by(func.lower(func.trim(Track.artist)))
    )
    rows = (await db.execute(stmt)).all()
    return [(row.display, row.mbid) for row in rows]


async def _migrate_artist_info(db: AsyncSession) -> tuple[int, int]:
    """Copy cached fields from ``artist_info`` onto matching ``Artist`` rows.

    Returns ``(matched, skipped)``. A row is matched when its normalized
    name exists in ``artist_aliases``; skipped rows have no canonical
    artist yet (e.g. the artist_info row was created for an alias that
    never appeared as a track tag).
    """
    matched = 0
    skipped = 0
    info_rows = (await db.execute(select(ArtistInfo))).scalars().all()
    for info in info_rows:
        alias = await db.get(ArtistAlias, info.artist_name_normalized)
        if alias is None:
            skipped += 1
            continue
        artist = await db.get(Artist, alias.artist_id)
        if artist is None:
            skipped += 1
            continue

        # Image + Last.fm fields were null on Artist until now; copy
        # them straight across. Don't copy musicbrainz_id from
        # artist_info — the resolver already attached the authoritative
        # MBID via strict-match MB lookup, and Last.fm's stored MBID can
        # collide across name variants (e.g. Kahimi Karie carries the
        # same MBID under both Japanese and English info rows, but each
        # resolves to its own canonical Artist row).
        artist.image_url = info.image_url
        artist.image_checked_at = info.image_checked_at
        artist.bio_summary = info.bio_summary
        artist.bio_content = info.bio_content
        artist.lastfm_url = info.lastfm_url
        artist.listeners = info.listeners
        artist.playcount = info.playcount
        if info.similar_artists:
            artist.similar_artists = info.similar_artists
        if info.tags:
            artist.tags = info.tags
        artist.fetched_at = info.fetched_at
        artist.fetch_error = info.fetch_error
        matched += 1
    await db.flush()
    return matched, skipped


async def _set_canonical_artist_ids(db: AsyncSession) -> int:
    """Bulk-update ``tracks.canonical_artist_id`` from ``artist_aliases``."""
    stmt = text(
        """
        UPDATE tracks AS t
        SET canonical_artist_id = aa.artist_id
        FROM artist_aliases aa
        WHERE aa.alias_normalized = lower(trim(t.artist))
          AND t.canonical_artist_id IS NULL
          AND t.artist IS NOT NULL
        """
    )
    result = await db.execute(stmt)
    return result.rowcount or 0  # type: ignore[attr-defined]


async def run_backfill(
    *,
    dry_run: bool,
    do_mb_lookup: bool,
    limit: int | None,
) -> dict[str, int]:
    """Execute the backfill. Returns counts for the summary print.

    Opens its own engine + session — running it in-process inside a
    request handler is unsupported.
    """
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    counts = {
        "distinct_artists_input": 0,
        "artists_created": 0,
        "aliases_registered": 0,
        "info_rows_migrated": 0,
        "info_rows_skipped": 0,
        "tracks_updated": 0,
        "mb_lookups": 0,
        "resolve_failures": 0,
    }

    try:
        async with session_maker() as db:
            # Step 1: distinct (tag, mbid) pairs from tracks.
            pairs = await _distinct_artist_strings(db)
            if limit is not None:
                pairs = pairs[:limit]
            counts["distinct_artists_input"] = len(pairs)
            logger.info(
                f"Found {len(pairs)} distinct artist tag strings to resolve"
            )

            artists_before = await db.scalar(
                select(func.count()).select_from(Artist)
            )
            aliases_before = await db.scalar(
                select(func.count()).select_from(ArtistAlias)
            )

            # Step 2: resolve each tag → canonical Artist.
            t0 = time.time()
            for i, (tag, mbid) in enumerate(pairs, start=1):
                # Pre-check: alias already registered? If so, no MB call
                # needed, no work to do.
                normalized = normalize_artist_name(tag)
                if not normalized:
                    continue
                existing_alias = await db.get(ArtistAlias, normalized)

                will_call_mb = (
                    do_mb_lookup
                    and existing_alias is None
                    and not mbid
                )
                if will_call_mb:
                    counts["mb_lookups"] += 1

                try:
                    artist = await resolve_canonical_artist(
                        db,
                        tag,
                        musicbrainz_artist_id=mbid,
                        do_mb_lookup=do_mb_lookup,
                        create_if_missing=not dry_run,
                    )
                    if artist is None and not dry_run:
                        counts["resolve_failures"] += 1
                except Exception as e:
                    logger.warning(
                        f"resolve failed for tag={tag!r} mbid={mbid!r}: {e}"
                    )
                    counts["resolve_failures"] += 1
                    continue

                if i % 50 == 0:
                    elapsed = time.time() - t0
                    rate = i / max(elapsed, 0.001)
                    logger.info(
                        f"  resolved {i}/{len(pairs)} "
                        f"({rate:.1f}/s, mb_lookups={counts['mb_lookups']})"
                    )
                    if not dry_run:
                        await db.commit()

            if not dry_run:
                await db.commit()

            artists_after = await db.scalar(
                select(func.count()).select_from(Artist)
            )
            aliases_after = await db.scalar(
                select(func.count()).select_from(ArtistAlias)
            )
            counts["artists_created"] = (artists_after or 0) - (
                artists_before or 0
            )
            counts["aliases_registered"] = (aliases_after or 0) - (
                aliases_before or 0
            )

            # Step 3: migrate ArtistInfo rows.
            if not dry_run:
                matched, skipped = await _migrate_artist_info(db)
                counts["info_rows_migrated"] = matched
                counts["info_rows_skipped"] = skipped
                await db.commit()

            # Step 4: bulk-set canonical_artist_id on tracks.
            if not dry_run:
                counts["tracks_updated"] = await _set_canonical_artist_ids(
                    db
                )
                await db.commit()
    finally:
        await engine.dispose()

    return counts


def _print_summary(counts: dict[str, int], dry_run: bool) -> None:
    label = "DRY RUN" if dry_run else "DONE"
    print(f"\n=== Artist backfill {label} ===")
    for k, v in counts.items():
        print(f"  {k:30s} {v:>8d}")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="backfill_artists",
        description=(
            "Populate the canonical artists data model from existing "
            "tracks. Pass 1 of the canonical-artists migration."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect what would change but write nothing.",
    )
    parser.add_argument(
        "--no-mb",
        action="store_true",
        help=(
            "Skip the strict-MB lookup step. Fast (no rate limit) but "
            "leaves unknown-MBID tags as their own canonical artist."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N distinct tag strings (smoke test).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    counts = asyncio.run(
        run_backfill(
            dry_run=args.dry_run,
            do_mb_lookup=not args.no_mb,
            limit=args.limit,
        )
    )
    _print_summary(counts, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
