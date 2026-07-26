"""Track streaming, artwork, and lyrics endpoints."""

import asyncio
import logging
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import DbSession
from app.api.exceptions import NotFoundError, TrackNotFoundError, TranscodeError, ValidationError
from app.db.models import Track
from app.services.artwork import compute_album_hash, get_artwork_path

from . import AUDIO_MIME_TYPES

logger = logging.getLogger(__name__)

# Per-track locks to prevent redundant concurrent transcodes
_transcode_locks: dict[UUID, asyncio.Lock] = {}
_locks_lock = asyncio.Lock()

router = APIRouter()

# Formats that browsers can't natively decode — need server-side transcoding
TRANSCODE_EXTENSIONS = {".aiff", ".aif"}

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_ARTWORK_SIZE = 10 * 1024 * 1024  # 10MB


def get_audio_mime_type(file_path: Path) -> str:
    """Get MIME type for audio file."""
    suffix = file_path.suffix.lower()
    return AUDIO_MIME_TYPES.get(suffix, "application/octet-stream")


class ArtworkUploadResponse(BaseModel):
    """Response for artwork upload."""

    success: bool
    message: str
    embedded_in_file: bool = False
    saved_to_cache: bool = False


class LyricLineResponse(BaseModel):
    """A single line of lyrics with timing."""
    time: float
    text: str


class LyricsResponse(BaseModel):
    """Lyrics response schema."""
    synced: bool
    lines: list[LyricLineResponse]
    plain_text: str
    source: str


@router.get("/{track_id}/stream")
async def stream_track(
    db: DbSession,
    track_id: UUID,
    request: Request,
) -> StreamingResponse:
    """Stream audio file with range request support for seeking."""
    from sqlalchemy import select

    # Get track from database (only ACTIVE tracks can be streamed)
    query = select(Track).where(Track.id == track_id, Track.active_filter())
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        logger.warning("Stream request for unknown track_id=%s", track_id)
        raise TrackNotFoundError()

    file_path = Path(track.file_path)
    if not file_path.exists():
        logger.warning("Audio file missing: track_id=%s path=%s", track_id, file_path)
        raise NotFoundError("Audio file not found")

    # Transcode tracks with browser-unsupported codecs
    if track.needs_transcode:
        logger.info("Transcoding (unsupported codec=%s) track_id=%s", track.codec, track_id)
        return await _get_or_transcode(track_id, file_path, request)

    # Transcode formats that browsers can't natively decode
    if file_path.suffix.lower() in TRANSCODE_EXTENSIONS:
        logger.debug("Transcoding track_id=%s path=%s to FLAC", track_id, file_path)
        return await _get_or_transcode(track_id, file_path, request)

    mime_type = get_audio_mime_type(file_path)
    logger.debug("Streaming track_id=%s path=%s type=%s", track_id, file_path, mime_type)

    from app.api.streaming import stream_file
    return await stream_file(file_path, request, mime_type)


