"""Discovery dashboard endpoints."""

import logging
from datetime import timedelta

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import DbSession, RequiredProfile
from app.api.routes._external_albums_schemas import (
    ExternalAlbumResponse,
    ExternalAlbumsResponse,
)
from app.db.models import Artist, ArtistAlias, Track, TrackStatus
from app.services.external_albums_helpers import normalize_artist_name
from app.services.recommendations import RecommendationsService
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(tags=["discover"])


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


class RediscoverySuggestion(BaseModel):
    """An unheard library track, and the played track that reached it."""

    track: DiscoverTrack
    #: **The reason, as a real pair of tracks.** ADR-0093 tried three times to name a
    #: cluster and failed each time; "because you play X" is both true and checkable
    #: where a generated label is neither. ADR-0101 point 3 keeps that rule here.
    because_of_title: str | None
    because_of_artist: str | None
    similarity: float
    #: How many of your played tracks independently reached this one. Agreement, not
    #: an average — see `collection_suggestions` for why the average was abandoned.
    votes: int


class DiscoverResponse(BaseModel):
    """Aggregated discovery data for the dashboard."""

    #: Owned, unheard, ranked against what you actually listen to (ADR-0101).
    #:
    #: Replaces `unheard_tracks` and `deep_cuts`, which were `ORDER BY random()` over
    #: tracks by artists already played — not a ranking, and unable to reach an artist
    #: the listener had never played however well it matched.
    rediscovery: list[RediscoverySuggestion]
    #: Seeds behind the list, so an empty result can say *why*. No listening history
    #: and nothing similar found are different answers (ADR-0101 point 7).
    rediscovery_seed_count: int

    # Recommended artists based on top-played artists (external only)
    recommended_artists: list[DiscoverRecommendedArtist]

    # Recently added to library
    recently_added_count: int


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

    from app.db.models import ProfilePlayHistory
    from app.services.lastfm import get_lastfm_service
    from app.services.search_links import generate_artist_search_url

    # 1. Recommended artists, seeded by canonical top-played artists.
    recommended_artists: list[DiscoverRecommendedArtist] = []

    play_history_query = (
        select(
            Artist.id.label("artist_id"),
            Artist.name.label("artist_name"),
            Artist.similar_artists.label("similar_cached"),
            func.sum(ProfilePlayHistory.play_count).label("total_plays"),
        )
        .join(Track, ProfilePlayHistory.track_id == Track.id)
        .join(Artist, Artist.id == Track.canonical_artist_id)
        .where(ProfilePlayHistory.profile_id == profile.id)
        .group_by(Artist.id, Artist.name, Artist.similar_artists)
        .order_by(func.sum(ProfilePlayHistory.play_count).desc())
        .limit(seed_artists)
    )
    play_result = await db.execute(play_history_query)
    top_artists = play_result.fetchall()

    seen_recommendations: set[str] = set()
    similar_candidates: list[tuple[str, str, dict, str]] = []  # (name, normalized, similar_data, based_on)

    for row in top_artists:
        artist_name = row.artist_name
        if not artist_name:
            continue

        # Use Artist.similar_artists if cached, else fetch from Last.fm.
        if row.similar_cached:
            raw_similar = row.similar_cached
        else:
            lastfm_service = get_lastfm_service()
            if lastfm_service.is_configured():
                try:
                    info = await lastfm_service.get_artist_info(artist_name)
                    raw_similar = (
                        info.get("similar", {}).get("artist", []) if info else []
                    )
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
            normalized = normalize_artist_name(name)
            if normalized in seen_recommendations:
                continue
            seen_recommendations.add(normalized)
            similar_candidates.append((name, normalized, similar, artist_name))

    # Library presence check for similar artists — alias-keyed so spelling
    # variants of the same canonical artist count as in-library.
    all_normalized_names = [c[1] for c in similar_candidates]
    lib_counts: dict[str, int] = {}
    if all_normalized_names:
        lib_result = await db.execute(
            select(
                ArtistAlias.alias_normalized.label("alias_norm"),
                func.count(Track.id).label("cnt"),
            )
            .join(Artist, Artist.id == ArtistAlias.artist_id)
            .join(Track, Track.canonical_artist_id == Artist.id)
            .where(
                ArtistAlias.alias_normalized.in_(all_normalized_names),
                Track.status == TrackStatus.ACTIVE,
            )
            .group_by(ArtistAlias.alias_normalized)
        )
        for lib_row in lib_result.all():
            lib_counts[lib_row.alias_norm] = lib_row.cnt

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

    # Replace Last.fm placeholder image_urls. Synchronous path is cache + a
    # short Wikipedia probe (direct + opensearch). Anything still missing is
    # fired off to a background task (MB + Wikidata, no time pressure) so
    # subsequent dashboard loads pick up real images. UI shows gradient
    # initial avatars for whatever isn't resolved yet. The seed artist
    # (``based_on_artist``) is passed as a disambiguation hint — picks the
    # right page when multiple Wikipedia musicians share a name.
    from app.services.artist_image import (
        resolve_many_artist_images,
        schedule_background_resolve,
    )

    items: list[tuple[str, str | None]] = [
        (a.name, a.based_on_artist) for a in recommended_artists
    ]
    resolved_images = await resolve_many_artist_images(db, items)
    await db.commit()
    for a in recommended_artists:
        a.image_url = resolved_images.get(a.name)

    unresolved = [
        (a.name, a.based_on_artist)
        for a in recommended_artists
        if resolved_images.get(a.name) is None
    ]
    schedule_background_resolve(unresolved)

    # 2. Track-based discovery using top canonical artist ids.
    # **Ranked against listening, not ordered at random** (ADR-0101 point 2).
    #
    # The engine is ADR-0093's: each played track's nearest neighbours, counted by how
    # many seeds independently reach a candidate. Crucially the candidate pool is the
    # whole library, so an unheard record by an artist never played can surface if it
    # sounds like what this listener loves — which the previous top-artist filter made
    # impossible by construction.
    from app.services.rediscovery import suggest_rediscovery

    suggestions, seed_count = await suggest_rediscovery(
        db, profile_id=profile.id, limit=15
    )
    rediscovery = [
        RediscoverySuggestion(
            track=DiscoverTrack(
                id=str(s.track.id),
                title=s.track.title,
                artist=s.track.artist,
                album=s.track.album,
                duration_seconds=s.track.duration_seconds,
                play_count=0,
            ),
            because_of_title=s.because_of.title,
            because_of_artist=s.because_of.artist,
            similarity=round(s.similarity, 4),
            votes=s.votes,
        )
        for s in suggestions
    ]

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
        rediscovery=rediscovery,
        rediscovery_seed_count=seed_count,
        recommended_artists=recommended_artists,
        recently_added_count=recently_added_count,
    )


@router.get(
    "/discover/external-albums",
    response_model=ExternalAlbumsResponse,
)
async def get_listening_profile_external_albums(
    db: DbSession,
    profile: RequiredProfile,
    limit: int = Query(12, ge=1, le=50),
    refresh: bool = Query(False),
) -> ExternalAlbumsResponse:
    """External album recommendations seeded by the user's top-played artists.

    Profile-wide (no specific playlist). Persists rows with
    ``discovery_context='listening_profile_recommendation'``. 24h TTL —
    pass ``refresh=true`` to force a recompute.
    """
    service = RecommendationsService(db)
    try:
        rows = await service.get_listening_profile_external_albums(
            profile.id, limit=limit, refresh=refresh
        )
        await db.commit()
        return ExternalAlbumsResponse(
            albums=[ExternalAlbumResponse(**row) for row in rows]
        )
    finally:
        await service.close()
