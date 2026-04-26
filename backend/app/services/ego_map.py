"""Ego-centric music map visualization.

Computes artist positions for an ego-centric map centered on a specific artist.
Artists are positioned radially based on their similarity to the center artist.
"""

import hashlib
import json
import logging
import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Track, TrackAnalysis, TrackStatus
from app.services.normalize import normalize_for_matching

logger = logging.getLogger(__name__)

# Redis cache settings
ARTIST_EMBEDDING_CACHE_PREFIX = "artist_emb"
ARTIST_EMBEDDING_CACHE_TTL = 3600  # 1 hour
EGO_MAP_CACHE_PREFIX = "ego_map"
EGO_MAP_CACHE_TTL = 1800  # 30 minutes

# Minimum tracks needed to include an artist
MIN_TRACKS_PER_ARTIST = 1


@dataclass
class EgoMapArtist:
    """An artist node in the ego-centric map."""

    name: str
    x: float  # -1 to 1
    y: float  # -1 to 1
    distance: float  # 0 to 1, dissimilarity from center
    track_count: int
    first_track_id: str


@dataclass
class EgoMapCenter:
    """The center artist of the map."""

    name: str
    track_count: int
    first_track_id: str


@dataclass
class EgoMapData:
    """Complete ego-centric map data."""

    center: EgoMapCenter
    artists: list[EgoMapArtist]
    mode: str
    total_artists: int


