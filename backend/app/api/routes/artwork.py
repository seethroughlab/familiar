"""Artwork endpoints for proactive artwork downloading."""

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import DbSession
from app.api.exceptions import (
    ConflictError,
    NotFoundError,
    UnprocessableEntityError,
    ValidationError,
)
from app.services.album_resolver import album_key_for_tags
from app.services.artwork import get_artwork_path, should_refetch_online
from app.services.background import get_background_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/artwork", tags=["artwork"])


class ArtworkCoverageResponse(BaseModel):
    """How much of the library has real cover art.

    `total_albums` is counted the way `/library/albums` and `/library/stats` count, so the three
    agree (ADR-0058 point 6). It would have been easier to count canonical `Album` rows, and it
    would have been wrong: the dashboard tile beside this one says 3,927, and a coverage figure over
    a different denominator is the "plausible-looking number" that point exists to forbid.

    `generated` is broken out rather than folded into `with_artwork` because a generated placeholder
    is what the app draws when it has nothing — counting it as coverage would report a library with
    no cover art at all as fully covered.
    """

    total_albums: int
    with_artwork: int
    generated: int
    without_artwork: int


class RefetchGeneratedResponse(BaseModel):
    """What a bulk placeholder re-fetch queued."""

    considered: int
    queued: int
    skipped_recent: int


@router.post("/refetch-generated", response_model=RefetchGeneratedResponse)
async def refetch_generated_artwork(db: DbSession) -> RefetchGeneratedResponse:
    """Ask the internet again for every album currently showing a placeholder.

    **Bulk, because the per-album path only fires when an album scrolls into view.** Fixing the
    queue routes makes browsing self-healing, but reaching 661 placeholders that way means browsing
    past 661 albums. This queues them in one go.

    Placeholders only. An album with real art is never touched, and one whose placeholder was drawn
    inside `ARTWORK_REFETCH_INTERVAL` is left for later — `should_refetch_online` is the same rule
    the queue routes use, so a button press cannot bypass the rate limit that protects Last.fm and
    MusicBrainz from being asked about an artless album every day.

    Grouped exactly as `/artwork/coverage` groups, so "queued" is comparable with the "generated"
    figure shown beside the button. `/artwork/regenerate-stale` groups by bare `Track.artist` with
    no status filter and therefore agrees with neither; that is a separate defect, left alone here.
    """
    from sqlalchemy import TEXT, cast, func, select

    from app.db.models import Track, TrackStatus
    from app.services.artwork import compute_album_hash, is_generated_artwork

    album_artist_col = func.coalesce(func.nullif(Track.album_artist, ""), Track.artist)
    result = await db.execute(
        select(
            func.max(cast(Track.canonical_album_id, TEXT)).label("album_id"),
            func.max(album_artist_col).label("artist"),
            func.max(Track.album).label("album"),
        )
        .where(
            Track.status == TrackStatus.ACTIVE,
            Track.album.isnot(None),
            Track.album != "",
        )
        .group_by(func.lower(album_artist_col), func.lower(Track.album))
    )

    bg = get_background_manager()
    considered = 0
    queued = 0
    skipped_recent = 0

    for row in result.all():
        key = row.album_id or compute_album_hash(row.artist, row.album)
        if not is_generated_artwork(key):
            continue
        considered += 1
        if not should_refetch_online(key):
            skipped_recent += 1
            continue
        if await bg.queue_artwork_fetch(key, row.artist or "", row.album or ""):
            queued += 1

    logger.info(
        "Placeholder re-fetch: %d placeholders, %d queued, %d still inside the retry interval",
        considered, queued, skipped_recent,
    )
    return RefetchGeneratedResponse(
        considered=considered, queued=queued, skipped_recent=skipped_recent
    )


