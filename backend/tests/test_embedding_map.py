"""Tests for embedding map service (embedding_map.py).

Tests cover similarity search, UMAP dimensionality reduction, and edge computation.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import numpy as np
import pytest

pytest.importorskip("sklearn")

from app.services.embedding_map import (
    EmbeddingMapService,
    MapData,
    MapData3D,
    MapNode,
    get_embedding_map_service,
)


def _stream_rows(rows):
    """Build an async-iterable that mimics ``await db.stream(query)``."""

    async def _gen():
        for row in rows:
            yield row

    return _gen()


class TestEmbeddingMapServiceInit:
    """Tests for EmbeddingMapService initialization."""

    def test_singleton_returns_same_instance(self):
        """get_embedding_map_service should return singleton."""
        service1 = get_embedding_map_service()
        service2 = get_embedding_map_service()
        assert service1 is service2

    def test_umap_lazy_loaded(self):
        """UMAP should only be loaded when needed."""
        service = EmbeddingMapService()
        assert service._umap_2d is None
        assert service._umap_3d is None


class TestMapComputation:
    """Tests for 2D map computation."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def service(self):
        return EmbeddingMapService()

    @pytest.mark.asyncio
    async def test_compute_map_returns_empty_when_few_entities(self, service, mock_db):
        """Should return empty map when fewer than 3 entities."""
        with patch.object(service, "_aggregate_by_artist") as mock_agg:
            mock_agg.return_value = {
                "Artist 1": {"mean_embedding": np.zeros(512), "track_count": 5, "first_track_id": str(uuid4())},
            }

            result = await service.compute_map(mock_db, entity_type="artists")

            assert isinstance(result, MapData)
            assert len(result.nodes) == 0
            assert len(result.edges) == 0

    @pytest.mark.asyncio
    async def test_compute_map_creates_nodes(self, service, mock_db):
        """Should create nodes for each entity."""
        # Create mock embeddings for 5 artists
        mock_embeddings = {}
        for i in range(5):
            mock_embeddings[f"Artist {i}"] = {
                "mean_embedding": np.random.rand(512),
                "track_count": 10 - i,
                "first_track_id": str(uuid4()),
            }

        with patch.object(service, "_aggregate_by_artist", return_value=mock_embeddings):
            with patch.object(service, "_get_cached_map", return_value=None):
                with patch.object(service, "_cache_map"):
                    # Mock UMAP
                    with patch.object(service, "_get_umap") as mock_umap:
                        mock_umap_instance = MagicMock()
                        mock_umap_instance.fit_transform.return_value = np.random.rand(5, 2)
                        mock_umap.return_value = mock_umap_instance

                        result = await service.compute_map(mock_db, entity_type="artists", limit=100)

                        assert len(result.nodes) == 5
                        for node in result.nodes:
                            assert 0 <= node.x <= 1
                            assert 0 <= node.y <= 1

    @pytest.mark.asyncio
    async def test_compute_map_limits_entities(self, service, mock_db):
        """Should limit number of entities by track count."""
        mock_embeddings = {}
        for i in range(10):
            mock_embeddings[f"Artist {i}"] = {
                "mean_embedding": np.random.rand(512),
                "track_count": 100 - i * 10,
                "first_track_id": str(uuid4()),
            }

        with patch.object(service, "_aggregate_by_artist", return_value=mock_embeddings):
            with patch.object(service, "_get_cached_map", return_value=None):
                with patch.object(service, "_cache_map"):
                    with patch.object(service, "_get_umap") as mock_umap:
                        mock_umap_instance = MagicMock()
                        mock_umap_instance.fit_transform.return_value = np.random.rand(5, 2)
                        mock_umap.return_value = mock_umap_instance

                        result = await service.compute_map(mock_db, entity_type="artists", limit=5)

                        assert len(result.nodes) == 5
                        # Should include artists with highest track counts
                        names = [n.name for n in result.nodes]
                        assert "Artist 0" in names  # 100 tracks

    @pytest.mark.asyncio
    async def test_compute_map_uses_cache(self, service, mock_db):
        """Should return cached result if available."""
        cached_data = MapData(
            nodes=[MapNode(id="cached", name="Cached Artist", x=0.5, y=0.5, track_count=10, first_track_id=str(uuid4()))],
            edges=[],
        )

        with patch.object(service, "_get_cached_map", return_value=cached_data):
            result = await service.compute_map(mock_db, entity_type="artists")

            assert result == cached_data
            assert result.nodes[0].name == "Cached Artist"


class TestMap3DComputation:
    """Tests for 3D map computation."""

    @pytest.fixture
    def service(self):
        return EmbeddingMapService()

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_compute_3d_map_creates_3d_nodes(self, service, mock_db):
        """3D map should have x, y, z coordinates."""
        mock_embeddings = {}
        for i in range(5):
            mock_embeddings[f"Artist {i}"] = {
                "mean_embedding": np.random.rand(512),
                "track_count": 10,
                "first_track_id": str(uuid4()),
                "representative_track_id": str(uuid4()),
            }

        with patch.object(service, "_aggregate_by_artist", return_value=mock_embeddings):
            with patch.object(service, "_get_cached_3d_map", return_value=None):
                with patch.object(service, "_cache_3d_map"):
                    with patch.object(service, "_get_umap") as mock_umap:
                        mock_umap_instance = MagicMock()
                        mock_umap_instance.fit_transform.return_value = np.random.rand(5, 3)
                        mock_umap.return_value = mock_umap_instance

                        result = await service.compute_3d_map(mock_db, entity_type="artists")

                        assert isinstance(result, MapData3D)
                        assert len(result.nodes) == 5
                        for node in result.nodes:
                            assert -1 <= node.x <= 1
                            assert -1 <= node.y <= 1
                            assert -1 <= node.z <= 1


