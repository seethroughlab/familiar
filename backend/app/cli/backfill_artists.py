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
from app.db.models import Artist, ArtistAlias, Track, TrackStatus
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


async def _distinct_album_artist_strings(db: AsyncSession) -> list[str]:
    """Return distinct ``Track.album_artist`` strings (Pass 3 alias source)."""
    stmt = (
        select(func.max(Track.album_artist).label("display"))
        .where(
            Track.album_artist.isnot(None),
            Track.album_artist != "",
            Track.status == TrackStatus.ACTIVE,
        )
        .group_by(func.lower(func.trim(Track.album_artist)))
    )
    return [row.display for row in (await db.execute(stmt)).all() if row.display]


async def _set_canonical_artist_ids(db: AsyncSession) -> int:
    """Set ``tracks.canonical_artist_id`` for every track via its alias.

    Two passes:
      1. Bulk SQL UPDATE keyed off ``lower(trim(artist)) =
         alias_normalized`` — fast, covers tags whose normalize form
         is identical to lower-trim (the vast majority).
      2. Python pass for the remainder — tracks whose tag has
         diacritics (Björk, Sigur Rós, Röyksopp, etc.). Their
         ``alias_normalized`` is NFKD-stripped (per
         ``normalize_artist_name``) but the SQL JOIN compares
         lower-trim form. Postgres can't strip combining marks
         without the ``unaccent`` extension, so we resolve these in
         Python — N is small, ~600 on a 23k-track library.
    """
    return await _set_canonical_fk(
        db,
        column_name="canonical_artist_id",
        source_attr="artist",
        source_col="t.artist",
    )


async def _set_canonical_album_artist_ids(db: AsyncSession) -> int:
    """Mirror of ``_set_canonical_artist_ids`` for ``canonical_album_artist_id``.

    Pass 3 introduces this so a track tagged ``artist="John Lennon"
    album_artist="The Beatles"`` surfaces under both canonical artists
    in ``get_artist_detail``.
    """
    return await _set_canonical_fk(
        db,
        column_name="canonical_album_artist_id",
        source_attr="album_artist",
        source_col="t.album_artist",
    )


async def _set_canonical_fk(
    db: AsyncSession,
    *,
    column_name: str,
    source_attr: str,
    source_col: str,
) -> int:
    """Shared two-pass updater for both canonical FK columns."""
    bulk_sql = text(
        f"""
        UPDATE tracks AS t
        SET {column_name} = aa.artist_id
        FROM artist_aliases aa
        WHERE aa.alias_normalized = lower(trim({source_col}))
          AND t.{column_name} IS NULL
          AND {source_col} IS NOT NULL
          AND {source_col} <> ''
        """
    )
    bulk_updated = (await db.execute(bulk_sql)).rowcount or 0  # type: ignore[attr-defined]

    column = getattr(Track, column_name)
    source = getattr(Track, source_attr)
    leftover_q = (
        select(Track.id, source)
        .where(
            column.is_(None),
            source.isnot(None),
            source != "",
            Track.status == TrackStatus.ACTIVE,
        )
    )
    leftover = (await db.execute(leftover_q)).all()
    py_updated = 0
    for track_id, source_value in leftover:
        normalized = normalize_artist_name(source_value)
        if not normalized:
            continue
        alias = await db.get(ArtistAlias, normalized)
        if alias is None:
            continue
        await db.execute(
            text(
                f"UPDATE tracks SET {column_name} = :aid "
                f"WHERE id = :tid AND {column_name} IS NULL"
            ),
            {"aid": alias.artist_id, "tid": track_id},
        )
        py_updated += 1
    return bulk_updated + py_updated


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
        "distinct_album_artists_input": 0,
        "artists_created": 0,
        "aliases_registered": 0,
        "tracks_updated": 0,
        "tracks_album_artist_updated": 0,
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

            # Step 2b: Pass 3 — register album_artist as alias source so
            # compilation/diacritic tracks can be linked back to the right
            # canonical artist via the OR clause in get_artist_detail.
            album_artist_strings = await _distinct_album_artist_strings(db)
            counts["distinct_album_artists_input"] = len(album_artist_strings)
            for tag in album_artist_strings:
                normalized = normalize_artist_name(tag)
                if not normalized:
                    continue
                if await db.get(ArtistAlias, normalized) is not None:
                    continue
                try:
                    await resolve_canonical_artist(
                        db,
                        tag,
                        musicbrainz_artist_id=None,
                        do_mb_lookup=do_mb_lookup,
                        create_if_missing=not dry_run,
                    )
                except Exception as e:
                    logger.warning(
                        f"album_artist resolve failed for tag={tag!r}: {e}"
                    )
                    counts["resolve_failures"] += 1
            if not dry_run:
                await db.commit()

            # Step 3 (Pass 1's ArtistInfo→Artist migration) shipped on
            # the live DB and the table is now dropped (Pass 4). The
            # function and its tests have been retired.

            # Step 4: bulk-set both canonical FK columns on tracks.
            if not dry_run:
                counts["tracks_updated"] = await _set_canonical_artist_ids(db)
                counts["tracks_album_artist_updated"] = (
                    await _set_canonical_album_artist_ids(db)
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
