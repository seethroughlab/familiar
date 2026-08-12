"""One-shot backfill: populate ``albums`` + ``album_aliases`` from existing tracks.

ADR-0052. Run via ``python -m app.cli.backfill_albums`` (or ``make backfill-albums``
from ``backend/``). Idempotent — safe to re-run after a partial failure, because every
update is guarded by ``canonical_album_id IS NULL`` and alias insertion is
``ON CONFLICT DO NOTHING``.

Algorithm
---------
1. Distinct ``(canonical album artist id, raw album title)`` pairs over active tracks.
   For each, resolve an ``Album`` and set the FK on every track carrying that exact
   pair.
2. Distinct parent directories of active tracks with **no** album tag. Each becomes one
   folder-keyed album, which replaces the single ``unknown::unknown`` bucket those
   tracks shared.

**Why this does not mirror the artist backfill's two-pass shape.**
``backfill_artists`` does a bulk ``UPDATE ... FROM artist_aliases`` joining on
``lower(trim(artist))``, then a Python pass for the ~600 rows Postgres cannot match
because it has no ``unaccent``. That split is impossible here: the album alias key is
``{artist_uuid}::{normalize_for_matching(title)}``, and ``normalize_for_matching`` does
NFKD decomposition, combining-mark stripping, casefolding and quote/dash folding — none
of which Postgres will do. Rather than reproduce a *partial* version of the rule in SQL
and quietly miss every title with an apostrophe, all key computation happens in Python.

That is not the slow choice it sounds like. Grouping first means roughly 4,300 distinct
pairs rather than 26,000 tracks, so it is ~4,300 resolver calls and ~4,300 bulk updates.

Expected on the production library: a few thousand albums, seconds to a minute. No
network calls — unlike the artist backfill, nothing here talks to MusicBrainz.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.models import Track, TrackStatus
from app.services.album_resolver import resolve_canonical_album

logger = logging.getLogger("backfill_albums")

COMMIT_EVERY = 50


async def _distinct_titled_albums(db: AsyncSession) -> list[tuple[UUID | None, str]]:
    """Every ``(album artist id, raw title)`` pair that needs an album.

    The artist half is ``album_artist`` falling back to ``artist``, matching the
    resolver and the scanner. Grouped on the *raw* title rather than a normalized one:
    two spellings that normalize alike will resolve to the same album through the alias
    table anyway, and each raw spelling needs its own ``UPDATE`` predicate.
    """
    artist_id = func.coalesce(Track.canonical_album_artist_id, Track.canonical_artist_id)
    stmt = (
        select(artist_id.label("artist_id"), Track.album)
        .where(
            Track.album.isnot(None),
            Track.album != "",
            Track.status == TrackStatus.ACTIVE,
        )
        .group_by(artist_id, Track.album)
    )
    return [(row.artist_id, row.album) for row in (await db.execute(stmt)).all()]


async def _distinct_albumless_folders(db: AsyncSession) -> list[str]:
    """Directories holding active tracks with no album tag.

    A representative path per directory is enough — the resolver only reads the parent
    directory from it.
    """
    stmt = text(
        """
        SELECT max(file_path) AS sample
        FROM tracks
        WHERE status = 'active'
          AND (album IS NULL OR trim(album) = '')
        GROUP BY regexp_replace(file_path, '/[^/]*$', '')
        """
    )
    return [row.sample for row in (await db.execute(stmt)).all()]


async def _point_titled_tracks(
    db: AsyncSession, artist_id: UUID | None, title: str, album_id: UUID
) -> int:
    """Set the FK on every active track carrying this exact pair.

    ``IS NULL`` guard so a re-run never repoints a track that is already resolved — the
    same property that makes the artist backfill safe to run twice, and what stops this
    from undoing a future merge.
    """
    if artist_id is None:
        artist_predicate = (
            "coalesce(canonical_album_artist_id, canonical_artist_id) IS NULL"
        )
        params: dict[str, object] = {"aid": album_id, "title": title}
    else:
        artist_predicate = (
            "coalesce(canonical_album_artist_id, canonical_artist_id) = :artist_id"
        )
        params = {"aid": album_id, "title": title, "artist_id": artist_id}

    result = await db.execute(
        text(
            f"""
            UPDATE tracks
            SET canonical_album_id = :aid
            WHERE canonical_album_id IS NULL
              AND status = 'active'
              AND album = :title
              AND {artist_predicate}
            """
        ),
        params,
    )
    return result.rowcount or 0  # type: ignore[attr-defined]


async def _point_albumless_tracks(db: AsyncSession, folder: str, album_id: UUID) -> int:
    """Set the FK on active album-less tracks in one directory."""
    result = await db.execute(
        text(
            """
            UPDATE tracks
            SET canonical_album_id = :aid
            WHERE canonical_album_id IS NULL
              AND status = 'active'
              AND (album IS NULL OR trim(album) = '')
              AND regexp_replace(file_path, '/[^/]*$', '') = :folder
            """
        ),
        {"aid": album_id, "folder": folder},
    )
    return result.rowcount or 0  # type: ignore[attr-defined]


async def run_backfill(*, dry_run: bool, limit: int | None) -> dict[str, int]:
    """Resolve every album and point its tracks at it.

    Opens its own engine — like ``backfill_artists``, this is a CLI and is explicitly
    not supported inside a request handler.
    """
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    stats = {
        "titled_pairs": 0,
        "albums_resolved": 0,
        "tracks_pointed": 0,
        "folders": 0,
        "folder_albums": 0,
        "folder_tracks_pointed": 0,
        "failures": 0,
    }
    started = time.monotonic()

    async with sessionmaker() as db:
        pairs = await _distinct_titled_albums(db)
        if limit is not None:
            pairs = pairs[:limit]
        stats["titled_pairs"] = len(pairs)
        logger.info("%d distinct (album artist, title) pairs", len(pairs))

        for index, (artist_id, title) in enumerate(pairs, start=1):
            try:
                album = await resolve_canonical_album(
                    db,
                    title,
                    album_artist_id=artist_id,
                    create_if_missing=not dry_run,
                )
                if album is None:
                    continue
                stats["albums_resolved"] += 1
                if not dry_run:
                    stats["tracks_pointed"] += await _point_titled_tracks(
                        db, artist_id, title, album.id
                    )
            except Exception as e:
                # One unresolvable title must not cost the whole run. The FK stays NULL
                # and the next run picks it up, exactly as the scanner's policy allows.
                stats["failures"] += 1
                logger.warning("resolve failed for %r: %s", title, e)

            if not dry_run and index % COMMIT_EVERY == 0:
                await db.commit()
                logger.info("  %d/%d pairs", index, len(pairs))

        if not dry_run:
            await db.commit()

        folders = await _distinct_albumless_folders(db)
        if limit is not None:
            folders = folders[:limit]
        stats["folders"] = len(folders)
        logger.info("%d directories holding album-less tracks", len(folders))

        for index, sample_path in enumerate(folders, start=1):
            try:
                album = await resolve_canonical_album(
                    db,
                    None,
                    album_artist_id=None,
                    file_path=sample_path,
                    create_if_missing=not dry_run,
                )
                if album is None:
                    continue
                stats["folder_albums"] += 1
                if not dry_run:
                    folder = sample_path.rsplit("/", 1)[0]
                    stats["folder_tracks_pointed"] += await _point_albumless_tracks(
                        db, folder, album.id
                    )
            except Exception as e:
                stats["failures"] += 1
                logger.warning("folder resolve failed for %r: %s", sample_path, e)

            if not dry_run and index % COMMIT_EVERY == 0:
                await db.commit()

        if not dry_run:
            await db.commit()

    await engine.dispose()
    stats["seconds"] = int(time.monotonic() - started)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill canonical albums (ADR-0052).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be created without writing anything.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Only the first N of each pass.")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    stats = asyncio.run(run_backfill(dry_run=args.dry_run, limit=args.limit))
    logger.info("done in %ss: %s", stats.pop("seconds", 0), stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
