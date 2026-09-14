"""Find the "videos" that are one picture for the length of the track, and remove them.

Run via ``python -m app.cli.find_still_videos`` (or ``make find-stills`` from ``backend/``) to
report; add ``--delete`` to remove what it finds, file and row together.

Why this exists
---------------
A music video's grid tile is its poster, and a poster of the album cover looked wrong next to
the others. It was not wrong: 52 of the library's 242 videos on 2026-09-14 *were* the album cover
— audio uploads with a picture, matched by hand before anything checked, and by the batch matcher
before it learned to. Nothing in a search result reliably says so (see `match_music_videos`), but
the file does: eight frames across the timeline that never differ is not a video.

`--delete` removes them the way the Videos screen would, so the track is simply one without a
video again and can be matched to a real one.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Track, TrackVideo
from app.db.session import async_session_maker
from app.services.video import STILL_IMAGE_THRESHOLD, VideoService, get_video_service

logger = logging.getLogger(__name__)

# Above the still threshold but below what a video with any real motion scores. Reported so a
# person can look, never removed.
LOW_MOTION_CEILING = 15.0


async def find(
    service: VideoService | None = None,
    *,
    delete: bool = False,
    session_maker: async_sessionmaker = async_session_maker,
) -> tuple[int, int, int]:
    """Return (stills, low_motion, videos)."""
    service = service or get_video_service()

    async with session_maker() as session:
        rows = (
            await session.execute(
                select(TrackVideo, Track).join(Track, TrackVideo.track_id == Track.id)
                .order_by(Track.artist, Track.title)
            )
        ).all()

    stills = low = videos = 0
    for video, track in rows:
        track_id = str(video.track_id)
        path = service.get_video_path(track_id)
        if path is None:
            continue
        score = await service.motion_score(path)
        label = f"{track.artist} — {track.title}"
        if score is None:
            print(f"  ?      {label}  (could not read)")
            continue
        if score < STILL_IMAGE_THRESHOLD:
            stills += 1
            print(f"  still  {label}  (score {score:.1f})")
            if delete:
                async with session_maker() as session:
                    await service.delete_video(session, track_id)
        elif score < LOW_MOTION_CEILING:
            low += 1
            print(f"  low    {label}  (score {score:.1f}; kept — look at it)")
        else:
            videos += 1

    return (stills, low, videos)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--delete", action="store_true", help="remove the stills, file and row")
    args = parser.parse_args()

    stills, low, videos = asyncio.run(find(delete=args.delete))
    verb = "removed" if args.delete else "found"
    print(f"\n{verb} {stills} stills; {low} low-motion kept for a look; {videos} videos")


if __name__ == "__main__":
    main()
