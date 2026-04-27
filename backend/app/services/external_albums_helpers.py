"""Shared helpers for external-album discovery (#2 and #3).

Both ``new_releases.py`` (#3 — new releases from library artists) and
``recommendations.py`` (#2 — external album recommendations from playlist
context) need the same artist-name normalization and library-album-match
logic. Living here so both features stay in sync.
"""

import unicodedata

from rapidfuzz import fuzz
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Track


def normalize_artist_name(name: str) -> str:
    """Normalize an artist name for consistent matching.

    Lowercase, strip NFKD-decomposable diacritics, collapse whitespace.
    Note: non-decomposable letters (e.g. ``ð``, ``ł``) are preserved as-is —
    this is intentional and matches the behavior of the original new-releases
    feature.
    """
    name = name.lower().strip()
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = " ".join(name.split())
    return name


async def check_user_has_release(
    db: AsyncSession,
    artist_name: str,
    album_name: str,
    musicbrainz_album_id: str | None = None,
) -> bool:
    """Return True if the user already has this release in their library.

    Matching tiers:
    1. MusicBrainz release-group/album id (exact match) — short-circuits.
    2. Lowercase exact match on (artist, album).
    3. Fuzzy match (rapidfuzz, weighted album 0.7 + artist 0.3, threshold 85).
    """
    if musicbrainz_album_id:
        result = await db.execute(
            select(func.count(Track.id)).where(
                Track.musicbrainz_album_id == musicbrainz_album_id
            )
        )
        if (result.scalar() or 0) > 0:
            return True

    artist_lower = artist_name.lower().strip()
    album_lower = album_name.lower().strip()

    result = await db.execute(
        select(func.count(Track.id)).where(
            func.lower(Track.artist) == artist_lower,
            func.lower(Track.album) == album_lower,
        )
    )
    if (result.scalar() or 0) > 0:
        return True

    result = await db.execute(
        select(Track.album, Track.artist)
        .where(
            Track.album.isnot(None),
            func.lower(Track.artist).contains(artist_lower[:10]),
        )
        .distinct()
        .limit(500)
    )
    for track_album, track_artist in result.fetchall():
        if not track_album or not track_artist:
            continue
        album_score = fuzz.ratio(album_lower, track_album.lower())
        artist_score = fuzz.ratio(artist_lower, track_artist.lower())
        combined = (album_score * 0.7) + (artist_score * 0.3)
        if combined >= 85:
            return True

    return False
