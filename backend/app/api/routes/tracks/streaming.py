"""Track streaming, artwork, and lyrics endpoints."""

import asyncio
import functools
import hashlib
import logging
import random
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal, TypeVar
from uuid import UUID

from fastapi import APIRouter, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.concurrency import encoder_limiter
from app.api.deps import DbSession, release_connection
from app.api.exceptions import NotFoundError, TrackNotFoundError, TranscodeError, ValidationError
from app.config import settings
from app.db.models import Track
from app.db.session import async_session_maker
from app.services.artwork import album_key_for_track, get_artwork_path
from app.services.flac_remux import AAC, FLAC, TranscodeTarget, transcode_to_file
from app.services.lyrics import (
    LyricLine,
    LyricsOutcome,
    LyricsResult,
    LyricsStatus,
)
from app.services.quality import is_lossless_source

from . import AUDIO_MIME_TYPES

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: ADR-0163 point 7. LRCLIB is user-contributed and grows, so a miss is not forever; the jitter keeps
#: a library's worth of misses from all expiring in the same hour.
LYRICS_MISS_TTL_SECONDS = 14 * 24 * 3600
LYRICS_MISS_TTL_JITTER_SECONDS = 2 * 24 * 3600

# Per-(track, target) locks to prevent redundant concurrent transcodes. Keyed on the target too,
# since ADR-0118: a track's FLAC remux and its AAC encode are different files and may run at once.
_transcode_locks: dict[tuple[UUID, str], asyncio.Lock] = {}
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
    #: ADR-0163 point 5. A plain string, not an enum: a generated client's enum is closed, and one
    #: new value would fail the whole decode. Optional, so a client built before it still decodes.
    status: str | None = Field(
        default=None,
        description=(
            "found, plain_only, instrumental, not_found or unavailable. `unavailable` says nothing "
            "about the track: the lyrics service could not be asked, so try again later."
        ),
    )


@router.get(
    "/{track_id}/stream", tags=["tracks"],
    # Declare the real media type. Without this the schema claims application/json and a
    # generated client would try to JSON-decode audio (ADR-0007). This endpoint is
    # hand-written per platform; the schema only needs to describe it honestly.
    response_class=FileResponse,
    responses={
        200: {
            "content": {"audio/*": {}},
            "description": "Whole audio file.",
        },
        # The usual response during playback, and previously undeclared.
        206: {
            "content": {"audio/*": {}},
            "description": "Partial content for a Range request (seeking, buffering).",
        },
        416: {"description": "Requested range is not satisfiable."},
    },
)
async def stream_track(
    db: DbSession,
    track_id: UUID,
    request: Request,
    format: Literal["aac"] | None = Query(
        None,
        description=(
            "Ask for the track no larger than AAC (ADR-0118). A lossless source is encoded to "
            "256 kbps AAC in an MP4 container, once, and cached; a lossy source is served exactly "
            "as it is, with its own media type — an MP3 stays an MP3. Name the file from the "
            "response, not from this parameter. Omit it and the library file is served."
        ),
    ),
) -> FileResponse:
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

    # Everything the response needs is now a plain value, so the connection can go back.
    #
    # **This is the endpoint that exhausted the pool.** A `yield` dependency is held until the
    # response finishes *sending*, so before this line every in-flight download pinned a connection
    # for the whole transfer — one per concurrent download, against a pool of 40. Bulk-downloading
    # 1,720 favourites on 2026-08-02 produced 2,416 `QueuePool limit ... timed out` errors, and the
    # Mac client stored 834 of the resulting 500 bodies as `.mp3`.
    #
    # Read `track` into locals *first*: after this, touching a lazy attribute would begin a new
    # transaction and take another connection.
    needs_transcode = track.needs_transcode
    codec = track.codec
    await release_connection(db)

    # **ADR-0118: a phone asks for AAC and gets it only if the source is lossless.** Checked before
    # the two browser branches below so an AIFF asked for as AAC goes AIFF → AAC directly rather
    # than AIFF → FLAC → AAC. Decided by codec first and suffix second (`is_lossless_source`),
    # because an ALAC file is `.m4a` — the same suffix as the AAC it is not.
    #
    # A lossy source falls through to exactly what it got before this parameter existed. That is
    # point 2 of the decision and the property the tests guard hardest: the parameter means "no
    # larger than AAC", never "re-encode".
    if format == "aac" and is_lossless_source(file_path.suffix, codec):
        logger.debug("Encoding track_id=%s path=%s to AAC for download", track_id, file_path)
        return await _get_or_transcode(track_id, file_path, request, AAC)

    # Transcode tracks with browser-unsupported codecs
    if needs_transcode:
        logger.info("Transcoding (unsupported codec=%s) track_id=%s", codec, track_id)
        return await _get_or_transcode(track_id, file_path, request, FLAC)

    # Transcode formats that browsers can't natively decode
    if file_path.suffix.lower() in TRANSCODE_EXTENSIONS:
        logger.debug("Transcoding track_id=%s path=%s to FLAC", track_id, file_path)
        return await _get_or_transcode(track_id, file_path, request, FLAC)

    mime_type = get_audio_mime_type(file_path)
    logger.debug("Streaming track_id=%s path=%s type=%s", track_id, file_path, mime_type)

    from app.api.streaming import stream_file
    return await stream_file(file_path, request, mime_type)