async def _get_or_transcode(track_id: UUID, file_path: Path, request: Request) -> StreamingResponse:
    """Transcode audio to FLAC (cached to disk), then serve via stream_file().

    Caching to disk ensures the served file has complete FLAC headers (streaminfo +
    seektable), Content-Length, and range request support — fixing PTS errors during
    crossfade that occurred with the previous chunked-stream approach.

    Uses per-track locking to prevent redundant concurrent transcodes.
    """
    from app.api.streaming import stream_file
    from app.services.flac_remux import transcode_to_file

    cache_dir = Path("data/transcode_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{track_id}.flac"

    # Acquire per-track lock to prevent redundant concurrent transcodes
    async with _locks_lock:
        if track_id not in _transcode_locks:
            _transcode_locks[track_id] = asyncio.Lock()
        lock = _transcode_locks[track_id]

    async with lock:
        # Re-transcode if source is newer or cache doesn't exist
        needs_transcode = not cached.exists() or file_path.stat().st_mtime > cached.stat().st_mtime
        # Also re-transcode if cached file is empty (corrupt from prior crash)
        if not needs_transcode and cached.stat().st_size == 0:
            cached.unlink(missing_ok=True)
            needs_transcode = True

        if needs_transcode:
            try:
                await transcode_to_file(file_path, cached)
            except RuntimeError:
                logger.exception("Transcode failed: track_id=%s path=%s", track_id, file_path)
                cached.unlink(missing_ok=True)
                raise TranscodeError(f"Failed to transcode {file_path.name}")

    # Clean up lock if no one else is waiting
    async with _locks_lock:
        if track_id in _transcode_locks and not lock.locked():
            del _transcode_locks[track_id]

    return await stream_file(cached, request, "audio/flac")


@router.post("/{track_id}/report-playback-error")
async def report_playback_error(
    db: DbSession,
    track_id: UUID,
) -> dict:
    """Report a client-side playback/decode error for a track.

    Auto-repair has been removed. Returns a skip status.
    """
    from sqlalchemy import select

    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise TrackNotFoundError()

    file_path = Path(track.file_path)
    if not file_path.exists():
        raise NotFoundError("Audio file not found")

    # Clear transcode cache if it exists — may be corrupt
    cache_file = Path("data/transcode_cache") / f"{track_id}.flac"
    cache_cleared = False
    if cache_file.exists():
        cache_file.unlink(missing_ok=True)
        cache_cleared = True
        logger.info("Cleared transcode cache for track %s (%s)", track.title, file_path.name)

    if cache_cleared:
        logger.info("Playback error reported for track %s (%s) — cache cleared, retry may help", track.title, file_path.name)
        return {"status": "retry", "reason": "cache_cleared"}

    logger.info("Playback error reported for track %s (%s) — skipped", track.title, file_path.name)
    return {"status": "skip", "reason": "no_cache"}


@router.get("/{track_id}/artwork")
async def get_track_artwork(
    db: DbSession,
    track_id: UUID,
    size: str = Query("full", pattern="^(full|thumb)$"),
) -> StreamingResponse:
    """Get album artwork for a track.

    Artwork is extracted from the audio file on first request and cached.
    """
    from sqlalchemy import select

    # Get track from database (only ACTIVE tracks)
    query = select(Track).where(Track.id == track_id, Track.active_filter())
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise TrackNotFoundError()

    # Compute album hash
    album_hash = compute_album_hash(track.artist, track.album)
    artwork_path = get_artwork_path(album_hash, size)

    # Check if artwork exists on disk
    if not artwork_path.exists():
        # Try to extract from audio file
        file_path = Path(track.file_path)
        if file_path.exists():
            from app.services.artwork import extract_and_save_artwork
            extract_and_save_artwork(file_path, track.artist, track.album)

        # Check again
        if not artwork_path.exists():
            raise NotFoundError("No artwork available")

    # Stream the artwork file
    def stream_artwork() -> Iterator[bytes]:
        with open(artwork_path, "rb") as f:
            yield f.read()

    return StreamingResponse(
        stream_artwork(),  # type: ignore[no-untyped-call]
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=31536000",  # Cache for 1 year
        },
    )


@router.post("/{track_id}/artwork", response_model=ArtworkUploadResponse)
async def upload_track_artwork(
    db: DbSession,
    track_id: UUID,
    file: UploadFile,
) -> ArtworkUploadResponse:
    """Upload or replace album artwork for a track.

    The artwork is saved to the cache.
    All tracks from the same album will share this artwork.

    Accepts JPEG, PNG, or WebP images up to 10MB.
    """
    from sqlalchemy import select

    from app.services.artwork import compute_album_hash, save_artwork

    # Validate content type
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise ValidationError("Invalid image type", detail=f"Allowed: {', '.join(ALLOWED_IMAGE_TYPES)}")

    # Read file data
    image_data = await file.read()

    if len(image_data) > MAX_ARTWORK_SIZE:
        raise ValidationError("Image too large", detail=f"Max size: {MAX_ARTWORK_SIZE // 1024 // 1024}MB")

    if len(image_data) == 0:
        raise ValidationError("Empty file uploaded")

    # Get track
    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise TrackNotFoundError()

    # Save to cache
    album_hash = compute_album_hash(track.artist, track.album)
    saved_paths = save_artwork(image_data, album_hash)
    saved_to_cache = len(saved_paths) > 0

    return ArtworkUploadResponse(
        success=saved_to_cache,
        message="Artwork uploaded successfully" if saved_to_cache else "Failed to save artwork",
        embedded_in_file=False,
        saved_to_cache=saved_to_cache,
    )


