"""Track discovery endpoints: similar tracks, discover, album gain."""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.api.exceptions import NotFoundError, TrackNotFoundError
from app.db.models import Track, TrackAnalysis

from . import TrackResponse

logger = logging.getLogger(__name__)

router = APIRouter()


class AlbumGainResponse(BaseModel):
    """Album-level loudness/gain data."""

    album_gain_db: float | None = None
    album_peak: float | None = None
    track_count: int = 0


class SimilarArtistInfo(BaseModel):
    """Similar artist with library status and external links."""

    name: str
    match_score: float
    in_library: bool
    track_count: int | None = None
    image_url: str | None = None
    lastfm_url: str | None = None
    bandcamp_url: str | None = None


class TrackDiscoverResponse(BaseModel):
    """Discovery data for a track - similar tracks and artists."""

    # Source track info
    track_id: str
    artist: str | None
    title: str | None

    # Similar tracks in library (from embedding similarity)
    similar_tracks: list[TrackResponse]

    # Similar artists (from Last.fm, enriched with library status)
    similar_artists: list[SimilarArtistInfo]

    # External discovery links
    bandcamp_artist_url: str | None = None
    bandcamp_track_url: str | None = None


@router.get("/{track_id}/album-gain", response_model=AlbumGainResponse)
async def get_album_gain(
    db: DbSession,
    track_id: UUID,
) -> AlbumGainResponse:
    """Compute average LUFS for all tracks sharing the same album_artist + album.

    Returns album-level gain (dB relative to -14 LUFS target) and peak.
    Used for album-mode volume normalization.
    """
    # Get the track to find its album_artist and album
    track = await db.get(Track, track_id)
    if not track:
        raise TrackNotFoundError()

    if not track.album:
        return AlbumGainResponse()

    # Find all tracks with same album_artist (or artist) and album
    album_artist = track.album_artist or track.artist
    if not album_artist:
        return AlbumGainResponse()

    # Get loudness_lufs for all tracks in this album
    album_query = (
        select(
            TrackAnalysis.loudness_lufs.label("lufs"),
            TrackAnalysis.track_peak.label("peak"),
        )
        .join(Track, Track.id == TrackAnalysis.track_id)
        .where(
            Track.album == track.album,
            (Track.album_artist == album_artist) | (Track.artist == album_artist),
            TrackAnalysis.loudness_lufs.isnot(None),
        )
    )

    result = await db.execute(album_query)
    rows = result.all()

    if not rows:
        return AlbumGainResponse()

    lufs_values = [r.lufs for r in rows if r.lufs is not None]
    peak_values = [r.peak for r in rows if r.peak is not None]

    if not lufs_values:
        return AlbumGainResponse(track_count=len(rows))

    # Average LUFS across album tracks
    import numpy as np

    avg_lufs = float(np.mean(lufs_values))
    max_peak = float(max(peak_values)) if peak_values else None

    # Album gain = target - average loudness (target defaults to -14 LUFS)
    album_gain_db = -14.0 - avg_lufs

    return AlbumGainResponse(
        album_gain_db=album_gain_db,
        album_peak=max_peak,
        track_count=len(lufs_values),
    )


@router.get("/{track_id}/similar")
async def get_similar_tracks(
    db: DbSession,
    track_id: UUID,
    limit: int = Query(10, ge=1, le=50),
) -> list[TrackResponse]:
    """Find similar tracks using embedding similarity (pgvector)."""
    # Get the track's embedding
    query = (
        select(TrackAnalysis.embedding)
        .where(TrackAnalysis.track_id == track_id)
    )
    result = await db.execute(query)
    embedding = result.scalar_one_or_none()

    if embedding is None:
        raise NotFoundError("Track not analyzed yet")

    # Find similar tracks using cosine distance
    # Note: pgvector uses <=> for cosine distance, <-> for L2 distance
    similar_query = (
        select(Track)
        .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
        .where(Track.id != track_id)
        .where(TrackAnalysis.embedding.isnot(None))
        .order_by(TrackAnalysis.embedding.cosine_distance(embedding))
        .limit(limit)
    )

    result = await db.execute(similar_query)
    tracks = result.scalars().all()

    return [TrackResponse.model_validate(t) for t in tracks]