async def _get_or_transcode(
    track_id: UUID, file_path: Path, request: Request, target: TranscodeTarget
) -> FileResponse:
    """Transcode audio to ``target`` (cached to disk), then serve via stream_file().

    Caching to disk ensures the served file has complete headers (FLAC's streaminfo +
    seektable, MP4's moov), Content-Length, and range request support — fixing PTS errors
    during crossfade that occurred with the previous chunked-stream approach. It is also
    why ADR-0118 declined to stream an encode as it runs.

    Uses per-(track, target) locking to prevent redundant concurrent transcodes.
    """
    from app.api.streaming import stream_file

    cache_dir = settings.transcode_cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{track_id}{target.cache_suffix}"

    # Acquire per-(track, target) lock to prevent redundant concurrent transcodes
    key = (track_id, target.name)
    async with _locks_lock:
        if key not in _transcode_locks:
            _transcode_locks[key] = asyncio.Lock()
        lock = _transcode_locks[key]

    async with lock:
        # Re-transcode if source is newer or cache doesn't exist
        needs_transcode = not cached.exists() or file_path.stat().st_mtime > cached.stat().st_mtime
        # Also re-transcode if cached file is empty (corrupt from prior crash)
        if not needs_transcode and cached.stat().st_size == 0:
            cached.unlink(missing_ok=True)
            needs_transcode = True

        if needs_transcode:
            # The encoder bound wraps the ffmpeg run only — not the lock, not the serve — so a
            # cache hit never waits on it and a waiter for the same track holds no encoder slot.
            await encoder_limiter.acquire()
            try:
                await transcode_to_file(file_path, cached, target)
            except RuntimeError:
                logger.exception("Transcode failed: track_id=%s path=%s", track_id, file_path)
                cached.unlink(missing_ok=True)
                raise TranscodeError(f"Failed to transcode {file_path.name}")
            finally:
                encoder_limiter.release()

    # Clean up lock if no one else is waiting
    async with _locks_lock:
        if key in _transcode_locks and not lock.locked():
            del _transcode_locks[key]

    return await stream_file(cached, request, target.mime_type)


class PlaybackErrorResponse(BaseModel):
    """Outcome of reporting a playback error for a track."""

    # 'retry' means a stale transcode was cleared and replaying may work;
    # 'skip' means nothing could be repaired.
    status: Literal["retry", "skip"]
    reason: Literal["cache_cleared", "no_cache"]


@router.post("/{track_id}/report-playback-error", tags=["plays"], response_model=PlaybackErrorResponse)
async def report_playback_error(
    db: DbSession,
    track_id: UUID,
) -> PlaybackErrorResponse:
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
    cache_file = settings.transcode_cache_dir / f"{track_id}.flac"
    cache_cleared = False
    if cache_file.exists():
        cache_file.unlink(missing_ok=True)
        cache_cleared = True
        logger.info("Cleared transcode cache for track %s (%s)", track.title, file_path.name)

    if cache_cleared:
        logger.info("Playback error reported for track %s (%s) — cache cleared, retry may help", track.title, file_path.name)
        return PlaybackErrorResponse(status="retry", reason="cache_cleared")

    logger.info("Playback error reported for track %s (%s) — skipped", track.title, file_path.name)
    return PlaybackErrorResponse(status="skip", reason="no_cache")


