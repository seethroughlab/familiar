"""Resolve a raw artist tag string to a canonical ``Artist`` row.

The single owner of the alias→canonical chain. Both the backfill CLI
(``app.cli.backfill_artists``) and the scanner dual-write call into
``resolve_canonical_artist`` so the two stay in lockstep.

Resolution order (first hit wins):
  1. Tag-side MusicBrainz id — if the track tag carries an MBID, find or
     create an ``Artist`` with that ``musicbrainz_id``.
  2. Alias hit — normalize the tag and look up ``ArtistAlias``.
  3. Strict MB lookup — call ``strict_mb_artist_lookup`` (the
     normalized-name verifier from ``artist_image``) for a canonical MBID;
     merge with an existing ``Artist`` by mbid or create new.
  4. Fallback — when ``create_if_missing`` is True, create a new
     ``Artist`` with the tag string as canonical name and no MBID.

Whatever path resolves, the input tag is registered in ``ArtistAlias``
(idempotent) so the next call short-circuits at step 2.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Artist, ArtistAlias
from app.services.artist_image import strict_mb_artist_lookup
from app.services.external_albums_helpers import normalize_artist_name
from app.services.metadata import musicbrainz

logger = logging.getLogger(__name__)


def _compute_sort_name(name: str) -> str:
    """Compute a sort_name when MusicBrainz doesn't provide one.

    Move a leading "The " to the end as ", The". So "The Beatles" sorts
    as "Beatles, The". For everything else, sort by the name unchanged.
    """
    stripped = name.strip()
    if stripped.lower().startswith("the "):
        return f"{stripped[4:]}, The"
    return stripped


def _canonicalize_for_match(name: str) -> str:
    """Loose-match form that ignores common 'The' / ', The' decorations.

    Used to check whether a track tag plausibly refers to the same
    artist as a candidate MB row. "Beatles", "The Beatles", "beatles,
    the" all collapse to "beatles".
    """
    n = normalize_artist_name(name)
    if n.startswith("the "):
        n = n[4:]
    if n.endswith(", the"):
        n = n[: -len(", the")]
    return n


def _tag_matches_canonical(tag: str, canonical_name: str) -> bool:
    """Whether ``tag`` plausibly refers to the artist named ``canonical_name``.

    Defends against corrupt tag-side MBIDs (a track tagged "Beatles"
    whose ``musicbrainz_artist_id`` points at "Bob Nanna" — real case
    in the test library). Honors the article-decoration variants but
    rejects unrelated names.
    """
    if not tag or not canonical_name:
        return False
    return _canonicalize_for_match(tag) == _canonicalize_for_match(
        canonical_name
    )


async def _find_artist_by_mbid(
    db: AsyncSession, mbid: str
) -> Artist | None:
    return (
        await db.execute(select(Artist).where(Artist.musicbrainz_id == mbid))
    ).scalar_one_or_none()


async def _register_alias(
    db: AsyncSession,
    artist: Artist,
    tag: str,
    *,
    source: str,
) -> None:
    """Insert ``ArtistAlias`` for ``tag`` → ``artist`` if it doesn't exist.

    Treats a normalize-collision with a different artist as a no-op (the
    first writer wins). Real cross-artist alias collisions surface during
    manual merges in Pass 2's admin UI; for backfill they're vanishingly
    rare and not worth a hard error.
    """
    normalized = normalize_artist_name(tag)
    if not normalized:
        return
    existing = await db.get(ArtistAlias, normalized)
    if existing is not None:
        return
    db.add(
        ArtistAlias(
            alias_normalized=normalized,
            alias=tag.strip(),
            artist_id=artist.id,
            source=source,
        )
    )
    await db.flush()


async def _create_artist_from_mb(
    db: AsyncSession, mbid: str, fallback_name: str
) -> Artist:
    """Create an ``Artist`` row from a MusicBrainz id.

    Pulls canonical name + sort-name via ``get_artist_by_id`` (blocking,
    runs in a thread). Falls back to the input tag if MB returns no
    name.
    """
    mb = await asyncio.to_thread(musicbrainz.get_artist_by_id, mbid)
    name = (mb or {}).get("name") or fallback_name.strip()
    sort_name = (mb or {}).get("sort_name") or _compute_sort_name(name)
    artist = Artist(
        name=name,
        sort_name=sort_name,
        musicbrainz_id=mbid,
    )
    db.add(artist)
    await db.flush()
    return artist


async def resolve_canonical_artist(
    db: AsyncSession,
    artist_tag: str,
    *,
    musicbrainz_artist_id: str | None = None,
    do_mb_lookup: bool = False,
    create_if_missing: bool = True,
) -> Artist | None:
    """Return the canonical ``Artist`` for an artist tag string.

    Args:
        artist_tag: The raw artist tag value as it appears in the file.
        musicbrainz_artist_id: Optional tag-side MBID (from
            ``Track.musicbrainz_artist_id`` or import metadata).
        do_mb_lookup: When True and no alias hit, fall back to a strict
            MB search. False is the default for the scanner (MB is slow,
            1 RPS); the backfill CLI sets True.
        create_if_missing: Create a new ``Artist`` row when nothing
            else matches. False disables side effects entirely (used
            by tests and dry-run).

    Returns:
        The matched/created ``Artist``, or None if nothing matched and
        ``create_if_missing`` is False.
    """
    if not artist_tag or not artist_tag.strip():
        return None

    normalized = normalize_artist_name(artist_tag)
    if not normalized:
        return None

    # 1. Tag-side MBID match — but only if the MBID's canonical name
    #    plausibly matches the tag. Some libraries carry corrupt MBIDs
    #    (e.g. a "Beatles" track tagged with Bob Nanna's MBID) and
    #    blindly trusting them attaches tracks to the wrong canonical
    #    artist. On mismatch we fall through to the alias / strict-MB
    #    paths.
    if musicbrainz_artist_id:
        existing = await _find_artist_by_mbid(db, musicbrainz_artist_id)
        if existing is not None:
            if _tag_matches_canonical(artist_tag, existing.name):
                await _register_alias(
                    db, existing, artist_tag, source="tag"
                )
                return existing
            # Tag-side MBID points at a known artist by a different
            # name — reject this MBID and fall through.
        elif create_if_missing:
            mb = await asyncio.to_thread(
                musicbrainz.get_artist_by_id, musicbrainz_artist_id
            )
            mb_name = (mb or {}).get("name")
            if mb_name and _tag_matches_canonical(artist_tag, mb_name):
                sort_name = (mb or {}).get("sort_name") or _compute_sort_name(
                    mb_name
                )
                artist = Artist(
                    name=mb_name,
                    sort_name=sort_name,
                    musicbrainz_id=musicbrainz_artist_id,
                )
                db.add(artist)
                await db.flush()
                await _register_alias(
                    db, artist, artist_tag, source="tag"
                )
                return artist
            # MBID lookup either failed or returned a non-matching name —
            # fall through. The MBID is not registered against any
            # Artist row, so a future tag with the same MBID won't get a
            # path-1a hit either.

    # 2. Alias hit.
    alias = await db.get(ArtistAlias, normalized)
    if alias is not None:
        return await db.get(Artist, alias.artist_id)

    # 3. Strict MB lookup (only when caller opts in — slow at 1 RPS).
    if do_mb_lookup:
        try:
            mb_id = await asyncio.to_thread(
                strict_mb_artist_lookup, artist_tag
            )
        except Exception as e:
            logger.debug(
                f"strict_mb_artist_lookup raised for '{artist_tag}': {e}"
            )
            mb_id = None
        if mb_id:
            existing = await _find_artist_by_mbid(db, mb_id)
            if existing is not None:
                await _register_alias(db, existing, artist_tag, source="mb")
                return existing
            if create_if_missing:
                artist = await _create_artist_from_mb(db, mb_id, artist_tag)
                await _register_alias(db, artist, artist_tag, source="mb")
                return artist

    # 4. Fallback: a fresh standalone Artist with no MBID.
    if not create_if_missing:
        return None

    name = artist_tag.strip()
    artist = Artist(name=name, sort_name=_compute_sort_name(name))
    db.add(artist)
    await db.flush()
    await _register_alias(db, artist, artist_tag, source="tag")
    return artist
