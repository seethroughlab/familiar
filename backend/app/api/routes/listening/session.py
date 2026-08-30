"""The durable playback session (ADR-0003, ADR-0028).

The **queue is a client concept** — the Apple client builds and owns it (ADR-0028). What the
server keeps is a *session*: the queue a listener left behind, so another device can pick it up.
That distinction is why this module is no longer called `queue.py` (ADR-0074).

Conflict resolution runs on the client's `updated_at`, because only the client knows when an
offline edit happened. Nothing is destroyed on conflict — the loser is archived and restorable.
"""

import hashlib
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.api.schemas.common import UTCDateTime, error_responses
from app.db.models import PlaybackSession, PlaybackSessionArchive
from app.db.models.profiles import PlaybackSessionPayload
from app.services.app_settings import get_app_settings_service
from app.utils.time import to_naive_utc, utcnow

router = APIRouter(prefix="/listening/session", tags=["playback-session"])


# Ceilings on a session write. The materialised queue is a window plus whatever has been
# refilled into it, so it stays small; the reservoir is the whole eligible library, which
# is 26,462 IDs here — the limit is headroom above that, not a target.
MAX_QUEUE_TRACKS = 10_000
MAX_RESERVOIR_TRACKS = 200_000

# How many superseded queues to keep per profile. The conflict rule promises nothing is
# destroyed, but "nothing, ever" would grow without bound for a queue nobody will ask for.
ARCHIVE_LIMIT = 10

# How far ahead of the server a client's clock may be and still be believed. Conflict
# resolution runs on the client's `updated_at` because only the client knows when an
# offline edit happened — which means a device with a badly wrong clock could otherwise
# win every conflict forever.
MAX_CLOCK_SKEW = timedelta(minutes=5)
class LibraryFilters(BaseModel):
    """The library filters a queue was built from.

    Typed field by field rather than left as a free-form dict because `toggleShuffle`
    replays these verbatim against the library — a filter silently dropped in transit
    would reshuffle the wrong set of tracks. Mirrors `LibraryFilters` in
    `player/playerStore.types.ts`.
    """

    search: str | None = None
    artist: str | None = None
    album: str | None = None
    genre: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    energy_min: float | None = None
    energy_max: float | None = None
    valence_min: float | None = None
    valence_max: float | None = None


class QueueSource(BaseModel):
    """Where a queue came from.

    The vocabulary is the client's queue *source*, which is deliberately narrower than
    `PlayContext`: 'radio' and 'ambient' describe how a track came to be playing, not
    where the queue came from, and conflating them would corrupt listening-event context
    (ADR-0003 point 8).
    """

    type: Literal["library", "album", "playlist", "artist", "ephemeral", "other"]
    id: str | None = None
    filters: LibraryFilters | None = None


class PlaybackSessionBody(BaseModel):
    """A queue as a client holds it.

    `reservoir_ids` is optional on a write: omitting it means "unchanged, and it hashes to
    `reservoir_hash`". For this library the reservoir is 26,462 UUIDs (~1 MB), and it
    changes only on `setLazyQueue`, `toggleShuffle` and a refill — shipping it with every
    cursor advance would be absurd (ADR-0003 point 4).
    """

    track_ids: list[UUID] = Field(default_factory=list, max_length=MAX_QUEUE_TRACKS)
    cursor: int = -1
    shuffle_order: list[int] = Field(default_factory=list, max_length=MAX_QUEUE_TRACKS)
    shuffle_index: int = -1
    shuffle: bool = False
    repeat: Literal["off", "all", "one"] = "off"
    consume: bool = False
    queue_source: QueueSource | None = None
    reservoir_ids: list[UUID] | None = Field(default=None, max_length=MAX_RESERVOIR_TRACKS)
    reservoir_cursor: int = -1
    reservoir_hash: str | None = Field(default=None, max_length=64)
    position_seconds: float = 0.0


class PlaybackSessionWrite(PlaybackSessionBody):
    """A session write, carrying what the client believes the server already has."""

    # The version this write is based on. Equal to the stored version means an ordinary
    # sequential update; lower means the client edited a stale queue, which is the only
    # case that counts as a conflict.
    version: int = 0
    # When the client last changed this queue, by its own clock. The server cannot know
    # when an offline edit happened, so the conflict rule has to trust this — bounded by
    # MAX_CLOCK_SKEW so a wrong clock cannot win every conflict forever.
    updated_at: datetime | None = None


