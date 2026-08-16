"""Library management endpoints - router aggregation."""

import logging

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.api.routes.library_aggregations import router as aggregations_router
from app.api.routes.library_albums import router as albums_router
from app.api.routes.library_analysis import router as analysis_router
from app.api.routes.library_artists import router as artists_router
from app.api.routes.library_deduplicate import router as deduplicate_router
from app.api.routes.library_discover import router as discover_router
from app.api.routes.library_import import router as import_router
from app.api.routes.library_maps import router as maps_router
from app.api.routes.library_missing import router as missing_router
from app.api.routes.library_sync import router as sync_router
from app.db.models import Track, TrackAnalysis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/library", tags=["library"])


class LibraryStats(BaseModel):
    """Library statistics.

    The three totals agree with the list endpoints that show the same things, and are counted the
    same way — see ``get_library_stats``. They did not until 2026-08-16.
    """

    total_tracks: int
    total_albums: int
    total_artists: int
    # Deprecated, and structurally meaningless: nothing in the codebase ever writes
    # ``Track.album_type``. Every row keeps the ``default=AlbumType.ALBUM`` set on the column, so
    # ``albums`` is a track count and the other two are always 0 — on a library ADR-0052 found 297
    # compilations in. Kept only because `library` is a generated tag (ADR-0007) and dropping
    # required fields is a cross-repo break; do not display them. See ADR-0058's follow-up.
    albums: int
    compilations: int
    soundtracks: int
    analyzed_tracks: int
    pending_analysis: int
    pending_backfill: int = 0
    pending_melodic: int = 0
    pending_mood_tags: int = 0


@router.get("/stats", response_model=LibraryStats)
async def get_library_stats(db: DbSession) -> LibraryStats:
    """Get library statistics.

    **These are the same counts the list endpoints return, counted the same way**, because a
    dashboard figure that disagrees with the screen it links to is worse than no figure
    (ADR-0058 point 6). Verified against the 26k-track library on 2026-08-16, when all three
    disagreed:

    - ``total_tracks`` counted every row regardless of status, so 66 missing/deleted tracks were
      reported as library size (26,488 against ``/tracks``' 26,422).
    - ``total_albums`` was ``count(distinct Track.album)`` — a *string* distinct, which merges
      same-titled albums by different artists. ``library_albums`` groups by
      ``(album_artist, album)`` case-insensitively, and said 3,927 against this query's 3,873.
    - ``total_artists`` was ``count(distinct Track.artist)`` over raw tag strings, so "The
      Beatles" and "Beatles, The" counted twice and features counted separately.
      ``library_artists`` reads the canonical ``Artist`` table (ADR-0052) and said 3,477 against
      this query's 3,664.

    ``tests/test_library_stats.py`` asserts the agreement rather than the arithmetic, so a future
    change to either side has to move both.
    """
    from sqlalchemy import and_, literal_column

    from app.config import FEATURES_VERSION, MELODIC_VERSION, MOOD_TAGS_VERSION
    from app.db.models import Artist, TrackStatus

    active = Track.status == TrackStatus.ACTIVE

    total_tracks = await db.scalar(select(func.count(Track.id)).where(active)) or 0

    # Mirrors ``library_albums.list_albums``' base query: coalesce album_artist to artist, group
    # case-insensitively on both halves. Counting the grouped subquery is what makes it agree.
    album_artist_col = func.coalesce(func.nullif(Track.album_artist, ""), Track.artist)
    total_albums = await db.scalar(
        select(func.count()).select_from(
            select(literal_column("1"))
            .where(active, Track.album.isnot(None), Track.album != "")
            .group_by(func.lower(album_artist_col), func.lower(Track.album))
            .subquery()
        )
    ) or 0

    # Mirrors ``library_artists.list_artists``: canonical artists that have at least one active
    # track. Tracks with no ``canonical_artist_id`` are scanner-failed and excluded there too.
    total_artists = await db.scalar(
        select(func.count(func.distinct(Artist.id)))
        .select_from(Artist)
        .join(Track, Track.canonical_artist_id == Artist.id)
        .where(active)
    ) or 0
    # Every analysis count joins ``Track`` and filters to active, for the same reason the totals
    # do — and here it is load-bearing rather than cosmetic. ``pending_analysis`` below is
    # ``total_tracks - analyzed_tracks``, so counting analyses of tracks that are no longer in the
    # library against an active-only total produces a *negative* backlog. On the 26k library that
    # was -41 the moment the total was corrected.
    def analysis_count(*conditions):
        return select(func.count(TrackAnalysis.id)).join(
            Track, Track.id == TrackAnalysis.track_id
        ).where(active, *conditions)

    analyzed_tracks = await db.scalar(
        analysis_count(TrackAnalysis.features_version >= FEATURES_VERSION)
    ) or 0

    # Per-phase pending counts
    pending_backfill = await db.scalar(
        analysis_count(
            and_(
                TrackAnalysis.features_version >= FEATURES_VERSION,
                TrackAnalysis.analysis_detail.is_(None),
            )
        )
    ) or 0

    pending_melodic = await db.scalar(
        analysis_count(
            and_(
                TrackAnalysis.features_version >= FEATURES_VERSION,
                TrackAnalysis.analysis_detail.is_not(None),
                TrackAnalysis.melodic_version < MELODIC_VERSION,
            )
        )
    ) or 0

    pending_mood_tags = await db.scalar(
        analysis_count(
            and_(
                TrackAnalysis.embedding.isnot(None),
                TrackAnalysis.mood_tags_version < MOOD_TAGS_VERSION,
            )
        )
    ) or 0

    return LibraryStats(
        total_tracks=total_tracks,
        total_albums=total_albums,
        total_artists=total_artists,
        # See the deprecation note on the model. These are wrong by construction, not by query.
        albums=total_tracks,
        compilations=0,
        soundtracks=0,
        analyzed_tracks=analyzed_tracks,
        # Clamped: a backlog is a count of work, and there is no such thing as -41 of it.
        pending_analysis=max(0, total_tracks - analyzed_tracks),
        pending_backfill=pending_backfill,
        pending_melodic=pending_melodic,
        pending_mood_tags=pending_mood_tags,
    )


# Include sub-routers
router.include_router(artists_router)
router.include_router(albums_router)
router.include_router(aggregations_router)
router.include_router(maps_router)
router.include_router(sync_router)
router.include_router(analysis_router)
router.include_router(import_router)
router.include_router(deduplicate_router)
router.include_router(missing_router)
router.include_router(discover_router)
