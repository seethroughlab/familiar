"""Artist browsing and detail endpoints."""

import asyncio
import html
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.sql import ColumnElement

from app.api.deps import CurrentProfile, DbSession
from app.api.exceptions import NotFoundError
from app.api.schemas.artists import SimilarArtistInfo
from app.api.schemas.common import UTCDateTime
from app.db.models import Artist, ArtistAlias, ProfilePlayHistory, Track, TrackAnalysis, TrackStatus
from app.services.external_albums_helpers import normalize_artist_name
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

router = APIRouter()


class ArtistSummary(BaseModel):
    """Artist with aggregated stats."""

    id: str | None = None  # Canonical Artist.id (UUID); None if not in canonical table
    name: str
    track_count: int
    album_count: int
    first_track_id: str  # For artwork lookup
    first_album: str | None = None
    image_url: str | None = None  # Resolved Wikipedia/Wikidata/Spotify thumbnail

    # Columns for the Mac's artists table (ADR-0094). All are aggregates over the same grouped
    # query the counts already use, so they cost no extra round trip.
    total_duration_seconds: float | None = None
    year_min: int | None = None
    year_max: int | None = None
    #: When this artist first appeared in the library — `min(Track.created_at)`.
    date_added: UTCDateTime | None = None
    #: Per-profile, and null when the request carries no profile. "How often have you played this"
    #: has no answer when there is no you — the same reasoning `PROFILE_SORT_FIELDS` uses on the
    #: tracks list.
    play_count: int | None = None
    last_played_at: UTCDateTime | None = None


class ArtistListResponse(BaseModel):
    """Paginated list of artists."""

    items: list[ArtistSummary]
    total: int
    page: int
    page_size: int