class PlaybackSessionResponse(PlaybackSessionBody):
    """The session the server now holds.

    Always the server's view, including when a write lost its conflict — the client is
    expected to adopt what comes back rather than retry.
    """

    version: int
    updated_at: UTCDateTime
    # True when this response is the *other* device's queue because the write lost.
    superseded: bool = False


class ArchivedSessionResponse(BaseModel):
    """A superseded queue, kept so a lost conflict is recoverable."""

    id: UUID
    track_ids: list[UUID]
    cursor: int
    queue_source: QueueSource | None
    position_seconds: float
    superseded_at: UTCDateTime
    archived_at: UTCDateTime


class ArchivedSessionsResponse(BaseModel):
    sessions: list[ArchivedSessionResponse]
def reservoir_digest(ids: list[str]) -> str | None:
    """Hash a reservoir so an unchanged one can be referenced instead of resent.

    Computed server-side from what is actually stored, so the hash can never disagree
    with the list it names. The client's hash is only ever compared against this.
    """
    if not ids:
        return None
    digest = hashlib.sha256()
    for track_id in ids:
        digest.update(track_id.encode())
        digest.update(b"\x00")
    return digest.hexdigest()


def _as_strings(ids: list[UUID] | None) -> list[str] | None:
    return None if ids is None else [str(i) for i in ids]


def _resolve_reservoir(
    body: PlaybackSessionWrite, existing: PlaybackSession | None
) -> tuple[list[str] | None, str | None]:
    """Work out the reservoir a write should end up with.

    An omitted `reservoir_ids` means "unchanged", which is only safe if the hash the
    client names matches what is stored. A mismatch is answered with a 409 rather than a
    silent fallback: keeping the wrong reservoir would truncate the queue at the
    materialised window, and that failure is invisible until playback simply stops.
    """
    if body.reservoir_ids is not None:
        ids = _as_strings(body.reservoir_ids)
        return ids, reservoir_digest(ids or [])

    stored = existing.reservoir_ids if existing else None
    stored_hash = existing.reservoir_hash if existing else None
    if body.reservoir_hash == stored_hash:
        return stored, stored_hash

    raise ConflictError(
        "Reservoir hash does not match the stored reservoir; resend reservoir_ids in full."
    )


def _apply(
    row: PlaybackSessionPayload,
    body: PlaybackSessionBody,
    reservoir: tuple[list[str] | None, str | None],
) -> None:
    """Copy a write onto a session or archive row — both carry the same payload mixin."""
    row.track_ids = [str(i) for i in body.track_ids]
    row.cursor = body.cursor
    row.shuffle_order = list(body.shuffle_order)
    row.shuffle_index = body.shuffle_index
    row.shuffle = body.shuffle
    row.repeat = body.repeat
    row.consume = body.consume
    row.queue_source = (
        body.queue_source.model_dump(exclude_none=True) if body.queue_source else None
    )
    row.reservoir_ids, row.reservoir_hash = reservoir
    row.reservoir_cursor = body.reservoir_cursor
    row.position_seconds = body.position_seconds


def _copy_payload(src: PlaybackSessionPayload, dst: PlaybackSessionPayload) -> None:
    """Copy the queue itself between a session and an archive row, in either direction."""
    dst.track_ids = list(src.track_ids)
    dst.cursor = src.cursor
    dst.shuffle_order = list(src.shuffle_order)
    dst.shuffle_index = src.shuffle_index
    dst.shuffle = src.shuffle
    dst.repeat = src.repeat
    dst.consume = src.consume
    dst.queue_source = src.queue_source
    dst.reservoir_ids = src.reservoir_ids
    dst.reservoir_cursor = src.reservoir_cursor
    dst.reservoir_hash = src.reservoir_hash
    dst.position_seconds = src.position_seconds


