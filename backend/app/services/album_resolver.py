"""Resolve a raw album tag to a canonical ``Album`` row (ADR-0052).

The single owner of the alias→canonical chain for albums, the way
``app.services.artist_resolver`` is for artists. Both the backfill CLI
(``app.cli.backfill_albums``) and the scanner dual-write call
``resolve_canonical_album``, so the two cannot drift.

Resolution order (first hit wins):

1. **A verified MusicBrainz release id.** Authoritative where present and absent
   almost everywhere — 1,782 of 26,422 tracks carried one when this was measured.
   Verified rather than trusted: the artist resolver learned the hard way that a
   track can carry somebody else's MBID, and the same defence applies here.
2. **An alias hit** on ``{album_artist_id}::{normalized title}``. A PK fetch.
3. **A folder alias** when there is no album tag at all. 801 tracks are in that
   position, and they used to share a single ``unknown::unknown`` artwork bucket.
4. **Create**, registering the alias so the next call short-circuits at step 2.

Whatever path resolves, the observed spelling is registered in ``AlbumAlias``.

**The artist half of the key is a uuid, not a string.** That is what makes album
identity inherit artist identity: two spellings of one artist already collapse to one
``Artist`` row, so their albums collapse too, and a future artist merge improves album
grouping without touching this code.
"""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Album, AlbumAlias
from app.services.normalize import normalize_for_matching

logger = logging.getLogger(__name__)


def album_alias_key(album_artist_id: UUID | None, album_tag: str) -> str:
    """The alias key for a titled album.

    ``normalize_for_matching`` rather than ``normalize_artist_name`` (which the artist
    resolver uses): it also folds quote and dash variants, which matter far more in
    album titles — "Don't Stop" and "Don't Stop", "Rock — Roll" and "Rock - Roll" — than
    they do in artist names. It is also what ``compute_album_hash`` used, which keeps
    the old-hash → album-id mapping in the artwork migration consistent.

    A null artist id is a real key, not an error: an album tag with no resolvable artist
    still groups its own tracks together.
    """
    return f"{album_artist_id or 'unknown'}::{normalize_for_matching(album_tag)}"


def folder_alias_key(folder: str) -> str:
    """The alias key for tracks with no album tag, grouped by containing directory.

    97.5% of directories in this library hold exactly one album, which makes the folder
    the best signal available when the tags offer none. The alternative — one shared
    bucket for everything untagged — is what put a single dropped cover onto 61
    unrelated tracks.
    """
    return f"folder::{folder.rstrip('/')}"


def _compute_sort_name(name: str) -> str:
    """Move a leading article to the end, so "The Wall" sorts under W.

    Same rule as ``artist_resolver._compute_sort_name``, kept separate rather than
    imported because the two answer questions about different things and there is no
    reason a change to one should silently move the other.
    """
    stripped = name.strip()
    if stripped.lower().startswith("the "):
        return f"{stripped[4:]}, The"
    return stripped


def _titles_match(tag: str, canonical_name: str) -> bool:
    """Whether an album tag is plausibly the same title as a canonical row.

    Guards the MBID path. `artist_resolver` has the same check because a track was found
    carrying an unrelated artist's MBID; release ids are no better curated, and trusting
    one blindly would silently fold two different records together.
    """
    return normalize_for_matching(tag) == normalize_for_matching(canonical_name)


async def _register_alias(
    db: AsyncSession, album: Album, key: str, raw: str, *, source: str
) -> None:
    """Point ``key`` at ``album`` unless something already claims it.

    ``ON CONFLICT DO NOTHING`` so two scan sessions racing on the same key do not raise
    ``IntegrityError`` and poison the transaction — the failure mode
    ``artist_resolver._register_alias`` documents. First writer wins; a genuine
    cross-album collision is for a merge UI to settle, not a scan.
    """
    if not key:
        return
    await db.execute(
        pg_insert(AlbumAlias)
        .values(alias_normalized=key, alias=raw.strip(), album_id=album.id, source=source)
        .on_conflict_do_nothing(index_elements=["alias_normalized"])
    )


async def _album_by_alias(db: AsyncSession, key: str) -> Album | None:
    alias = await db.get(AlbumAlias, key)
    if alias is None:
        return None
    return await db.get(Album, alias.album_id)