@router.delete("/{track_id}/artwork", response_model=ArtworkUploadResponse)
async def delete_track_artwork(
    db: DbSession,
    track_id: UUID,
) -> ArtworkUploadResponse:
    """Remove album artwork for a track.

    Removes artwork from the cache.
    Note: This affects all tracks from the same album.
    """
    from sqlalchemy import select

    from app.services.artwork import compute_album_hash, get_artwork_path

    # Get track
    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise TrackNotFoundError()

    # Remove cached artwork
    album_hash = compute_album_hash(track.artist, track.album)
    removed_cache = False

    for size in ["full", "thumb"]:
        artwork_path = get_artwork_path(album_hash, size)
        if artwork_path.exists():
            artwork_path.unlink()
            removed_cache = True

    if not removed_cache:
        return ArtworkUploadResponse(
            success=False,
            message="No cached artwork found to remove",
            embedded_in_file=False,
            saved_to_cache=False,
        )

    return ArtworkUploadResponse(
        success=True,
        message="Artwork removed from cache",
        embedded_in_file=False,
        saved_to_cache=False,
    )


def _empty_lyrics() -> LyricsResponse:
    """An empty (no-lyrics) response — returned on a genuine miss so the client
    can distinguish 'no lyrics for this track' from an actual error."""
    return LyricsResponse(synced=False, lines=[], plain_text="", source="none")


@router.get("/{track_id}/lyrics", response_model=LyricsResponse)
async def get_track_lyrics(
    db: DbSession,
    track_id: UUID,
) -> LyricsResponse:
    """
    Get lyrics for a track.

    Returns synced lyrics with timestamps when available. Results are cached on
    the track (``synced_lyrics``) so repeat requests don't re-hit LRCLIB. A
    genuine miss returns an empty 200 response (not a 404).
    """
    from sqlalchemy import select

    from app.services.lyrics import get_lyrics_service

    # Get track from database
    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise TrackNotFoundError()

    # Serve from cache when we've already fetched synced lyrics for this track.
    if track.synced_lyrics:
        cached = track.synced_lyrics
        return LyricsResponse(
            synced=cached.get("synced", False),
            lines=[
                LyricLineResponse(time=line["time"], text=line["text"])
                for line in cached.get("lines", [])
            ],
            plain_text=cached.get("plain_text", ""),
            source=cached.get("source", "cache"),
        )

    # Need title + artist to search; treat as a miss rather than erroring out.
    if not track.title or not track.artist:
        return _empty_lyrics()

    # Search for lyrics
    lyrics_service = get_lyrics_service()
    lyrics = await lyrics_service.search(
        track_name=track.title,
        artist_name=track.artist,
        album_name=track.album,
        duration=track.duration_seconds
    )

    if not lyrics:
        return _empty_lyrics()

    response = LyricsResponse(
        synced=lyrics.synced,
        lines=[LyricLineResponse(time=line.time, text=line.text) for line in lyrics.lines],
        plain_text=lyrics.plain_text,
        source=lyrics.source
    )

    # Cache only positive *synced* results — the visualizer needs the timing,
    # and a negative result shouldn't be pinned in case lyrics appear later.
    if lyrics.synced and lyrics.lines:
        track.synced_lyrics = {
            "synced": lyrics.synced,
            "lines": [{"time": line.time, "text": line.text} for line in lyrics.lines],
            "plain_text": lyrics.plain_text,
            "source": lyrics.source,
        }
        await db.commit()

    return response
