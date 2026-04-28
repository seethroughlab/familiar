"""New releases discovery service for finding new music from library artists.

Phase 1 (revival): MusicBrainz only. Reads/writes the shared
``external_album_cache`` table filtered to ``discovery_context='artist_new_release'``.
The same table will host playlist-context external recommendations in a later
pass under a different ``discovery_context`` value.
"""

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Float, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Artist,
    ArtistCheckCache,
    ExternalAlbumCache,
    ProfilePlayHistory,
    Track,
    TrackStatus,
)
from app.services.external_albums_helpers import (
    check_user_has_release,
    normalize_artist_name,
)
from app.services.search_links import generate_release_search_urls
from app.utils.time import utcnow

# Re-export normalize_artist_name for back-compat with existing imports.
__all__ = ["DISCOVERY_CONTEXT", "NewReleasesService", "normalize_artist_name"]

logger = logging.getLogger(__name__)

DISCOVERY_CONTEXT = "artist_new_release"


class NewReleasesService:
    """Service for discovering new releases from artists in the user's library."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_library_artists(self) -> list[dict[str, Any]]:
        """Return one entry per canonical library artist with name + MB id.

        Reads from the canonical ``artists`` table (joined to active
        tracks) so spelling variants of the same artist collapse into
        one entry. ``ArtistCheckCache`` is keyed by the normalized
        canonical name (Python-side ``normalize_artist_name``), not by
        ``Artist.id`` — the cache table is legacy string-keyed and
        stays that way until a Pass-3 cleanup.
        """
        result = await self.db.execute(
            select(
                Artist.id,
                Artist.name,
                Artist.musicbrainz_id,
            )
            .join(Track, Track.canonical_artist_id == Artist.id)
            .where(Track.status == TrackStatus.ACTIVE)
            .group_by(Artist.id, Artist.name, Artist.musicbrainz_id)
        )
        rows = result.fetchall()

        return [
            {
                "name": row.name,
                "normalized_name": normalize_artist_name(row.name),
                "musicbrainz_artist_id": row.musicbrainz_id,
            }
            for row in rows
        ]

    async def get_artist_check_cache(self, artist_normalized: str) -> ArtistCheckCache | None:
        result = await self.db.execute(
            select(ArtistCheckCache).where(
                ArtistCheckCache.artist_name_normalized == artist_normalized
            )
        )
        return result.scalar_one_or_none()

    async def should_check_artist(
        self,
        artist_normalized: str,
        cache_hours: int = 24,
    ) -> bool:
        cache = await self.get_artist_check_cache(artist_normalized)
        if not cache:
            return True
        cutoff = utcnow() - timedelta(hours=cache_hours)
        return cache.last_checked_at < cutoff

    async def update_artist_cache(
        self,
        artist_normalized: str,
        musicbrainz_id: str | None = None,
    ) -> None:
        cache = await self.get_artist_check_cache(artist_normalized)
        if cache:
            cache.last_checked_at = utcnow()
            if musicbrainz_id:
                cache.musicbrainz_artist_id = musicbrainz_id
        else:
            cache = ArtistCheckCache(
                artist_name_normalized=artist_normalized,
                musicbrainz_artist_id=musicbrainz_id,
                last_checked_at=utcnow(),
            )
            self.db.add(cache)
        await self.db.flush()

    async def check_if_user_has_release(
        self,
        artist_name: str,
        album_name: str,
        musicbrainz_album_id: str | None = None,
    ) -> bool:
        """Thin wrapper around ``check_user_has_release`` for back-compat."""
        return await check_user_has_release(
            self.db, artist_name, album_name, musicbrainz_album_id
        )

    async def save_discovered_release(
        self,
        artist_name: str,
        release_id: str,
        release_name: str,
        release_type: str | None = None,
        release_date: datetime | None = None,
        artwork_url: str | None = None,
        external_url: str | None = None,
        track_count: int | None = None,
        extra_data: dict[str, Any] | None = None,
        musicbrainz_artist_id: str | None = None,
    ) -> ExternalAlbumCache | None:
        """Save a discovered release if not already cached. Returns the row or None."""
        existing = await self.db.execute(
            select(ExternalAlbumCache).where(
                ExternalAlbumCache.release_id == release_id,
            )
        )
        if existing.scalar_one_or_none():
            return None

        local_match = await self.check_if_user_has_release(artist_name, release_name)

        release = ExternalAlbumCache(
            discovery_context=DISCOVERY_CONTEXT,
            artist_name=artist_name,
            artist_name_normalized=normalize_artist_name(artist_name),
            musicbrainz_artist_id=musicbrainz_artist_id,
            release_id=release_id,
            release_name=release_name,
            release_type=release_type,
            release_date=release_date,
            artwork_url=artwork_url,
            external_url=external_url,
            track_count=track_count,
            extra_data=extra_data or {},
            local_album_match=local_match,
        )
        self.db.add(release)
        await self.db.flush()
        return release

    async def get_cached_releases(
        self,
        limit: int = 50,
        offset: int = 0,
        include_dismissed: bool = False,
        include_owned: bool = False,
    ) -> list[dict[str, Any]]:
        query = select(ExternalAlbumCache).where(
            ExternalAlbumCache.discovery_context == DISCOVERY_CONTEXT
        )
        if not include_dismissed:
            query = query.where(ExternalAlbumCache.dismissed.is_(False))
        if not include_owned:
            query = query.where(ExternalAlbumCache.local_album_match.is_(False))

        query = (
            query.order_by(
                ExternalAlbumCache.release_date.desc().nullslast(),
                ExternalAlbumCache.discovered_at.desc(),
            )
            .offset(offset)
            .limit(limit)
        )

        result = await self.db.execute(query)
        releases = result.scalars().all()

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
                "local_album_match": r.local_album_match,
                "dismissed": r.dismissed,
                "discovered_at": r.discovered_at.isoformat(),
                "purchase_links": generate_release_search_urls(r.artist_name, r.release_name),
            }
            for r in releases
        ]

    async def get_releases_count(
        self,
        include_dismissed: bool = False,
        include_owned: bool = False,
    ) -> int:
        query = select(func.count(ExternalAlbumCache.id)).where(
            ExternalAlbumCache.discovery_context == DISCOVERY_CONTEXT
        )
        if not include_dismissed:
            query = query.where(ExternalAlbumCache.dismissed.is_(False))
        if not include_owned:
            query = query.where(ExternalAlbumCache.local_album_match.is_(False))
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def dismiss_release(
        self,
        release_id: UUID,
        profile_id: UUID,
    ) -> bool:
        result = await self.db.execute(
            select(ExternalAlbumCache).where(
                ExternalAlbumCache.id == release_id,
                ExternalAlbumCache.discovery_context == DISCOVERY_CONTEXT,
            )
        )
        release = result.scalar_one_or_none()
        if not release:
            return False
        release.dismissed = True
        release.dismissed_by_profile_id = profile_id
        await self.db.flush()
        return True

    async def get_prioritized_artists_batch(
        self,
        profile_id: UUID,
        batch_size: int = 75,
        min_days_since_check: int = 7,
    ) -> list[dict[str, Any]]:
        """Return artists prioritized by listening recency (60%) + frequency (40%).

        Groups by canonical ``Artist.id`` so spelling variants share one
        priority score. ``ArtistCheckCache`` is joined on a Python-side
        normalized form of ``Artist.name`` — the cache table is legacy
        string-keyed and stays that way; the join condition uses the same
        ``lower(trim(Artist.name))`` normalization the resolver wrote
        with.
        """
        artist_stats = (
            select(
                Artist.id.label("artist_id"),
                Artist.name.label("artist_name"),
                Artist.musicbrainz_id.label("musicbrainz_artist_id"),
                func.lower(func.trim(Artist.name)).label("artist_normalized"),
                func.max(ProfilePlayHistory.last_played_at).label("last_played"),
                func.sum(ProfilePlayHistory.play_count).label("total_plays"),
            )
            .select_from(ProfilePlayHistory)
            .join(Track, ProfilePlayHistory.track_id == Track.id)
            .join(Artist, Artist.id == Track.canonical_artist_id)
            .where(ProfilePlayHistory.profile_id == profile_id)
            .group_by(
                Artist.id,
                Artist.name,
                Artist.musicbrainz_id,
            )
        ).subquery("artist_stats")

        max_plays_result = await self.db.execute(select(func.max(artist_stats.c.total_plays)))
        max_plays = max_plays_result.scalar() or 1

        cache_cutoff = utcnow() - timedelta(days=min_days_since_check)

        days_since_played = (
            func.extract("epoch", func.now() - artist_stats.c.last_played) / 86400.0
        )

        recency_score = 60.0 * func.greatest(
            0.0, 1.0 - func.least(days_since_played, 365.0) / 365.0
        )

        frequency_score = 40.0 * (
            func.ln(artist_stats.c.total_plays.cast(Float) + 1.0)
            / func.ln(float(max_plays) + 1.0)
        )

        priority_score = (recency_score + frequency_score).label("priority_score")

        query = (
            select(
                artist_stats.c.artist_normalized,
                artist_stats.c.artist_name,
                artist_stats.c.musicbrainz_artist_id,
                artist_stats.c.last_played,
                artist_stats.c.total_plays,
                priority_score,
            )
            .select_from(artist_stats)
            .outerjoin(
                ArtistCheckCache,
                artist_stats.c.artist_normalized == ArtistCheckCache.artist_name_normalized,
            )
            .where(
                or_(
                    ArtistCheckCache.last_checked_at.is_(None),
                    ArtistCheckCache.last_checked_at < cache_cutoff,
                )
            )
            .order_by(priority_score.desc())
            .limit(batch_size)
        )

        result = await self.db.execute(query)
        rows = result.fetchall()

        return [
            {
                "name": row.artist_name,
                "normalized_name": row.artist_normalized,
                "musicbrainz_artist_id": row.musicbrainz_artist_id,
                "last_played": row.last_played.isoformat() if row.last_played else None,
                "total_plays": row.total_plays,
                "priority_score": float(row.priority_score) if row.priority_score else 0.0,
            }
            for row in rows
        ]

    async def get_rotation_status(self, profile_id: UUID) -> dict[str, Any]:
        total_in_rotation_result = await self.db.execute(
            select(func.count(func.distinct(Track.canonical_artist_id)))
            .select_from(ProfilePlayHistory)
            .join(Track, ProfilePlayHistory.track_id == Track.id)
            .where(
                ProfilePlayHistory.profile_id == profile_id,
                Track.canonical_artist_id.isnot(None),
            )
        )
        total_in_rotation = total_in_rotation_result.scalar() or 0

        week_ago = utcnow() - timedelta(days=7)
        checked_this_week_result = await self.db.execute(
            select(func.count(ArtistCheckCache.artist_name_normalized)).where(
                ArtistCheckCache.last_checked_at >= week_ago
            )
        )
        checked_this_week = checked_this_week_result.scalar() or 0

        remaining = max(0, total_in_rotation - checked_this_week)
        days_to_complete = (remaining // 75) + (1 if remaining % 75 > 0 else 0)

        return {
            "total_artists_in_rotation": total_in_rotation,
            "checked_this_week": checked_this_week,
            "remaining_this_week": remaining,
            "estimated_days_to_complete": days_to_complete,
        }

    async def get_check_status(self) -> dict[str, Any]:
        total_releases = await self.get_releases_count(
            include_dismissed=True, include_owned=True
        )
        new_releases = await self.get_releases_count()

        result = await self.db.execute(select(func.max(ArtistCheckCache.last_checked_at)))
        last_check = result.scalar()

        result = await self.db.execute(
            select(func.count(ArtistCheckCache.artist_name_normalized))
        )
        artists_checked = result.scalar() or 0

        artists = await self.get_library_artists()

        return {
            "total_releases_found": total_releases,
            "new_releases_available": new_releases,
            "artists_in_library": len(artists),
            "artists_checked": artists_checked,
            "last_check_at": last_check.isoformat() if last_check else None,
        }
