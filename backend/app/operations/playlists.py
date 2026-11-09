"""Playlist use cases shared by REST and the LLM/MCP tools (ADR-0173 point 3).

Until ADR-0173 the tool handler (`app/services/llm/handlers/playlists.py`) called the route
functions themselves, so a tool depended on HTTP signatures: `include_auto` had to be passed
explicitly because the route defaulted it with `Query(...)`, which arrives as a FastAPI object when
the function is called directly, and an append re-read the whole playlist to count what it added.
These functions hold the behaviour once; the routes and the tool are adapters over them.

They return domain values (ORM rows plus what was computed), never response models: a route
serialises, a tool summarises.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Playlist, PlaylistTrack, ProfilePlayHistory, Track
from app.operations.errors import PlaylistNotFound


@dataclass(frozen=True)
class PlaylistSummary:
    playlist: Playlist
    track_count: int


@dataclass(frozen=True)
class PlaylistEntry:
    """One local track on a playlist, with this profile's history of it."""

    item: PlaylistTrack
    track: Track
    history: ProfilePlayHistory | None


@dataclass(frozen=True)
class PlaylistDetail:
    playlist: Playlist
    entries: list[PlaylistEntry] = field(default_factory=list)


@dataclass(frozen=True)
class TracksAdded:
    playlist: Playlist
    requested: int
    added: int


async def _owned(db: AsyncSession, profile_id: UUID, playlist_id: UUID) -> Playlist:
    playlist = await db.get(Playlist, playlist_id)
    if playlist is None or playlist.profile_id != profile_id:
        raise PlaylistNotFound(playlist_id)
    return playlist


async def list_playlists(
    db: AsyncSession, profile_id: UUID, *, include_auto: bool = True
) -> list[PlaylistSummary]:
    """The profile's playlists, most recently updated first, with their track counts."""
    query = select(Playlist).where(Playlist.profile_id == profile_id)
    if not include_auto:
        query = query.where(Playlist.is_auto_generated.is_(False))
    playlists = (await db.execute(query.order_by(Playlist.updated_at.desc()))).scalars().all()

    # One GROUP BY rather than a count per playlist.
    counts: dict[UUID, int] = {}
    if playlists:
        rows = await db.execute(
            select(PlaylistTrack.playlist_id, func.count(PlaylistTrack.id))
            .where(PlaylistTrack.playlist_id.in_([p.id for p in playlists]))
            .group_by(PlaylistTrack.playlist_id)
        )
        counts = {playlist_id: total for playlist_id, total in rows.all()}
    return [PlaylistSummary(p, counts.get(p.id, 0)) for p in playlists]


async def get_playlist(db: AsyncSession, profile_id: UUID, playlist_id: UUID) -> PlaylistDetail:
    """A playlist and its local tracks in order, each with this profile's play history.

    Raises `PlaylistNotFound` for a playlist that does not exist or is not this profile's.
    """
    playlist = await _owned(db, profile_id, playlist_id)
    items = (
        await db.execute(
            select(PlaylistTrack)
            .where(PlaylistTrack.playlist_id == playlist_id)
            .order_by(PlaylistTrack.position)
            .options(selectinload(PlaylistTrack.track).selectinload(Track.analyses))
        )
    ).scalars().all()

    local = [item for item in items if item.track]
    history: dict[UUID, ProfilePlayHistory] = {}
    if local:
        rows = await db.execute(
            select(ProfilePlayHistory).where(
                ProfilePlayHistory.profile_id == profile_id,
                ProfilePlayHistory.track_id.in_([item.track.id for item in local]),
            )
        )
        history = {h.track_id: h for h in rows.scalars().all()}
    return PlaylistDetail(
        playlist=playlist,
        entries=[PlaylistEntry(item, item.track, history.get(item.track.id)) for item in local],
    )


async def add_tracks(
    db: AsyncSession, profile_id: UUID, playlist_id: UUID, track_ids: list[str]
) -> TracksAdded:
    """Append tracks to the end of a playlist, skipping ids that are malformed, not in the library,
    or already on it. Commits. Raises `PlaylistNotFound`."""
    playlist = await _owned(db, profile_id, playlist_id)

    max_position = (
        await db.execute(
            select(func.max(PlaylistTrack.position)).where(PlaylistTrack.playlist_id == playlist_id)
        )
    ).scalar()
    next_position = -1 if max_position is None else max_position

    candidates: list[UUID] = []
    for raw in track_ids:
        try:
            candidates.append(UUID(str(raw)))
        except ValueError:
            continue

    existing: set[UUID] = set()
    in_library: set[UUID] = set()
    if candidates:
        in_library = set(
            (await db.execute(select(Track.id).where(Track.id.in_(candidates)))).scalars().all()
        )
        existing = {
            row
            for row in (
                await db.execute(
                    select(PlaylistTrack.track_id).where(
                        PlaylistTrack.playlist_id == playlist_id,
                        PlaylistTrack.track_id.in_(candidates),
                    )
                )
            ).scalars().all()
            if row
        }

    added = 0
    for i, track_id in enumerate(candidates):
        if track_id not in in_library or track_id in existing:
            continue
        db.add(PlaylistTrack(playlist_id=playlist.id, track_id=track_id, position=next_position + 1 + i))
        existing.add(track_id)  # a repeated id in one request is added once
        added += 1

    await db.commit()
    return TracksAdded(playlist=playlist, requested=len(track_ids), added=added)
