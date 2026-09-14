"""Music video service using yt-dlp for YouTube video download."""


import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models.tracks import TrackVideo
from app.db.session import async_session_maker
from app.utils.time import utcnow

logger = logging.getLogger(__name__)
# What the Mac can decode (ADR-0085 point 3: the video is an `AVPlayer` backdrop). VP9 and AV1
# are not on this list because AVFoundation does not decode them, whatever the container says.
PLAYABLE_CODECS = frozenset({"h264", "hevc"})

H264_FORMAT = (
    "bestvideo[height<=1080][vcodec^=avc1]+bestaudio[ext=m4a]"
    "/bestvideo[height<=1080][vcodec^=avc1]+bestaudio"
    "/best[height<=1080][vcodec^=avc1]"
    "/bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]"
    "/best[height<=1080][ext=mp4]/best"
)


class VideoSearchUnavailable(Exception):
    """YouTube could not be searched — as distinct from having nothing to return.

    The two must not look alike to a caller. An empty list means "no videos match"; this means
    "the question could not be asked", and only one of them is worth telling somebody about.
    """



@dataclass
class VideoSearchResult:
    """Result from YouTube search."""
    video_id: str
    title: str
    channel: str
    duration: int  # seconds
    thumbnail_url: str
    url: str
    # The upload's description. Not shown anywhere; `video_matching` reads its first line, which
    # is how YouTube's auto-generated audio uploads announce themselves.
    description: str = ""


@dataclass
class VideoDownloadStatus:
    """Status of a video download."""
    track_id: str
    video_id: str
    status: str  # 'pending', 'downloading', 'complete', 'error'
    progress: float  # 0-100
    error: str | None = None
    file_path: str | None = None


