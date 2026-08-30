"""Recommendations service for discovering similar artists and tracks."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Float, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ArtistCheckCache,
    ExternalAlbumCache,
    Playlist,
    PlaylistTrack,
    ProfilePlayHistory,
    Track,
)
from app.services.bandcamp import BandcampService
from app.services.external_albums_helpers import (
    _INDEX_WHERE_BY_CONTEXT,
    LISTENING_PROFILE_CONTEXT,
    PLAYLIST_REC_CONTEXT,
    check_user_has_release,
    normalize_artist_name,
)
from app.services.lastfm import get_lastfm_service
from app.services.search_links import generate_release_search_urls
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

# Re-exported from `external_albums_helpers`, which owns the discovery contexts and
# the index predicates keyed on them, so the three writers cannot disagree.

PLAYLIST_REC_TTL_HOURS = 24
PLAYLIST_REC_MB_RELEASE_TYPES = ["album", "ep"]
PLAYLIST_REC_MB_DAYS_BACK = 3650  # 10-year window — effectively "all releases"
PLAYLIST_REC_SEED_LIMIT = 5  # how many seed artists to feed into similarity
PLAYLIST_REC_SIMILAR_PER_SEED = 5  # similar artists per seed
PLAYLIST_REC_RELEASES_PER_ARTIST = 2  # albums to take per similar artist


@dataclass
class RecommendedArtist:
    """A recommended artist."""

    name: str
    source: str  # "lastfm" or "bandcamp"
    match_score: float  # 0-1 similarity
    image_url: str | None
    external_url: str | None
    local_track_count: int  # How many tracks by this artist are in the library


@dataclass
class RecommendedTrack:
    """A recommended track."""

    title: str
    artist: str
    source: str  # "lastfm" or "bandcamp"
    match_score: float  # 0-1 similarity
    external_url: str | None
    local_track_id: str | None  # If track exists in library
    album: str | None = None  # Album name if track exists in library


@dataclass
class Recommendations:
    """Recommendations for a playlist."""

    artists: list[RecommendedArtist]
    tracks: list[RecommendedTrack]
    sources_used: list[str]


class RecommendationsService:
    """Service for generating recommendations based on playlist content."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.lastfm = get_lastfm_service()
        self.bandcamp = BandcampService()

    async def get_playlist_recommendations(
        self,
        playlist_id: UUID,
        artist_limit: int = 10,
        track_limit: int = 10,
    ) -> Recommendations:
        """Get recommendations based on a playlist's content.

        Extracts unique artists from the playlist, then:
        - If Last.fm is configured: Gets similar artists/tracks from Last.fm
        - Fallback: Searches Bandcamp for each artist

        Returns recommendations matched against local library.
        """
        # Get playlist with tracks
        playlist = await self.db.get(Playlist, playlist_id)
        if not playlist:
            return Recommendations(artists=[], tracks=[], sources_used=[])

        # Get unique artists from playlist
        artists = await self._get_playlist_artists(playlist_id)
        if not artists:
            return Recommendations(artists=[], tracks=[], sources_used=[])

        sources_used: list[str] = []
        recommended_artists: list[RecommendedArtist] = []
        recommended_tracks: list[RecommendedTrack] = []

        # Try Last.fm first
        if self.lastfm.is_configured():
            sources_used.append("lastfm")
            lastfm_artists, lastfm_tracks = await self._get_lastfm_recommendations(
                artists, artist_limit, track_limit
            )
            recommended_artists.extend(lastfm_artists)
            recommended_tracks.extend(lastfm_tracks)
        else:
            # Fallback to Bandcamp
            sources_used.append("bandcamp")
            bandcamp_artists = await self._get_bandcamp_recommendations(
                artists, artist_limit
            )
            recommended_artists.extend(bandcamp_artists)

        # Deduplicate and sort by match score
        recommended_artists = self._dedupe_artists(recommended_artists)[:artist_limit]
        recommended_tracks = self._dedupe_tracks(recommended_tracks)[:track_limit]

        return Recommendations(
            artists=recommended_artists,
            tracks=recommended_tracks,
            sources_used=sources_used,
        )

    async def _get_playlist_artists(self, playlist_id: UUID) -> list[str]:
        """Get unique artist names from a playlist."""
        result = await self.db.execute(
            select(Track.artist)
            .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
            .where(PlaylistTrack.playlist_id == playlist_id)
            .where(Track.artist.isnot(None))
            .distinct()
        )
        artists = [row[0] for row in result.all() if row[0]]
        return artists[:10]  # Limit to avoid too many API calls

    async def _get_lastfm_recommendations(
        self,
        artists: list[str],
        artist_limit: int,
        track_limit: int,
    ) -> tuple[list[RecommendedArtist], list[RecommendedTrack]]:
        """Get recommendations from Last.fm."""
        recommended_artists: list[RecommendedArtist] = []
        recommended_tracks: list[RecommendedTrack] = []

        # Get similar artists for each playlist artist
        for artist in artists[:5]:  # Limit API calls
            try:
                similar = await self.lastfm.get_similar_artists(artist, limit=5)
                for item in similar:
                    name = item.get("name", "")
                    if not name:
                        continue

                    # Get match score (0-1)
                    match_str = item.get("match", "0")
                    try:
                        match_score = float(match_str)
                    except (ValueError, TypeError):
                        match_score = 0.5

                    # Get image URL (Last.fm provides multiple sizes)
                    image_url = None
                    images = item.get("image", [])
                    if images:
                        # Get largest image
                        for img in reversed(images):
                            if img.get("#text"):
                                image_url = img["#text"]
                                break

                    # Check local library
                    local_count = await self._count_artist_tracks(name)

                    recommended_artists.append(
                        RecommendedArtist(
                            name=name,
                            source="lastfm",
                            match_score=match_score,
                            image_url=image_url,
                            external_url=item.get("url"),
                            local_track_count=local_count,
                        )
                    )
            except Exception as e:
                logger.warning(f"Failed to get similar artists for {artist}: {e}")

        # Get similar tracks for some playlist tracks
        playlist_tracks = await self._get_sample_tracks(artists)
        for track_artist, track_title in playlist_tracks[:3]:
            try:
                similar = await self.lastfm.get_similar_tracks(
                    track_artist, track_title, limit=5
                )
                for item in similar:
                    title = item.get("name", "")
                    artist_info = item.get("artist", {})
                    artist_name = (
                        artist_info.get("name", "")
                        if isinstance(artist_info, dict)
                        else str(artist_info)
                    )

                    if not title or not artist_name:
                        continue

                    # Get match score
                    match_str = item.get("match", "0")
                    try:
                        match_score = float(match_str)
                    except (ValueError, TypeError):
                        match_score = 0.5

                    # Check if track exists locally
                    local_track_id, album = await self._find_local_track(
                        artist_name, title
                    )

                    recommended_tracks.append(
                        RecommendedTrack(
                            title=title,
                            artist=artist_name,
                            source="lastfm",
                            match_score=match_score,
                            external_url=item.get("url"),
                            local_track_id=local_track_id,
                            album=album,
                        )
                    )
            except Exception as e:
                logger.warning(
                    f"Failed to get similar tracks for {track_title}: {e}"
                )

        return recommended_artists, recommended_tracks

    async def _get_bandcamp_recommendations(
        self,
        artists: list[str],
        limit: int,
    ) -> list[RecommendedArtist]:
        """Get recommendations from Bandcamp search."""
        recommended: list[RecommendedArtist] = []

        for artist in artists[:5]:  # Limit searches
            try:
                results = await self.bandcamp.search(artist, item_type="b", limit=3)
                for result in results:
                    if not result.name:
                        continue

                    # Skip if it's the same artist
                    if result.name.lower() == artist.lower():
                        continue

                    # Check local library
                    local_count = await self._count_artist_tracks(result.name)

                    recommended.append(
                        RecommendedArtist(
                            name=result.name,
                            source="bandcamp",
                            match_score=0.5,  # Bandcamp doesn't provide similarity
                            image_url=result.image_url,
                            external_url=result.url,
                            local_track_count=local_count,
                        )
                    )
            except Exception as e:
                logger.warning(f"Failed to search Bandcamp for {artist}: {e}")

        return recommended

    async def _count_artist_tracks(self, artist: str) -> int:
        """Count how many tracks by this artist are in the library."""
        result = await self.db.execute(
            select(func.count(Track.id)).where(
                func.lower(Track.artist) == artist.lower()
            )
        )
        return result.scalar() or 0

    async def _find_local_track(
        self, artist: str, title: str
    ) -> tuple[str | None, str | None]:
        """Find a track in the local library by artist and title.

        Returns (track_id, album) tuple.
        """
        result = await self.db.execute(
            select(Track.id, Track.album).where(
                func.lower(Track.artist) == artist.lower(),
                func.lower(Track.title) == title.lower(),
            )
        )
        row = result.first()
        if row:
            return str(row[0]), row[1]
        return None, None

    async def _get_sample_tracks(
        self, artists: list[str]
    ) -> list[tuple[str, str]]:
        """Get sample tracks from the library for the given artists."""
        tracks: list[tuple[str, str]] = []
        for artist in artists[:3]:
            result = await self.db.execute(
                select(Track.artist, Track.title)
                .where(func.lower(Track.artist) == artist.lower())
                .limit(2)
            )
            for row in result.all():
                if row[0] and row[1]:
                    tracks.append((row[0], row[1]))
        return tracks

    def _dedupe_artists(
        self, artists: list[RecommendedArtist]
    ) -> list[RecommendedArtist]:
        """Deduplicate artists by name, keeping highest match score."""
        seen: dict[str, RecommendedArtist] = {}
        for artist in artists:
            key = artist.name.lower()
            if key not in seen or artist.match_score > seen[key].match_score:
                seen[key] = artist
        # Sort by match score descending
        return sorted(seen.values(), key=lambda a: a.match_score, reverse=True)

    def _dedupe_tracks(
        self, tracks: list[RecommendedTrack]
    ) -> list[RecommendedTrack]:
        """Deduplicate tracks by artist+title, keeping highest match score."""
        seen: dict[str, RecommendedTrack] = {}
        for track in tracks:
            key = f"{track.artist.lower()}:{track.title.lower()}"
            if key not in seen or track.match_score > seen[key].match_score:
                seen[key] = track
        # Sort by match score descending
        return sorted(seen.values(), key=lambda t: t.match_score, reverse=True)

    # ----- External-album recommendations (#2 lane) -----

    async def get_playlist_external_albums(
        self,
        playlist_id: UUID,
        *,
        limit: int = 12,
        refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """Return external album recommendations for a playlist.

        Persists per-playlist rows in ``external_album_cache`` with
        ``discovery_context='playlist_recommendation'``. Recompute is skipped
        on cache hit within ``PLAYLIST_REC_TTL_HOURS`` unless ``refresh=True``.
        """
        playlist = await self.db.get(Playlist, playlist_id)
        if not playlist:
            return []

        if not refresh and not await self._needs_recompute(
            PLAYLIST_REC_CONTEXT, source_playlist_id=playlist_id
        ):
            return await self._read_external_albums(
                PLAYLIST_REC_CONTEXT, source_playlist_id=playlist_id, limit=limit
            )

        if not self.lastfm.is_configured():
            logger.info(
                "Last.fm not configured; cannot compute external album recommendations"
            )
            return []

        seed_artists = await self._get_playlist_artists(playlist_id)
        if not seed_artists:
            return []

        await self._compute_external_albums_from_seeds(
            seed_artists,
            discovery_context=PLAYLIST_REC_CONTEXT,
            source_playlist_id=playlist_id,
        )
        return await self._read_external_albums(
            PLAYLIST_REC_CONTEXT, source_playlist_id=playlist_id, limit=limit
        )

    async def get_listening_profile_external_albums(
        self,
        profile_id: UUID,
        *,
        limit: int = 12,
        refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """Return external album recommendations seeded by the user's top-played artists.

        Profile-wide (no specific playlist). Persists rows with
        ``discovery_context='listening_profile_recommendation'`` and
        ``source_playlist_id IS NULL``. 24h TTL.
        """
        if not refresh:
            # **Never compute on the request path.** Recomputing means Last.fm plus MusicBrainz plus
            # Cover Art Archive for every seed artist, measured at **71 seconds** against the real
            # library on 2026-08-26 — so the first caller after the TTL expired paid for everyone,
            # and no UI waits that long. "Albums you might want" therefore looked permanently
            # broken while the endpoint was, strictly speaking, working.
            #
            # Stale is served in preference to slow, and an empty cache returns empty rather than
            # blocking. `_daily_external_albums_refresh` keeps it warm; `refresh=true` still forces
            # a synchronous recompute for anyone who asks for one deliberately.
            return await self._read_external_albums(
                LISTENING_PROFILE_CONTEXT, source_playlist_id=None, limit=limit
            )

        if not self.lastfm.is_configured():
            logger.info(
                "Last.fm not configured; cannot compute listening-profile recommendations"
            )
            return []

        seed_artists = await self._get_top_played_artists(profile_id)
        if not seed_artists:
            return []

        await self._compute_external_albums_from_seeds(
            seed_artists,
            discovery_context=LISTENING_PROFILE_CONTEXT,
            source_playlist_id=None,
        )
        return await self._read_external_albums(
            LISTENING_PROFILE_CONTEXT, source_playlist_id=None, limit=limit
        )

    async def _get_top_played_artists(
        self, profile_id: UUID, limit: int = PLAYLIST_REC_SEED_LIMIT
    ) -> list[str]:
        """Top distinct artists from the profile's play history, by play count."""
        result = await self.db.execute(
            select(
                Track.artist,
                func.sum(ProfilePlayHistory.play_count).label("plays"),
            )
            .join(ProfilePlayHistory, ProfilePlayHistory.track_id == Track.id)
            .where(
                ProfilePlayHistory.profile_id == profile_id,
                Track.artist.isnot(None),
            )
            .group_by(Track.artist)
            .order_by(func.sum(ProfilePlayHistory.play_count).desc())
            .limit(limit)
        )
        return [row[0] for row in result.all() if row[0]]

    async def _needs_recompute(
        self,
        discovery_context: str,
        *,
        source_playlist_id: UUID | None,
    ) -> bool:
        """True if cache is empty or all rows are older than the TTL."""
        scope = ExternalAlbumCache.source_playlist_id == source_playlist_id
        if source_playlist_id is None:
            scope = ExternalAlbumCache.source_playlist_id.is_(None)
        result = await self.db.execute(
            select(func.max(ExternalAlbumCache.discovered_at)).where(
                scope,
                ExternalAlbumCache.discovery_context == discovery_context,
            )
        )
        last = result.scalar()
        if last is None:
            return True
        return last < utcnow() - timedelta(hours=PLAYLIST_REC_TTL_HOURS)

    async def _compute_external_albums_from_seeds(
        self,
        seed_artists: list[str],
        *,
        discovery_context: str,
        source_playlist_id: UUID | None,
    ) -> None:
        """Discover and persist external album recommendations from a seed list.

        Shared between #2 (playlist-context) and listening-profile #2.
        Differs only in ``discovery_context`` and ``source_playlist_id``.
        """
        from app.services.metadata.musicbrainz import (
            get_artist_releases_recent,
            search_artist,
        )

        # Step 1: collect candidate similar artists from Last.fm.
        candidates: dict[str, dict[str, Any]] = {}
        for artist in seed_artists[:PLAYLIST_REC_SEED_LIMIT]:
            try:
                similar = await self.lastfm.get_similar_artists(
                    artist, limit=PLAYLIST_REC_SIMILAR_PER_SEED
                )
            except Exception as e:
                logger.warning(f"Last.fm get_similar_artists failed for {artist}: {e}")
                continue

            for item in similar:
                name = (item or {}).get("name") or ""
                if not name:
                    continue
                normalized = normalize_artist_name(name)
                if not normalized:
                    continue
                try:
                    score = float(item.get("match", 0) or 0)
                except (TypeError, ValueError):
                    score = 0.0
                existing = candidates.get(normalized)
                if existing is None or score > existing["match_score"]:
                    candidates[normalized] = {
                        "name": name,
                        "normalized": normalized,
                        "match_score": score,
                        "seed_artist": artist,
                    }

        if not candidates:
            return

        # Step 2: resolve MB ids (using ArtistCheckCache to skip known artists).
        for cand in candidates.values():
            mb_id = await self._lookup_mb_id(cand["normalized"])
            if mb_id is None:
                try:
                    mb_result = await asyncio.to_thread(search_artist, cand["name"])
                except Exception as e:
                    logger.warning(
                        f"MusicBrainz search_artist failed for {cand['name']}: {e}"
                    )
                    mb_result = None
                if mb_result and mb_result.get("score", 0) >= 80:
                    found_name = mb_result.get("name", "")
                    if normalize_artist_name(found_name) == cand["normalized"]:
                        mb_id = mb_result.get("musicbrainz_artist_id")
                        await self._upsert_artist_cache(cand["normalized"], mb_id)
            cand["mb_id"] = mb_id

        # Step 3: fetch releases per resolved artist and persist.
        #
        # Stamped before the first write so the prune below can tell this run's rows from the
        # previous run's. Deliberately *not* used to clear the cache up front: the old set stays
        # readable for the whole recompute, which is what lets the page keep showing something
        # while this runs for a minute.
        run_started_at = utcnow()

        for cand in candidates.values():
            mb_id = cand.get("mb_id")
            if not mb_id:
                continue
            try:
                releases = await asyncio.to_thread(
                    get_artist_releases_recent,
                    mb_id,
                    days_back=PLAYLIST_REC_MB_DAYS_BACK,
                    release_types=PLAYLIST_REC_MB_RELEASE_TYPES,
                )
            except Exception as e:
                logger.warning(
                    f"MusicBrainz releases fetch failed for {cand['name']}: {e}"
                )
                continue

            for release in releases[:PLAYLIST_REC_RELEASES_PER_ARTIST]:
                await self._save_external_album(
                    discovery_context=discovery_context,
                    source_playlist_id=source_playlist_id,
                    artist_name=cand["name"],
                    artist_normalized=cand["normalized"],
                    musicbrainz_artist_id=mb_id,
                    match_score=cand["match_score"],
                    seed_artist=cand["seed_artist"],
                    release=release,
                )

        # **This run replaces the last one on the page.** Anything not rediscovered is dropped, so
        # Discover shows the current recommendations rather than an accumulation — an album found a
        # year ago could otherwise outrank today's, since the read orders by score first.
        #
        # Dismissed rows are kept. They are excluded from the read anyway, and keeping them is what
        # stops a dismissed album reappearing at the next refresh: the row survives, so the upsert
        # above conflicts with it and never re-adds it as undismissed.
        scope = ExternalAlbumCache.source_playlist_id == source_playlist_id
        if source_playlist_id is None:
            scope = ExternalAlbumCache.source_playlist_id.is_(None)
        await self.db.execute(
            delete(ExternalAlbumCache).where(
                ExternalAlbumCache.discovery_context == discovery_context,
                scope,
                ExternalAlbumCache.discovered_at < run_started_at,
                ExternalAlbumCache.dismissed.is_(False),
            )
        )
        await self.db.flush()

    async def _lookup_mb_id(self, artist_normalized: str) -> str | None:
        result = await self.db.execute(
            select(ArtistCheckCache.musicbrainz_artist_id).where(
                ArtistCheckCache.artist_name_normalized == artist_normalized
            )
        )
        return result.scalar_one_or_none()

    async def _upsert_artist_cache(
        self, artist_normalized: str, musicbrainz_id: str | None
    ) -> None:
        result = await self.db.execute(
            select(ArtistCheckCache).where(
                ArtistCheckCache.artist_name_normalized == artist_normalized
            )
        )
        cache = result.scalar_one_or_none()
        if cache:
            cache.last_checked_at = utcnow()
            if musicbrainz_id and not cache.musicbrainz_artist_id:
                cache.musicbrainz_artist_id = musicbrainz_id
        else:
            self.db.add(
                ArtistCheckCache(
                    artist_name_normalized=artist_normalized,
                    musicbrainz_artist_id=musicbrainz_id,
                    last_checked_at=utcnow(),
                )
            )
        await self.db.flush()

    async def _save_external_album(
        self,
        *,
        discovery_context: str,
        source_playlist_id: UUID | None,
        artist_name: str,
        artist_normalized: str,
        musicbrainz_artist_id: str | None,
        match_score: float,
        seed_artist: str,
        release: dict[str, Any],
    ) -> None:
        """Idempotent upsert against the appropriate partial unique index.

        For ``playlist_recommendation``: keyed on (release_id, source_playlist_id).
        For ``listening_profile_recommendation``: keyed on (release_id) — single
        listening profile per Familiar profile, source_playlist_id is NULL.
        """
        release_id = release.get("musicbrainz_release_group_id")
        release_name = release.get("title")
        if not release_id or not release_name:
            return

        release_date: datetime | None = None
        raw_date = release.get("release_date_parsed") or release.get("release_date")
        if isinstance(raw_date, datetime):
            release_date = raw_date
        elif isinstance(raw_date, str) and raw_date:
            try:
                release_date = datetime.fromisoformat(raw_date)
            except Exception:
                release_date = None

        local_match = await check_user_has_release(self.db, artist_name, release_name)

        if discovery_context == PLAYLIST_REC_CONTEXT:
            conflict_elements = ["release_id", "source_playlist_id"]
        else:
            conflict_elements = ["release_id"]

        stmt = (
            pg_insert(ExternalAlbumCache)
            .values(
                release_id=release_id,
                # **Stamped from the application clock, not `server_default=func.now()`.** In
                # PostgreSQL `now()` is the *transaction* timestamp, so a row inserted here would
                # carry the time the transaction opened — earlier than the `run_started_at` computed
                # in Python afterwards. The prune then deleted the rows the same run had just
                # written, and every recommendation vanished.
                discovered_at=utcnow(),
                discovery_context=discovery_context,
                source_playlist_id=source_playlist_id,
                artist_name=artist_name,
                artist_name_normalized=artist_normalized,
                musicbrainz_artist_id=musicbrainz_artist_id,
                release_name=release_name,
                release_type=release.get("release_type"),
                release_date=release_date,
                artwork_url=release.get("artwork_url"),
                track_count=release.get("track_count"),
                extra_data={
                    "match_score": match_score,
                    "seed_artist": seed_artist,
                },
                local_album_match=local_match,
            )
            .on_conflict_do_update(
                index_elements=conflict_elements,
                index_where=_INDEX_WHERE_BY_CONTEXT[discovery_context],
                # **`do_nothing` here meant the TTL never advanced.** A release already in the cache
                # was skipped entirely, so `discovered_at` kept its original date — and
                # `_needs_recompute` reads `max(discovered_at)`. For a library whose recommendations
                # are stable, every run rediscovered the same albums, nothing was written, the
                # maximum never moved, and the 24h TTL was permanently expired. That is why this
                # recomputed on *every* request rather than once a day.
                #
                # Touching the row also marks it as belonging to this run, which is what lets the
                # prune below tell "still recommended" from "no longer recommended".
                #
                # **`dismissed` is deliberately absent from this set.** It is the listener's decision
                # and a refresh must not undo it.
                set_={
                    "discovered_at": utcnow(),
                    "artist_name": artist_name,
                    "musicbrainz_artist_id": musicbrainz_artist_id,
                    "release_name": release_name,
                    "release_type": release.get("release_type"),
                    "release_date": release_date,
                    "artwork_url": release.get("artwork_url"),
                    "track_count": release.get("track_count"),
                    "extra_data": {
                        "match_score": match_score,
                        "seed_artist": seed_artist,
                    },
                    "local_album_match": local_match,
                },
            )
        )
        await self.db.execute(stmt)

    async def _read_external_albums(
        self,
        discovery_context: str,
        *,
        source_playlist_id: UUID | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        score_expr = func.coalesce(
            ExternalAlbumCache.extra_data["match_score"].astext.cast(Float()),
            0.0,
        )
        scope = ExternalAlbumCache.source_playlist_id == source_playlist_id
        if source_playlist_id is None:
            scope = ExternalAlbumCache.source_playlist_id.is_(None)
        result = await self.db.execute(
            select(ExternalAlbumCache)
            .where(
                scope,
                ExternalAlbumCache.discovery_context == discovery_context,
                ExternalAlbumCache.dismissed.is_(False),
                ExternalAlbumCache.local_album_match.is_(False),
            )
            .order_by(score_expr.desc(), ExternalAlbumCache.discovered_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()

        return [
            {
                "id": str(r.id),
                "artist_name": r.artist_name,
                "release_name": r.release_name,
                "release_type": r.release_type,
                "release_date": r.release_date.isoformat() if r.release_date else None,
                "artwork_url": r.artwork_url
                or f"https://coverartarchive.org/release-group/{r.release_id}/front-250",
                "external_url": r.external_url,
                "track_count": r.track_count,
                "match_score": float((r.extra_data or {}).get("match_score") or 0.0),
                "seed_artist": (r.extra_data or {}).get("seed_artist"),
                "local_album_match": r.local_album_match,
                "dismissed": r.dismissed,
                "discovered_at": r.discovered_at.isoformat(),
                "purchase_links": generate_release_search_urls(
                    r.artist_name, r.release_name
                ),
            }
            for r in rows
        ]

    # ----- /External-album recommendations -----

    async def close(self) -> None:
        """Close resources."""
        await self.bandcamp.close()
