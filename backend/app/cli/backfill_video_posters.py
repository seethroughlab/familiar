"""One-shot backfill: give already-downloaded videos the poster frame a fresh download keeps.

Run via ``python -m app.cli.backfill_video_posters`` (or ``make backfill-video-posters`` from
``backend/``). Idempotent — a video that already has a poster is skipped unless ``--force``.

Why this exists
---------------
Since familiar#305 a download saves the source's poster beside the video as ``{track_id}.jpg``,
and the Videos grid draws it. Every video downloaded before that has none, and the grid shows the
album cover in its place — correct, but it makes the shelf look like a record shelf rather than a
video one until each video is matched again. The library had 114 such videos on 2026-09-13.

Re-downloading 114 videos to get 114 pictures is the wrong trade. YouTube keeps a video's poster at
a URL derived from nothing but its id — ``i.ytimg.com/vi/{id}/maxresdefault.jpg`` — and every row
written by the download path knows its id (``source_id``). So this asks for the picture alone.

``maxresdefault`` is the 16:9 frame, and is missing for older uploads; ``hqdefault`` always exists
but is 4:3 with black bars. The order here prefers the first and falls back to the second, and the
client crops both to 16:9, which on ``hqdefault`` removes exactly the bars.

What it cannot recover, and why that is acceptable
--------------------------------------------------
The twelve rows ``adopt_orphan_videos`` wrote carry ``source_id = "adopted"`` because the file
they describe was named after the track, not the video — there is no id to build a URL from.
They are counted and skipped, and the grid keeps showing their album covers. Matching one again
is the only way to give it a poster, and that is a decision per video, not this script's.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.db.models import Track, TrackVideo
from app.db.session import async_session_maker

logger = logging.getLogger(__name__)

# In preference order. See the module docstring for why there are two.
CANDIDATES = ("maxresdefault.jpg", "hqdefault.jpg")

# Ids this backfill cannot build a URL from. ``adopted`` is what `adopt_orphan_videos` writes.
UNKNOWN_SOURCE_IDS = frozenset({"", "adopted"})

Fetch = Callable[[str], Awaitable[bytes | None]]


def poster_url(video_id: str, candidate: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/{candidate}"


async def fetch_with_httpx(url: str) -> bytes | None:
    """The real fetch: the bytes on 200, None on anything else.

    YouTube answers a missing ``maxresdefault`` with a 404 that carries a placeholder image, so
    the status is the signal — the body of a 404 is not a poster.
    """
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        response = await client.get(url)
    if response.status_code != 200:
        return None
    return response.content


async def backfill(
    fetch: Fetch = fetch_with_httpx,
    *,
    dry_run: bool = False,
    force: bool = False,
    session_maker: async_sessionmaker = async_session_maker,
    videos_dir: Path | None = None,
) -> tuple[int, int, int, int]:
    """Return (written, already_had_one, no_source_id, not_found)."""
    videos_dir = videos_dir or settings.videos_path
    videos_dir.mkdir(parents=True, exist_ok=True)

    written = existing = unknown = missing = 0

    async with session_maker() as session:
        rows = (
            await session.execute(
                select(TrackVideo, Track)
                .join(Track, TrackVideo.track_id == Track.id)
                .order_by(TrackVideo.downloaded_at.desc().nullslast(), TrackVideo.id)
            )
        ).all()

    for video, track in rows:
        label = f"{track.artist} — {track.title}"
        poster_path = videos_dir / f"{video.track_id}.jpg"

        if video.source != "youtube" or video.source_id in UNKNOWN_SOURCE_IDS:
            print(f"  skip   {label}  (no source id to ask for)")
            unknown += 1
            continue
        if poster_path.exists() and not force:
            existing += 1
            continue

        found: bytes | None = None
        for candidate in CANDIDATES:
            found = await fetch(poster_url(video.source_id, candidate))
            if found:
                break
        if not found:
            print(f"  miss   {label}  ({video.source_id})")
            missing += 1
            continue

        print(f"  poster {label}  ({candidate}, {len(found) // 1000} KB)")
        if not dry_run:
            # Written under the temp name the download path uses and renamed into place, so a
            # crash mid-write leaves nothing `has_poster` would mistake for a poster.
            temp_path = videos_dir / f"{video.track_id}.temp.jpg"
            temp_path.write_bytes(found)
            temp_path.replace(poster_path)
        written += 1

    return (written, existing, unknown, missing)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="fetch and report without writing")
    parser.add_argument("--force", action="store_true", help="replace posters that already exist")
    args = parser.parse_args()

    written, existing, unknown, missing = asyncio.run(
        backfill(dry_run=args.dry_run, force=args.force)
    )
    verb = "would write" if args.dry_run else "wrote"
    print(
        f"\n{verb} {written}; {existing} already had one; "
        f"{unknown} without a source id; {missing} not found at YouTube"
    )


if __name__ == "__main__":
    main()