class VideoService:
    """Service for searching and downloading music videos from YouTube."""

    def __init__(self, videos_dir: Path | None = None) -> None:
        # Overridable so a test can watch what a download leaves on disk in a directory of its
        # own; the app never passes one.
        self.videos_dir = videos_dir or settings.videos_path
        self.videos_dir.mkdir(parents=True, exist_ok=True)
        self._downloads: dict[str, VideoDownloadStatus] = {}

    @staticmethod
    def _base_ytdlp_args() -> list[str]:
        """Common yt-dlp args.

        **Deliberately empty, and that is the fix.** This used to pin
        `--extractor-args youtube:player_client=web`. YouTube now answers that client with
        storyboard images only, so every search failed with *"Only images are available for
        download"* → *"Requested format is not available"* — measured on 2026-08-29 against
        yt-dlp 2026.08.19, where `web` and `web_safari` both failed and no argument at all
        returned 32 playable formats up to 1080p.

        Pinning a client is a standing bet that YouTube will not change, against a project whose
        entire job is tracking those changes — `docker/entrypoint.sh` already updates yt-dlp on
        every boot for exactly that reason. Letting it choose is what makes that update useful.

        Kept as a method rather than inlined so a future argument has an obvious home and this
        note stays attached to the decision not to have one.
        """
        return []

    async def search(
        self,
        query: str,
        limit: int = 5
    ) -> list[VideoSearchResult]:
        """
        Search YouTube for music videos matching the query.
        Uses yt-dlp for search without downloading.
        """
        try:
            # Use yt-dlp to search YouTube
            cmd = [
                "yt-dlp",
                *self._base_ytdlp_args(),
                "--dump-json",
                "--no-playlist",
                f"ytsearch{limit}:{query}"
            ]

            logger.info("Video search: query=%r, cmd=%s", query, " ".join(cmd))

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=30.0
                )
            except TimeoutError:
                logger.error("Video search timed out after 30s for query: %r", query)
                process.kill()
                await process.wait()
                raise VideoSearchUnavailable("search timed out after 30s") from None

            stderr_text = stderr.decode().strip() if stderr else ""

            if process.returncode != 0:
                # Raised, not swallowed. Returning `[]` here made a broken search look exactly
                # like an empty one — the defect ADR-0077 records for `search_bandcamp`, which
                # "answered 'no results' for every query, for however long it had been". A
                # listener seeing "no videos found" has no reason to report anything.
                logger.error(
                    "yt-dlp search failed (rc=%d) for query %r: %s",
                    process.returncode, query, stderr_text[:500]
                )
                raise VideoSearchUnavailable(stderr_text[:300] or "yt-dlp failed")

            if stderr_text:
                logger.debug("yt-dlp search warnings for %r: %s", query, stderr_text[:500])

            results = []
            for line in stdout.decode().strip().split('\n'):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    # Get thumbnail - try 'thumbnail' first, fall back to 'thumbnails' array
                    thumbnail_url = data.get('thumbnail') or ''
                    if not thumbnail_url and data.get('thumbnails'):
                        # Get the first thumbnail from the array
                        thumbnail_url = data['thumbnails'][0].get('url', '')
                    results.append(VideoSearchResult(
                        video_id=data.get('id', ''),
                        title=data.get('title', ''),
                        channel=data.get('channel', data.get('uploader', '')),
                        duration=data.get('duration', 0) or 0,
                        description=data.get('description') or '',
                        thumbnail_url=thumbnail_url,
                        url=f"https://www.youtube.com/watch?v={data.get('id', '')}"
                    ))
                except json.JSONDecodeError:
                    continue

            logger.info("Video search returned %d results for query: %r", len(results), query)
            return results
        except VideoSearchUnavailable:
            # Already the honest answer — do not let the catch-all below turn it back into "no
            # results", which is what this handler did to every failure before.
            raise
        except Exception as exc:
            logger.exception("Video search failed for query: %r", query)
            raise VideoSearchUnavailable(str(exc)) from exc

    def get_video_path(self, track_id: str) -> Path | None:
        """Get the path to a downloaded video for a track."""
        video_path = self.videos_dir / f"{track_id}.mp4"
        if video_path.exists():
            return video_path
        return None

    def has_video(self, track_id: str) -> bool:
        """Check if a video exists for a track.

        The file on disk is the authority for *existence*; the row is the authority for *identity*
        (ADR-0086 point 2). Answering existence from disk keeps this synchronous and keeps a video
        playable even if its row was lost, which matters because the file is what the stream serves.
        """
        return self.get_video_path(track_id) is not None

    async def video_codec(self, path: Path) -> str | None:
        """The name of the file's first video stream's codec, as ffprobe reports it, or None.

        What decides whether the Mac can show it — see `PLAYABLE_CODECS`. ffprobe ships with
        the ffmpeg the download's merge step already requires.
        """
        process = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await process.communicate()
        codec = stdout.decode().strip().splitlines()
        return codec[0].strip() if codec and codec[0].strip() else None

    def get_poster_path(self, track_id: str) -> Path | None:
        """The poster frame saved beside a track's video, or None.

        Kept beside the mp4 as `{track_id}.jpg` rather than in the artwork tree: it is a fact about
        the video (which frame the source chose to advertise it with), not about the album, and it
        should leave with the video. `adopt_orphan_videos` globs `*.mp4`, so a poster is never
        mistaken for an orphan.
        """
        poster_path = self.videos_dir / f"{track_id}.jpg"
        if poster_path.exists():
            return poster_path
        return None

    def has_poster(self, track_id: str) -> bool:
        """Whether a poster exists, answered from disk the way `has_video` is.

        Synchronous and cheap on purpose: the list endpoint asks this once per row so a grid of
        tiles knows which posters to request instead of finding out with a 404 apiece.
        """
        return self.get_poster_path(track_id) is not None

    async def get_video_record(
        self, session: AsyncSession, track_id: str
    ) -> TrackVideo | None:
        """The row for a track's video, or None.

        Takes the caller's session rather than opening one. Every caller is a request handler that
        already has `DbSession`, and a service that opens a second session against the same engine
        binds its pool to whichever event loop touched it first — which is exactly the conflict
        `conftest.async_db` exists to work around.

        Reconciles the two sources ADR-0086 point 2 names: a row whose file is gone is deleted
        rather than reported, so "which video is attached" can never outlive the thing it describes.
        """
        record = await session.scalar(
            select(TrackVideo).where(TrackVideo.track_id == UUID(track_id))
        )
        if record is None:
            return None
        if self.get_video_path(track_id) is None:
            await session.execute(delete(TrackVideo).where(TrackVideo.id == record.id))
            await session.commit()
            return None
        return record

    async def get_download_status(
        self, session: AsyncSession, track_id: str
    ) -> VideoDownloadStatus | None:
        """The status of a video download.

        The in-memory dict is the progress cache for a download running *in this process* — that is
        the one thing it is good at, and it is the only place a percentage exists. It is consulted
        first for exactly that reason. When it is empty, the table answers instead, so a restart no
        longer erases the fact that a video exists.
        """
        live = self._downloads.get(track_id)
        if live is not None:
            return live

        record = await self.get_video_record(session, track_id)
        if record is None:
            return None

        return VideoDownloadStatus(
            track_id=track_id,
            video_id=record.source_id,
            status='complete',
            progress=100,
            file_path=record.file_path,
        )

    async def _record_download(
        self,
        track_id: str,
        video_id: str,
        video_url: str,
        output_path: Path,
    ) -> None:
        """Write the `track_videos` row for a completed download.

        **The one place in this service that opens its own session**, and it has to: `download` is
        invoked from `BackgroundTasks`, which runs after the request's session has been committed and
        closed, so there is nothing to borrow. Every other DB method here takes the caller's session
        instead.

        Failures here are logged and swallowed on purpose. The file is already on disk and playable;
        losing the row costs the *identity* of the video, not the video. Raising would leave the
        caller's `except` marking a completed download as an error, which is the worse of the two.
        """
        try:
            async with async_session_maker() as session:
                existing = await session.scalar(
                    select(TrackVideo).where(TrackVideo.track_id == UUID(track_id))
                )
                if existing is not None:
                    await session.execute(
                        delete(TrackVideo).where(TrackVideo.id == existing.id)
                    )

                session.add(
                    TrackVideo(
                        id=uuid4(),
                        track_id=UUID(track_id),
                        source='youtube',
                        source_id=video_id,
                        source_url=video_url,
                        file_path=str(output_path),
                        is_audio_only=False,
                        file_size_bytes=output_path.stat().st_size,
                        downloaded_at=utcnow(),
                    )
                )
                await session.commit()
        except Exception:
            logger.exception(
                "Downloaded video for track %s but could not record it; "
                "the file is on disk and playable, its source is not known",
                track_id,
            )

    @staticmethod
    def _extract_video_id(video_url: str) -> str:
        """Extract YouTube video ID from a URL."""
        if "v=" in video_url:
            return video_url.split("v=")[1].split("&")[0]
        elif "youtu.be/" in video_url:
            return video_url.split("youtu.be/")[1].split("?")[0]
        return ""

    def set_pending(self, track_id: str, video_url: str) -> None:
        """Set a track's download status to pending immediately."""
        video_id = self._extract_video_id(video_url)
        self._downloads[track_id] = VideoDownloadStatus(
            track_id=track_id,
            video_id=video_id,
            status='pending',
            progress=0,
        )

    async def download(
        self,
        track_id: str,
        video_url: str,
        progress_callback: Callable[[float], None] | None = None
    ) -> VideoDownloadStatus:
        """
        Download a video from YouTube using yt-dlp.
        Returns the download status.
        """
        # Check if already downloading
        if track_id in self._downloads:
            status = self._downloads[track_id]
            if status.status == 'downloading':
                return status

        video_id = self._extract_video_id(video_url)

        output_path = self.videos_dir / f"{track_id}.mp4"
        temp_path = self.videos_dir / f"{track_id}.temp.mp4"
        poster_path = self.videos_dir / f"{track_id}.jpg"
        # The thumbnail template has no extension, and that is what makes its output name
        # predictable. yt-dlp derives the thumbnail's name by replacing the template's extension
        # *only when it equals the video's* — so `-o {id}.temp.mp4` alone yields `{id}.temp.jpg`
        # for a merged mp4 but `{id}.temp.mp4.jpg` when the `/best` fallback lands on webm. With
        # `{id}.temp` the suffix is never a video extension, so the converter always writes
        # `{id}.temp.jpg` (yt-dlp 2026.02, `_write_thumbnails` / `FFmpegThumbnailsConvertorPP`).
        temp_poster_base = self.videos_dir / f"{track_id}.temp"
        temp_poster = self.videos_dir / f"{track_id}.temp.jpg"

        status = VideoDownloadStatus(
            track_id=track_id,
            video_id=video_id,
            status='downloading',
            progress=0
        )
        self._downloads[track_id] = status

        try:
            # Use yt-dlp to download
            cmd = [
                "yt-dlp",
                *self._base_ytdlp_args(),
                # H.264 by name, not "mp4" by extension. `ext=mp4` was satisfied by YouTube's VP9
                # and AV1 streams in an MP4 container, and AVFoundation decodes neither: the Mac
                # played the audio track under AVKit's audio-only glyph. On 2026-09-13, 67 of the
                # library's 114 videos were like that and 47 had ever shown a frame. YouTube has
                # an avc1 rendition of practically everything at 1080p and below; the last
                # fallback is there for the rest and is what `PLAYABLE_CODECS` exists to catch.
                "-f", H264_FORMAT,
                "--merge-output-format", "mp4",
                "--no-playlist",
                "--progress",
                "--newline",
                # The poster frame, fetched from the source alongside the video so the Videos
                # grid has something to draw. Converted to jpg because YouTube's best thumbnail
                # is webp and every artwork consumer here speaks jpeg; the conversion needs the
                # ffmpeg the merge above already requires. yt-dlp treats a thumbnail failure as a
                # warning, never a non-zero exit, and so does the success branch below.
                "--write-thumbnail",
                "--convert-thumbnails", "jpg",
                "-o", str(temp_path),
                "-o", f"thumbnail:{temp_poster_base}",
                video_url
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )

            # Read progress from stdout
            error_lines: list[str] = []
            if process.stdout:
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        break

                    line_str = line.decode().strip()
                    # Capture error lines from yt-dlp
                    if line_str.startswith('ERROR:'):
                        error_lines.append(line_str.removeprefix('ERROR:').strip())
                    # Parse progress from yt-dlp output
                    elif '[download]' in line_str and '%' in line_str:
                        try:
                            # Extract percentage from output like "[download]  50.0% of ..."
                            parts = line_str.split('%')[0].split()[-1]
                            progress = float(parts)
                            status.progress = progress
                            if progress_callback:
                                progress_callback(progress)
                        except (ValueError, IndexError):
                            pass

            await process.wait()

            if process.returncode == 0 and temp_path.exists():
                # Move temp file to final location
                temp_path.rename(output_path)
                # A missing poster never fails a download. But a poster left over from a previous
                # download of this track would describe a different video, so it goes either way.
                if temp_poster.exists():
                    temp_poster.replace(poster_path)
                else:
                    poster_path.unlink(missing_ok=True)
                self._sweep_temp_files(track_id)
                status.status = 'complete'
                status.progress = 100
                status.file_path = str(output_path)
                # ADR-0086 point 1. Deliberately inside the success branch and before the status is
                # observable as complete, so "there is a file" and "we know what it is" become true
                # together. `_record_download` swallows its own failures — see its docstring for why
                # a lost row must not turn a finished download into an error.
                await self._record_download(track_id, video_id, video_url, output_path)
            else:
                status.status = 'error'
                # Use the last (most specific) yt-dlp error, or generic fallback
                error_msg = error_lines[-1] if error_lines else 'Download failed'
                status.error = error_msg[:300]
                self._sweep_temp_files(track_id)

        except Exception as e:
            status.status = 'error'
            status.error = str(e)
            self._sweep_temp_files(track_id)

        return status

    def _sweep_temp_files(self, track_id: str) -> None:
        """Remove whatever yt-dlp left under the temp name.

        A glob rather than the two names we expect: a failed `--convert-thumbnails` leaves the
        original `.temp.webp` behind, and a future format fallback could leave something else.
        Anything under `{track_id}.temp.*` is ours and is not a finished artefact.
        """
        for leftover in self.videos_dir.glob(f"{track_id}.temp.*"):
            leftover.unlink(missing_ok=True)

    async def delete_video(self, session: AsyncSession, track_id: str) -> bool:
        """Delete a downloaded video, and the row that says what it was.

        The row goes whether or not the file was there: a `track_videos` row whose file is missing
        describes nothing, and leaving one behind would make `get_video_record` reconcile it away
        later anyway.
        """
        video_path = self.get_video_path(track_id)
        deleted = False
        if video_path:
            video_path.unlink()
            deleted = True
        # The poster leaves with the video. It does not count towards `deleted`: a poster with no
        # video and no row was never something the client could see.
        if poster_path := self.get_poster_path(track_id):
            poster_path.unlink()

        if track_id in self._downloads:
            del self._downloads[track_id]

        result = await session.execute(
            delete(TrackVideo).where(TrackVideo.track_id == UUID(track_id))
        )
        await session.commit()
        # `session.execute` is typed `Result[Any]`; a DELETE really returns a `CursorResult`,
        # which has `rowcount`. Same ignore the other eight call sites in this codebase use.
        deleted = deleted or bool(result.rowcount)  # type: ignore[attr-defined]

        return deleted


# Singleton instance
_video_service: VideoService | None = None


def get_video_service() -> VideoService:  # type: ignore[no-untyped-call]
    """Get or create the video service singleton."""
    global _video_service
    if _video_service is None:
        _video_service = VideoService()
    return _video_service
