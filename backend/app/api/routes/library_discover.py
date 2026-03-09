"""Discovery dashboard endpoints."""

import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import DbSession, RequiredProfile
from app.db.models import Track, TrackStatus
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(tags=["library"])


class DiscoverTrack(BaseModel):
    """A track for discovery sections."""

    id: str
    title: str | None
    artist: str | None
    album: str | None
    duration_seconds: float | None
    play_count: int


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

    # Track-based discovery
    unheard_tracks: list[DiscoverTrack]
    deep_cuts: list[DiscoverTrack]

    # Recommended artists based on top-played artists (external only)
    recommended_artists: list[DiscoverRecommendedArtist]

    # Recently added to library
    recently_added_count: int


@router.get("/discover", response_model=DiscoverResponse)
async def get_discover_dashboard(
    db: DbSession,
    profile: RequiredProfile,
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

    # Get top-played artists (filtered by profile)
    play_history_query = (
        select(
            func.lower(func.trim(Track.artist)).label("artist_normalized"),
            Track.artist,
            func.sum(ProfilePlayHistory.play_count).label("total_plays"),
        )
        .join(Track, ProfilePlayHistory.track_id == Track.id)
        .where(
            Track.artist.isnot(None),
            ProfilePlayHistory.profile_id == profile.id,
        )
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

    # Filter to external artists only
    recommended_artists = [a for a in recommended_artists if not a.in_library]

    # 2. Track-based discovery using top artist names
    unheard_tracks: list[DiscoverTrack] = []
    deep_cuts: list[DiscoverTrack] = []

    top_artist_names = [row.artist_normalized for row in top_artists if row.artist_normalized]

    if top_artist_names:
        # Subquery: track IDs this profile has played
        played_track_ids = (
            select(ProfilePlayHistory.track_id)
            .where(ProfilePlayHistory.profile_id == profile.id)
        )

        # Unheard tracks: by top artists, never played by this profile
        unheard_query = (
            select(
                Track.id,
                Track.title,
                Track.artist,
                Track.album,
                Track.duration_seconds,
            )
            .where(
                func.lower(func.trim(Track.artist)).in_(top_artist_names),
                Track.status == TrackStatus.ACTIVE,
                Track.id.notin_(played_track_ids),
            )
            .order_by(func.random())
            .limit(15)
        )
        unheard_result = await db.execute(unheard_query)
        unheard_rows = unheard_result.fetchall()
        unheard_track_ids = set()

        for row in unheard_rows:
            unheard_track_ids.add(row.id)
            unheard_tracks.append(
                DiscoverTrack(
                    id=row.id,
                    title=row.title,
                    artist=row.artist,
                    album=row.album,
                    duration_seconds=row.duration_seconds,
                    play_count=0,
                )
            )

        # Deep cuts: by top artists, played but low play count
        deep_cuts_query = (
            select(
                Track.id,
                Track.title,
                Track.artist,
                Track.album,
                Track.duration_seconds,
                ProfilePlayHistory.play_count,
            )
            .join(ProfilePlayHistory, ProfilePlayHistory.track_id == Track.id)
            .where(
                func.lower(func.trim(Track.artist)).in_(top_artist_names),
                Track.status == TrackStatus.ACTIVE,
                ProfilePlayHistory.profile_id == profile.id,
                ProfilePlayHistory.play_count > 0,
            )
            .order_by(ProfilePlayHistory.play_count.asc())
            .limit(20)  # Fetch extra to filter out unheard overlap
        )
        deep_cuts_result = await db.execute(deep_cuts_query)

        for row in deep_cuts_result.fetchall():
            if row.id in unheard_track_ids:
                continue
            deep_cuts.append(
                DiscoverTrack(
                    id=row.id,
                    title=row.title,
                    artist=row.artist,
                    album=row.album,
                    duration_seconds=row.duration_seconds,
                    play_count=row.play_count,
                )
            )
            if len(deep_cuts) >= 15:
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
        unheard_tracks=unheard_tracks,
        deep_cuts=deep_cuts,
        recommended_artists=recommended_artists,
        recently_added_count=recently_added_count,
    )
