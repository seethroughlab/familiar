"""Shared helpers for external-album discovery (#2 and #3).

Both ``new_releases.py`` (#3 — new releases from library artists) and
``recommendations.py`` (#2 — external album recommendations from playlist
context) need the same artist-name normalization and library-album-match
logic. Living here so both features stay in sync.
"""

import unicodedata

from rapidfuzz import fuzz
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import TextClause

from app.db.models import Track

# The three values `ExternalAlbumCache.discovery_context` may take. They live here,
# rather than in the service that writes each one, because the partial unique indexes
# below are keyed on them and all three must agree.
ARTIST_NEW_RELEASE_CONTEXT = "artist_new_release"
PLAYLIST_REC_CONTEXT = "playlist_recommendation"
LISTENING_PROFILE_CONTEXT = "listening_profile_recommendation"

# Literal predicates that exactly mirror the partial-unique-index `postgresql_where`
# clauses on ExternalAlbumCache (see `app/db/models/artists.py`). PostgreSQL needs
# the ON CONFLICT inference predicate to imply the partial index predicate at plan
# time; a parameterized comparison (`discovery_context = $param`) breaks inference,
# so each context maps to a fixed text clause that matches the index definition.
#
# `artist_new_release` was missing here until 2026-08-30, and its absence is not why
# it was added: `save_discovered_release` was deduping on `release_id` alone, without
# any context predicate at all. Uniqueness in this table is *per context*, so one
# release legitimately exists once per context, and `scalar_one_or_none()` raised
# `MultipleResultsFound` on the single release that did. That killed the nightly
# discovery job every night for nineteen nights. See ADR-0099.
_INDEX_WHERE_BY_CONTEXT: dict[str, TextClause] = {
    ARTIST_NEW_RELEASE_CONTEXT: text("discovery_context = 'artist_new_release'"),
    PLAYLIST_REC_CONTEXT: text("discovery_context = 'playlist_recommendation'"),
    LISTENING_PROFILE_CONTEXT: text(
        "discovery_context = 'listening_profile_recommendation'"
    ),
}


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
