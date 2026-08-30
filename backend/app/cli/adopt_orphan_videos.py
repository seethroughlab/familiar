"""One-shot backfill: give already-downloaded video files a `track_videos` row.

Run via ``python -m app.cli.adopt_orphan_videos`` (or ``make adopt-videos`` from ``backend/``).
Idempotent — a file that already has a row is skipped, so it is safe to re-run.

Why this exists
---------------
`ADR-0086` moved "does this track have a video" from *a file exists on disk* to *a row exists in
`track_videos`*. It says, in point 2, that where the two disagree **the file on disk wins for
existence** — but it only built half of that: a row whose file is gone is deleted, while a file
with no row is simply invisible. `GET /videos` lists from the table.

The other half was never a hypothetical. The production library had **twelve videos, 136 MB,
downloaded between February and June 2026** by the pre-ADR-0086 feature, every one of them
matching a real track, and none of them visible anywhere in the app. Nobody would have found that
by reading the code: the API answers "no videos", which is exactly what it would say if the
directory were empty.

What it cannot recover, and why that is acceptable
--------------------------------------------------
The old feature named files after the *track* id, not the video, so the YouTube id it came from is
not in the filename and is nowhere else either — the row that would have held it is the row that
does not exist. `source_id` is therefore recorded as ``adopted``, which is honest and searchable:
these rows can be found later if the source id ever matters.

Everything that makes the video *playable* — the path, the size, the track it belongs to — is
recoverable, and playing it is the point. `downloaded_at` comes from the file's mtime, which is
when it really was downloaded.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select

from app.config import settings
from app.db.models import Track, TrackVideo
from app.db.session import async_session_maker
from app.utils.time import to_naive_utc

logger = logging.getLogger(__name__)


async def adopt(dry_run: bool = False) -> tuple[int, int, int]:
    """Return (adopted, already_had_a_row, no_matching_track)."""
    videos_dir = settings.videos_path
    if not videos_dir.exists():
        print(f"No videos directory at {videos_dir} — nothing to do.")
        return (0, 0, 0)

    adopted = existing = unmatched = 0

    async with async_session_maker() as session:
        for path in sorted(videos_dir.glob("*.mp4")):
            try:
                track_id = UUID(path.stem)
            except ValueError:
                # Not named after a track id — not something this backfill can claim.
                print(f"  skip   {path.name}  (filename is not a track id)")
                unmatched += 1
                continue

            track = await session.scalar(select(Track).where(Track.id == track_id))
            if track is None:
                print(f"  skip   {path.name}  (no such track)")
                unmatched += 1
                continue

            already = await session.scalar(
                select(TrackVideo).where(TrackVideo.track_id == track_id)
            )
            if already is not None:
                existing += 1
                continue

            stat = path.stat()
            print(f"  adopt  {track.artist} — {track.title}  ({stat.st_size // 1_000_000} MB)")
            if not dry_run:
                session.add(
                    TrackVideo(
                        id=uuid4(),
                        track_id=track_id,
                        source="youtube",
                        # Not knowable from the file — see the module docstring.
                        source_id="adopted",
                        source_url=None,
                        file_path=str(path),
                        is_audio_only=False,
                        file_size_bytes=stat.st_size,
                        # `downloaded_at` is TIMESTAMP WITHOUT TIME ZONE, so a tz-aware value is
                        # rejected by asyncpg outright — the whole insert fails rather than
                        # silently storing the wrong instant, which is the better failure.
                        downloaded_at=to_naive_utc(datetime.fromtimestamp(stat.st_mtime, tz=UTC)),
                    )
                )
            adopted += 1

        if not dry_run:
            await session.commit()

    return (adopted, existing, unmatched)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    args = parser.parse_args()

    adopted, existing, unmatched = asyncio.run(adopt(dry_run=args.dry_run))
    verb = "would adopt" if args.dry_run else "adopted"
    print(f"\n{verb} {adopted}; {existing} already had a row; {unmatched} unmatched")


if __name__ == "__main__":
    main()
