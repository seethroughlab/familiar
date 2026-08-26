"""Move existing artwork from tag-hash filenames onto album ids (ADR-0052).

    uv run python scripts/migrate_artwork_keys.py --dry-run     # plan only, writes nothing
    uv run python scripts/migrate_artwork_keys.py               # do it

Run it **inside the container**: in production ``art_path`` is ``/data/art`` in the
named Docker volume ``art_data``, with no host bind mount.

    docker exec -w /app -e PYTHONPATH=/app familiar-api \\
        python scripts/migrate_artwork_keys.py --dry-run

## What makes this awkward

**Nothing in the database records an artwork key.** It has always been recomputed from
``(track.artist, track.album)`` on demand, so a filename is the only trace of what an
image belongs to, and the only way back is to recompute the old hash for every distinct
pair in the library and see which files that accounts for. Whatever is left over cannot
be attributed to anything.

**A hand-uploaded cover is indistinguishable from a fetched one.** The only provenance
bit on disk is the *absence* of a ``.generated`` marker, and ``/artwork/regenerate``
relies on exactly that to refuse overwriting real art. So the presence or absence of
that marker is preserved byte-for-byte through the move, and "no marker" is treated as
"possibly somebody's own cover, never destroy it".

## Rules

1. **Nothing is deleted.** Losers and orphans move to ``<art_path>/quarantine/``. 283 MB
   is not worth being clever with, and an orphan may be a cover somebody chose for an
   album they have since renamed.
2. **Collisions are expected, not exceptional.** Re-keying is a *merge*: 284 new keys
   receive more than one old key, 2,274 old keys collide, and one album absorbs 49.
   Precedence: real art beats generated art; between two real ones the larger file wins,
   on the theory that it is the higher resolution. The loser is quarantined.
3. **Idempotent.** A file already sitting at its destination is left alone, so a partial
   run can simply be repeated.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("migrate_artwork_keys")

SIZES = ("full", "thumb")


def _paths_for(art_path: Path, key: str) -> dict[str, Path]:
    """The three files an album can have on disk.

    ``full`` carries no suffix, so a ``f"{key}*"`` glob would also match the thumb and
    the marker. Enumerated explicitly for that reason — fine when moving, dangerous when
    deleting, and this script does both.
    """
    return {
        "full": art_path / f"{key}.jpg",
        "thumb": art_path / f"{key}_thumb.jpg",
        "generated": art_path / f"{key}.generated",
    }


def _weight(art_path: Path, key: str) -> tuple[int, int]:
    """How strong a claim this key's art has, for resolving a merge.

    ``(is_real, bytes)`` — real art outranks generated art outright, and among equals the
    larger file wins as a proxy for resolution. Both halves are read from disk rather
    than the database, because the database has never known anything about these files.
    """
    files = _paths_for(art_path, key)
    is_real = 0 if files["generated"].exists() else 1
    size = files["full"].stat().st_size if files["full"].exists() else 0
    return (is_real, size)


async def _old_key_to_album_id() -> tuple[dict[str, str], dict[str, str]]:
    """Recompute every legacy hash and map it to the album its tracks now belong to.

    Returns ``(hash -> album_id, hash -> label)``; the label is only for the report.

    Grouped on the same ``(artist, album)`` pair ``compute_album_hash`` took, which is
    what makes the recomputed hash match what is actually on disk. Tracks whose
    ``canonical_album_id`` is still NULL are skipped — the backfill has to run first, and
    ``--dry-run`` says so loudly when it finds none.
    """
    from sqlalchemy import Text, cast, func, select

    from app.db.models import Track, TrackStatus
    from app.db.session import async_session_maker
    from app.services.artwork import compute_album_hash

    mapping: dict[str, str] = {}
    labels: dict[str, str] = {}

    async with async_session_maker() as db:
        stmt = (
            select(
                Track.artist,
                Track.album,
                func.max(cast(Track.canonical_album_id, Text)).label("album_id"),
            )
            .where(Track.status == TrackStatus.ACTIVE)
            .group_by(Track.artist, Track.album)
        )
        for artist, album, album_id in (await db.execute(stmt)).all():
            if not album_id:
                continue
            old = compute_album_hash(artist, album)
            mapping[old] = album_id
            labels[old] = f"{artist or '?'} — {album or '?'}"

    return mapping, labels


def _plan(
    art_path: Path, mapping: dict[str, str]
) -> tuple[dict[str, list[str]], list[str]]:
    """Group the keys present on disk by where they are going.

    Returns ``(album_id -> [old keys], orphan keys)``. A key counts as present if it has
    any of its three files; ``.tmp`` siblings left by ``atomic_write_via`` are ignored.
    """
    present: set[str] = set()
    for entry in art_path.iterdir():
        if not entry.is_file() or entry.name.endswith(".tmp"):
            continue
        name = entry.name
        for suffix in ("_thumb.jpg", ".generated", ".jpg"):
            if name.endswith(suffix):
                present.add(name[: -len(suffix)])
                break

    by_album: dict[str, list[str]] = defaultdict(list)
    orphans: list[str] = []
    for key in sorted(present):
        album_id = mapping.get(key)
        if album_id is None:
            orphans.append(key)
        else:
            by_album[album_id].append(key)
    return by_album, orphans


def _move(src: Path, dst: Path, *, dry_run: bool) -> None:
    if not src.exists() or src == dst:
        return
    if dst.exists():
        # Idempotence: a previous run already placed this one.
        return
    logger.debug("  %s -> %s", src.name, dst.name)
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))


def _quarantine(art_path: Path, key: str, *, reason: str, dry_run: bool) -> None:
    target = art_path / "quarantine" / reason
    for path in _paths_for(art_path, key).values():
        _move(path, target / path.name, dry_run=dry_run)


async def run(*, dry_run: bool) -> dict[str, int]:
    from app.config import settings

    art_path = Path(settings.art_path)
    if not art_path.exists():
        logger.error("art_path does not exist: %s", art_path)
        return {}

    mapping, labels = await _old_key_to_album_id()
    if not mapping:
        logger.error(
            "No track has a canonical_album_id — run `make backfill-albums` first, "
            "otherwise this would quarantine the entire artwork directory."
        )
        return {}

    by_album, orphans = _plan(art_path, mapping)

    stats = {
        "albums": len(by_album),
        "keys_on_disk": sum(len(v) for v in by_album.values()) + len(orphans),
        "moved": 0,
        "collisions": 0,
        "quarantined_losers": 0,
        "orphans": len(orphans),
        "already_done": 0,
    }

    for album_id, keys in sorted(by_album.items()):
        if album_id in keys:
            stats["already_done"] += 1

        winner = max(keys, key=lambda k: _weight(art_path, k))
        losers = [k for k in keys if k != winner]

        if losers:
            stats["collisions"] += 1
            logger.info(
                "merge -> %s: %d keys, keeping %s (%s)",
                album_id,
                len(keys),
                winner,
                labels.get(winner, "?"),
            )
            for loser in losers:
                logger.info("    quarantining %s (%s)", loser, labels.get(loser, "?"))
                _quarantine(art_path, loser, reason="merged", dry_run=dry_run)
                stats["quarantined_losers"] += 1

        src = _paths_for(art_path, winner)
        dst = _paths_for(art_path, album_id)
        for kind in ("full", "thumb", "generated"):
            # The marker moves with its images, presence and absence both. It is the only
            # signal that art was fetched rather than hand-uploaded, and `/artwork/
            # regenerate` refuses to overwrite art that has no marker.
            _move(src[kind], dst[kind], dry_run=dry_run)
        stats["moved"] += 1

    for key in orphans:
        _quarantine(art_path, key, reason="orphan", dry_run=dry_run)

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-key artwork onto album ids (ADR-0052).")
    parser.add_argument("--dry-run", action="store_true", help="Plan only; write nothing.")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(message)s",
    )

    stats = asyncio.run(run(dry_run=args.dry_run))
    if not stats:
        return 1

    logger.info("")
    logger.info("%s", "PLAN (nothing written)" if args.dry_run else "DONE")
    for label, value in stats.items():
        logger.info("  %-20s %d", label, value)
    if args.dry_run:
        logger.info("")
        logger.info("Re-run without --dry-run to apply. Nothing is ever deleted:")
        logger.info("  losers and orphans move to %s", "art_path/quarantine/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
