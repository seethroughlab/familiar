"""Discovery dashboard endpoints."""

import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.db.models import Track, TrackStatus
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(tags=["library"])


class DiscoverRecommendedArtist(BaseModel):
    """A recommended artist based on listening patterns."""

    name: str
    match_score: float
    in_library: bool
    track_count: int | None = None
    image_url: str | None = None
    lastfm_url: str | None = None
    bandcamp_url: str | None = None
    based_on_artist: str  # Which library artist triggered this recommendation


class DiscoverResponse(BaseModel):
    """Aggregated discovery data for the dashboard."""

    # Recommended artists based on top-played artists
    recommended_artists: list[DiscoverRecommendedArtist]

    # Recently added to library
    recently_added_count: int


@router.get("/discover", response_model=DiscoverResponse)
async def get_discover_dashboard(
    db: DbSession,
    recommendations_limit: int = Query(8, ge=1, le=20),
) -> DiscoverResponse:
    """Get aggregated discovery data for the dashboard.

    Combines:
    - New releases from library artists
    - Recommended artists based on most-played
    - Recently added track count
    """
    from datetime import timedelta

    from app.db.models import ArtistInfo, ProfilePlayHistory
    from app.services.lastfm import get_lastfm_service
    from app.services.search_links import generate_artist_search_url

    # 1. Get recommended artists based on top-played artists
    recommended_artists: list[DiscoverRecommendedArtist] = []

    # Get top-played artists
    play_history_query = (
        select(
            func.lower(func.trim(Track.artist)).label("artist_normalized"),
            Track.artist,
            func.sum(ProfilePlayHistory.play_count).label("total_plays"),
        )
        .join(Track, ProfilePlayHistory.track_id == Track.id)
        .where(Track.artist.isnot(None))
        .group_by(func.lower(func.trim(Track.artist)), Track.artist)
        .order_by(func.sum(ProfilePlayHistory.play_count).desc())
        .limit(5)  # Top 5 artists
    )
    play_result = await db.execute(play_history_query)
    top_artists = play_result.fetchall()

    # For each top artist, get similar artists
    seen_recommendations: set[str] = set()

    for row in top_artists:
        artist_name = row.artist
        if not artist_name:
            continue

        artist_normalized = artist_name.lower().strip()

        # Check cached artist info for similar artists
        cached_info = await db.get(ArtistInfo, artist_normalized)
        if cached_info and cached_info.similar_artists:
            raw_similar = cached_info.similar_artists
        else:
            # Try fetching from Last.fm
            lastfm_service = get_lastfm_service()
            if lastfm_service.is_configured():
                try:
                    info = await lastfm_service.get_artist_info(artist_name)
                    if info:
                        raw_similar = info.get("similar", {}).get("artist", [])
                    else:
                        raw_similar = []
                except Exception:
                    raw_similar = []
            else:
                raw_similar = []

        # Process similar artists
        for similar in raw_similar[:3]:  # Take top 3 from each
            name = similar.get("name", "")
            if not name:
                continue

            normalized = name.lower().strip()
            if normalized in seen_recommendations:
                continue
            seen_recommendations.add(normalized)

            # Check if in library
            lib_check = await db.execute(
                select(func.count(Track.id))
                .where(
                    func.lower(func.trim(Track.artist)) == normalized,
                    Track.status == TrackStatus.ACTIVE,
                )
            )
            track_count = lib_check.scalar() or 0
            in_library = track_count > 0

            # Extract image URL
            images = similar.get("image", [])
            image_url = None
            for img in images:
                if img.get("size") == "large" and img.get("#text"):
                    image_url = img["#text"]
                    break

            # Parse match score
            try:
                match_score = float(similar.get("match", 0))
            except (ValueError, TypeError):
                match_score = 0.0

            recommended_artists.append(
                DiscoverRecommendedArtist(
                    name=name,
                    match_score=match_score,
                    in_library=in_library,
                    track_count=track_count if in_library else None,
                    image_url=image_url,
                    lastfm_url=similar.get("url"),
                    bandcamp_url=generate_artist_search_url("bandcamp", name),
                    based_on_artist=artist_name,
                )
            )

            if len(recommended_artists) >= recommendations_limit:
                break

        if len(recommended_artists) >= recommendations_limit:
            break

    # 3. Get recently added count (last 30 days)
    thirty_days_ago = utcnow() - timedelta(days=30)
    recent_query = (
        select(func.count(Track.id))
        .where(
            Track.created_at >= thirty_days_ago,
            Track.status == TrackStatus.ACTIVE,
        )
    )
    recently_added_count = await db.scalar(recent_query) or 0

    return DiscoverResponse(
        recommended_artists=recommended_artists,
        recently_added_count=recently_added_count,
    )