@router.get("/artists", tags=["library"], response_model=ArtistListResponse)
async def list_artists(
    db: DbSession,
    profile: CurrentProfile = None,
    search: str | None = None,
    sort_by: str = "name",
    sort_order: str | None = None,
    page: int = 1,
    page_size: int = 100,
    has_embeddings: bool = False,
) -> ArtistListResponse:
    """Get distinct artists with aggregated stats.

    Includes first_track_id for artwork lookup.

    **The aggregates are all over the one grouped query**, so the extra columns the Mac's table
    shows (ADR-0094) cost no second round trip: duration, year range and date-added come from the
    `Track` join that already computes the counts.

    ``play_count`` and ``last_played_at`` are **per profile** and null without one, via an outer
    join to ``ProfilePlayHistory``. That mirrors ``PROFILE_SORT_FIELDS`` on the tracks list: "how
    often have you played this" has no answer when there is no you, and ordering by it anyway
    would leave the database to invent a cross join.

    ``sort_by`` accepts ``name``, ``track_count``, ``album_count``, ``duration``, ``date_added``,
    ``year``, ``play_count`` and ``last_played`` — the last two only with a profile, falling back
    to name without one rather than erroring.

    ``sort_order`` is ``asc``/``desc``, and defaults to whichever way the column is usually read:
    A-first for a name, biggest-first for a count or a date. A client that offers a direction
    control must send one, or the arrow it draws will disagree with the rows it gets.

    Args:
        has_embeddings: If True, only include artists that have at least one
            track with an embedding (for use in similarity-based features).
    """
    from sqlalchemy import cast, desc, literal_column
    from sqlalchemy.dialects.postgresql import TEXT

    # Pass 2 read cutover: group by canonical artist (joined via
    # ``Track.canonical_artist_id``) instead of by lowered tag string.
    # Display name + sort_name come from the ``Artist`` row, so "The
    # Beatles" and "Beatles, The" collapse into one tile and sort
    # under B (via ``sort_name``). Tracks with no canonical artist are
    # excluded — Pass 1 resolved 100% of active tracks; any leftover
    # NULLs are scanner-failed and not really "in the library" yet.
    base_query = (
        select(
            Artist.id.label("artist_id"),
            Artist.name.label("name"),
            Artist.sort_name.label("sort_name"),
            Artist.image_url.label("image_url"),
            func.count(Track.id).label("track_count"),
            func.count(func.distinct(Track.album)).label("album_count"),
            func.min(cast(Track.id, TEXT)).label("first_track_id"),
            func.min(Track.album).label("first_album"),
            # ADR-0094's columns, aggregated over the join that is already here.
            func.sum(Track.duration_seconds).label("total_duration_seconds"),
            func.min(Track.year).label("year_min"),
            func.max(Track.year).label("year_max"),
            func.min(Track.created_at).label("date_added"),
            # Per profile, and null without one — see the docstring.
            func.sum(ProfilePlayHistory.play_count).label("play_count"),
            func.max(ProfilePlayHistory.last_played_at).label("last_played_at"),
        )
        .join(Track, Track.canonical_artist_id == Artist.id)
        .where(Track.status == TrackStatus.ACTIVE)
        .group_by(Artist.id, Artist.name, Artist.sort_name, Artist.image_url)
    )

    # **Outer** join, and scoped to this profile in the ON clause rather than in `WHERE`. In
    # `WHERE` it would become an inner join and silently drop every artist the listener has never
    # played — which is exactly the set "last played" is most useful for finding.
    if profile is not None:
        base_query = base_query.outerjoin(
            ProfilePlayHistory,
            (ProfilePlayHistory.track_id == Track.id)
            & (ProfilePlayHistory.profile_id == profile.id),
        )
    else:
        # No profile: keep the columns in the row shape, always null, so the response schema does
        # not change between requests.
        base_query = base_query.outerjoin(ProfilePlayHistory, literal_column("false"))

    # Filter to only artists with embeddings if requested.
    if has_embeddings:
        tracks_with_embeddings = (
            select(TrackAnalysis.track_id)
            .where(TrackAnalysis.embedding.isnot(None))
            .distinct()
            .subquery()
        )
        base_query = base_query.where(Track.id.in_(select(tracks_with_embeddings)))

    # Search filter — match on canonical artist name (and sort_name) so
    # users can search for "Beatles" and find "The Beatles".
    if search:
        s = search.lower()
        base_query = base_query.where(
            func.lower(Artist.name).contains(s) | func.lower(Artist.sort_name).contains(s)
        )

    # Total count.
    count_query = select(func.count()).select_from(base_query.subquery())
    total = await db.scalar(count_query) or 0

    # Sorting — prefer ``Artist.sort_name`` so "The Beatles" sorts under B.
    # Counts and dates descend; the name ascends. "Sort by tracks" means the biggest first, and
    # "sort by name" means A first — one direction for both would make one of them useless.
    #
    # `Artist.sort_name` is the tiebreaker on every branch so the order is total: without it, rows
    # tied on an aggregate have no defined order and OFFSET paging may repeat or skip them between
    # pages, which is the defect `apply_track_sort` records on the tracks list.
    descending = {
        "track_count": "track_count",
        "album_count": "album_count",
        "duration": "total_duration_seconds",
        "date_added": "date_added",
        "year": "year_max",
    }
    # Per-profile sorts need a profile, for the reason `PROFILE_SORT_FIELDS` gives: ordering by a
    # column from a table that was never joined is a wrong answer served slowly. Fall back to name.
    if profile is not None:
        descending["play_count"] = "play_count"
        descending["last_played"] = "last_played_at"

    if column := descending.get(sort_by):
        # Natural direction unless the caller says otherwise.
        ascending = sort_order == "asc"
        ordering: ColumnElement[Any] = literal_column(column)
        base_query = base_query.order_by(
            ordering.asc().nullslast() if ascending else desc(ordering).nullslast(),
            Artist.sort_name,
        )
    else:
        base_query = base_query.order_by(
            Artist.sort_name.desc() if sort_order == "desc" else Artist.sort_name
        )

    offset = (page - 1) * page_size
    base_query = base_query.offset(offset).limit(page_size)

    result = await db.execute(base_query)
    rows = result.all()

    items = [
        ArtistSummary(
            id=str(row.artist_id),
            name=row.name,
            track_count=row.track_count,
            album_count=row.album_count,
            first_track_id=str(row.first_track_id),
            first_album=row.first_album,
            total_duration_seconds=row.total_duration_seconds,
            year_min=row.year_min,
            year_max=row.year_max,
            date_added=row.date_added,
            play_count=row.play_count,
            last_played_at=row.last_played_at,
            image_url=row.image_url,
        )
        for row in rows
    ]

    # For artists whose ``Artist.image_url`` is NULL, fill in from the image cache — and **only**
    # from the cache.
    #
    # This used to call ``resolve_many_artist_images``, which reads the same cache and then spends
    # up to its four-second ``wikipedia_timeout`` resolving whatever missed. On a page of 100
    # artists that is a Wikipedia round trip on the request path, and it measured at **4.1 seconds
    # per page** against 0.12 for ``/library/albums`` doing the same shape of work. It is the same
    # defect as the external-albums endpoint ADR-0090's work found at 71 seconds: expensive
    # external calls where a listener is waiting.
    #
    # The misses go to ``schedule_background_resolve``, which was already being called three lines
    # below for whatever the synchronous attempt failed to find. It runs the fuller Wikipedia → MB →
    # Wikidata chain on its own session, persists, and negative-caches every input — its own
    # docstring says "no time pressure ... off the request path". The synchronous call was doing a
    # weaker version of that work while a request waited for it.
    #
    # The cost is that an artist whose image has never been resolved renders without one on first
    # paint instead of after a four-second wait. Clients already handle a null ``image_url``
    # (``ArtistInitials`` in the Apple client draws initials), and the next load has the image.
    unresolved_names = [a.name for a in items if a.image_url is None]
    if unresolved_names:
        from app.services.artist_image import (
            read_cached_artist_images,
            schedule_background_resolve,
        )

        cached = await read_cached_artist_images(db, unresolved_names)
        for a in items:
            if a.image_url is None:
                a.image_url = cached.get(a.name)
        still_missing: list[tuple[str, str | None]] = [
            (a.name, None) for a in items if a.image_url is None
        ]
        schedule_background_resolve(still_missing)

    return ArtistListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


