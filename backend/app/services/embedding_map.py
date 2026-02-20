"""Embedding-based music map visualization.

Computes 2D positions for artists/albums based on audio similarity
using UMAP dimensionality reduction on CLAP embeddings.
"""

import json
import logging
from collections import defaultdict
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Literal

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Track, TrackAnalysis, TrackStatus
from app.services.normalize import normalize_for_matching

logger = logging.getLogger(__name__)

# Redis cache settings
MAP_CACHE_KEY_PREFIX = "music_map"
MAP_CACHE_TTL = 1800  # 30 minutes

# Minimum tracks needed to include an entity in the map
MIN_TRACKS_PER_ENTITY = 1

# Maximum entities to include (for performance)
MAX_ENTITIES = 500


@dataclass
class MapNode:
    """A node in the music map."""

    id: str
    name: str
    x: float
    y: float
    track_count: int
    first_track_id: str


@dataclass
class MapNode3D:
    """A node in the 3D music map."""

    id: str
    name: str
    x: float
    y: float
    z: float
    track_count: int
    first_track_id: str
    representative_track_id: str | None = None  # Track closest to centroid


@dataclass
class MapData3D:
    """Complete 3D map data for visualization."""

    nodes: list[MapNode3D]
    entity_type: str
    total_entities: int


@dataclass
class MapEdge:
    """An edge connecting similar nodes."""

    source: str
    target: str
    weight: float  # Similarity score 0-1


@dataclass
class MapData:
    """Complete map data for visualization."""

    nodes: list[MapNode]
    edges: list[MapEdge]


@dataclass
class MapProgress:
    """Progress update for map computation."""

    phase: str
    progress: float  # 0.0 to 1.0
    message: str


