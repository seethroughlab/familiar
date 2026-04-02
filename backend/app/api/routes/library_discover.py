"""Discovery dashboard endpoints."""

import json
import logging
from datetime import datetime

import anthropic
from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import DbSession, RequiredProfile
from app.db.models import Track, TrackStatus
from app.services.app_settings import get_app_settings_service
from app.services.redis_client import get_redis
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


class CuratedPrompt(BaseModel):
    """A single AI-generated listening suggestion."""

    prompt: str
    context: str
    icon: str | None = None


class CuratedPromptsResponse(BaseModel):
    """AI-generated listening suggestions."""

    prompts: list[CuratedPrompt]
    generated_at: str | None = None


@router.get("/discover/prompts", response_model=CuratedPromptsResponse)
async def get_curated_prompts(
    db: DbSession,
    profile: RequiredProfile,
    refresh: bool = Query(False),
) -> CuratedPromptsResponse:
    """Generate AI-powered listening suggestions based on the user's library."""
    from app.db.models import ProfilePlayHistory

    cache_key = f"curated_prompts:{profile.id}"

    # Check Redis cache (unless refresh requested)
    if not refresh:
        try:
            r = get_redis()
            cached = r.get(cache_key)
            if cached:
                return CuratedPromptsResponse(**json.loads(cached))
        except Exception:
            pass

    # Gather library context
    try:
        # Top 5 genres
        genre_query = (
            select(Track.genre, func.count(Track.id).label("cnt"))
            .where(Track.genre.isnot(None), Track.status == TrackStatus.ACTIVE)
            .group_by(Track.genre)
            .order_by(func.count(Track.id).desc())
            .limit(5)
        )
        genre_result = await db.execute(genre_query)
        top_genres = [row.genre for row in genre_result.fetchall() if row.genre]

        # Top 5 artists by play count
        artist_query = (
            select(Track.artist, func.sum(ProfilePlayHistory.play_count).label("plays"))
            .join(Track, ProfilePlayHistory.track_id == Track.id)
            .where(
                Track.artist.isnot(None),
                ProfilePlayHistory.profile_id == profile.id,
            )
            .group_by(Track.artist)
            .order_by(func.sum(ProfilePlayHistory.play_count).desc())
            .limit(5)
        )
        artist_result = await db.execute(artist_query)
        top_artists = [row.artist for row in artist_result.fetchall() if row.artist]

        # Total track count
        total_tracks = await db.scalar(
            select(func.count(Track.id)).where(Track.status == TrackStatus.ACTIVE)
        ) or 0

        # Recently added count (30 days)
        from datetime import timedelta

        thirty_days_ago = utcnow() - timedelta(days=30)
        recently_added = await db.scalar(
            select(func.count(Track.id)).where(
                Track.created_at >= thirty_days_ago,
                Track.status == TrackStatus.ACTIVE,
            )
        ) or 0

    except Exception as e:
        logger.warning(f"Failed to gather library context for prompts: {e}")
        return CuratedPromptsResponse(prompts=[])

    # Build LLM prompt
    current_hour = datetime.now().hour
    time_of_day = (
        "morning" if 5 <= current_hour < 12
        else "afternoon" if 12 <= current_hour < 17
        else "evening" if 17 <= current_hour < 21
        else "late night"
    )
    day_of_week = datetime.now().strftime("%A")

    llm_prompt = f"""Generate 5 listening suggestions for a music lover based on their library.

Library context:
- Top genres: {', '.join(top_genres) if top_genres else 'Unknown'}
- Top artists: {', '.join(top_artists) if top_artists else 'Unknown'}
- Total tracks: {total_tracks}
- Recently added: {recently_added} tracks in last 30 days
- Current time: {day_of_week} {time_of_day}

Rules:
- Each suggestion should be a natural language prompt the user can send to an AI DJ
- Reference specific artists/genres from their library when possible
- Mix different moods and styles — don't make them all similar
- Consider the time of day for 1-2 suggestions
- Keep prompts conversational (10-20 words)
- Each context line should be a brief explanation (5-10 words)
- Choose an icon from: music, headphones, radio, mic, sparkles, sun, moon, coffee, zap, heart

Respond with ONLY a JSON array, no other text:
[{{"prompt": "...", "context": "...", "icon": "..."}}]"""

    try:
        api_key = get_app_settings_service().get_effective("anthropic_api_key")
        if not api_key:
            return CuratedPromptsResponse(prompts=[])

        client = anthropic.Anthropic(api_key=api_key, timeout=15.0)
        message = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=600,
            messages=[{"role": "user", "content": llm_prompt}],
        )

        text = ""
        if message.content:
            first_block = message.content[0]
            if hasattr(first_block, "text"):
                text = first_block.text.strip()

        # Parse JSON from response (handle markdown code blocks)
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        raw_prompts = json.loads(text)
        prompts = [
            CuratedPrompt(
                prompt=p["prompt"],
                context=p.get("context", ""),
                icon=p.get("icon"),
            )
            for p in raw_prompts
            if isinstance(p, dict) and "prompt" in p
        ][:6]

        generated_at = utcnow().isoformat()
        response = CuratedPromptsResponse(prompts=prompts, generated_at=generated_at)

        # Cache in Redis (4 hours)
        try:
            r = get_redis()
            r.setex(cache_key, 14400, json.dumps(response.model_dump()))
        except Exception:
            pass

        return response

    except Exception as e:
        logger.warning(f"Failed to generate curated prompts: {e}")
        return CuratedPromptsResponse(prompts=[])