# ============================================================================
# Artist Detail
# ============================================================================


class ArtistAlbum(BaseModel):
    """Album belonging to an artist in the library."""

    name: str
    year: int | None
    track_count: int
    first_track_id: str


class ArtistTrack(BaseModel):
    """Track belonging to an artist."""

    id: str
    title: str | None
    album: str | None
    track_number: int | None
    duration_seconds: float | None
    year: int | None


class ArtistDetailResponse(BaseModel):
    """Detailed artist info with bio, albums, and tracks."""

    # Basic info (from library)
    id: str | None = None  # Canonical Artist.id (UUID)
    name: str
    track_count: int
    album_count: int
    total_duration_seconds: float

    # From Last.fm (may be None if not fetched/available)
    bio_summary: str | None = None
    bio_content: str | None = None
    image_url: str | None = None
    lastfm_url: str | None = None
    listeners: int | None = None
    playcount: int | None = None
    tags: list[str] = []
    similar_artists: list[SimilarArtistInfo] = []

    # Library content
    albums: list[ArtistAlbum]
    tracks: list[ArtistTrack]

    # First track ID for fallback artwork
    first_track_id: str

    # Cache status
    lastfm_fetched: bool = False
    lastfm_error: str | None = None


# ── Artist Detail ─────────────────────────────────────────────