class EmbeddingMapService:
    """Service for computing embedding-based music maps."""

    def __init__(self):
        self._umap_2d = None
        self._umap_3d = None

    def _get_umap(self, n_components: int = 2):
        """Lazy-load UMAP to avoid import overhead."""
        try:
            from umap import UMAP
        except ImportError:
            logger.error("umap-learn not installed")
            raise ImportError("umap-learn is required for music map visualization")

        if n_components == 3:
            if self._umap_3d is None:
                self._umap_3d = UMAP(
                    n_components=3,
                    n_neighbors=15,
                    min_dist=0.1,
                    metric="cosine",
                    random_state=42,
                )
            return self._umap_3d
        else:
            if self._umap_2d is None:
                self._umap_2d = UMAP(
                    n_components=2,
                    n_neighbors=15,
                    min_dist=0.1,
                    metric="cosine",
                    random_state=42,
                )
            return self._umap_2d

    def _get_cache_key(self, entity_type: str, limit: int) -> str:
        """Generate Redis cache key for map data."""
        return f"{MAP_CACHE_KEY_PREFIX}:{entity_type}:{limit}"

    def _get_cached_map(self, entity_type: str, limit: int) -> MapData | None:
        """Try to get cached map from Redis."""
        try:
            from app.services.redis_client import get_redis

            r = get_redis()
            key = self._get_cache_key(entity_type, limit)
            data: bytes | None = r.get(key)  # type: ignore[assignment]
            if data:
                cached = json.loads(data)
                logger.info(f"Cache hit for music map {entity_type}:{limit}")
                return MapData(
                    nodes=[MapNode(**n) for n in cached["nodes"]],
                    edges=[MapEdge(**e) for e in cached["edges"]],
                )
        except Exception as e:
            logger.warning(f"Failed to get cached map: {e}")
        return None

    def _cache_map(self, entity_type: str, limit: int, map_data: MapData) -> None:
        """Cache computed map to Redis."""
        try:
            from app.services.redis_client import get_redis

            r = get_redis()
            key = self._get_cache_key(entity_type, limit)
            data = {
                "nodes": [
                    {
                        "id": n.id,
                        "name": n.name,
                        "x": n.x,
                        "y": n.y,
                        "track_count": n.track_count,
                        "first_track_id": n.first_track_id,
                    }
                    for n in map_data.nodes
                ],
                "edges": [
                    {"source": e.source, "target": e.target, "weight": e.weight}
                    for e in map_data.edges
                ],
            }
            r.set(key, json.dumps(data), ex=MAP_CACHE_TTL)
            logger.info(f"Cached music map {entity_type}:{limit} for {MAP_CACHE_TTL}s")
        except Exception as e:
            logger.warning(f"Failed to cache map: {e}")

    def invalidate_cache(self) -> None:
        """Invalidate all cached maps (call after library changes)."""
        try:
            from app.services.redis_client import get_redis

            r = get_redis()
            # Delete all music map cache keys
            for key in r.scan_iter(f"{MAP_CACHE_KEY_PREFIX}:*"):
                r.delete(key)
            logger.info("Invalidated music map cache")
        except Exception as e:
            logger.warning(f"Failed to invalidate map cache: {e}")

    async def compute_map_with_progress(
        self,
        db: AsyncSession,
        entity_type: Literal["artists", "albums"] = "artists",
        limit: int = MAX_ENTITIES,
    ) -> AsyncGenerator[MapProgress | MapData, None]:
        """Compute map with progress updates for SSE streaming.

        Yields MapProgress updates during computation, then MapData at the end.
        """
        # Check cache first
        yield MapProgress(phase="checking_cache", progress=0.0, message="Checking cache...")
        cached = self._get_cached_map(entity_type, limit)
        if cached:
            yield MapProgress(phase="complete", progress=1.0, message="Loaded from cache")
            yield cached
            return

        # Phase 1: Database query
        yield MapProgress(phase="db_query", progress=0.1, message="Loading embeddings from database...")

        if entity_type == "artists":
            embeddings = await self._aggregate_by_artist(db)
        else:
            embeddings = await self._aggregate_by_album(db)

        if len(embeddings) < 3:
            logger.warning(f"Not enough entities with embeddings: {len(embeddings)}")
            yield MapProgress(phase="complete", progress=1.0, message="Not enough data")
            yield MapData(nodes=[], edges=[])
            return

        yield MapProgress(
            phase="db_query",
            progress=0.3,
            message=f"Found {len(embeddings)} {entity_type} with embeddings",
        )

        # Phase 2: Aggregation
        yield MapProgress(phase="aggregating", progress=0.35, message="Sorting and filtering...")

        sorted_entities = sorted(
            embeddings.items(), key=lambda x: x[1]["track_count"], reverse=True
        )[:limit]

        if len(sorted_entities) < 3:
            yield MapProgress(phase="complete", progress=1.0, message="Not enough entities")
            yield MapData(nodes=[], edges=[])
            return

        names = [name for name, _ in sorted_entities]
        matrix = np.array([embeddings[name]["mean_embedding"] for name in names])

        yield MapProgress(
            phase="aggregating",
            progress=0.5,
            message=f"Processing {len(names)} {entity_type}...",
        )

        # Phase 3: UMAP
        yield MapProgress(
            phase="umap",
            progress=0.55,
            message=f"Computing 2D positions for {len(names)} entities...",
        )

        try:
            umap = self._get_umap()
            positions_2d = umap.fit_transform(matrix)
        except Exception as e:
            logger.error(f"UMAP failed: {e}")
            raise

        yield MapProgress(phase="umap", progress=0.8, message="Normalizing positions...")

        # Normalize to [0, 1] range
        min_vals = positions_2d.min(axis=0)
        max_vals = positions_2d.max(axis=0)
        range_vals = max_vals - min_vals
        range_vals[range_vals == 0] = 1
        positions_2d = (positions_2d - min_vals) / range_vals

        # Phase 4: Build nodes and edges
        yield MapProgress(phase="edges", progress=0.85, message="Computing similarity connections...")

        nodes = []
        for i, name in enumerate(names):
            entity_data = embeddings[name]
            nodes.append(
                MapNode(
                    id=name,
                    name=name,
                    x=float(positions_2d[i][0]),
                    y=float(positions_2d[i][1]),
                    track_count=entity_data["track_count"],
                    first_track_id=entity_data["first_track_id"],
                )
            )

        edges = self._compute_knn_edges(matrix, names, k=5)

        yield MapProgress(phase="edges", progress=0.95, message="Finalizing...")

        map_data = MapData(nodes=nodes, edges=edges)

        # Cache the result
        self._cache_map(entity_type, limit, map_data)

        yield MapProgress(
            phase="complete",
            progress=1.0,
            message=f"Complete: {len(nodes)} nodes, {len(edges)} edges",
        )
        yield map_data

    async def compute_map(
        self,
        db: AsyncSession,
        entity_type: Literal["artists", "albums"] = "artists",
        limit: int = MAX_ENTITIES,
    ) -> MapData:
        """Compute 2D positions for entities based on audio similarity.

        Args:
            db: Database session
            entity_type: "artists" or "albums"
            limit: Maximum number of entities to include

        Returns:
            MapData with nodes and edges
        """
        # Check cache first
        cached = self._get_cached_map(entity_type, limit)
        if cached:
            return cached

        # Get aggregated embeddings
        if entity_type == "artists":
            embeddings = await self._aggregate_by_artist(db)
        else:
            embeddings = await self._aggregate_by_album(db)

        if len(embeddings) < 3:
            logger.warning(f"Not enough entities with embeddings: {len(embeddings)}")
            return MapData(nodes=[], edges=[])

        # Sort by track count and limit
        sorted_entities = sorted(
            embeddings.items(), key=lambda x: x[1]["track_count"], reverse=True
        )[:limit]

        if len(sorted_entities) < 3:
            return MapData(nodes=[], edges=[])

        # Build embedding matrix
        names = [name for name, _ in sorted_entities]
        matrix = np.array([embeddings[name]["mean_embedding"] for name in names])

        logger.info(f"Computing UMAP for {len(names)} {entity_type}")

        # UMAP reduction: 512D -> 2D
        try:
            umap = self._get_umap()
            positions_2d = umap.fit_transform(matrix)
        except Exception as e:
            logger.error(f"UMAP failed: {e}")
            raise

        # Normalize to [0, 1] range
        min_vals = positions_2d.min(axis=0)
        max_vals = positions_2d.max(axis=0)
        range_vals = max_vals - min_vals
        # Avoid division by zero
        range_vals[range_vals == 0] = 1
        positions_2d = (positions_2d - min_vals) / range_vals

        # Build nodes
        nodes = []
        for i, name in enumerate(names):
            entity_data = embeddings[name]
            nodes.append(
                MapNode(
                    id=name,
                    name=name,
                    x=float(positions_2d[i][0]),
                    y=float(positions_2d[i][1]),
                    track_count=entity_data["track_count"],
                    first_track_id=entity_data["first_track_id"],
                )
            )

        # Compute k-NN edges (k=5)
        edges = self._compute_knn_edges(matrix, names, k=5)

        map_data = MapData(nodes=nodes, edges=edges)

        # Cache result
        self._cache_map(entity_type, limit, map_data)

        logger.info(f"Map computed: {len(nodes)} nodes, {len(edges)} edges")
        return map_data

    async def _aggregate_by_artist(
        self, db: AsyncSession
    ) -> dict[str, dict]:
        """Aggregate embeddings by artist.

        Returns dict mapping artist name to:
            - mean_embedding: averaged 512D vector
            - track_count: number of tracks
            - first_track_id: UUID for artwork lookup
            - representative_track_id: track closest to centroid (best for preview)
        """
        from app.config import FEATURES_VERSION

        # Fetch all tracks with embeddings
        query = (
            select(Track)
            .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
            .options(selectinload(Track.analyses))
            .where(
                Track.status == TrackStatus.ACTIVE,
                Track.artist.isnot(None),
                Track.artist != "",
                TrackAnalysis.features_version >= FEATURES_VERSION,
            )
        )
        result = await db.execute(query)
        tracks = result.scalars().all()

        # Group by artist - store both embeddings and track IDs
        artist_embeddings: dict[str, dict] = defaultdict(
            lambda: {
                "embeddings": [],
                "track_ids": [],
                "track_count": 0,
                "first_track_id": None,
            }
        )

        for track in tracks:
            if not track.analyses:
                continue

            # Get latest analysis with embedding
            latest = track.analyses[0]
            if latest.embedding is None:
                continue

            display_name = track.artist.strip()
            if not display_name:
                continue

            key = normalize_for_matching(display_name)
            if not key:
                continue

            embedding = np.array(latest.embedding)
            artist_data = artist_embeddings[key]
            artist_data["embeddings"].append(embedding)
            artist_data["track_ids"].append(str(track.id))
            artist_data["track_count"] += 1
            if artist_data["first_track_id"] is None:
                artist_data["first_track_id"] = str(track.id)
                artist_data["display_name"] = display_name

        # Compute mean embeddings and find representative track
        result_dict = {}
        for key, data in artist_embeddings.items():
            if data["track_count"] >= MIN_TRACKS_PER_ENTITY:
                embeddings_matrix = np.array(data["embeddings"])
                mean_embedding = np.mean(embeddings_matrix, axis=0)

                # Find track closest to centroid (representative track)
                representative_track_id = data["first_track_id"]
                if len(embeddings_matrix) > 1:
                    # Compute cosine similarity of each track to centroid
                    # Normalize embeddings for cosine similarity
                    norm_mean = mean_embedding / (np.linalg.norm(mean_embedding) + 1e-8)
                    norms = np.linalg.norm(embeddings_matrix, axis=1, keepdims=True) + 1e-8
                    norm_embeddings = embeddings_matrix / norms
                    similarities = norm_embeddings @ norm_mean
                    closest_idx = int(np.argmax(similarities))
                    representative_track_id = data["track_ids"][closest_idx]

                # Use display_name (first casing encountered) as the dict key
                display_name = data.get("display_name", key)
                result_dict[display_name] = {
                    "mean_embedding": mean_embedding,
                    "track_count": data["track_count"],
                    "first_track_id": data["first_track_id"],
                    "representative_track_id": representative_track_id,
                }

        return result_dict

    async def _aggregate_by_album(
        self, db: AsyncSession
    ) -> dict[str, dict]:
        """Aggregate embeddings by album.

        Returns dict mapping "Artist - Album" to embedding data.
        """
        from app.config import FEATURES_VERSION

        query = (
            select(Track)
            .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
            .options(selectinload(Track.analyses))
            .where(
                Track.status == TrackStatus.ACTIVE,
                Track.album.isnot(None),
                Track.album != "",
                TrackAnalysis.features_version >= FEATURES_VERSION,
            )
        )
        result = await db.execute(query)
        tracks = result.scalars().all()

        # Group by artist-album
        album_embeddings: dict[str, dict] = defaultdict(
            lambda: {"embeddings": [], "track_count": 0, "first_track_id": None}
        )

        for track in tracks:
            if not track.analyses:
                continue

            latest = track.analyses[0]
            if latest.embedding is None:
                continue

            artist = (track.artist or "Unknown Artist").strip()
            album = track.album.strip()
            if not album:
                continue

            key = f"{artist} - {album}"
            embedding = np.array(latest.embedding)
            album_data = album_embeddings[key]
            album_data["embeddings"].append(embedding)
            album_data["track_count"] += 1
            if album_data["first_track_id"] is None:
                album_data["first_track_id"] = str(track.id)

        # Compute mean embeddings
        result_dict = {}
        for key, data in album_embeddings.items():
            if data["track_count"] >= MIN_TRACKS_PER_ENTITY:
                result_dict[key] = {
                    "mean_embedding": np.mean(data["embeddings"], axis=0),
                    "track_count": data["track_count"],
                    "first_track_id": data["first_track_id"],
                }

        return result_dict

    def _get_3d_cache_key(self, entity_type: str) -> str:
        """Generate Redis cache key for 3D map data."""
        return f"{MAP_CACHE_KEY_PREFIX}:3d:{entity_type}"

    def _get_cached_3d_map(self, entity_type: str) -> MapData3D | None:
        """Try to get cached 3D map from Redis."""
        try:
            from app.services.redis_client import get_redis

            r = get_redis()
            key = self._get_3d_cache_key(entity_type)
            data: bytes | None = r.get(key)  # type: ignore[assignment]
            if data:
                cached = json.loads(data)
                logger.info(f"Cache hit for 3D music map {entity_type}")
                # Handle missing representative_track_id for backwards compatibility
                nodes = []
                for n in cached["nodes"]:
                    nodes.append(MapNode3D(
                        id=n["id"],
                        name=n["name"],
                        x=n["x"],
                        y=n["y"],
                        z=n["z"],
                        track_count=n["track_count"],
                        first_track_id=n["first_track_id"],
                        representative_track_id=n.get("representative_track_id"),
                    ))
                return MapData3D(
                    nodes=nodes,
                    entity_type=cached["entity_type"],
                    total_entities=cached["total_entities"],
                )
        except Exception as e:
            logger.warning(f"Failed to get cached 3D map: {e}")
        return None

    def _cache_3d_map(self, entity_type: str, map_data: MapData3D) -> None:
        """Cache computed 3D map to Redis (1 hour TTL)."""
        try:
            from app.services.redis_client import get_redis

            r = get_redis()
            key = self._get_3d_cache_key(entity_type)
            data = {
                "nodes": [
                    {
                        "id": n.id,
                        "name": n.name,
                        "x": n.x,
                        "y": n.y,
                        "z": n.z,
                        "track_count": n.track_count,
                        "first_track_id": n.first_track_id,
                        "representative_track_id": n.representative_track_id,
                    }
                    for n in map_data.nodes
                ],
                "entity_type": map_data.entity_type,
                "total_entities": map_data.total_entities,
            }
            # 1 hour cache for 3D map (more expensive to compute)
            r.set(key, json.dumps(data), ex=3600)
            logger.info(f"Cached 3D music map {entity_type} for 3600s")
        except Exception as e:
            logger.warning(f"Failed to cache 3D map: {e}")

    async def compute_3d_map(
        self,
        db: AsyncSession,
        entity_type: Literal["artists", "albums"] = "artists",
    ) -> MapData3D:
        """Compute 3D positions for all entities based on audio similarity.

        Unlike 2D maps, 3D maps include ALL entities (no limit) since we want
        to explore the entire library. The results are cached for 1 hour.

        Args:
            db: Database session
            entity_type: "artists" or "albums"

        Returns:
            MapData3D with all entity positions
        """
        # Check cache first
        cached = self._get_cached_3d_map(entity_type)
        if cached:
            return cached

        # Get aggregated embeddings (no limit)
        if entity_type == "artists":
            embeddings = await self._aggregate_by_artist(db)
        else:
            embeddings = await self._aggregate_by_album(db)

        if len(embeddings) < 3:
            logger.warning(f"Not enough entities with embeddings: {len(embeddings)}")
            return MapData3D(nodes=[], entity_type=entity_type, total_entities=0)

        # Sort by track count but include ALL entities
        sorted_entities = sorted(
            embeddings.items(), key=lambda x: x[1]["track_count"], reverse=True
        )

        # Build embedding matrix
        names = [name for name, _ in sorted_entities]
        matrix = np.array([embeddings[name]["mean_embedding"] for name in names])

        logger.info(f"Computing 3D UMAP for {len(names)} {entity_type}")

        # UMAP reduction: 512D -> 3D
        try:
            umap = self._get_umap(n_components=3)
            positions_3d = umap.fit_transform(matrix)
        except Exception as e:
            logger.error(f"3D UMAP failed: {e}")
            raise

        # Normalize to [-1, 1] range for 3D visualization
        min_vals = positions_3d.min(axis=0)
        max_vals = positions_3d.max(axis=0)
        range_vals = max_vals - min_vals
        range_vals[range_vals == 0] = 1
        # Normalize to [0, 1] then scale to [-1, 1]
        positions_3d = (positions_3d - min_vals) / range_vals * 2 - 1

        # Build nodes
        nodes = []
        for i, name in enumerate(names):
            entity_data = embeddings[name]
            nodes.append(
                MapNode3D(
                    id=name,
                    name=name,
                    x=float(positions_3d[i][0]),
                    y=float(positions_3d[i][1]),
                    z=float(positions_3d[i][2]),
                    track_count=entity_data["track_count"],
                    first_track_id=entity_data["first_track_id"],
                    representative_track_id=entity_data.get("representative_track_id"),
                )
            )

        map_data = MapData3D(
            nodes=nodes,
            entity_type=entity_type,
            total_entities=len(nodes),
        )

        # Cache result
        self._cache_3d_map(entity_type, map_data)

        logger.info(f"3D Map computed: {len(nodes)} nodes")
        return map_data

    async def compute_3d_map_with_progress(
        self,
        db: AsyncSession,
        entity_type: Literal["artists", "albums"] = "artists",
    ) -> AsyncGenerator[MapProgress | MapData3D, None]:
        """Compute 3D map with progress updates for SSE streaming.

        Yields MapProgress updates during computation, then MapData3D at the end.
        """
        # Check cache first
        yield MapProgress(phase="checking_cache", progress=0.0, message="Checking cache...")
        cached = self._get_cached_3d_map(entity_type)
        if cached:
            yield MapProgress(phase="complete", progress=1.0, message="Loaded from cache")
            yield cached
            return

        # Phase 1: Database query
        yield MapProgress(
            phase="db_query",
            progress=0.1,
            message="Loading embeddings from database...",
        )

        if entity_type == "artists":
            embeddings = await self._aggregate_by_artist(db)
        else:
            embeddings = await self._aggregate_by_album(db)

        if len(embeddings) < 3:
            logger.warning(f"Not enough entities with embeddings: {len(embeddings)}")
            yield MapProgress(phase="complete", progress=1.0, message="Not enough data")
            yield MapData3D(nodes=[], entity_type=entity_type, total_entities=0)
            return

        yield MapProgress(
            phase="db_query",
            progress=0.3,
            message=f"Found {len(embeddings)} {entity_type} with embeddings",
        )

        # Phase 2: Sorting
        yield MapProgress(phase="sorting", progress=0.35, message="Sorting by track count...")

        sorted_entities = sorted(
            embeddings.items(), key=lambda x: x[1]["track_count"], reverse=True
        )

        names = [name for name, _ in sorted_entities]
        matrix = np.array([embeddings[name]["mean_embedding"] for name in names])

        yield MapProgress(
            phase="sorting",
            progress=0.4,
            message=f"Processing {len(names)} {entity_type}...",
        )

        # Phase 3: UMAP (this is the slow part)
        yield MapProgress(
            phase="umap",
            progress=0.45,
            message=f"Computing 3D positions for {len(names)} entities (this may take a while)...",
        )

        try:
            umap = self._get_umap(n_components=3)
            positions_3d = umap.fit_transform(matrix)
        except Exception as e:
            logger.error(f"3D UMAP failed: {e}")
            raise

        yield MapProgress(phase="umap", progress=0.85, message="Normalizing positions...")

        # Normalize to [-1, 1] range
        min_vals = positions_3d.min(axis=0)
        max_vals = positions_3d.max(axis=0)
        range_vals = max_vals - min_vals
        range_vals[range_vals == 0] = 1
        positions_3d = (positions_3d - min_vals) / range_vals * 2 - 1

        # Phase 4: Build nodes
        yield MapProgress(phase="building", progress=0.9, message="Building node data...")

        nodes = []
        for i, name in enumerate(names):
            entity_data = embeddings[name]
            nodes.append(
                MapNode3D(
                    id=name,
                    name=name,
                    x=float(positions_3d[i][0]),
                    y=float(positions_3d[i][1]),
                    z=float(positions_3d[i][2]),
                    track_count=entity_data["track_count"],
                    first_track_id=entity_data["first_track_id"],
                    representative_track_id=entity_data.get("representative_track_id"),
                )
            )

        map_data = MapData3D(
            nodes=nodes,
            entity_type=entity_type,
            total_entities=len(nodes),
        )

        # Cache result
        yield MapProgress(phase="caching", progress=0.95, message="Caching result...")
        self._cache_3d_map(entity_type, map_data)

        yield MapProgress(
            phase="complete",
            progress=1.0,
            message=f"Complete: {len(nodes)} {entity_type}",
        )
        yield map_data

    def _compute_knn_edges(
        self, embeddings: np.ndarray, names: list[str], k: int = 5
    ) -> list[MapEdge]:
        """Compute k-nearest-neighbor edges based on cosine similarity.

        Args:
            embeddings: NxD matrix of embeddings
            names: List of entity names
            k: Number of neighbors per entity

        Returns:
            List of edges connecting similar entities
        """
        from sklearn.metrics.pairwise import cosine_similarity

        # Compute pairwise similarities
        similarities = cosine_similarity(embeddings)

        # For each entity, find k nearest neighbors
        edges = []
        seen_pairs = set()

        for i in range(len(names)):
            # Get indices of k most similar (excluding self)
            sim_scores = similarities[i].copy()
            sim_scores[i] = -1  # Exclude self
            top_k_indices = np.argsort(sim_scores)[-k:][::-1]

            for j in top_k_indices:
                if sim_scores[j] <= 0:
                    continue

                # Avoid duplicate edges
                pair = tuple(sorted([i, j]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                edges.append(
                    MapEdge(
                        source=names[i],
                        target=names[j],
                        weight=float(sim_scores[j]),
                    )
                )

        return edges


# Singleton instance
_map_service: EmbeddingMapService | None = None


def get_embedding_map_service() -> EmbeddingMapService:
    """Get the singleton embedding map service."""
    global _map_service
    if _map_service is None:
        _map_service = EmbeddingMapService()
    return _map_service
