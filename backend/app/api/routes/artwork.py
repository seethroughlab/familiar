"""Artwork endpoints for proactive artwork downloading."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import DbSession
from app.services.artwork import compute_album_hash, get_artwork_path
from app.services.background import get_background_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/artwork", tags=["artwork"])


class ArtworkQueueRequest(BaseModel):
    """Request to queue artwork for download."""

    artist: str
    album: str
    track_id: str | None = None  # Optional track ID for fallback extraction


class ArtworkQueueBatchRequest(BaseModel):
    """Request to queue multiple artworks for download."""

    items: list[ArtworkQueueRequest]


class ArtworkStatusResponse(BaseModel):
    """Response with artwork status."""

    album_hash: str
    exists: bool
    queued: bool = False


@router.post("/queue", status_code=202)
async def queue_artwork_download(request: ArtworkQueueRequest) -> dict[str, Any]:
    """Queue a single album for artwork download.

    Returns immediately (202 Accepted). Artwork will be fetched in background.
    """
    album_hash = compute_album_hash(request.artist, request.album)

    # Check if artwork already exists
    full_path = get_artwork_path(album_hash, "full")
    if full_path.exists():
        return {
            "status": "exists",
            "album_hash": album_hash,
            "message": "Artwork already exists",
        }

    # Queue for background download
    bg = get_background_manager()
    await bg.queue_artwork_fetch(
        album_hash=album_hash,
        artist=request.artist,
        album=request.album,
        track_id=request.track_id,
    )

    return {
        "status": "queued",
        "album_hash": album_hash,
        "message": "Artwork queued for download",
    }


@router.post("/queue/batch", status_code=202)
async def queue_artwork_batch(request: ArtworkQueueBatchRequest) -> dict[str, Any]:
    """Queue multiple albums for artwork download.

    Returns immediately (202 Accepted). Artworks will be fetched in background.
    Duplicates and existing artworks are automatically filtered.
    """
    from app.services.artwork_fetcher import get_artwork_fetcher

    bg = get_background_manager()
    fetcher = get_artwork_fetcher()

    queued = []
    exists = []
    pending = []  # Already in queue or in progress from previous request
    seen_hashes: set[str] = set()

    for item in request.items:
        album_hash = compute_album_hash(item.artist, item.album)
        logger.info(f"Queue batch: '{item.artist}' - '{item.album}' -> hash: {album_hash}")

        # Skip duplicates in this batch
        if album_hash in seen_hashes:
            continue
        seen_hashes.add(album_hash)

        # Check if artwork already exists
        full_path = get_artwork_path(album_hash, "full")
        logger.info(f"Checking path {full_path} exists: {full_path.exists()}")
        if full_path.exists():
            exists.append(album_hash)
            logger.info(f"Album exists: {album_hash}")
            continue

        # Check if already pending (queued or in progress from previous request)
        if fetcher.is_pending(album_hash):
            pending.append(album_hash)
            continue

        # Queue for background download
        was_queued = await bg.queue_artwork_fetch(
            album_hash=album_hash,
            artist=item.artist,
            album=item.album,
            track_id=item.track_id,
        )
        if was_queued:
            queued.append(album_hash)
        # If not queued here, it must have been recently failed - frontend will treat as 'missing'

    logger.info(f"Batch result: queued={len(queued)}, existing={len(exists)}, pending={len(pending)}")
    return {
        "status": "accepted",
        "queued_count": len(queued),
        "existing_count": len(exists),
        "queued_hashes": queued,
        "existing_hashes": exists,
        "pending_hashes": pending,  # Already being fetched
    }


@router.get("/status/{album_hash}")
async def get_artwork_status(album_hash: str) -> ArtworkStatusResponse:
    """Check if artwork exists for an album hash."""
    full_path = get_artwork_path(album_hash, "full")
    thumb_path = get_artwork_path(album_hash, "thumb")

    return ArtworkStatusResponse(
        album_hash=album_hash,
        exists=full_path.exists() and thumb_path.exists(),
    )


@router.get("/{album_hash}/{size}")
async def get_artwork_by_hash(album_hash: str, size: str) -> Any:
    """Get artwork by album hash.

    This is the preferred endpoint for fetching artwork as it uses
    the stable album hash directly rather than requiring a track ID.
    """
    from starlette.responses import FileResponse

    if size not in ("full", "thumb"):
        raise HTTPException(status_code=400, detail="Size must be 'full' or 'thumb'")

    artwork_path = get_artwork_path(album_hash, size)

    if not artwork_path.exists():
        raise HTTPException(status_code=404, detail="Artwork not found")

    return FileResponse(
        artwork_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000"},
    )


class ArtworkStatusBatchRequest(BaseModel):
    """Request to check status of multiple album hashes."""

    hashes: list[str]


class ArtworkStatusBatchResponse(BaseModel):
    """Response with status for multiple album hashes."""

    status: dict[str, bool]  # hash -> exists
    failed: list[str] = []  # hashes that failed to fetch (stop polling)
    generated: list[str] = []  # hashes where art is generated (not real)


@router.post("/status/batch")
async def check_artwork_batch(request: ArtworkStatusBatchRequest) -> ArtworkStatusBatchResponse:
    """Check if artwork exists for multiple album hashes.

    Returns a map of hash -> exists (bool) and list of failed hashes.
    Used by frontend to poll for artwork completion.
    """
    from app.services.artwork import is_generated_artwork
    from app.services.artwork_fetcher import get_artwork_fetcher

    fetcher = get_artwork_fetcher()
    result = {}
    failed = []
    generated = []

    for h in request.hashes:
        thumb_path = get_artwork_path(h, "thumb")
        if thumb_path.exists():
            result[h] = True
            if is_generated_artwork(h):
                generated.append(h)
        elif fetcher.is_failed(h):
            result[h] = False
            failed.append(h)
        else:
            # Still pending - not yet processed or currently in progress
            result[h] = False

    return ArtworkStatusBatchResponse(status=result, failed=failed, generated=generated)


class ArtworkRegenerateRequest(BaseModel):
    """Request to regenerate artwork for an album."""

    artist: str
    album: str


@router.post("/regenerate")
async def regenerate_artwork(request: ArtworkRegenerateRequest) -> dict[str, Any]:
    """Force-regenerate artwork from audio analysis features.

    Only works if artwork is currently generated or missing (refuses to
    overwrite real art). Useful after re-analysis to get updated generative art.
    """
    from app.services.artwork import is_generated_artwork

    album_hash = compute_album_hash(request.artist, request.album)
    full_path = get_artwork_path(album_hash, "full")

    if full_path.exists() and not is_generated_artwork(album_hash):
        raise HTTPException(
            status_code=409,
            detail="Album has real artwork — will not overwrite with generated art",
        )

    from app.services.generative_art import generate_album_art

    success = await generate_album_art(album_hash, request.artist, request.album)

    if success:
        return {"status": "regenerated", "album_hash": album_hash}
    else:
        raise HTTPException(
            status_code=422,
            detail="No analyzed tracks available for generation",
        )


@router.post("/regenerate-stale")
async def regenerate_stale_artwork(db: DbSession) -> dict[str, Any]:
    """Regenerate all generated artwork that is older than the current art version.

    Returns count of albums queued for regeneration.
    """
    from sqlalchemy import distinct, select

    from app.config import GENERATIVE_ART_VERSION
    from app.db.models import Track
    from app.services.artwork import is_generated_art_current, is_generated_artwork
    from app.services.generative_art import generate_album_art

    # Find all distinct artist/album pairs
    stmt = select(distinct(Track.artist), Track.album).where(
        Track.artist.isnot(None), Track.album.isnot(None)
    )
    result = await db.execute(stmt)
    albums = result.all()

    regenerated = 0
    failed = 0
    for artist, album in albums:
        album_hash = compute_album_hash(artist, album)
        if is_generated_artwork(album_hash) and not is_generated_art_current(album_hash):
            success = await generate_album_art(album_hash, artist, album)
            if success:
                regenerated += 1
            else:
                failed += 1

    return {
        "status": "done",
        "version": GENERATIVE_ART_VERSION,
        "regenerated": regenerated,
        "failed": failed,
    }


@router.head("/check/{artist}/{album}")
async def check_artwork_exists(artist: str, album: str) -> None:
    """Fast HEAD request to check if artwork exists.

    Returns 200 if artwork exists, 404 if not.
    Used by frontend for quick existence checks without body overhead.
    """
    album_hash = compute_album_hash(artist, album)
    full_path = get_artwork_path(album_hash, "full")

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Artwork not found")

    # 200 OK (no body for HEAD request)