async def _resolve_artist_via_alias(db: DbSession, artist_name: str) -> Artist | None:
    """Resolve a URL artist name to a canonical ``Artist`` row.

    Tries the NFKD-stripped form first (the resolver's preferred key),
    falls back to a raw lower-trim lookup so URLs that preserve diacritics
    (``/library/artists/Björk``) still resolve when they happen to differ
    from the stored alias_normalized form.
    """
    normalized = normalize_artist_name(artist_name)
    if not normalized:
        return None
    alias = await db.get(ArtistAlias, normalized)
    if alias is None:
        alt = artist_name.lower().strip()
        if alt and alt != normalized:
            alias = await db.get(ArtistAlias, alt)
    if alias is None:
        return None
    return await db.get(Artist, alias.artist_id)


_TAG_RE = re.compile(r"<[^>]+>")


def _plain_text(value: str | None) -> str | None:
    """Last.fm biography HTML, as text.

    Only tags are removed. The trailing "Read more on Last.fm" anchor becomes its own text, which
    reads as a sentence rather than as markup — and `lastfm_url` is returned alongside for a client
    that wants a real link.
    """
    if not value:
        return value
    stripped = html.unescape(_TAG_RE.sub("", value))
    # Collapse the whitespace the removed tags leave behind, without touching paragraph breaks.
    return re.sub(r"[ \t]{2,}", " ", stripped).strip()


