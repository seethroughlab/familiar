"""Match and download music videos for the tracks a profile plays and keeps, in a batch.

Run via ``python -m app.cli.match_music_videos --profile Jeff`` (or ``make match-videos
ARGS="--profile Jeff"`` from ``backend/``). Resumable: every decision is appended to
``{videos_path}/match-log.jsonl`` and a track already in the log is not asked about again unless
``--retry``. Stop it whenever you like; the videos it has finished are already rows.

Why this exists
---------------
The Mac's "Match Music Video…" (ADR-0085 point 7) is one track at a time: search, five results,
choose, download. That is the right shape for a track you are looking at and the wrong one for
"a few hundred more" — nobody sits through three hundred sheets. This is the same flow with the
choosing written down (`app.services.video_matching`) and the sheet replaced by a log.

Which tracks
------------
The profile's favourites, and anything it has played at least ``--min-plays`` times, most played
first — the tracks somebody has already said they want more of. Tracks that have a video are left
out, so the batch is only ever the gap.

Why it is slow on purpose
-------------------------
Every search and every download is a request to YouTube from one address, and yt-dlp is already
the thing YouTube changes its mind about most (see `VideoService._base_ytdlp_args`). ``--pause``
seconds sit between tracks, and three consecutive search failures stop the run rather than
hammer on: a run that stops early can be started again; an address that gets flagged cannot.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Profile, ProfileFavorite, ProfilePlayHistory, Track, TrackVideo
from app.db.session import async_session_maker
from app.services.video import (
    VideoDownloadStatus,
    VideoSearchResult,
    VideoSearchUnavailable,
    get_video_service,
)
from app.services.video_matching import choose

logger = logging.getLogger(__name__)

LOG_NAME = "match-log.jsonl"
# How many searches may fail in a row before the run assumes YouTube has stopped answering.
CONSECUTIVE_FAILURES_TO_STOP = 3

Search = Callable[[str], Awaitable[list[VideoSearchResult]]]
Download = Callable[[str, str], Awaitable[VideoDownloadStatus]]


@dataclass(frozen=True)
class Candidate:
    track_id: UUID
    title: str
    artist: str
    duration_seconds: float | None
    plays: int
    favourite: bool

    @property
    def label(self) -> str:
        return f"{self.artist} — {self.title}"

    @property
    def query(self) -> str:
        # The same query the match sheet's search route builds, so the batch sees what a person
        # would have seen.
        return f"{self.artist} {self.title} official music video"


@dataclass
class Tally:
    matched: int = 0
    skipped: int = 0
    failed: int = 0
    already_logged: int = 0


async def resolve_profile(session_maker: async_sessionmaker, name_or_id: str | None) -> Profile:
    async with session_maker() as session:
        if name_or_id is None:
            profiles = (await session.execute(select(Profile))).scalars().all()
            if len(profiles) == 1:
                return profiles[0]
            names = ", ".join(sorted(p.name for p in profiles))
            raise SystemExit(f"More than one profile; pass --profile. ({names})")
        try:
            wanted = Profile.id == UUID(name_or_id)
        except ValueError:
            wanted = func.lower(Profile.name) == name_or_id.lower()
        profile = await session.scalar(select(Profile).where(wanted))
        if profile is None:
            raise SystemExit(f"No profile {name_or_id!r}.")
        return profile


async def candidates(
    session_maker: async_sessionmaker,
    profile_id: UUID,
    *,
    min_plays: int,
    limit: int,
) -> list[Candidate]:
    """Favourites and well-played tracks without a video, most played first."""
    async with session_maker() as session:
        has_video = select(TrackVideo.track_id)
        favourite = (
            select(ProfileFavorite.track_id)
            .where(ProfileFavorite.profile_id == profile_id)
            .subquery()
        )
        plays = (
            select(ProfilePlayHistory.track_id, ProfilePlayHistory.play_count)
            .where(ProfilePlayHistory.profile_id == profile_id)
            .subquery()
        )
        rows = (
            await session.execute(
                select(Track, plays.c.play_count, favourite.c.track_id.isnot(None))
                .outerjoin(favourite, favourite.c.track_id == Track.id)
                .outerjoin(plays, plays.c.track_id == Track.id)
                .where(Track.active_filter())
                .where(Track.id.notin_(has_video))
                .where(
                    (favourite.c.track_id.isnot(None))
                    | (plays.c.play_count >= min_plays)
                )
                .order_by(plays.c.play_count.desc().nullslast(), Track.artist, Track.title)
                .limit(limit)
            )
        ).all()

    return [
        Candidate(
            track_id=track.id,
            title=track.title or "",
            artist=track.artist or "",
            duration_seconds=track.duration_seconds,
            plays=play_count or 0,
            favourite=bool(is_favourite),
        )
        for track, play_count, is_favourite in rows
        if track.title and track.artist
    ]


def already_logged(log_path: Path) -> set[str]:
    if not log_path.exists():
        return set()
    seen: set[str] = set()
    for line in log_path.read_text().splitlines():
        if line.strip():
            seen.add(json.loads(line)["track_id"])
    return seen


def _log(
    log_path: Path | None, candidate: Candidate, decision: str, reason: str, video_id: str | None
) -> None:
    # `None` is the dry run: it decides out loud and remembers nothing, so the real run that
    # follows asks every question again.
    if log_path is None:
        return
    entry = {
        "track_id": str(candidate.track_id),
        "artist": candidate.artist,
        "title": candidate.title,
        "decision": decision,
        "reason": reason,
        "video_id": video_id,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    with log_path.open("a") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


async def run(
    picks: list[Candidate],
    *,
    search: Search,
    download: Download,
    log_path: Path,
    dry_run: bool = False,
    pause: float = 0.0,
    retry: bool = False,
) -> Tally:
    tally = Tally()
    seen = set() if retry else already_logged(log_path)
    consecutive_failures = 0
    write_to = None if dry_run else log_path

    for candidate in picks:
        if str(candidate.track_id) in seen:
            tally.already_logged += 1
            continue

        try:
            results = await search(candidate.query)
        except VideoSearchUnavailable as exc:
            consecutive_failures += 1
            print(f"  fail   {candidate.label}  (search: {exc})")
            _log(write_to, candidate, "failed", f"search: {exc}", None)
            tally.failed += 1
            if consecutive_failures >= CONSECUTIVE_FAILURES_TO_STOP:
                print(f"\n{consecutive_failures} searches failed in a row — stopping rather than pressing on.")
                break
            await asyncio.sleep(pause)
            continue
        consecutive_failures = 0

        verdict = choose(
            title=candidate.title,
            artist=candidate.artist,
            duration_seconds=candidate.duration_seconds,
            results=results,
        )
        if not verdict.matched or verdict.result is None:
            print(f"  skip   {candidate.label}  ({verdict.reason})")
            _log(write_to, candidate, "skipped", verdict.reason, None)
            tally.skipped += 1
            await asyncio.sleep(pause)
            continue

        picked = verdict.result
        print(f"  match  {candidate.label}  → {picked.title!r} [{picked.channel}] ({verdict.reason})")
        if dry_run:
            tally.matched += 1
            await asyncio.sleep(pause)
            continue

        status = await download(str(candidate.track_id), picked.url)
        if status.status == "complete":
            _log(write_to, candidate, "matched", verdict.reason, picked.video_id)
            tally.matched += 1
        else:
            print(f"  fail   {candidate.label}  (download: {status.error})")
            _log(write_to, candidate, "failed", f"download: {status.error}", picked.video_id)
            tally.failed += 1
        await asyncio.sleep(pause)

    return tally


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", help="profile name or id whose favourites and plays to use")
    parser.add_argument("--limit", type=int, default=300, help="at most this many tracks (default 300)")
    parser.add_argument("--min-plays", type=int, default=3, help="a non-favourite needs this many plays (default 3)")
    parser.add_argument("--pause", type=float, default=4.0, help="seconds between tracks (default 4)")
    parser.add_argument("--dry-run", action="store_true", help="search and decide, download nothing")
    parser.add_argument("--retry", action="store_true", help="ask again about tracks already in the log")
    args = parser.parse_args()

    async def go() -> None:
        profile = await resolve_profile(async_session_maker, args.profile)
        picks = await candidates(
            async_session_maker, profile.id, min_plays=args.min_plays, limit=args.limit
        )
        print(f"{len(picks)} candidates for {profile.name} without a video\n")

        service = get_video_service()
        log_path = service.videos_dir / LOG_NAME

        async def search(query: str) -> list[VideoSearchResult]:
            return await service.search(query, limit=6)

        tally = await run(
            picks,
            search=search,
            download=service.download,
            log_path=log_path,
            dry_run=args.dry_run,
            pause=args.pause,
            retry=args.retry,
        )
        verb = "would download" if args.dry_run else "downloaded"
        print(
            f"\n{verb} {tally.matched}; skipped {tally.skipped}; failed {tally.failed}; "
            f"{tally.already_logged} already in {log_path.name}"
        )

    asyncio.run(go())


if __name__ == "__main__":
    main()