class EgoMapService:
    """Service for computing ego-centric music maps."""

    def __init__(self):
        self._artist_embeddings_cache: dict[str, np.ndarray] = {}

    def _get_artist_cache_key(self, artist_name: str) -> str:
        """Generate Redis cache key for artist embedding."""
        normalized = artist_name.lower().strip()
        return f"{ARTIST_EMBEDDING_CACHE_PREFIX}:{normalized}"

    def _get_map_cache_key(self, center: str, limit: int) -> str:
        """Generate Redis cache key for ego map."""
        normalized = center.lower().strip()
        return f"{EGO_MAP_CACHE_PREFIX}:{normalized}:{limit}"

    def _get_cached_map(self, center: str, limit: int) -> EgoMapData | None:
        """Try to get cached map from Redis."""
        try:
            from app.services.redis_client import get_redis

            r = get_redis()
            key = self._get_map_cache_key(center, limit)
            data: bytes | None = r.get(key)  # type: ignore[assignment]
            if data:
                cached = json.loads(data)
                logger.info(f"Cache hit for ego map {center}:{limit}")
                return EgoMapData(
                    center=EgoMapCenter(**cached["center"]),
                    artists=[EgoMapArtist(**a) for a in cached["artists"]],
                    mode=cached["mode"],
                    total_artists=cached["total_artists"],
                )
        except Exception as e:
            logger.warning(f"Failed to get cached ego map: {e}")
        return None

    def _cache_map(self, center: str, limit: int, data: EgoMapData) -> None:
        """Cache computed map to Redis."""
        try:
            from app.services.redis_client import get_redis

            r = get_redis()
            key = self._get_map_cache_key(center, limit)
            cache_data = {
                "center": {
                    "name": data.center.name,
                    "track_count": data.center.track_count,
                    "first_track_id": data.center.first_track_id,
                },
                "artists": [
                    {
                        "name": a.name,
                        "x": a.x,
                        "y": a.y,
                        "distance": a.distance,
                        "track_count": a.track_count,
                        "first_track_id": a.first_track_id,
                    }
                    for a in data.artists
                ],
                "mode": data.mode,
                "total_artists": data.total_artists,
            }
            r.setex(key, EGO_MAP_CACHE_TTL, json.dumps(cache_data))
            logger.info(f"Cached ego map {center}:{limit} for {EGO_MAP_CACHE_TTL}s")
        except Exception as e:
            logger.warning(f"Failed to cache ego map: {e}")

    async def get_all_artist_embeddings(
        self, db: AsyncSession
    ) -> dict[str, dict]:
        """Get mean embeddings for all artists.

        Returns dict mapping artist name to:
            - mean_embedding: averaged 512D vector
            - track_count: number of tracks
            - first_track_id: UUID for artwork lookup
        """
        from app.config import FEATURES_VERSION

        # Project only the columns we need + filter null embeddings at SQL level.
        # Loading full Track ORM rows + selectinload of TrackAnalysis pulled
        # hundreds of MB into memory for large libraries and OOM-killed the
        # container.
        query = (
            select(Track.id, Track.artist, TrackAnalysis.embedding)
            .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
            .where(
                Track.status == TrackStatus.ACTIVE,
                Track.artist.isnot(None),
                Track.artist != "",
                TrackAnalysis.embedding.isnot(None),
                TrackAnalysis.features_version >= FEATURES_VERSION,
            )
            .execution_options(yield_per=2000)
        )

        # Group by artist
        artist_embeddings: dict[str, dict] = defaultdict(
            lambda: {"embeddings": [], "track_count": 0, "first_track_id": None}
        )

        result = await db.stream(query)
        async for track_id, artist, embedding in result:
            display_name = artist.strip()
            if not display_name:
                continue

            key = normalize_for_matching(display_name)
            if not key:
                continue

            artist_data = artist_embeddings[key]
            artist_data["embeddings"].append(np.asarray(embedding, dtype=np.float32))
            artist_data["track_count"] += 1
            if artist_data["first_track_id"] is None:
                artist_data["first_track_id"] = str(track_id)
                artist_data["display_name"] = display_name

        # Compute mean embeddings
        result_dict = {}
        for key, data in artist_embeddings.items():
            if data["track_count"] >= MIN_TRACKS_PER_ARTIST:
                display_name = data.get("display_name", key)
                result_dict[display_name] = {
                    "mean_embedding": np.mean(data["embeddings"], axis=0),
                    "track_count": data["track_count"],
                    "first_track_id": data["first_track_id"],
                }

        return result_dict

    def _compute_stable_angle(self, artist_name: str) -> float:
        """Compute a stable angle for an artist based on name hash.

        This ensures the same artist always appears at the same angle
        relative to any center, making the map feel more stable when
        recentering.
        """
        name_hash = hashlib.md5(artist_name.lower().encode()).hexdigest()[:8]
        hash_int = int(name_hash, 16)
        return (hash_int / 0xFFFFFFFF) * 2 * math.pi

    def compute_radial_positions(
        self,
        center_name: str,
        center_embedding: np.ndarray,
        artists: dict[str, dict],
        limit: int = 200,
    ) -> list[EgoMapArtist]:
        """Compute radial positions for artists around a center.

        Distance from center = dissimilarity (1 - cosine_similarity)
        Angle = stable hash of artist name

        Returns list of EgoMapArtist sorted by similarity (closest first).
        """
        if not artists:
            return []

        # Build matrix of all embeddings (excluding center)
        other_artists = {k: v for k, v in artists.items() if k != center_name}
        if not other_artists:
            return []

        names = list(other_artists.keys())
        embeddings = np.array([other_artists[n]["mean_embedding"] for n in names])

        # Compute similarities to center
        center_2d = center_embedding.reshape(1, -1)
        similarities = cosine_similarity(center_2d, embeddings)[0]

        # Create artist data with positions
        artist_data = []
        for i, name in enumerate(names):
            similarity = float(similarities[i])
            distance = 1.0 - similarity  # 0 = identical, 1 = orthogonal

            # Compute stable angle
            angle = self._compute_stable_angle(name)

            # Convert to cartesian (distance is radius)
            x = distance * math.cos(angle)
            y = distance * math.sin(angle)

            artist_data.append({
                "name": name,
                "x": x,
                "y": y,
                "distance": distance,
                "similarity": similarity,
                "track_count": other_artists[name]["track_count"],
                "first_track_id": other_artists[name]["first_track_id"],
            })

        # Sort by similarity (highest first) and limit
        artist_data.sort(key=lambda a: a["similarity"], reverse=True)
        artist_data = artist_data[:limit]

        # Convert to EgoMapArtist objects
        return [
            EgoMapArtist(
                name=a["name"],
                x=a["x"],
                y=a["y"],
                distance=a["distance"],
                track_count=a["track_count"],
                first_track_id=a["first_track_id"],
            )
            for a in artist_data
        ]

    async def compute_ego_map(
        self,
        db: AsyncSession,
        center: str,
        limit: int = 200,
        mode: str = "radial",
    ) -> EgoMapData:
        """Compute ego-centric map centered on an artist.

        Args:
            db: Database session
            center: Name of the center artist
            limit: Maximum number of surrounding artists
            mode: Layout mode (currently only "radial" supported)

        Returns:
            EgoMapData with center, positioned artists, and metadata

        Raises:
            ValueError: If center artist not found or has no embeddings
        """
        # Check cache first
        cached = self._get_cached_map(center, limit)
        if cached:
            return cached

        # Get all artist embeddings
        all_artists = await self.get_all_artist_embeddings(db)
        total_artists = len(all_artists)

        # Find center artist using normalized matching
        center_norm = normalize_for_matching(center)
        center_data = None
        center_key = None

        for artist_name, data in all_artists.items():
            if normalize_for_matching(artist_name) == center_norm:
                center_data = data
                center_key = artist_name
                break

        if center_data is None:
            raise ValueError(f"Artist '{center}' not found or has no embeddings")

        # Compute positions
        artists = self.compute_radial_positions(
            center_name=center_key,
            center_embedding=center_data["mean_embedding"],
            artists=all_artists,
            limit=limit,
        )

        # Build result
        result = EgoMapData(
            center=EgoMapCenter(
                name=center_key,
                track_count=center_data["track_count"],
                first_track_id=center_data["first_track_id"],
            ),
            artists=artists,
            mode=mode,
            total_artists=total_artists,
        )

        # Cache result
        self._cache_map(center, limit, result)

        return result

    def invalidate_cache(self) -> None:
        """Invalidate all cached ego maps (call after library changes)."""
        try:
            from app.services.redis_client import get_redis

            r = get_redis()
            # Delete all ego map cache keys
            for key in r.scan_iter(f"{EGO_MAP_CACHE_PREFIX}:*"):
                r.delete(key)
            for key in r.scan_iter(f"{ARTIST_EMBEDDING_CACHE_PREFIX}:*"):
                r.delete(key)
            logger.info("Invalidated ego map cache")
        except Exception as e:
            logger.warning(f"Failed to invalidate ego map cache: {e}")


# Singleton instance
_ego_map_service: EgoMapService | None = None


def get_ego_map_service() -> EgoMapService:
    """Get the singleton EgoMapService instance."""
    global _ego_map_service
    if _ego_map_service is None:
        _ego_map_service = EgoMapService()
    return _ego_map_service