@router.get("/artists/{artist_name}", tags=["library"], response_model=ArtistDetailResponse)
async def get_artist_detail(
    db: DbSession,
    artist_name: str,
    refresh_lastfm: bool = False,
) -> ArtistDetailResponse:
    """Get detailed artist information including Last.fm bio and library content.

    Resolves the URL name to a canonical ``Artist`` row via ``ArtistAlias``,
    then queries stats/albums/tracks via ``Track.canonical_artist_id``. The
    response ``name`` is the canonical name, not the URL input — that's
    what makes "Beatles" and "The Beatles" visually de-duplicate.

    Last.fm cache is read from / written to ``Artist.*`` (already migrated
    by Pass 1's backfill). The legacy ``ArtistInfo`` table is no longer
    written from this endpoint; Pass 3 will drop it.

    Args:
        artist_name: The artist name (URL-encoded)
        refresh_lastfm: Force refresh of Last.fm data
    """
    from datetime import timedelta
    from urllib.parse import unquote

    from sqlalchemy import cast
    from sqlalchemy.dialects.postgresql import TEXT

    from app.services.lastfm import get_lastfm_service

    artist_name = unquote(artist_name)

    artist = await _resolve_artist_via_alias(db, artist_name)
    if artist is None:
        raise NotFoundError("Artist not found in library")

    # Library stats — match tracks via either canonical FK so a track
    # tagged ``artist="John Lennon" album_artist="The Beatles"`` shows up
    # under both. The album_artist column is populated by Pass 3's
    # scanner dual-write + backfill, with the same diacritic-Python
    # pass-2 protection as canonical_artist_id.
    canonical_match = (Track.canonical_artist_id == artist.id) | (
        Track.canonical_album_artist_id == artist.id
    )

    stats_query = select(
        func.count(Track.id).label("track_count"),
        func.count(func.distinct(Track.album)).label("album_count"),
        func.sum(Track.duration_seconds).label("total_duration"),
        func.min(cast(Track.id, TEXT)).label("first_track_id"),
    ).where(canonical_match, Track.status == TrackStatus.ACTIVE)
    stats = (await db.execute(stats_query)).one_or_none()
    if not stats or stats.track_count == 0:
        raise NotFoundError("Artist not found in library")

    albums_query = (
        select(
            Track.album.label("name"),
            func.max(Track.year).label("year"),
            func.count(Track.id).label("track_count"),
            func.min(cast(Track.id, TEXT)).label("first_track_id"),
        )
        .where(
            canonical_match,
            Track.status == TrackStatus.ACTIVE,
            Track.album.isnot(None),
            Track.album != "",
        )
        .group_by(Track.album)
        .order_by(func.max(Track.year).desc().nullslast(), Track.album)
    )
    albums_result = await db.execute(albums_query)
    albums = [
        ArtistAlbum(
            name=row.name or "Unknown Album",
            year=row.year,
            track_count=row.track_count,
            first_track_id=str(row.first_track_id),
        )
        for row in albums_result.all()
    ]

    tracks_query = (
        select(Track)
        .where(canonical_match, Track.status == TrackStatus.ACTIVE)
        .order_by(Track.album, Track.disc_number, Track.track_number, Track.title)
        .limit(500)
    )
    tracks_result = await db.execute(tracks_query)
    tracks = [
        ArtistTrack(
            id=str(t.id),
            title=t.title,
            album=t.album,
            track_number=t.track_number,
            duration_seconds=t.duration_seconds,
            year=t.year,
        )
        for t in tracks_result.scalars().all()
    ]

    # Last.fm cache lives on the Artist row (migrated from ArtistInfo in
    # Pass 1's backfill). Refresh if stale or if similar_artists is empty
    # (legacy entries from before similar-artist support).
    cache_max_age = timedelta(days=30)
    lastfm_fetched = False
    lastfm_error: str | None = artist.fetch_error

    if artist.fetched_at and not refresh_lastfm:
        cache_age = utcnow() - artist.fetched_at
        needs_similar_refresh = not artist.fetch_error and (
            not artist.similar_artists
            or "match" not in (artist.similar_artists[0] if artist.similar_artists else {})
        )
        if cache_age < cache_max_age and not needs_similar_refresh:
            lastfm_fetched = True

    # Fetch from Last.fm if needed.
    if (not lastfm_fetched) or refresh_lastfm:
        lastfm_service = get_lastfm_service()
        if lastfm_service.is_configured():
            try:
                info, similar_from_api = await asyncio.gather(
                    lastfm_service.get_artist_info(artist.name),
                    lastfm_service.get_similar_artists(artist.name, limit=20),
                )
                if info:
                    images = info.get("image", [])
                    image_urls: dict[str, str] = {
                        img.get("size"): img.get("#text")
                        for img in images
                        if img.get("#text")
                        and "2a96cbd8b46e442fc41c2b86b821562f" not in img.get("#text", "")
                    }
                    similar = similar_from_api or info.get("similar", {}).get("artist", [])
                    tags = [
                        t.get("name") for t in info.get("tags", {}).get("tag", []) if t.get("name")
                    ]
                    artist.lastfm_url = info.get("url")
                    artist.bio_summary = info.get("bio", {}).get("summary")
                    artist.bio_content = info.get("bio", {}).get("content")
                    artist.listeners = int(info.get("stats", {}).get("listeners", 0)) or None
                    artist.playcount = int(info.get("stats", {}).get("playcount", 0)) or None
                    artist.similar_artists = similar
                    artist.tags = tags
                    artist.fetched_at = utcnow()
                    artist.fetch_error = None
                    # Promote a Last.fm image to Artist.image_url only when
                    # we don't already have a resolved (Wikipedia/Wikidata/
                    # Spotify) photo — the resolver chain is preferred.
                    if not artist.image_url:
                        promoted = (
                            image_urls.get("extralarge")
                            or image_urls.get("large")
                            or image_urls.get("medium")
                        )
                        if promoted:
                            artist.image_url = promoted
                            artist.image_checked_at = utcnow()
                    await db.commit()
                    lastfm_fetched = True
                    lastfm_error = None
                else:
                    artist.fetch_error = "Artist not found on Last.fm"
                    artist.fetched_at = utcnow()
                    await db.commit()
                    lastfm_error = "Artist not found on Last.fm"
            except Exception as e:
                lastfm_error = str(e)

    # Enrich similar artists — alias-keyed library lookup so spelling
    # variants of the same canonical artist count as in-library.
    enriched_similar: list[SimilarArtistInfo] = []
    raw_similar = artist.similar_artists or []

    if raw_similar:
        from app.services.search_links import generate_artist_search_url

        similar_names = [s.get("name", "") for s in raw_similar if s.get("name")]
        similar_normalized = [normalize_artist_name(n) for n in similar_names if n]
        library_map: dict[str, int] = {}
        if similar_normalized:
            similar_query = (
                select(
                    ArtistAlias.alias_normalized.label("alias_norm"),
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
            similar_result = await db.execute(similar_query)
            library_map = {row.alias_norm: row.track_count for row in similar_result.all()}

        for similar in raw_similar:
            name = similar.get("name", "")
            if not name:
                continue

            normalized = normalize_artist_name(name)
            in_library = normalized in library_map
            track_count = library_map.get(normalized)

            LASTFM_PLACEHOLDER = "2a96cbd8b46e442fc41c2b86b821562f"
            images = similar.get("image", [])
            image_url_s: str | None = None
            for img in images:
                url = img.get("#text", "")
                if img.get("size") == "large" and url and LASTFM_PLACEHOLDER not in url:
                    image_url_s = url
                    break
            if not image_url_s:
                for img in images:
                    url = img.get("#text", "")
                    if url and LASTFM_PLACEHOLDER not in url:
                        image_url_s = url
                        break

            match_str = similar.get("match", "0")
            try:
                match_score = float(match_str)
            except (ValueError, TypeError):
                match_score = 0.0

            enriched_similar.append(
                SimilarArtistInfo(
                    name=name,
                    match_score=match_score,
                    in_library=in_library,
                    track_count=track_count,
                    image_url=image_url_s,
                    lastfm_url=similar.get("url"),
                    bandcamp_url=generate_artist_search_url("bandcamp", name),
                )
            )

    # Read ``Artist.image_url`` first (populated for most by Pass 1's backfill), then the image
    # cache, and hand a miss to the background chain.
    #
    # **Off the request path for the same reason as ``list_artists`` above**, and it is not a
    # smaller problem here just because it is one artist rather than a hundred: this is a single
    # Wikipedia round trip, on its own four-second timeout, between tapping an artist and seeing
    # their albums. A screen that takes four seconds to open is more noticeable than a list that
    # takes four seconds to page, not less.
    #
    # The write-through stays: promoting a cache hit onto ``Artist.image_url`` is one row, and it
    # means the next listing reads it from the artist directly.
    image_url = artist.image_url
    if image_url is None:
        from app.services.artist_image import (
            read_cached_artist_images,
            schedule_background_resolve,
        )

        detail_hints: list[tuple[str, str | None]] = [(artist.name, None)]
        cached = await read_cached_artist_images(db, [artist.name])
        image_url = cached.get(artist.name)
        if image_url is not None:
            artist.image_url = image_url
            artist.image_checked_at = utcnow()
            await db.commit()
        else:
            schedule_background_resolve(detail_hints)

    return ArtistDetailResponse(
        id=str(artist.id),
        name=artist.name,
        track_count=stats.track_count,
        album_count=stats.album_count,
        total_duration_seconds=stats.total_duration or 0,
        # Last.fm's biographies are HTML, and every client renders them as plain text — so the
        # artist screen showed a literal
        # `<a href="https://www.last.fm/music/Interpol">Read more on Last.fm</a>` at the end of the
        # summary. Stripped here rather than in each client, and rather than at write time, because
        # doing it on read fixes every row already stored without a Last.fm re-fetch.
        #
        # The link is not lost: `lastfm_url` is returned separately, which is what a client should
        # be building its own affordance from.
        bio_summary=_plain_text(artist.bio_summary),
        bio_content=_plain_text(artist.bio_content),
        image_url=image_url,
        lastfm_url=artist.lastfm_url,
        listeners=artist.listeners,
        playcount=artist.playcount,
        tags=(artist.tags or []),
        similar_artists=enriched_similar,
        albums=albums,
        tracks=tracks,
        first_track_id=str(stats.first_track_id),
        lastfm_fetched=lastfm_fetched,
        lastfm_error=lastfm_error,
    )


# ============================================================================
# Artist Image
# ============================================================================


@router.get("/artists/{artist_name}/image", tags=["library"], response_class=StreamingResponse)
async def get_artist_image(
    db: DbSession,
    request: Request,
    artist_name: str,
    size: str = "large",  # small, medium, large, extralarge
):
    """Get artist image with fallback chain.

    Fallback order:
    1. ``Artist.image_url`` if set (already populated for most by Pass 1).
    2. Fetch from Last.fm API; promote to ``Artist.image_url`` on success.
    3. Fallback to first album's artwork.

    Args:
        artist_name: The artist name (URL-encoded)
        size: Image size: small, medium, large, or extralarge

    Returns:
        Redirect to image URL or streamed image from album artwork
    """
    from urllib.parse import unquote

    from app.services.artwork import album_key_for_track, extract_and_save_artwork, get_artwork_path
    from app.services.lastfm import get_lastfm_service

    if size not in ("small", "medium", "large", "extralarge"):
        size = "large"

    artist_name = unquote(artist_name)
    LASTFM_PLACEHOLDER = "2a96cbd8b46e442fc41c2b86b821562f"

    def is_valid_image(url: str | None) -> bool:
        return bool(url and LASTFM_PLACEHOLDER not in url)

    # Resolve the URL name to a canonical Artist row.
    artist = await _resolve_artist_via_alias(db, artist_name)
    if artist is None:
        raise NotFoundError("Artist not found in library")

    # Step 1: Cached Artist.image_url (resolved Wikipedia/Wikidata/Spotify
    # photo, populated by Pass 1's backfill or by the resolver chain).
    if is_valid_image(artist.image_url):
        return RedirectResponse(
            url=artist.image_url,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # Step 2: Try Last.fm. Promote to Artist.image_url on success so the
    # next request short-circuits at step 1.
    lastfm_service = get_lastfm_service()
    if lastfm_service.is_configured():
        try:
            info = await lastfm_service.get_artist_info(artist.name)
            if info:
                images = info.get("image", [])
                image_urls: dict[str, str] = {
                    img.get("size"): img.get("#text")
                    for img in images
                    if img.get("#text") and LASTFM_PLACEHOLDER not in img.get("#text", "")
                }
                image_url = (
                    image_urls.get(size)
                    or image_urls.get("extralarge")
                    or image_urls.get("large")
                    or image_urls.get("medium")
                    or image_urls.get("small")
                )
                if image_url:
                    artist.image_url = image_url
                    artist.image_checked_at = utcnow()
                    await db.commit()
                    return RedirectResponse(
                        url=image_url,
                        headers={"Cache-Control": "public, max-age=86400"},
                    )
        except Exception as e:
            logger.debug(f"Last.fm artist image lookup failed for '{artist.name}': {e}")

    # Step 3: Album-artwork fallback — first track for this canonical artist.
    track_query = (
        select(Track)
        .where(
            Track.canonical_artist_id == artist.id,
            Track.status == TrackStatus.ACTIVE,
        )
        .order_by(Track.album, Track.track_number)
        .limit(1)
    )
    track = (await db.execute(track_query)).scalar_one_or_none()

    if track:
        album_key = album_key_for_track(track)
        artwork_size = "thumb" if size in ("small", "medium") else "full"
        artwork_path = get_artwork_path(album_key, artwork_size)

        if artwork_path.exists():

            def stream_artwork():
                with open(artwork_path, "rb") as f:
                    yield f.read()

            return StreamingResponse(
                stream_artwork(),
                media_type="image/jpeg",
                headers={"Cache-Control": "public, max-age=31536000"},
            )

        file_path = Path(track.file_path)
        if file_path.exists():
            extract_and_save_artwork(file_path, track.artist, track.album, album_key=album_key)
            if artwork_path.exists():

                def stream_artwork():
                    with open(artwork_path, "rb") as f:
                        yield f.read()

                return StreamingResponse(
                    stream_artwork(),
                    media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=31536000"},
                )

    raise NotFoundError("No artist image available")