class TestKNNEdgeComputation:
    """Tests for k-nearest-neighbor edge computation."""

    @pytest.fixture
    def service(self):
        return EmbeddingMapService()

    def test_compute_knn_edges_creates_edges(self, service):
        """Should create edges between similar entities."""
        # Create embeddings where Artist 0 and Artist 1 are similar
        embeddings = np.array([
            [1, 0, 0, 0],  # Artist 0
            [0.9, 0.1, 0, 0],  # Artist 1 - similar to 0
            [0, 1, 0, 0],  # Artist 2
            [0, 0.9, 0.1, 0],  # Artist 3 - similar to 2
            [0, 0, 1, 0],  # Artist 4
        ])
        names = ["Artist 0", "Artist 1", "Artist 2", "Artist 3", "Artist 4"]

        edges = service._compute_knn_edges(embeddings, names, k=2)

        assert len(edges) > 0
        # Check that edges connect similar artists
        edge_pairs = {(e.source, e.target) for e in edges}
        # Artist 0 and 1 should be connected
        assert ("Artist 0", "Artist 1") in edge_pairs or ("Artist 1", "Artist 0") in edge_pairs

    def test_compute_knn_edges_no_self_loops(self, service):
        """Edges should not connect entity to itself."""
        embeddings = np.random.rand(5, 512)
        names = [f"Artist {i}" for i in range(5)]

        edges = service._compute_knn_edges(embeddings, names, k=3)

        for edge in edges:
            assert edge.source != edge.target

    def test_compute_knn_edges_no_duplicate_pairs(self, service):
        """Should not have duplicate edges (A-B and B-A)."""
        embeddings = np.random.rand(10, 512)
        names = [f"Artist {i}" for i in range(10)]

        edges = service._compute_knn_edges(embeddings, names, k=5)

        seen_pairs = set()
        for edge in edges:
            pair = tuple(sorted([edge.source, edge.target]))
            assert pair not in seen_pairs, f"Duplicate edge: {pair}"
            seen_pairs.add(pair)

    def test_compute_knn_edges_weights_are_valid(self, service):
        """Edge weights should be similarity scores between 0 and 1."""
        embeddings = np.random.rand(5, 512)
        names = [f"Artist {i}" for i in range(5)]

        edges = service._compute_knn_edges(embeddings, names, k=3)

        for edge in edges:
            assert 0 < edge.weight <= 1


class TestAggregation:
    """Tests for embedding aggregation by artist/album."""

    @pytest.fixture
    def service(self):
        return EmbeddingMapService()

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_aggregate_by_artist_groups_tracks(self, service, mock_db):
        """Should group tracks by artist and average embeddings."""
        rows = [
            (uuid4(), "Test Artist", list(np.ones(512))),
            (uuid4(), "Test Artist", list(np.ones(512) * 2)),
            (uuid4(), "Other Artist", list(np.zeros(512))),
        ]
        mock_db.stream = AsyncMock(return_value=_stream_rows(rows))

        with patch("app.config.FEATURES_VERSION", 1):
            result = await service._aggregate_by_artist(mock_db)

        assert "Test Artist" in result
        assert "Other Artist" in result
        assert result["Test Artist"]["track_count"] == 2
        assert result["Other Artist"]["track_count"] == 1
        # Mean embedding of [1,1,...] and [2,2,...] should be [1.5,1.5,...]
        assert result["Test Artist"]["mean_embedding"][0] == pytest.approx(1.5)

    @pytest.mark.asyncio
    async def test_aggregate_skips_blank_artists(self, service, mock_db):
        """Should skip rows with whitespace-only artist names."""
        rows = [
            (uuid4(), "Artist With Embedding", list(np.ones(512))),
            (uuid4(), "   ", list(np.ones(512))),
        ]
        mock_db.stream = AsyncMock(return_value=_stream_rows(rows))

        with patch("app.config.FEATURES_VERSION", 1):
            result = await service._aggregate_by_artist(mock_db)

        assert "Artist With Embedding" in result
        assert len(result) == 1


class TestCaching:
    """Tests for Redis caching functionality."""

    @pytest.fixture
    def service(self):
        return EmbeddingMapService()

    def test_get_cache_key_format(self, service):
        """Cache key should include entity type and limit."""
        key = service._get_cache_key("artists", 100)
        assert "artists" in key
        assert "100" in key

    def test_invalidate_cache(self, service):
        """Should delete all map cache keys."""
        with patch("app.services.tasks.get_redis") as mock_get_redis:
            mock_redis = MagicMock()
            mock_redis.scan_iter.return_value = ["music_map:artists:100", "music_map:albums:50"]
            mock_get_redis.return_value = mock_redis

            service.invalidate_cache()

            assert mock_redis.delete.call_count == 2