@router.get("/discover", response_model=DiscoverResponse)
async def get_discover_dashboard(
    db: DbSession,
    profile: RequiredProfile,
    recommendations_limit: int = Query(8, ge=1, le=50),
    include_in_library: bool = Query(False),
    seed_artists: int = Query(5, ge=1, le=20),
    similar_per_artist: int = Query(3, ge=1, le=15),
    min_match_score: float = Query(0.0, ge=0.0, le=1.0),
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
        .limit(seed_artists)
    )
    play_result = await db.execute(play_history_query)
    top_artists = play_result.fetchall()

    seen_recommendations: set[str] = set()
    similar_candidates: list[tuple[str, str, dict, str]] = []  # (name, normalized, similar_data, based_on)

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

        for similar in raw_similar[:similar_per_artist]:
            name = similar.get("name", "")
            if not name:
                continue
            try:
                score = float(similar.get("match", 0))
            except (ValueError, TypeError):
                score = 0.0
            if score < min_match_score:
                continue
            normalized = name.lower().strip()
            if normalized in seen_recommendations:
                continue
            seen_recommendations.add(normalized)
            similar_candidates.append((name, normalized, similar, artist_name))

    # Single GROUP BY query to check library counts for all candidate artists at once
    all_normalized_names = [c[1] for c in similar_candidates]
    lib_counts: dict[str, int] = {}
    if all_normalized_names:
        lib_result = await db.execute(
            select(
                func.lower(func.trim(Track.artist)).label("artist_norm"),
                func.count(Track.id).label("cnt"),
            )
            .where(
                func.lower(func.trim(Track.artist)).in_(all_normalized_names),
                Track.status == TrackStatus.ACTIVE,
            )
            .group_by(func.lower(func.trim(Track.artist)))
        )
        for lib_row in lib_result.all():
            lib_counts[lib_row.artist_norm] = lib_row.cnt

    # Build recommended artists list using the pre-fetched counts
    for name, normalized, similar, based_on_artist in similar_candidates:
        track_count = lib_counts.get(normalized, 0)
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
                based_on_artist=based_on_artist,
            )
        )

    # Filter to external artists only (unless caller wants all)
    if not include_in_library:
        recommended_artists = [a for a in recommended_artists if not a.in_library]

    # Sort by match score (best first) and apply limit
    recommended_artists.sort(key=lambda a: a.match_score, reverse=True)
    recommended_artists = recommended_artists[:recommendations_limit]

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
                    id=str(row.id),
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
                    id=str(row.id),
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
