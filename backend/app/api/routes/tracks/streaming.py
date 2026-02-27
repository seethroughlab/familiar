"""Track streaming, artwork, and lyrics endpoints."""

import asyncio
import logging
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import DbSession
from app.db.models import Track
from app.services.artwork import compute_album_hash, get_artwork_path

from . import AUDIO_MIME_TYPES

logger = logging.getLogger(__name__)

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
    background_tasks: BackgroundTasks,
) -> StreamingResponse:
    """Stream audio file with range request support for seeking."""
    from sqlalchemy import select

    # Get track from database
    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        logger.warning("Stream request for unknown track_id=%s", track_id)
        raise HTTPException(status_code=404, detail="Track not found")

    # Trigger auto-enrichment in background if track has incomplete metadata
    from app.services.metadata_enrichment import needs_enrichment
    from app.services.tasks import propose_enrichment_for_track

    if needs_enrichment(track, check_artwork=False):
        background_tasks.add_task(propose_enrichment_for_track, str(track.id))

    file_path = Path(track.file_path)
    if not file_path.exists():
        logger.warning("Audio file missing: track_id=%s path=%s", track_id, file_path)
        raise HTTPException(status_code=404, detail="Audio file not found")

    # Fix FLAC files missing PTS timestamps (causes Chromium playback errors)
    if file_path.suffix.lower() == ".flac":
        from app.services.flac_remux import needs_remux, remux_flac_in_place

        try:
            if await needs_remux(file_path):
                logger.info("Re-muxing FLAC for PTS fix: %s", file_path.name)
                await remux_flac_in_place(file_path)
                # Update hash/size so scanner doesn't detect false change
                from app.services.scanner import compute_file_hash

                track.file_hash = compute_file_hash(file_path)
                track.file_size = file_path.stat().st_size
                track.file_modified_at = datetime.fromtimestamp(
                    file_path.stat().st_mtime
                )
                await db.commit()
        except Exception:
            logger.warning(
                "FLAC PTS check/re-mux failed for %s, serving as-is",
                track_id,
                exc_info=True,
            )

    # Transcode formats that browsers can't natively decode
    if file_path.suffix.lower() in TRANSCODE_EXTENSIONS:
        logger.debug("Transcoding track_id=%s path=%s to FLAC", track_id, file_path)
        return await _stream_transcoded(file_path)

    mime_type = get_audio_mime_type(file_path)
    logger.debug("Streaming track_id=%s path=%s type=%s", track_id, file_path, mime_type)

    from app.api.streaming import stream_file
    return await stream_file(file_path, request, mime_type)