def _archive(db: DbSession, session: PlaybackSession) -> None:
    """Retain a superseded queue. ADR-0003 point 6: the loser is never destroyed."""
    row = PlaybackSessionArchive(profile_id=session.profile_id, superseded_at=session.updated_at)
    _copy_payload(session, row)
    db.add(row)


async def _trim_archive(db: DbSession, profile_id: UUID) -> None:
    """Keep only the newest ARCHIVE_LIMIT entries for a profile.

    The explicit flush is load-bearing: sessions are created with ``autoflush=False``, so
    without it the row just added is invisible to this query and the archive settles one
    entry above the limit forever.
    """
    await db.flush()
    stale = (
        (
            await db.execute(
                select(PlaybackSessionArchive.id)
                .where(PlaybackSessionArchive.profile_id == profile_id)
                # `archived_at` defaults to now(), which in PostgreSQL is transaction
                # start time, so it can tie. `id` breaks the tie into a total order.
                .order_by(
                    PlaybackSessionArchive.archived_at.desc(),
                    PlaybackSessionArchive.id.desc(),
                )
                .offset(ARCHIVE_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    if stale:
        await db.execute(delete(PlaybackSessionArchive).where(PlaybackSessionArchive.id.in_(stale)))


def _to_response(session: PlaybackSession, *, superseded: bool = False) -> PlaybackSessionResponse:
    return PlaybackSessionResponse(
        track_ids=[UUID(i) for i in session.track_ids],
        cursor=session.cursor,
        shuffle_order=list(session.shuffle_order),
        shuffle_index=session.shuffle_index,
        shuffle=session.shuffle,
        repeat=session.repeat,  # type: ignore[arg-type]
        consume=session.consume,
        queue_source=QueueSource.model_validate(session.queue_source)
        if session.queue_source
        else None,
        reservoir_ids=[UUID(i) for i in session.reservoir_ids] if session.reservoir_ids else None,
        reservoir_cursor=session.reservoir_cursor,
        reservoir_hash=session.reservoir_hash,
        position_seconds=session.position_seconds,
        version=session.version,
        updated_at=session.updated_at,
        superseded=superseded,
    )


def _require_queue_sync_enabled() -> None:
    """Reject session traffic unless the server has opted in.

    ADR-0003 point 7 lands this behind a flag. Failing loudly beats accepting writes and
    doing nothing with them — a silently-ignored queue looks like a client bug and would
    be debugged on the wrong side.
    """
    if not get_app_settings_service().get().queue_sync_enabled:
        raise ServiceUnavailableError(
            "Playback queue sync is disabled on this server (queue_sync_enabled)."
        )


async def _load_session(db: DbSession, profile_id: UUID) -> PlaybackSession | None:
    return (
        await db.execute(select(PlaybackSession).where(PlaybackSession.profile_id == profile_id))
    ).scalar_one_or_none()
@router.get(
    "",
    response_model=PlaybackSessionResponse,
    # 503 is control flow too: these four are gated behind `queue_sync_enabled`, so "the server
    # does not do this" is an ordinary answer a client must expect on its very first call, not a
    # server fault. Undeclared, a generated client has no case to branch on and reports an
    # unexpected response for the flag simply being off.
    responses=error_responses(503),
)
async def get_playback_session(
    db: DbSession,
    profile: RequiredProfile,
) -> PlaybackSessionResponse:
    """Return this profile's durable queue.

    An empty session rather than a 404 when there is none: "no queue yet" is the ordinary
    starting state, not an error, and a client adopting it should not have to special-case
    a status code.
    """
    _require_queue_sync_enabled()
    session = await _load_session(db, profile.id)
    if session is None:
        return PlaybackSessionResponse(version=0, updated_at=utcnow())
    return _to_response(session)


@router.put(
    "",
    response_model=PlaybackSessionResponse,
    # 409 is control flow here, not an error condition: it means the client named a reservoir
    # hash the server does not hold and must resend `reservoir_ids` in full. A client that cannot
    # discover that from the schema will treat it as a generic failure and stop syncing
    # (ADR-0003 point 4).
    responses=error_responses(409, 503),
)
async def put_playback_session(
    body: PlaybackSessionWrite,
    db: DbSession,
    profile: RequiredProfile,
) -> PlaybackSessionResponse:
    """Upsert this profile's durable queue.

    Ordinary case: the client's `version` matches what is stored, so this is the next step
    in one device's own history and simply overwrites.

    Conflict case: the client wrote from a stale version, meaning two devices diverged —
    typically because one was offline. The later `updated_at` wins and the loser is
    archived, never dropped (ADR-0003 point 6). A losing write still gets the winning
    session back, so the client adopts rather than retries.
    """
    _require_queue_sync_enabled()
    session = await _load_session(db, profile.id)
    reservoir = _resolve_reservoir(body, session)
    # Clamp rather than reject: a skewed clock should lose conflicts, not fail writes.
    # `to_naive_utc` is load-bearing — clients send `Z`-suffixed ISO timestamps, which
    # Pydantic parses as offset-aware and cannot be compared with a naive `utcnow()`.
    now = utcnow()
    client_time = min(to_naive_utc(body.updated_at) or now, now + MAX_CLOCK_SKEW)

    if session is None:
        session = PlaybackSession(profile_id=profile.id, version=1)
        _apply(session, body, reservoir)
        session.updated_at = client_time
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return _to_response(session)

    if body.version != session.version:
        if client_time <= session.updated_at:
            # This write lost. Keep it as a restorable entry and hand back the winner.
            loser = PlaybackSessionArchive(profile_id=profile.id, superseded_at=client_time)
            _apply(loser, body, reservoir)
            db.add(loser)
            await _trim_archive(db, profile.id)
            await db.commit()
            await db.refresh(session)
            return _to_response(session, superseded=True)

        # This write won over a queue built independently, so retain the one it replaces.
        _archive(db, session)
        await _trim_archive(db, profile.id)

    _apply(session, body, reservoir)
    session.version += 1
    session.updated_at = client_time
    await db.commit()
    await db.refresh(session)
    return _to_response(session)


@router.get(
    "/archive",
    response_model=ArchivedSessionsResponse,
    responses=error_responses(503),
)
async def list_archived_sessions(
    db: DbSession,
    profile: RequiredProfile,
) -> ArchivedSessionsResponse:
    """List queues that lost a conflict and can still be restored."""
    _require_queue_sync_enabled()
    rows = (
        (
            await db.execute(
                select(PlaybackSessionArchive)
                .where(PlaybackSessionArchive.profile_id == profile.id)
                .order_by(
                    PlaybackSessionArchive.archived_at.desc(),
                    PlaybackSessionArchive.id.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return ArchivedSessionsResponse(
        sessions=[
            ArchivedSessionResponse(
                id=row.id,
                track_ids=[UUID(i) for i in row.track_ids],
                cursor=row.cursor,
                queue_source=QueueSource.model_validate(row.queue_source)
                if row.queue_source
                else None,
                position_seconds=row.position_seconds,
                superseded_at=row.superseded_at,
                archived_at=row.archived_at,
            )
            for row in rows
        ]
    )


@router.post(
    "/archive/{archive_id}/restore",
    response_model=PlaybackSessionResponse,
    responses=error_responses(404, 503),
)
async def restore_archived_session(
    archive_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> PlaybackSessionResponse:
    """Make an archived queue current again.

    Symmetrical with the conflict rule: whatever is live now is archived in its place, so
    restoring cannot itself destroy a queue.
    """
    _require_queue_sync_enabled()
    archived = (
        await db.execute(
            select(PlaybackSessionArchive).where(
                PlaybackSessionArchive.id == archive_id,
                PlaybackSessionArchive.profile_id == profile.id,
            )
        )
    ).scalar_one_or_none()
    if archived is None:
        raise NotFoundError("Archived playback session not found")

    session = await _load_session(db, profile.id)
    if session is None:
        session = PlaybackSession(profile_id=profile.id, version=0)
        db.add(session)
    else:
        _archive(db, session)

    _copy_payload(archived, session)
    session.version += 1
    session.updated_at = utcnow()

    # The restored queue is live now, so it is no longer an archive entry.
    await db.execute(delete(PlaybackSessionArchive).where(PlaybackSessionArchive.id == archive_id))
    await _trim_archive(db, profile.id)
    await db.commit()
    await db.refresh(session)
    return _to_response(session)
