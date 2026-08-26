"""Video endpoints for music video search and download."""

import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from starlette.responses import FileResponse

from app.api.deps import DbSession, release_connection
from app.api.exceptions import NotFoundError, TrackNotFoundError, ValidationError
from app.api.schemas.common import UTCDateTime
from app.api.schemas.tracks import TrackResponse
from app.api.streaming import stream_file
from app.db.models import Track
from app.db.models.tracks import TrackVideo
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


class VideoListItem(TrackResponse):
    """A track that has a video — the full track, plus which video and when it arrived.

    Subclasses `TrackResponse` for the same reason `FavoriteTrackResponse` does: the client drawing
    this list wants a track row, and reinventing a narrower one guarantees it diverges from every
    other track row in the app.
    """

    source: str
    source_id: str
    source_url: str | None = None
    file_size_bytes: int | None = None
    downloaded_at: UTCDateTime | None = None


class VideoListResponse(BaseModel):
    """Paginated list of tracks that have a video."""

    items: list[VideoListItem]
    total: int
    page: int
    page_size: int


@router.get("", response_model=VideoListResponse)
async def list_videos(
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> VideoListResponse:
    """
    List the tracks that have a downloaded video.

    ADR-0086 point 3, and the one thing the rest of this surface cannot do: every other operation is
    keyed by a track id you already have, so a destination that *lists* videos had nothing to call.
    """
    base = (
        select(TrackVideo, Track)
        .join(Track, TrackVideo.track_id == Track.id)
        .where(Track.active_filter())
    )

    total = await db.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0

    result = await db.execute(
        # `TrackVideo.id` last so the total order is unique. Ordering by `downloaded_at` alone ties
        # every row written in the same transaction, and OFFSET paging over a non-unique order may
        # repeat or skip rows between pages — see the same note on `tracks/listing.py`.
        base.order_by(TrackVideo.downloaded_at.desc().nullslast(), TrackVideo.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    items = [
        VideoListItem(
            **TrackResponse.model_validate(track, from_attributes=True).model_dump(),
            source=video.source,
            source_id=video.source_id,
            source_url=video.source_url,
            file_size_bytes=video.file_size_bytes,
            downloaded_at=video.downloaded_at,
        )
        for video, track in result.all()
    ]

    return VideoListResponse(items=items, total=total, page=page, page_size=page_size)


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
    download_status = await video_service.get_download_status(db, track_id_str)

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
    status = await video_service.get_download_status(db, track_id_str)
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


@router.get(
    "/{track_id}/stream",
    # Declare the real media type, exactly as `/tracks/{id}/stream` does. Without this the schema
    # claims `application/json` and a generated client would try to JSON-decode a video (ADR-0007).
    # This endpoint is hand-written per platform — `AVPlayer` is the caller — so the schema only
    # needs to describe it honestly (ADR-0086 point 5).
    response_class=FileResponse,
    responses={
        200: {"content": {"video/*": {}}, "description": "Whole video file."},
        206: {"content": {"video/*": {}}, "description": "Partial content for a Range request (seeking, buffering)."},
        416: {"description": "Requested range is not satisfiable."},
    },
)
async def stream_video(
    db: DbSession,
    track_id: UUID,
    request: Request,
) -> FileResponse:
    """
    Stream a downloaded video for a track, honouring `Range`.
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

    # Nothing below reads the database, so the connection goes back before the body is sent.
    # A `yield` dependency otherwise lives until the response *finishes*, which for a video is the
    # length of the video. See `release_connection`.
    await release_connection(db)

    # ADR-0086 point 4: `stream_file` hands the file to Starlette's `FileResponse`, which reads the
    # range off the ASGI scope and supplies 206, 416, suffix ranges, multipart, `ETag` and
    # `Last-Modified`. The handler this replaced set `Accept-Ranges: bytes` and then served the whole
    # file from byte 0 every time. **Do not reintroduce a hand-rolled parser here** — `stream_file`'s
    # docstring records the five defects the audio one had, and the incident they caused.
    return await stream_file(video_path, request, "video/mp4")


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
    deleted = await video_service.delete_video(db, str(track_id))

    if deleted:
        return VideoDeleteResponse(status="deleted", message="Video deleted successfully")
    else:
        raise NotFoundError("No video to delete")