async def _stream_transcoded(file_path: Path) -> StreamingResponse:
    """Transcode an audio file to FLAC via ffmpeg and stream the result."""
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-i", str(file_path), "-f", "flac", "-loglevel", "error", "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def stream_output():
        assert process.stdout is not None
        try:
            while chunk := await process.stdout.read(64 * 1024):
                yield chunk
        finally:
            await process.wait()

    return StreamingResponse(
        stream_output(),
        media_type="audio/flac",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.post("/{track_id}/report-playback-error")
async def report_playback_error(
    db: DbSession,
    track_id: UUID,
    background_tasks: BackgroundTasks,
) -> dict:
    """Report a client-side playback/decode error for a track.

    Triggers background validation and re-encoding of the audio file
    so it works on next playback.
    """
    from sqlalchemy import select

    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    file_path = Path(track.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    logger.info("Playback error reported for track %s (%s)", track.title, file_path.name)
    background_tasks.add_task(_validate_and_fix_track, str(track_id))
    return {"status": "queued"}


async def _validate_and_fix_track(track_id: str) -> None:
    """Background task: validate audio file and re-encode if errors found."""
    from sqlalchemy import select

    from app.db.session import async_session_maker

    async with async_session_maker() as db:
        query = select(Track).where(Track.id == track_id)
        result = await db.execute(query)
        track = result.scalar_one_or_none()
        if not track:
            return

        file_path = Path(track.file_path)
        if not file_path.exists():
            return

        from app.services.flac_remux import (
            REMUX_FORMATS,
            has_decode_errors,
            reencode_flac_in_place,
            remux_audio_in_place,
        )

        try:
            if not await has_decode_errors(file_path):
                logger.info("No decode errors found in %s, skipping re-encode", file_path.name)
                return

            suffix = file_path.suffix.lower()
            if suffix == ".flac":
                logger.info("Re-encoding %s to fix decode errors", file_path.name)
                await reencode_flac_in_place(file_path)
            elif suffix in REMUX_FORMATS:
                logger.info("Re-muxing %s to fix container/header issues", file_path.name)
                await remux_audio_in_place(file_path)
            else:
                logger.warning("Unsupported format for repair: %s", file_path.name)
                return

            # Update hash/size so scanner doesn't detect false change
            from app.services.scanner import compute_file_hash

            track.file_hash = compute_file_hash(file_path)
            track.file_size = file_path.stat().st_size
            track.file_modified_at = datetime.fromtimestamp(file_path.stat().st_mtime)
            await db.commit()
            logger.info("Successfully re-encoded %s", file_path.name)
        except Exception:
            logger.exception("Failed to validate/re-encode %s", file_path.name)


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

    # Get track from database
    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

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
            raise HTTPException(status_code=404, detail="No artwork available")

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
    embed_in_file: bool = Query(True, description="Embed artwork in audio file tags"),
) -> ArtworkUploadResponse:
    """Upload or replace album artwork for a track.

    The artwork is saved to the cache and optionally embedded in the audio file.
    All tracks from the same album will share this artwork.

    Accepts JPEG, PNG, or WebP images up to 10MB.
    """
    from sqlalchemy import select

    from app.services.artwork import compute_album_hash, save_artwork
    from app.services.metadata_writer import write_artwork

    # Validate content type
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid image type. Allowed: {', '.join(ALLOWED_IMAGE_TYPES)}",
        )

    # Read file data
    image_data = await file.read()

    if len(image_data) > MAX_ARTWORK_SIZE:
        raise HTTPException(
            status_code=400, detail=f"Image too large. Max size: {MAX_ARTWORK_SIZE // 1024 // 1024}MB"
        )

    if len(image_data) == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

    # Get track
    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    # Save to cache
    album_hash = compute_album_hash(track.artist, track.album)
    saved_paths = save_artwork(image_data, album_hash)
    saved_to_cache = len(saved_paths) > 0

    # Embed in file if requested
    embedded_in_file = False
    embed_error = None

    if embed_in_file:
        file_path = Path(track.file_path)
        if file_path.exists():
            write_result = write_artwork(file_path, image_data, file.content_type or "image/jpeg")
            embedded_in_file = write_result.success
            if not write_result.success:
                embed_error = write_result.error

    message = "Artwork uploaded successfully"
    if embed_in_file and not embedded_in_file:
        message = f"Artwork saved to cache but failed to embed in file: {embed_error}"

    return ArtworkUploadResponse(
        success=saved_to_cache or embedded_in_file,
        message=message,
        embedded_in_file=embedded_in_file,
        saved_to_cache=saved_to_cache,
    )


@router.delete("/{track_id}/artwork", response_model=ArtworkUploadResponse)
async def delete_track_artwork(
    db: DbSession,
    track_id: UUID,
    remove_from_file: bool = Query(False, description="Also remove embedded artwork from audio file"),
) -> ArtworkUploadResponse:
    """Remove album artwork for a track.

    Removes artwork from the cache. Optionally removes embedded artwork from the audio file.
    Note: This affects all tracks from the same album.
    """
    from sqlalchemy import select

    from app.services.artwork import compute_album_hash, get_artwork_path

    # Get track
    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    # Remove cached artwork
    album_hash = compute_album_hash(track.artist, track.album)
    removed_cache = False

    for size in ["full", "thumb"]:
        artwork_path = get_artwork_path(album_hash, size)
        if artwork_path.exists():
            artwork_path.unlink()
            removed_cache = True

    # Remove from file if requested (this is destructive and format-specific)
    removed_from_file = False
    if remove_from_file:
        # For now, we don't implement removal from files as it's risky
        # The user can re-embed new artwork instead
        pass

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
        embedded_in_file=removed_from_file,
        saved_to_cache=False,
    )


@router.get("/{track_id}/lyrics", response_model=LyricsResponse | None)
async def get_track_lyrics(
    db: DbSession,
    track_id: UUID,
) -> LyricsResponse | None:
    """
    Get lyrics for a track.
    Returns synced lyrics with timestamps if available, otherwise plain lyrics.
    """
    from sqlalchemy import select

    from app.services.lyrics import get_lyrics_service

    # Get track from database
    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    if not track.title or not track.artist:
        raise HTTPException(
            status_code=400,
            detail="Track must have title and artist to search for lyrics"
        )

    # Search for lyrics
    lyrics_service = get_lyrics_service()
    lyrics = await lyrics_service.search(
        track_name=track.title,
        artist_name=track.artist,
        album_name=track.album,
        duration=track.duration_seconds
    )

    if not lyrics:
        raise HTTPException(status_code=404, detail="No lyrics found")

    return LyricsResponse(
        synced=lyrics.synced,
        lines=[LyricLineResponse(time=line.time, text=line.text) for line in lyrics.lines],
        plain_text=lyrics.plain_text,
        source=lyrics.source
    )
