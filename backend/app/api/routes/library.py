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
from app.api.routes.library_discover import router as discover_router
from app.api.routes.library_import import router as import_router
from app.api.routes.library_maps import router as maps_router
from app.api.routes.library_missing import router as missing_router
from app.api.routes.library_sync import router as sync_router
from app.db.models import AlbumType, Track, TrackAnalysis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/library", tags=["library"])


class LibraryStats(BaseModel):
    """Library statistics."""

    total_tracks: int
    total_albums: int
    total_artists: int
    albums: int
    compilations: int
    soundtracks: int
    analyzed_tracks: int
    pending_analysis: int


@router.get("/stats", response_model=LibraryStats)
async def get_library_stats(db: DbSession) -> LibraryStats:
    """Get library statistics in a single query using conditional aggregation."""
    from sqlalchemy import case

    from app.config import FEATURES_VERSION

    result = await db.execute(
        select(
            func.count(Track.id).label("total_tracks"),
            func.count(func.distinct(Track.album)).label("total_albums"),
            func.count(func.distinct(Track.artist)).label("total_artists"),
            func.sum(case((Track.album_type == AlbumType.ALBUM, 1), else_=0)).label("albums"),
            func.sum(case((Track.album_type == AlbumType.COMPILATION, 1), else_=0)).label("compilations"),
            func.sum(case((Track.album_type == AlbumType.SOUNDTRACK, 1), else_=0)).label("soundtracks"),
        )
    )
    row = result.one()

    total_tracks = row.total_tracks or 0
    analyzed_tracks = await db.scalar(
        select(func.count(TrackAnalysis.id)).where(
            TrackAnalysis.features_version >= FEATURES_VERSION
        )
    ) or 0

    return LibraryStats(
        total_tracks=total_tracks,
        total_albums=row.total_albums or 0,
        total_artists=row.total_artists or 0,
        albums=row.albums or 0,
        compilations=row.compilations or 0,
        soundtracks=row.soundtracks or 0,
        analyzed_tracks=analyzed_tracks,
        pending_analysis=total_tracks - analyzed_tracks,
    )


# Include sub-routers
router.include_router(artists_router)
router.include_router(albums_router)
router.include_router(aggregations_router)
router.include_router(maps_router)
router.include_router(sync_router)
router.include_router(analysis_router)
router.include_router(import_router)
router.include_router(missing_router)
router.include_router(discover_router)