@router.get(
    "/{track_id}/artwork", tags=["tracks"],
    response_class=StreamingResponse,
    responses={200: {"content": {"image/*": {}}, "description": "Album artwork image."}},
)
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
    album_key = album_key_for_track(track)
    artwork_path = get_artwork_path(album_key, size)

    # Check if artwork exists on disk
    if not artwork_path.exists():
        # Try to extract from audio file
        file_path = Path(track.file_path)
        if file_path.exists():
            from app.services.artwork import extract_and_save_artwork
            extract_and_save_artwork(
                file_path, track.artist, track.album, album_key=album_key
            )

        # Check again
        if not artwork_path.exists():
            raise NotFoundError("No artwork available")

    # Artwork is small, but this endpoint is called once per visible row — a library grid asks for
    # dozens at a time, so holding a connection through each is the pool problem in miniature.
    # See `release_connection`.
    await release_connection(db)

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


@router.post("/{track_id}/artwork", tags=["tracks"], response_model=ArtworkUploadResponse)
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

    from app.services.artwork import album_key_for_track, save_artwork

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
    # The uploaded cover lands on the whole album, which is what the Mac's editor says
    # it does — and since ADR-0052 that is one key per record rather than one per track
    # artist, so it now reaches a compilation's other tracks too.
    album_key = album_key_for_track(track)
    saved_paths = save_artwork(image_data, album_key)
    saved_to_cache = len(saved_paths) > 0

    return ArtworkUploadResponse(
        success=saved_to_cache,
        message="Artwork uploaded successfully" if saved_to_cache else "Failed to save artwork",
        embedded_in_file=False,
        saved_to_cache=saved_to_cache,
    )


@router.delete("/{track_id}/artwork", tags=["tracks"], response_model=ArtworkUploadResponse)
async def delete_track_artwork(
    db: DbSession,
    track_id: UUID,
) -> ArtworkUploadResponse:
    """Remove album artwork for a track.

    Removes artwork from the cache.
    Note: This affects all tracks from the same album.
    """
    from sqlalchemy import select

    from app.services.artwork import album_key_for_track, get_artwork_path

    # Get track
    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise TrackNotFoundError()

    # Remove cached artwork
    album_key = album_key_for_track(track)
    removed_cache = False

    for size in ["full", "thumb"]:
        artwork_path = get_artwork_path(album_key, size)
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


def _lyrics_response(status: LyricsStatus, result: LyricsResult | None = None) -> LyricsResponse:
    if result is None:
        return LyricsResponse(
            synced=False, lines=[], plain_text="", source="none", status=status.value
        )
    return LyricsResponse(
        synced=result.synced,
        lines=[LyricLineResponse(time=line.time, text=line.text) for line in result.lines],
        plain_text=result.plain_text,
        source=result.source,
        status=status.value,
    )


def _lyrics_identity(track: Track) -> str:
    """What the stored answer was an answer to (ADR-0163 point 8).

    Compared on read, so a retag, an edit or a new sidecar re-resolves with nothing hooked into any of
    the paths that write those. The file's mtime covers its embedded tags.
    """
    from app.services.lyrics_local import sidecar_path

    def mtime(path: Path | None) -> int:
        try:
            return int(path.stat().st_mtime) if path else 0
        except OSError:
            return 0

    audio = Path(track.file_path) if track.file_path else None
    parts = [
        track.title or "",
        track.artist or "",
        track.album or "",
        track.album_artist or "",
        str(round(track.duration_seconds or 0)),
        hashlib.sha1((track.lyrics or "").encode()).hexdigest(),
        str(mtime(audio)),
        str(mtime(sidecar_path(audio) if audio else None)),
    ]
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()[:16]


def _miss_key(track_id: UUID, identity: str) -> str:
    return f"lyrics:miss:{track_id}:{identity}"