async def _album_by_release_id(db: AsyncSession, release_id: str) -> Album | None:
    return (
        await db.execute(
            select(Album).where(Album.musicbrainz_release_id == release_id)
        )
    ).scalar_one_or_none()


async def album_key_for_tags(
    db: AsyncSession, artist: str | None, album: str | None
) -> str:
    """The artwork key for an ``(artist, album)`` pair, looked up through the library.

    For the handful of callers that hold tag strings rather than a track — the artwork
    queue endpoints, `regenerate`, the `HEAD` check — all of which are asked about
    albums that already exist here, because the client is looking at one.

    Resolved through a track rather than by recomputing the alias key, because the alias
    key needs the *canonical artist id* and these callers have only a name. Matching on
    either `artist` or `album_artist` is what makes it work for a compilation, where the
    caller may hold either.

    Falls back to the legacy hash when nothing matches, so an album that is not in the
    library — or a call made before the backfill — behaves exactly as it did before.
    """
    from app.db.models import Track, TrackStatus
    from app.services.artwork import compute_album_hash

    album_name = (album or "").strip().lower()
    artist_name = (artist or "").strip().lower()
    if album_name:
        stmt = (
            select(Track.canonical_album_id)
            .where(
                func.lower(func.trim(Track.album)) == album_name,
                Track.status == TrackStatus.ACTIVE,
                Track.canonical_album_id.isnot(None),
                or_(
                    func.lower(func.trim(Track.artist)) == artist_name,
                    func.lower(func.trim(Track.album_artist)) == artist_name,
                ),
            )
            .limit(1)
        )
        album_id = (await db.execute(stmt)).scalar_one_or_none()
        if album_id:
            return str(album_id)

    return compute_album_hash(artist, album)


async def resolve_canonical_album(
    db: AsyncSession,
    album_tag: str | None,
    *,
    album_artist_id: UUID | None = None,
    file_path: str | None = None,
    musicbrainz_release_id: str | None = None,
    year: int | None = None,
    create_if_missing: bool = True,
) -> Album | None:
    """Return the canonical ``Album`` for a track's tags.

    Args:
        album_tag: The raw album title as tagged. May be blank.
        album_artist_id: The canonical artist id for this record — resolve the artist
            first. Its uuid, not its name, is half the alias key.
        file_path: The track's path, used only when ``album_tag`` is blank, to group by
            containing directory.
        musicbrainz_release_id: A tag-side release id, verified before it is trusted.
        year: Recorded on creation only; a later disagreement does not repoint anything.
        create_if_missing: False disables every side effect, for dry runs and tests.

    Returns ``None`` when there is nothing to go on — no album tag *and* no path — so
    nothing invents an album out of an empty tag.
    """
    tag = (album_tag or "").strip()

    if not tag and not file_path:
        return None

    # 1. A verified release id.
    if musicbrainz_release_id:
        existing = await _album_by_release_id(db, musicbrainz_release_id)
        if existing is not None:
            # A release id that disagrees with the title is somebody else's record;
            # fall through to the alias path rather than folding two albums together.
            if not tag or _titles_match(tag, existing.name):
                if tag:
                    await _register_alias(
                        db, existing, album_alias_key(album_artist_id, tag), tag, source="mb"
                    )
                return existing

    # 2. The ordinary path.
    if tag:
        key = album_alias_key(album_artist_id, tag)
        found = await _album_by_alias(db, key)
        if found is not None:
            return found

    # 3. No title at all — group by the directory the file sits in.
    folder_key = ""
    if not tag and file_path:
        parent = Path(file_path).parent
        folder_key = folder_alias_key(str(parent))
        found = await _album_by_alias(db, folder_key)
        if found is not None:
            return found

    if not create_if_missing:
        return None

    # 4. Create. A folder-derived album is named after its directory, which is the only
    # human-readable thing available and is usually the album name anyway.
    name = tag or Path(file_path or "").parent.name or "Unknown Album"
    album = Album(
        name=name,
        sort_name=_compute_sort_name(name),
        album_artist_id=album_artist_id,
        musicbrainz_release_id=musicbrainz_release_id or None,
        year=year,
    )
    db.add(album)
    await db.flush()

    if tag:
        await _register_alias(
            db, album, album_alias_key(album_artist_id, tag), tag, source="tag"
        )
    elif folder_key:
        await _register_alias(db, album, folder_key, name, source="folder")

    return album
