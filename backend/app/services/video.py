"""Music video service using yt-dlp for YouTube video download."""

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class VideoSearchResult:
    """Result from YouTube search."""
    video_id: str
    title: str
    channel: str
    duration: int  # seconds
    thumbnail_url: str
    url: str


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

    def __init__(self) -> None:
        self.videos_dir = settings.videos_path
        self.videos_dir.mkdir(parents=True, exist_ok=True)
        self._downloads: dict[str, VideoDownloadStatus] = {}

    @staticmethod
    def _base_ytdlp_args() -> list[str]:
        """Common yt-dlp args for YouTube compatibility."""
        return [
            "--extractor-args", "youtube:player_client=web",
        ]

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
                return []

            stderr_text = stderr.decode().strip() if stderr else ""

            if process.returncode != 0:
                logger.error(
                    "yt-dlp search failed (rc=%d) for query %r: %s",
                    process.returncode, query, stderr_text[:500]
                )
                return []

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
                        thumbnail_url=thumbnail_url,
                        url=f"https://www.youtube.com/watch?v={data.get('id', '')}"
                    ))
                except json.JSONDecodeError:
                    continue

            logger.info("Video search returned %d results for query: %r", len(results), query)
            return results
        except Exception:
            logger.exception("Video search failed for query: %r", query)
            return []

    def get_video_path(self, track_id: str) -> Path | None:
        """Get the path to a downloaded video for a track."""
        video_path = self.videos_dir / f"{track_id}.mp4"
        if video_path.exists():
            return video_path
        return None

    def has_video(self, track_id: str) -> bool:
        """Check if a video exists for a track."""
        return self.get_video_path(track_id) is not None

    def get_download_status(self, track_id: str) -> VideoDownloadStatus | None:
        """Get the status of a video download."""
        return self._downloads.get(track_id)

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
                "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
                "--merge-output-format", "mp4",
                "--no-playlist",
                "--progress",
                "--newline",
                "-o", str(temp_path),
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
                status.status = 'complete'
                status.progress = 100
                status.file_path = str(output_path)
            else:
                status.status = 'error'
                # Use the last (most specific) yt-dlp error, or generic fallback
                error_msg = error_lines[-1] if error_lines else 'Download failed'
                status.error = error_msg[:300]
                if temp_path.exists():
                    temp_path.unlink()

        except Exception as e:
            status.status = 'error'
            status.error = str(e)
            if temp_path.exists():
                temp_path.unlink()

        return status

    async def delete_video(self, track_id: str) -> bool:
        """Delete a downloaded video."""
        video_path = self.get_video_path(track_id)
        if video_path:
            video_path.unlink()
            if track_id in self._downloads:
                del self._downloads[track_id]
            return True
        return False


# Singleton instance
_video_service: VideoService | None = None


def get_video_service() -> VideoService:  # type: ignore[no-untyped-call]
    """Get or create the video service singleton."""
    global _video_service
    if _video_service is None:
        _video_service = VideoService()
    return _video_service