async def _remembered_miss(key: str) -> bool:
    """Fails open: a store that cannot answer costs one more lookup, never a wrong answer."""
    from app.services.redis_client import get_redis

    try:
        return bool(await _lyrics_thread(get_redis().exists, key))
    except Exception:
        logger.warning("Could not read the lyrics miss cache", exc_info=True)
        return False


async def _remember_miss(key: str) -> None:
    from app.services.redis_client import get_redis

    seconds = LYRICS_MISS_TTL_SECONDS + random.randint(0, LYRICS_MISS_TTL_JITTER_SECONDS)
    try:
        await _lyrics_thread(get_redis().setex, key, seconds, "1")
    except Exception:
        logger.warning("Could not write the lyrics miss cache", exc_info=True)


async def _store_lyrics(
    db: AsyncSession, track_id: UUID, identity: str, status: LyricsStatus, result: LyricsResult | None
) -> None:
    """Persist an answer **without moving `updated_at`**.

    `updated_at` is the library delta's cursor, and an ORM write would bump it through `onupdate`,
    re-sending the track to every phone for a change that is not in its payload.
    """
    payload = {
        "v": 2,
        "status": status.value,
        "identity": identity,
        "synced": bool(result and result.synced),
        "lines": [{"time": line.time, "text": line.text} for line in result.lines] if result else [],
        "plain_text": result.plain_text if result else "",
        "source": result.source if result else "none",
        "source_id": result.source_id if result else None,
    }
    await db.execute(
        update(Track)
        .where(Track.id == track_id)
        .values(synced_lyrics=payload, updated_at=Track.updated_at)
    )
    await db.commit()


def _cached(cached: dict[str, Any]) -> tuple[LyricsStatus, LyricsResult | None]:
    lines = [LyricLine(time=line["time"], text=line["text"]) for line in cached.get("lines", [])]
    synced = bool(cached.get("synced"))
    status = LyricsStatus(cached.get("status") or ("found" if synced else "plain_only"))
    if status == LyricsStatus.INSTRUMENTAL:
        return status, None
    return status, LyricsResult(
        synced=synced,
        lines=lines,
        plain_text=cached.get("plain_text", ""),
        source=cached.get("source", "cache"),
        source_id=cached.get("source_id"),
    )


@router.get("/{track_id}/lyrics", tags=["tracks"], response_model=LyricsResponse)
async def get_track_lyrics(
    db: DbSession,
    track_id: UUID,
) -> LyricsResponse:
    """
    Get lyrics for a track (ADR-0163).

    The listener's own lyrics first (an edit, a `.lrc` sidecar, the file's tags), then LRCLIB. The
    first synced source wins, otherwise the first plain one. `status` says which kind of answer this
    is; `unavailable` means LRCLIB could not be asked and says nothing about the track. Found, plain
    and instrumental answers are stored on the track, and a miss is remembered for about two weeks.
    """
    # Imported here like the other handlers' `select`: a module-level one shadows theirs, and mypy
    # then cannot type this module's `router` through the package's import cycle.
    from sqlalchemy import select

    track = (await db.execute(select(Track).where(Track.id == track_id))).scalar_one_or_none()
    if not track:
        raise TrackNotFoundError()

    identity = await _lyrics_thread(_lyrics_identity, track)
    cached = track.synced_lyrics
    if cached and cached.get("v") == 2 and cached.get("identity") == identity:
        return _lyrics_response(*_cached(cached))

    # A row stored before statuses existed is asked about once more, and kept if that cannot happen.
    legacy = _cached(cached) if cached and cached.get("v") is None and cached.get("lines") else None

    miss_key = _miss_key(track.id, identity)
    if legacy is None and await _remembered_miss(miss_key):
        return _lyrics_response(LyricsStatus.NOT_FOUND)

    title, artist, album = track.title, track.artist, track.album
    album_artist, duration = track.album_artist, track.duration_seconds
    file_path, edited = track.file_path, track.lyrics
    # Nothing below needs the row, and LRCLIB can take seconds: give the connection back first.
    # The lookup stores through a session of its own.
    await release_connection(db)

    # **Answered within a deadline, finished regardless.** The app's client gives up after ten
    # seconds without a byte, and a lookup once took 17.5 s: the phone said "Your server didn't
    # answer" while this went on to find and store the lyrics. So the work runs as its own task, the
    # request waits for it only so long, and an overrun answers `unavailable` (try again) while the
    # task finishes and stores. The app retries once, and then the stored answer is there. One task
    # per track: the app and the visualizer page often ask about the same track at the same moment.
    key = (track_id, identity)
    work = _LYRICS_IN_FLIGHT.get(key)
    if work is None:
        work = asyncio.ensure_future(_resolve_lyrics(
            track_id, identity, miss_key, legacy,
            title=title, artist=artist, album=album, album_artist=album_artist,
            duration=duration, file_path=file_path, edited=edited,
        ))
        _LYRICS_IN_FLIGHT[key] = work
        work.add_done_callback(lambda _: _LYRICS_IN_FLIGHT.pop(key, None))
    try:
        status, result = await asyncio.wait_for(asyncio.shield(work), LYRICS_DEADLINE_SECONDS)
    except TimeoutError:
        logger.info("Lyrics for %s are still being looked up; answering unavailable", track_id)
        return _lyrics_response(*legacy) if legacy else _lyrics_response(LyricsStatus.UNAVAILABLE)
    return _lyrics_response(status, result)


