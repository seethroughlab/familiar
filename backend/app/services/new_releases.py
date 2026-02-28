"""New releases discovery service for finding new music from library artists."""

import logging
import unicodedata
from datetime import datetime, timedelta
from app.utils.time import utcnow
from typing import Any
from uuid import UUID

from rapidfuzz import fuzz
from sqlalchemy import Float, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ArtistCheckCache, ArtistNewRelease, ProfilePlayHistory, Track
from app.services.search_links import generate_release_search_urls

logger = logging.getLogger(__name__)


def normalize_artist_name(name: str) -> str:
    """Normalize artist name for consistent matching.

    - Lowercase
    - Remove diacritics
    - Collapse whitespace
    """
    # Lowercase
    name = name.lower().strip()

    # Remove diacritics (é -> e, etc.)
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))

    # Collapse whitespace
    name = " ".join(name.split())

    return name


class NewReleasesService:
    """Service for discovering new releases from artists in the user's library."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_library_artists(self) -> list[dict[str, Any]]:
        """Get unique artists from the library with their IDs.

        Returns:
            List of artist info dicts with name, normalized name, and IDs
        """
        # Get distinct artists with their MusicBrainz IDs
        result = await self.db.execute(
            select(
                Track.artist,
                Track.album_artist,
                Track.musicbrainz_artist_id,
            )
            .where(Track.artist.isnot(None))
            .distinct()
        )
        rows = result.fetchall()

        # Collect unique artists
        artists: dict[str, dict[str, Any]] = {}

        for row in rows:
            # Use album_artist if available, else artist
            artist_name = row.album_artist or row.artist
            if not artist_name:
                continue

            normalized = normalize_artist_name(artist_name)
            if not normalized:
                continue

            # Track by normalized name to avoid duplicates
            if normalized not in artists:
                artists[normalized] = {
                    "name": artist_name,
                    "normalized_name": normalized,
                    "musicbrainz_artist_id": row.musicbrainz_artist_id,
                }
            elif row.musicbrainz_artist_id and not artists[normalized].get("musicbrainz_artist_id"):
                # Prefer entries with MusicBrainz ID
                artists[normalized]["musicbrainz_artist_id"] = row.musicbrainz_artist_id

        return list(artists.values())

    async def get_artist_check_cache(self, artist_normalized: str) -> ArtistCheckCache | None:
        """Get cache entry for artist if it exists and is recent."""
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
        """Check if we should query external APIs for this artist.

        Returns True if:
        - No cache entry exists
        - Cache entry is older than cache_hours
        """
        cache = await self.get_artist_check_cache(artist_normalized)
        if not cache:
            return True

        cutoff = utcnow() - timedelta(hours=cache_hours)
        return cache.last_checked_at < cutoff

    async def update_artist_cache(
        self,
        artist_normalized: str,
        musicbrainz_id: str | None = None,
        spotify_id: str | None = None,
    ) -> None:
        """Update or create artist check cache entry."""
        cache = await self.get_artist_check_cache(artist_normalized)

        if cache:
            cache.last_checked_at = utcnow()
            if musicbrainz_id:
                cache.musicbrainz_artist_id = musicbrainz_id
            if spotify_id:
                cache.spotify_artist_id = spotify_id
        else:
            cache = ArtistCheckCache(
                artist_name_normalized=artist_normalized,
                musicbrainz_artist_id=musicbrainz_id,
                spotify_artist_id=spotify_id,
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
        """Check if user already has this release in their library.

        Matching strategy:
        1. MusicBrainz Album ID (exact match)
        2. Exact album + artist name
        3. Fuzzy match (> 85%)
        """
        # 1. Try MusicBrainz ID match
        if musicbrainz_album_id:
            result = await self.db.execute(
                select(func.count(Track.id)).where(
                    Track.musicbrainz_album_id == musicbrainz_album_id
                )
            )
            if (result.scalar() or 0) > 0:
                return True

        # Normalize names
        artist_lower = artist_name.lower().strip()
        album_lower = album_name.lower().strip()

        # 2. Try exact match
        result = await self.db.execute(
            select(func.count(Track.id)).where(
                func.lower(Track.artist) == artist_lower,
                func.lower(Track.album) == album_lower,
            )
        )
        if (result.scalar() or 0) > 0:
            return True

        # 3. Fuzzy match - get candidate albums
        result = await self.db.execute(
            select(Track.album, Track.artist)
            .where(
                Track.album.isnot(None),
                func.lower(Track.artist).contains(artist_lower[:10])  # Rough filter
            )
            .distinct()
            .limit(500)
        )
        candidates = result.fetchall()

        for track_album, track_artist in candidates:
            if not track_album or not track_artist:
                continue

            album_score = fuzz.ratio(album_lower, track_album.lower())
            artist_score = fuzz.ratio(artist_lower, track_artist.lower())

            # Weighted: album name matters more
            combined = (album_score * 0.7) + (artist_score * 0.3)
            if combined >= 85:
                return True

        return False

    async def save_discovered_release(
        self,
        artist_name: str,
        release_id: str,
        source: str,
        release_name: str,
        release_type: str | None = None,
        release_date: datetime | None = None,
        artwork_url: str | None = None,
        external_url: str | None = None,
        track_count: int | None = None,
        extra_data: dict[str, Any] | None = None,
        musicbrainz_artist_id: str | None = None,
        spotify_artist_id: str | None = None,
    ) -> ArtistNewRelease | None:
        """Save a discovered release if it doesn't exist.

        Returns the release if newly created, None if it already exists.
        """
        # Check if release already exists
        existing = await self.db.execute(
            select(ArtistNewRelease).where(
                ArtistNewRelease.source == source,
                ArtistNewRelease.release_id == release_id,
            )
        )
        if existing.scalar_one_or_none():
            return None

        # Check if user already has this release
        local_match = await self.check_if_user_has_release(
            artist_name, release_name
        )

        release = ArtistNewRelease(
            artist_name=artist_name,
            artist_name_normalized=normalize_artist_name(artist_name),
            musicbrainz_artist_id=musicbrainz_artist_id,
            spotify_artist_id=spotify_artist_id,
            release_id=release_id,
            source=source,
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
        """Get cached new releases.

        Args:
            limit: Max releases to return
            offset: Pagination offset
            include_dismissed: Include releases user dismissed
            include_owned: Include releases user already owns

        Returns:
            List of release dicts with purchase links
        """
        query = select(ArtistNewRelease)

        if not include_dismissed:
            query = query.where(ArtistNewRelease.dismissed == False)  # noqa: E712

        if not include_owned:
            query = query.where(ArtistNewRelease.local_album_match == False)  # noqa: E712

        query = query.order_by(
            ArtistNewRelease.release_date.desc().nullslast(),
            ArtistNewRelease.discovered_at.desc(),
        ).offset(offset).limit(limit)

        result = await self.db.execute(query)
        releases = result.scalars().all()

        return [
            {
                "id": str(release.id),
                "artist_name": release.artist_name,
                "release_name": release.release_name,
                "release_type": release.release_type,
                "release_date": release.release_date.isoformat() if release.release_date else None,
                "artwork_url": release.artwork_url
                    if release.artwork_url
                    else (
                        f"https://coverartarchive.org/release-group/{release.release_id}/front-250"
                        if release.source == "musicbrainz"
                        else None
                    ),
                "external_url": release.external_url,
                "track_count": release.track_count,
                "source": release.source,
                "local_album_match": release.local_album_match,
                "dismissed": release.dismissed,
                "discovered_at": release.discovered_at.isoformat(),
                "purchase_links": generate_release_search_urls(
                    release.artist_name, release.release_name
                ),
            }
            for release in releases
        ]

    async def get_releases_count(
        self,
        include_dismissed: bool = False,
        include_owned: bool = False,
    ) -> int:
        """Get total count of cached releases."""
        query = select(func.count(ArtistNewRelease.id))

        if not include_dismissed:
            query = query.where(ArtistNewRelease.dismissed == False)  # noqa: E712

        if not include_owned:
            query = query.where(ArtistNewRelease.local_album_match == False)  # noqa: E712

        result = await self.db.execute(query)
        return result.scalar() or 0

    async def dismiss_release(
        self,
        release_id: UUID,
        profile_id: UUID,
    ) -> bool:
        """Mark a release as dismissed.

        Returns True if release was found and updated.
        """
        result = await self.db.execute(
            select(ArtistNewRelease).where(ArtistNewRelease.id == release_id)
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
        """Get a batch of artists prioritized by listening activity.

        Only includes artists the user has actually listened to.
        Priority is based on recency (60%) and frequency (40%) of listening.

        Args:
            profile_id: Profile to use for play history
            batch_size: Number of artists to return
            min_days_since_check: Skip artists checked more recently than this

        Returns:
            List of artist dicts sorted by priority (highest first)
        """
        # Subquery: aggregate play stats per artist from play history
        artist_stats = (
            select(
                func.lower(func.trim(Track.artist)).label("artist_normalized"),
                Track.artist.label("artist_name"),
                Track.musicbrainz_artist_id,
                func.max(ProfilePlayHistory.last_played_at).label("last_played"),
                func.sum(ProfilePlayHistory.play_count).label("total_plays"),
            )
            .select_from(ProfilePlayHistory)
            .join(Track, ProfilePlayHistory.track_id == Track.id)
            .where(
                ProfilePlayHistory.profile_id == profile_id,
                Track.artist.isnot(None),
            )
            .group_by(
                func.lower(func.trim(Track.artist)),
                Track.artist,
                Track.musicbrainz_artist_id,
            )
        ).subquery("artist_stats")

        # Get max plays for normalization
        max_plays_result = await self.db.execute(
            select(func.max(artist_stats.c.total_plays))
        )
        max_plays = max_plays_result.scalar() or 1  # Avoid division by zero

        # Calculate cutoff date for cache
        cache_cutoff = utcnow() - timedelta(days=min_days_since_check)

        # Main query: select artists with priority scores
        # Priority = recency (60%) + frequency (40%)
        # Recency: 60 * (1 - days_since_played / 365), capped at 0-60
        # Frequency: 40 * log(plays) / log(max_plays), capped at 0-40

        days_since_played = func.extract(
            "epoch",
            func.now() - artist_stats.c.last_played
        ) / 86400.0  # Convert seconds to days

        recency_score = 60.0 * func.greatest(
            0.0,
            1.0 - func.least(days_since_played, 365.0) / 365.0
        )

        frequency_score = 40.0 * (
            func.ln(artist_stats.c.total_plays.cast(Float) + 1.0) /
            func.ln(float(max_plays) + 1.0)
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
        """Get status of priority-based rotation checking.

        Returns info about how many artists are in rotation and progress.
        """
        # Count total artists with play history (these are in rotation)
        total_in_rotation_result = await self.db.execute(
            select(func.count(func.distinct(func.lower(func.trim(Track.artist)))))
            .select_from(ProfilePlayHistory)
            .join(Track, ProfilePlayHistory.track_id == Track.id)
            .where(
                ProfilePlayHistory.profile_id == profile_id,
                Track.artist.isnot(None),
            )
        )
        total_in_rotation = total_in_rotation_result.scalar() or 0

        # Count artists checked in last 7 days
        week_ago = utcnow() - timedelta(days=7)
        checked_this_week_result = await self.db.execute(
            select(func.count(ArtistCheckCache.artist_name_normalized))
            .where(ArtistCheckCache.last_checked_at >= week_ago)
        )
        checked_this_week = checked_this_week_result.scalar() or 0

        # Estimate days to complete full rotation at 75/day
        remaining = max(0, total_in_rotation - checked_this_week)
        days_to_complete = (remaining // 75) + (1 if remaining % 75 > 0 else 0)

        return {
            "total_artists_in_rotation": total_in_rotation,
            "checked_this_week": checked_this_week,
            "remaining_this_week": remaining,
            "estimated_days_to_complete": days_to_complete,
        }

    async def get_check_status(self) -> dict[str, Any]:
        """Get status of new releases checking."""
        # Get counts
        total_releases = await self.get_releases_count(
            include_dismissed=True, include_owned=True
        )
        new_releases = await self.get_releases_count()

        # Get most recent check time
        result = await self.db.execute(
            select(func.max(ArtistCheckCache.last_checked_at))
        )
        last_check = result.scalar()

        # Count artists checked
        result = await self.db.execute(
            select(func.count(ArtistCheckCache.artist_name_normalized))
        )
        artists_checked = result.scalar() or 0

        # Count library artists
        artists = await self.get_library_artists()

        return {
            "total_releases_found": total_releases,
            "new_releases_available": new_releases,
            "artists_in_library": len(artists),
            "artists_checked": artists_checked,
            "last_check_at": last_check.isoformat() if last_check else None,
        }