@router.get("/coverage", response_model=ArtworkCoverageResponse)
async def get_artwork_coverage(db: DbSession) -> ArtworkCoverageResponse:
    """Count albums with, without, and with only placeholder cover art.

    ADR-0058 phase 5. Artwork existence is a fact about the filesystem, not the database — there is
    no column recording it — so this stats one thumbnail path per album. That is ~4k stat calls on
    Jeff's library, which is why it runs in a worker thread rather than blocking the event loop, and
    why it is its own endpoint rather than three more fields on `/library/stats`: the dashboard
    should not pay for a filesystem sweep on every load.
    """
    import asyncio

    from sqlalchemy import TEXT, cast, func, select

    from app.db.models import Track, TrackStatus
    from app.services.artwork import compute_album_hash, is_generated_artwork

    # Same grouping as `library_albums.list_albums` and `library.get_library_stats`. The id is cast
    # to text for the same reason that module casts: PostgreSQL has no `max()` over uuid.
    album_artist_col = func.coalesce(func.nullif(Track.album_artist, ""), Track.artist)
    result = await db.execute(
        select(
            func.max(cast(Track.canonical_album_id, TEXT)).label("album_id"),
            func.max(album_artist_col).label("artist"),
            func.max(Track.album).label("album"),
        )
        .where(
            Track.status == TrackStatus.ACTIVE,
            Track.album.isnot(None),
            Track.album != "",
        )
        .group_by(func.lower(album_artist_col), func.lower(Track.album))
    )
    rows = result.all()

    def survey() -> tuple[int, int]:
        """Stat every album's thumbnail. Runs off the event loop."""
        found = 0
        placeholder = 0
        for row in rows:
            # Mirrors `album_key_for_track`: the canonical id when the resolver placed the album,
            # the legacy hash when it could not.
            key = row.album_id or compute_album_hash(row.artist, row.album)
            if get_artwork_path(key, "thumb").exists():
                found += 1
                if is_generated_artwork(key):
                    placeholder += 1
        return found, placeholder

    with_artwork, generated = await asyncio.to_thread(survey)

    return ArtworkCoverageResponse(
        total_albums=len(rows),
        with_artwork=with_artwork,
        generated=generated,
        without_artwork=len(rows) - with_artwork,
    )


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

    #: True when the cover on disk is one Familiar drew, not one it fetched.
    #:
    #: **`exists` alone cannot answer "does this album have artwork".** A placeholder is a real file,
    #: so it says yes — which is how 661 albums sat on drawn covers without anything noticing, and
    #: why the queue routes could report "exists" for art nobody had ever found. The batch endpoint
    #: below has always distinguished the two; this one did not, so a caller's answer depended on
    #: which of the two it happened to ask.
    generated: bool = False

    #: When the placeholder was drawn, which is also when the internet was last asked.
    #:
    #: Present so a caller can tell "we tried yesterday and found nothing" from "we tried a year
    #: ago" without knowing `ARTWORK_REFETCH_INTERVAL`. Null for real art.
    generated_at: datetime | None = None


