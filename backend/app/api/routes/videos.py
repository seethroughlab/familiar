"""Video endpoints for music video search and download."""

import logging
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DbSession, release_connection
from app.api.exceptions import NotFoundError, TrackNotFoundError, ValidationError
from app.db.models import Track
from app.services.video import get_video_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/videos", tags=["videos"])


class VideoSearchResultResponse(BaseModel):
    """Video search result response."""
    video_id: str
    title: str
    channel: str
    duration: int
    thumbnail_url: str
    url: str


class VideoStatusResponse(BaseModel):
    """Video status response."""
    has_video: bool
    download_status: str | None = None
    progress: float | None = None
    error: str | None = None


class DownloadRequest(BaseModel):
    """Request to download a video."""
    video_url: str


class DownloadResponse(BaseModel):
    """Response from download request."""
    status: str
    message: str
    track_id: str


@router.get("/{track_id}/search")
async def search_videos(
    db: DbSession,
    track_id: UUID,
    limit: int = Query(5, ge=1, le=10),
) -> list[VideoSearchResultResponse]:
    """
    Search YouTube for music videos matching the track.
    Returns a list of video search results.
    """
    # Get track from database
    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise TrackNotFoundError()

    if not track.title:
        raise ValidationError("Track must have a title to search for videos")

    # Build search query
    search_query = f"{track.artist or ''} {track.title} official music video"
    logger.info("Video search for track %s: '%s'", track_id, search_query)

    video_service = get_video_service()
    results = await video_service.search(search_query, limit=limit)

    return [
        VideoSearchResultResponse(
            video_id=r.video_id,
            title=r.title,
            channel=r.channel,
            duration=r.duration,
            thumbnail_url=r.thumbnail_url,
            url=r.url
        )
        for r in results
    ]


@router.get("/{track_id}/status")
async def get_video_status(
    db: DbSession,
    track_id: UUID,
) -> VideoStatusResponse:
    """
    Get the video status for a track.
    Returns whether a video exists and any download progress.
    """
    # Verify track exists
    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise TrackNotFoundError()

    video_service = get_video_service()
    track_id_str = str(track_id)

    has_video = video_service.has_video(track_id_str)
    download_status = video_service.get_download_status(track_id_str)

    if download_status:
        return VideoStatusResponse(
            has_video=has_video,
            download_status=download_status.status,
            progress=download_status.progress,
            error=download_status.error
        )

    return VideoStatusResponse(has_video=has_video)


@router.post("/{track_id}/download")
async def download_video(
    db: DbSession,
    track_id: UUID,
    request: DownloadRequest,
    background_tasks: BackgroundTasks,
) -> DownloadResponse:
    """
    Start downloading a video for a track.
    The download runs in the background.
    """
    # Verify track exists
    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise TrackNotFoundError()

    video_service = get_video_service()
    track_id_str = str(track_id)

    # Check if already downloading
    status = video_service.get_download_status(track_id_str)
    if status and status.status == 'downloading':
        return DownloadResponse(
            status="downloading",
            message="Video download already in progress",
            track_id=track_id_str
        )

    # Check if video already exists
    if video_service.has_video(track_id_str):
        return DownloadResponse(
            status="complete",
            message="Video already downloaded",
            track_id=track_id_str
        )

    # Set pending status immediately so the frontend sees it before the background task starts
    video_service.set_pending(track_id_str, request.video_url)

    # Start download in background
    background_tasks.add_task(
        video_service.download,
        track_id_str,
        request.video_url
    )

    return DownloadResponse(
        status="started",
        message="Video download started",
        track_id=track_id_str
    )


@router.get("/{track_id}/stream")
async def stream_video(
    db: DbSession,
    track_id: UUID,
) -> StreamingResponse:
    """
    Stream a downloaded video for a track.
    """
    # Verify track exists
    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise TrackNotFoundError()

    video_service = get_video_service()
    video_path = video_service.get_video_path(str(track_id))

    if not video_path:
        raise NotFoundError("No video available")

    file_size = video_path.stat().st_size

    # Nothing below reads the database, so the connection goes back before the body is sent.
    # A `yield` dependency otherwise lives until the response *finishes*, which for a video is the
    # length of the video. See `release_connection`.
    await release_connection(db)

    async def stream_video_file() -> AsyncIterator[bytes]:
        with open(video_path, "rb") as f:
            chunk_size = 64 * 1024  # 64KB chunks
            while chunk := f.read(chunk_size):
                yield chunk

    return StreamingResponse(
        stream_video_file(),  # type: ignore[no-untyped-call]
        media_type="video/mp4",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
        },
    )


class VideoDeleteResponse(BaseModel):
    """Response from video deletion."""
    status: str
    message: str


@router.delete("/{track_id}", response_model=VideoDeleteResponse)
async def delete_video(
    db: DbSession,
    track_id: UUID,
) -> VideoDeleteResponse:
    """Delete a downloaded video for a track."""
    # Verify track exists
    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise TrackNotFoundError()

    video_service = get_video_service()
    deleted = await video_service.delete_video(str(track_id))

    if deleted:
        return VideoDeleteResponse(status="deleted", message="Video deleted successfully")
    else:
        raise NotFoundError("No video to delete")
