"""One-shot repair: download again every video the Mac cannot decode.

Run via ``python -m app.cli.refetch_unplayable_videos`` (or ``make refetch-videos`` from
``backend/``). Idempotent — a file that is already H.264 is left alone, so it is safe to re-run.

Why this exists
---------------
The download's format selector said ``ext=mp4`` and meant "something the Mac can play". YouTube
serves VP9 and AV1 in an MP4 container, both matched, and AVFoundation decodes neither — so the
full player's video backdrop (ADR-0085 point 3) played the audio track under AVKit's audio-only
glyph. On 2026-09-13, 67 of the library's 114 videos were like that; nobody had noticed because
the backdrop had never been switched on from the Videos screen.

The selector now asks for ``avc1`` by name (`H264_FORMAT`). Every affected file has a
``source_url`` on its row, so the fix is the download path again, which also replaces the row and
fetches the poster. The container's ffmpeg has no software H.264 encoder, so transcoding was never
an option here; a file with no source to fetch from is reported and left as it is.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Track, TrackVideo
from app.db.session import async_session_maker
from app.services.video import PLAYABLE_CODECS, VideoService, get_video_service

logger = logging.getLogger(__name__)


async def refetch(
    service: VideoService | None = None,
    *,
    dry_run: bool = False,
    pause: float = 2.0,
    session_maker: async_sessionmaker = async_session_maker,
) -> tuple[int, int, int, int]:
    """Return (refetched, playable_already, no_source, failed)."""
    service = service or get_video_service()

    async with session_maker() as session:
        rows = (
            await session.execute(
                select(TrackVideo, Track)
                .join(Track, TrackVideo.track_id == Track.id)
                .order_by(TrackVideo.downloaded_at.desc().nullslast(), TrackVideo.id)
            )
        ).all()

    refetched = playable = unsourced = failed = 0
    for video, track in rows:
        track_id = str(video.track_id)
        label = f"{track.artist} — {track.title}"
        path = service.get_video_path(track_id)
        if path is None:
            continue
        codec = await service.video_codec(path)
        if codec in PLAYABLE_CODECS:
            playable += 1
            continue
        if not video.source_url:
            print(f"  skip   {label}  ({codec}; no source to fetch from)")
            unsourced += 1
            continue

        print(f"  fetch  {label}  ({codec} → h264, {video.source_url})")
        if dry_run:
            refetched += 1
            continue
        status = await service.download(track_id, video.source_url)
        if status.status == "complete":
            refetched += 1
        else:
            print(f"  fail   {label}  ({status.error})")
            failed += 1
        await asyncio.sleep(pause)

    return (refetched, playable, unsourced, failed)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="report without downloading")
    parser.add_argument("--pause", type=float, default=2.0, help="seconds between downloads (default 2)")
    args = parser.parse_args()

    refetched, playable, unsourced, failed = asyncio.run(
        refetch(dry_run=args.dry_run, pause=args.pause)
    )
    verb = "would refetch" if args.dry_run else "refetched"
    print(f"\n{verb} {refetched}; {playable} already playable; {unsourced} without a source; {failed} failed")


if __name__ == "__main__":
    main()
