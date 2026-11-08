"""Moving tracks to the album they belong on, and back (ADR-0166).

One operation covers both repairs. A **merge** moves the tracks of one folder, split across
several albums, onto the one kept album (*TRST*: nine tracks on a "Various Artists" album, two on
their own). A **split** moves one artist's tracks off an album that wrongly holds two records
(Portishead's and Soft Machine's *Third*, fused by the compilation label ADR-0167 stopped
writing).

Identity resolves from a file's tags (``scanner.py``), and an edit in Familiar only corrects
display fields on top of it, so editing ``album_artist`` never moves a track (ADR-0052 point 4).
This module is the one place that does move a track: directly, on purpose, and reversibly.
Everything a move changes is returned as a JSON-safe record, and ``undo_move`` puts it back.
"""

from __future__ import annotations

import logging
import shutil
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Album, AlbumAlias, Track
from app.services import metadata_overrides
from app.services.album_resolver import resolve_canonical_album
from app.services.artist_resolver import resolve_canonical_artist
from app.services.artwork import get_artwork_path, is_generated_artwork

logger = logging.getLogger(__name__)

MoveKind = Literal["merge", "split"]

_ALBUM_FIELDS = ("name", "sort_name", "album_artist_id", "musicbrainz_release_id", "year")


def _s(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _u(value: str | None) -> UUID | None:
    return UUID(value) if value else None


async def _target_album(
    db: AsyncSession, album_id: UUID | None, title: str, album_artist: str
) -> tuple[Album, bool]:
    """The album to move onto, and whether this move created it."""
    if album_id is not None:
        album = await db.get(Album, album_id, with_for_update=True)
        if album is None:
            raise LookupError(f"album {album_id} no longer exists")
        return album, False

    artist = await resolve_canonical_artist(db, album_artist)
    artist_id = artist.id if artist is not None else None
    before = (await db.execute(select(func.count()).select_from(Album))).scalar_one()
    album = await resolve_canonical_album(db, title, album_artist_id=artist_id)
    if album is None:
        raise LookupError(f"no album could be resolved for {title!r}")
    after = (await db.execute(select(func.count()).select_from(Album))).scalar_one()
    return album, after > before


def _copy_artwork(source_ids: list[UUID], target_id: UUID) -> str | None:
    """Give the target a cover from a source album when it has none of its own.

    Copies, never moves: a source's files stay filed under its id, which is what lets an undo
    bring each album back with its own cover. A generated cover isn't copied; the target will
    get one of its own.
    """
    target_key = str(target_id)
    if get_artwork_path(target_key).exists():
        return None
    for source_id in source_ids:
        key = str(source_id)
        full = get_artwork_path(key)
        if not full.exists() or is_generated_artwork(key):
            continue
        shutil.copy2(full, get_artwork_path(target_key))
        thumb = get_artwork_path(key, "thumb")
        if thumb.exists():
            shutil.copy2(thumb, get_artwork_path(target_key, "thumb"))
        return key
    return None


async def move_tracks_to_album(
    db: AsyncSession,
    track_ids: list[UUID],
    *,
    kind: MoveKind,
    album_artist: str,
    album_id: UUID | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Move ``track_ids`` onto one album and return the record ``undo_move`` needs.

    ``album_id`` names the target. Without one, the target is the album keyed by
    ``album_artist`` and ``title``, created if it doesn't exist (a split's destination).

    An album left with no tracks is deleted, after its tracks are repointed (the foreign key
    is ``ON DELETE SET NULL``). After a merge its aliases move to the target, so the files' own
    tags resolve there on the next rescan. After a split they are deleted: they key on the
    label being removed.

    Doesn't commit; the caller owns the transaction.
    """
    tracks = list(
        (await db.execute(select(Track).where(Track.id.in_(track_ids)).with_for_update())).scalars()
    )
    if not tracks:
        raise LookupError("none of the tracks to move exist")

    target, created = await _target_album(
        db, album_id, title or tracks[0].album or "", album_artist
    )

    record: dict[str, Any] = {
        "kind": kind,
        "target_album_id": str(target.id),
        "target_created": created,
        "target_took_release_id": None,
        "tracks": [],
        "deleted_albums": [],
        "artwork_copied_from": None,
    }

    source_ids: list[UUID] = []
    for track in tracks:
        record["tracks"].append(
            {
                "id": str(track.id),
                "canonical_album_id": _s(track.canonical_album_id),
                "canonical_album_artist_id": _s(track.canonical_album_artist_id),
                "album_artist": track.album_artist,
                "override": (track.metadata_overrides or {}).get("album_artist", _MISSING),
            }
        )
        if track.canonical_album_id and track.canonical_album_id != target.id:
            if track.canonical_album_id not in source_ids:
                source_ids.append(track.canonical_album_id)
        track.canonical_album_id = target.id
        track.canonical_album_artist_id = target.album_artist_id
        track.album_artist = album_artist
        # Accepting the move is a choice, so it outranks the file (ADR-0051 point 7).
        track.metadata_overrides = metadata_overrides.record(
            track.metadata_overrides, {"album_artist": album_artist}
        )
    await db.flush()

    for source_id in source_ids:
        remaining = (
            await db.execute(
                select(func.count()).select_from(Track).where(Track.canonical_album_id == source_id)
            )
        ).scalar_one()
        if remaining:
            continue
        source = await db.get(Album, source_id, with_for_update=True)
        if source is None:
            continue
        aliases = list(
            (await db.execute(select(AlbumAlias).where(AlbumAlias.album_id == source_id))).scalars()
        )
        record["deleted_albums"].append(
            {
                "id": str(source.id),
                **{
                    f: (_s(getattr(source, f)) if f == "album_artist_id" else getattr(source, f))
                    for f in _ALBUM_FIELDS
                },
                "aliases": [
                    {"alias_normalized": a.alias_normalized, "alias": a.alias, "source": a.source}
                    for a in aliases
                ],
            }
        )
        release_id = source.musicbrainz_release_id
        if kind == "merge":
            for alias in aliases:
                alias.album_id = target.id
        else:
            for alias in aliases:
                await db.delete(alias)
        await db.flush()
        await db.delete(source)
        await db.flush()
        if kind == "merge" and release_id and not target.musicbrainz_release_id:
            target.musicbrainz_release_id = release_id
            record["target_took_release_id"] = release_id
            await db.flush()

    record["artwork_copied_from"] = _copy_artwork(source_ids, target.id)
    logger.info(
        f"Moved {len(tracks)} track(s) to album {target.id} ({kind}); "
        f"deleted {len(record['deleted_albums'])} empty album(s)"
    )
    return record


#: Stored in a record when a track had no album_artist override before the move.
_MISSING = "__no_override__"


async def undo_move(db: AsyncSession, record: dict[str, Any]) -> None:
    """Put back everything ``move_tracks_to_album`` changed. Doesn't commit.

    Deleted albums come back **with their original ids**, so their covers, still filed under
    those ids, come back with them. A cover copied onto the target stays; it is harmless.
    """
    target_id = UUID(record["target_album_id"])
    target = await db.get(Album, target_id, with_for_update=True)

    if target is not None and record.get("target_took_release_id"):
        target.musicbrainz_release_id = None
        await db.flush()

    for row in record["deleted_albums"]:
        album = Album(
            id=UUID(row["id"]),
            name=row["name"],
            sort_name=row["sort_name"],
            album_artist_id=_u(row["album_artist_id"]),
            musicbrainz_release_id=row["musicbrainz_release_id"],
            year=row["year"],
        )
        db.add(album)
        await db.flush()
        for alias in row["aliases"]:
            existing = await db.get(AlbumAlias, alias["alias_normalized"])
            if existing is not None:
                existing.album_id = album.id
            else:
                db.add(
                    AlbumAlias(
                        alias_normalized=alias["alias_normalized"],
                        alias=alias["alias"],
                        album_id=album.id,
                        source=alias["source"],
                    )
                )
        await db.flush()

    by_id = {UUID(t["id"]): t for t in record["tracks"]}
    tracks = (await db.execute(select(Track).where(Track.id.in_(list(by_id))))).scalars()
    for track in tracks:
        before = by_id[track.id]
        track.canonical_album_id = _u(before["canonical_album_id"])
        track.canonical_album_artist_id = _u(before["canonical_album_artist_id"])
        track.album_artist = before["album_artist"]
        if before["override"] == _MISSING:
            # An undo is a retraction, not a new opinion (ADR-0051 point 7).
            track.metadata_overrides = metadata_overrides.forget(
                track.metadata_overrides, ["album_artist"]
            )
        else:
            track.metadata_overrides = metadata_overrides.record(
                track.metadata_overrides, {"album_artist": before["override"]}
            )
    await db.flush()

    if record.get("target_created") and target is not None:
        remaining = (
            await db.execute(
                select(func.count()).select_from(Track).where(Track.canonical_album_id == target_id)
            )
        ).scalar_one()
        if not remaining:
            await db.execute(delete(AlbumAlias).where(AlbumAlias.album_id == target_id))
            await db.delete(target)
            await db.flush()