@router.get("/{track_id}/discover", response_model=TrackDiscoverResponse)
async def get_track_discover(
    db: DbSession,
    track_id: UUID,
    track_limit: int = Query(6, ge=1, le=20),
    artist_limit: int = Query(6, ge=1, le=20),
) -> TrackDiscoverResponse:
    """Get discovery recommendations for a track.

    Combines:
    - Similar tracks from your library (embedding-based)
    - Similar artists (Last.fm, with library status)
    - External purchase/discovery links
    """

    from app.db.models import Artist, ArtistAlias, TrackStatus
    from app.services.external_albums_helpers import normalize_artist_name
    from app.services.lastfm import get_lastfm_service
    from app.services.search_links import generate_artist_search_url, generate_search_url

    # Get the source track
    query = select(Track).where(Track.id == track_id)
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise TrackNotFoundError()

    # Get similar tracks (reuse the embedding similarity logic)
    similar_tracks: list[TrackResponse] = []
    embedding_query = (
        select(TrackAnalysis.embedding)
        .where(TrackAnalysis.track_id == track_id)
    )
    embedding_result = await db.execute(embedding_query)
    embedding = embedding_result.scalar_one_or_none()

    if embedding is not None:
        similar_query = (
            select(Track)
            .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
            .where(Track.id != track_id)
            .where(TrackAnalysis.embedding.isnot(None))
            .order_by(TrackAnalysis.embedding.cosine_distance(embedding))
            .limit(track_limit)
        )
        sim_result = await db.execute(similar_query)
        similar_tracks = [TrackResponse.model_validate(t) for t in sim_result.scalars().all()]

    # Get similar artists from Last.fm (if artist is known)
    similar_artists: list[SimilarArtistInfo] = []

    if track.artist:
        # Pass 3 cutover: read similar_artists off the canonical Artist
        # row (migrated from ArtistInfo in Pass 1's backfill).
        alias = await db.get(ArtistAlias, normalize_artist_name(track.artist))
        artist_row = (
            await db.get(Artist, alias.artist_id) if alias else None
        )
        raw_similar = (
            artist_row.similar_artists
            if artist_row and artist_row.similar_artists
            else []
        )

        # If not cached or stale, try to fetch from Last.fm
        if not raw_similar:
            lastfm_service = get_lastfm_service()
            if lastfm_service.is_configured():
                try:
                    info = await lastfm_service.get_artist_info(track.artist)
                    if info:
                        raw_similar = info.get("similar", {}).get("artist", [])
                except Exception:
                    pass  # Ignore Last.fm errors

        # Enrich similar artists with library status — alias-keyed so
        # spelling variants of the same canonical artist count as in-library.
        if raw_similar:
            similar_names = [s.get("name", "") for s in raw_similar if s.get("name")]
            similar_normalized = [normalize_artist_name(n) for n in similar_names if n]

            if similar_normalized:
                library_query = (
                    select(
                        ArtistAlias.alias_normalized.label("artist_normalized"),
                        func.count(Track.id).label("track_count"),
                    )
                    .join(Artist, Artist.id == ArtistAlias.artist_id)
                    .join(Track, Track.canonical_artist_id == Artist.id)
                    .where(
                        ArtistAlias.alias_normalized.in_(similar_normalized),
                        Track.status == TrackStatus.ACTIVE,
                    )
                    .group_by(ArtistAlias.alias_normalized)
                )
                lib_result = await db.execute(library_query)
                library_map: dict[Any, int] = {row.artist_normalized: row.track_count for row in lib_result.all()}
            else:
                library_map = {}

            for similar in raw_similar[:artist_limit]:
                name = similar.get("name", "")
                if not name:
                    continue

                normalized = normalize_artist_name(name)
                in_library = normalized in library_map
                track_count = library_map.get(normalized)

                # Extract image URL
                images = similar.get("image", [])
                image_url = None
                for img in images:
                    if img.get("size") == "large" and img.get("#text"):
                        image_url = img["#text"]
                        break
                if not image_url:
                    for img in images:
                        if img.get("#text"):
                            image_url = img["#text"]
                            break

                # Parse match score
                match_str = similar.get("match", "0")
                try:
                    match_score = float(match_str)
                except (ValueError, TypeError):
                    match_score = 0.0

                similar_artists.append(
                    SimilarArtistInfo(
                        name=name,
                        match_score=match_score,
                        in_library=in_library,
                        track_count=track_count,
                        image_url=image_url,
                        lastfm_url=similar.get("url"),
                        bandcamp_url=generate_artist_search_url("bandcamp", name),
                    )
                )

    # Generate external discovery links
    bandcamp_artist_url = None
    bandcamp_track_url = None

    if track.artist:
        bandcamp_artist_url = generate_artist_search_url("bandcamp", track.artist)
    if track.artist and track.title:
        bandcamp_track_url = generate_search_url("bandcamp", track.artist, track.title)

    return TrackDiscoverResponse(
        track_id=str(track_id),
        artist=track.artist,
        title=track.title,
        similar_tracks=similar_tracks,
        similar_artists=similar_artists,
        bandcamp_artist_url=bandcamp_artist_url,
        bandcamp_track_url=bandcamp_track_url,
    )