#: **The lyrics route's blocking work runs on threads of its own.** On 2026-11-07, with MusicBrainz
#: returning 503s, orphaned MusicBrainz threads filled the default executor, and lyrics requests took
#: 80-90 s: the stat, the kv lookup and the tag read all queued behind them, before the deadline
#: below had even started. MusicBrainz has its own executor now too; this keeps lyrics independent of
#: whatever else uses `asyncio.to_thread`.
_LYRICS_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="lyrics")


async def _lyrics_thread(func: Callable[..., T], /, *args: Any) -> T:
    return await asyncio.get_running_loop().run_in_executor(_LYRICS_EXECUTOR, functools.partial(func, *args))


#: Under the Apple client's ten-second inactivity timeout, with room for the request around it.
LYRICS_DEADLINE_SECONDS = 8.0

#: Lookups running now, by track and identity. A finished one removes itself.
_LYRICS_IN_FLIGHT: dict[tuple[UUID, str], asyncio.Future[tuple[LyricsStatus, LyricsResult | None]]] = {}


async def _resolve_lyrics(
    track_id: UUID,
    identity: str,
    miss_key: str,
    legacy: tuple[LyricsStatus, LyricsResult | None] | None,
    *,
    title: str | None,
    artist: str | None,
    album: str | None,
    album_artist: str | None,
    duration: float | None,
    file_path: str | None,
    edited: str | None,
) -> tuple[LyricsStatus, LyricsResult | None]:
    """The lookup and its storage, independent of the request that started it.

    Stores through a session of its own: it can outlive the request, and the request's session is
    closed when the response goes.
    """
    from app.services.lyrics import get_lyrics_service
    from app.services.lyrics_local import read_local_lyrics

    async def keep(status: LyricsStatus, result: LyricsResult | None) -> tuple[LyricsStatus, LyricsResult | None]:
        async with async_session_maker() as session:
            await _store_lyrics(session, track_id, identity, status, result)
        return status, result

    local = await _lyrics_thread(read_local_lyrics, file_path, edited)
    if local.synced is not None:
        return await keep(LyricsStatus.FOUND, local.synced)

    if not title or not artist:
        outcome = LyricsOutcome(LyricsStatus.NOT_FOUND)
    else:
        outcome = await get_lyrics_service().resolve(
            track_name=title,
            artist_name=artist,
            album_name=album,
            duration=duration,
            album_artist=album_artist,
        )

    if outcome.status == LyricsStatus.FOUND or outcome.status == LyricsStatus.INSTRUMENTAL:
        return await keep(outcome.status, outcome.result)

    # The listener's own words outrank LRCLIB's when neither has timing.
    plain = local.plain or (outcome.result if outcome.status == LyricsStatus.PLAIN_ONLY else None)
    if plain is not None:
        return await keep(LyricsStatus.PLAIN_ONLY, plain)

    if outcome.status == LyricsStatus.UNAVAILABLE:
        return legacy if legacy else (LyricsStatus.UNAVAILABLE, None)

    await _remember_miss(miss_key)
    return LyricsStatus.NOT_FOUND, None