@router.post("/queue", status_code=202)
async def queue_artwork_download(
    db: DbSession, request: ArtworkQueueRequest
) -> dict[str, Any]:
    """Queue a single album for artwork download.

    Returns immediately (202 Accepted). Artwork will be fetched in background.
    """
    album_hash = await album_key_for_tags(db, request.artist, request.album)

    # Artwork already exists — unless it is a placeholder due another try (ADR-free bug fix; see
    # `should_refetch_online`). Testing `exists()` alone reported "done" for a picture Familiar drew
    # itself, which is what made a generated cover permanent.
    full_path = get_artwork_path(album_hash, "full")
    if full_path.exists() and not should_refetch_online(album_hash):
        return {
            "status": "exists",
            "album_hash": album_hash,
            "message": "Artwork already exists",
        }

    # Queue for background download
    bg = get_background_manager()
    await bg.queue_artwork_fetch(
        album_key=album_hash,
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
async def queue_artwork_batch(
    db: DbSession, request: ArtworkQueueBatchRequest
) -> dict[str, Any]:
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

    # `results` carries the key back per item, which is what lets the browser stop
    # deriving it. `packages/frontend/src/utils/albumHash.ts` reimplemented
    # `normalize_for_matching` *and* SHA-256 in JavaScript to guess this value, with a
    # comment conceding "toLowerCase is close enough for JS" where Python casefolds — so
    # the two could disagree, and when they did the album silently rendered blank. Since
    # ADR-0052 the key is an `Album.id`, which nothing in a browser could ever derive.
    results: list[dict[str, Any]] = []

    for item in request.items:
        album_key = await album_key_for_tags(db, item.artist, item.album)

        def record(status: str) -> None:
            results.append(
                {
                    "artist": item.artist,
                    "album": item.album,
                    "album_key": album_key,
                    "status": status,
                }
            )

        # Skip duplicates in this batch
        if album_key in seen_hashes:
            record("duplicate")
            continue
        seen_hashes.add(album_key)

        # Same rule as the single-album route above — these two have drifted before, so the
        # condition is shared rather than restated.
        full_path = get_artwork_path(album_key, "full")
        if full_path.exists() and not should_refetch_online(album_key):
            exists.append(album_key)
            record("exists")
            continue

        # Check if already pending (queued or in progress from previous request)
        if fetcher.is_pending(album_key):
            pending.append(album_key)
            record("pending")
            continue

        # Queue for background download
        was_queued = await bg.queue_artwork_fetch(
            album_key=album_key,
            artist=item.artist,
            album=item.album,
            track_id=item.track_id,
        )
        if was_queued:
            queued.append(album_key)
            record("queued")
        else:
            # Recently failed — the client shows a placeholder rather than polling.
            record("skipped")

    logger.info(f"Batch result: queued={len(queued)}, existing={len(exists)}, pending={len(pending)}")
    return {
        "status": "accepted",
        "queued_count": len(queued),
        "existing_count": len(exists),
        "queued_hashes": queued,
        "existing_hashes": exists,
        "pending_hashes": pending,  # Already being fetched
        "results": results,
    }


@router.get("/status/{album_hash}")
async def get_artwork_status(album_hash: str) -> ArtworkStatusResponse:
    """Check whether artwork exists for an album hash, and whether it is real.

    Reports the same provenance the batch endpoint reports. It did not, and the asymmetry is what
    let a placeholder pass for artwork everywhere a caller used this one.
    """
    from app.services.artwork import _generated_marker_path, is_generated_artwork

    full_path = get_artwork_path(album_hash, "full")
    thumb_path = get_artwork_path(album_hash, "thumb")
    generated = is_generated_artwork(album_hash)

    generated_at: datetime | None = None
    if generated:
        try:
            generated_at = datetime.fromtimestamp(
                _generated_marker_path(album_hash).stat().st_mtime, tz=UTC
            )
        except OSError:
            # Raced with a real cover landing and clearing the marker. Not an error: the album
            # simply has real art now, which the next call will report.
            generated = False

    return ArtworkStatusResponse(
        album_hash=album_hash,
        exists=full_path.exists() and thumb_path.exists(),
        generated=generated,
        generated_at=generated_at,
    )


@router.get("/{album_hash}/{size}")
async def get_artwork_by_hash(album_hash: str, size: str) -> Any:
    """Get artwork by album hash.

    This is the preferred endpoint for fetching artwork as it uses
    the stable album hash directly rather than requiring a track ID.
    """
    from starlette.responses import FileResponse

    if size not in ("full", "thumb"):
        raise ValidationError("Size must be 'full' or 'thumb'")

    artwork_path = get_artwork_path(album_hash, size)

    if not artwork_path.exists():
        raise NotFoundError("Artwork not found")

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
async def regenerate_artwork(
    db: DbSession, request: ArtworkRegenerateRequest
) -> dict[str, Any]:
    """Force-regenerate artwork from audio analysis features.

    Only works if artwork is currently generated or missing (refuses to
    overwrite real art). Useful after re-analysis to get updated generative art.
    """
    from app.services.artwork import is_generated_artwork

    album_hash = await album_key_for_tags(db, request.artist, request.album)
    full_path = get_artwork_path(album_hash, "full")

    if full_path.exists() and not is_generated_artwork(album_hash):
        raise ConflictError("Album has real artwork — will not overwrite with generated art")

    from app.services.generative_art import generate_album_art

    success = await generate_album_art(album_hash, request.artist, request.album)

    if success:
        return {"status": "regenerated", "album_hash": album_hash}
    else:
        raise UnprocessableEntityError("No analyzed tracks available for generation")


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
        album_hash = await album_key_for_tags(db, artist, album)
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
async def check_artwork_exists(db: DbSession, artist: str, album: str) -> None:
    """Fast HEAD request to check if artwork exists.

    Returns 200 if artwork exists, 404 if not.
    Used by frontend for quick existence checks without body overhead.
    """
    album_hash = await album_key_for_tags(db, artist, album)
    full_path = get_artwork_path(album_hash, "full")

    if not full_path.exists():
        raise NotFoundError("Artwork not found")

    # 200 OK (no body for HEAD request)
