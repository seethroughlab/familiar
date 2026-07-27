"""Music map (embedding-based similarity) endpoints."""

import logging
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import DbSession
from app.api.exceptions import (
    MapComputationError,
    NotFoundError,
    ServiceUnavailableError,
    create_sse_error,
    sanitize_error_for_client,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["library"])


class MapNode(BaseModel):
    """A node in the music map."""

    id: str
    name: str
    x: float
    y: float
    track_count: int
    first_track_id: str
    # Per-entity mean of each lens feature (energy/valence/etc.), for color/size lensing.
    features: dict[str, float] = {}


class MapEdge(BaseModel):
    """An edge connecting similar nodes."""

    source: str
    target: str
    weight: float


class MusicMapResponse(BaseModel):
    """Response for music map visualization."""

    nodes: list[MapNode]
    edges: list[MapEdge]
    entity_type: str
    total_entities: int


@router.get("/map", response_model=MusicMapResponse)
async def get_music_map(
    db: DbSession,
    entity_type: Literal["artists", "albums"] = "artists",
    limit: int = 200,
) -> MusicMapResponse:
    """Get 2D positions for artists/albums based on audio similarity.

    Uses UMAP dimensionality reduction on CLAP embeddings to position
    entities so that similar-sounding music appears close together.

    This is computationally expensive - results should be cached on the frontend.

    Args:
        entity_type: "artists" or "albums"
        limit: Maximum entities to include (default 200, max 500)
    """
    from app.services.embedding_map import get_embedding_map_service

    limit = min(limit, 500)  # Cap at 500 for performance

    service = get_embedding_map_service()

    try:
        map_data = await service.compute_map(db, entity_type=entity_type, limit=limit)
    except ImportError:
        raise ServiceUnavailableError("Required dependencies not available. Install umap-learn for map visualization.")
    except Exception:
        raise MapComputationError()

    return MusicMapResponse(
        nodes=[
            MapNode(
                id=n.id,
                name=n.name,
                x=n.x,
                y=n.y,
                track_count=n.track_count,
                first_track_id=n.first_track_id,
                features=n.features,
            )
            for n in map_data.nodes
        ],
        edges=[
            MapEdge(source=e.source, target=e.target, weight=e.weight)
            for e in map_data.edges
        ],
        entity_type=entity_type,
        total_entities=len(map_data.nodes),
    )


@router.get(
    "/map/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "Server-sent events reporting map build progress.",
        }
    },
)
async def get_music_map_stream(
    db: DbSession,
    entity_type: Literal["artists", "albums"] = "artists",
    limit: int = 200,
) -> StreamingResponse:
    """Stream music map computation progress via Server-Sent Events.

    Sends progress events during computation, then the complete map data.

    Event types:
    - progress: {"phase": "...", "progress": 0.5, "message": "..."}
    - complete: Full MusicMapResponse JSON
    - error: {"error": "..."}
    """
    import json

    from app.services.embedding_map import (
        MapData,
        MapProgress,
        get_embedding_map_service,
    )

    limit = min(limit, 500)  # Cap at 500 for performance

    async def event_stream():
        service = get_embedding_map_service()

        try:
            async for item in service.compute_map_with_progress(
                db, entity_type=entity_type, limit=limit
            ):
                if isinstance(item, MapProgress):
                    # Send progress event
                    data = {
                        "phase": item.phase,
                        "progress": item.progress,
                        "message": item.message,
                    }
                    yield f"event: progress\ndata: {json.dumps(data)}\n\n"
                elif isinstance(item, MapData):
                    # Send complete event with full map data
                    response = {
                        "nodes": [
                            {
                                "id": n.id,
                                "name": n.name,
                                "x": n.x,
                                "y": n.y,
                                "track_count": n.track_count,
                                "first_track_id": n.first_track_id,
                                "features": n.features,
                            }
                            for n in item.nodes
                        ],
                        "edges": [
                            {"source": e.source, "target": e.target, "weight": e.weight}
                            for e in item.edges
                        ],
                        "entity_type": entity_type,
                        "total_entities": len(item.nodes),
                    }
                    yield f"event: complete\ndata: {json.dumps(response)}\n\n"
        except ImportError as e:
            logger.warning(f"Map computation missing dependency: {e}")
            yield f"event: error\ndata: {create_sse_error('map_missing_dependency', 'Required dependencies not available. Install umap-learn for map visualization.')}\n\n"
        except Exception as e:
            logger.error(f"Map computation failed: {e}")
            yield f"event: error\ndata: {create_sse_error('map_computation_failed', 'Failed to compute library map. Please try again.')}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


# ============================================================================
# Ego-Centric Music Map
# ============================================================================


class EgoMapCenterResponse(BaseModel):
    """Center artist of the ego map."""

    name: str
    track_count: int
    first_track_id: str


class EgoMapArtistResponse(BaseModel):
    """An artist in the ego-centric map."""

    name: str
    x: float
    y: float
    distance: float
    track_count: int
    first_track_id: str


class EgoMapResponse(BaseModel):
    """Response for ego-centric music map."""

    center: EgoMapCenterResponse
    artists: list[EgoMapArtistResponse]
    mode: str
    total_artists: int


class MapNode3DResponse(BaseModel):
    """A node in the 3D music map."""

    id: str
    name: str
    x: float
    y: float
    z: float
    track_count: int
    first_track_id: str


class MusicMap3DResponse(BaseModel):
    """Response for 3D music map visualization."""

    nodes: list[MapNode3DResponse]
    entity_type: str
    total_entities: int


@router.get("/map/3d", response_model=MusicMap3DResponse)
async def get_3d_music_map(
    db: DbSession,
    entity_type: Literal["artists", "albums"] = "artists",
) -> MusicMap3DResponse:
    """Get 3D positions for all artists/albums based on audio similarity.

    Uses UMAP dimensionality reduction on CLAP embeddings to position
    entities in 3D space so that similar-sounding music appears close together.

    Unlike the 2D map, this includes ALL entities in your library for full
    exploration. Results are cached for 1 hour due to expensive computation.

    Args:
        entity_type: "artists" (default) or "albums"
    """
    from app.services.embedding_map import get_embedding_map_service

    service = get_embedding_map_service()

    try:
        map_data = await service.compute_3d_map(db, entity_type=entity_type)
    except ImportError:
        raise ServiceUnavailableError("Required dependencies not available. Install umap-learn for map visualization.")
    except Exception:
        raise MapComputationError("Failed to compute 3D library map")

    return MusicMap3DResponse(
        nodes=[
            MapNode3DResponse(
                id=n.id,
                name=n.name,
                x=n.x,
                y=n.y,
                z=n.z,
                track_count=n.track_count,
                first_track_id=n.first_track_id,
            )
            for n in map_data.nodes
        ],
        entity_type=map_data.entity_type,
        total_entities=map_data.total_entities,
    )


@router.get(
    "/map/3d/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "Server-sent events reporting 3D map build progress.",
        }
    },
)
async def get_3d_music_map_stream(
    db: DbSession,
    entity_type: Literal["artists", "albums"] = "artists",
) -> StreamingResponse:
    """Stream 3D music map computation progress via Server-Sent Events.

    Sends progress events during computation, then the complete map data.
    Use this for better UX during the initial (slow) UMAP computation.

    Event types:
    - progress: {"phase": "...", "progress": 0.5, "message": "..."}
    - complete: Full MusicMap3DResponse JSON
    - error: {"error": "..."}
    """
    import json

    from app.services.embedding_map import (
        MapData3D,
        MapProgress,
        get_embedding_map_service,
    )

    async def event_stream():
        service = get_embedding_map_service()

        try:
            async for item in service.compute_3d_map_with_progress(
                db, entity_type=entity_type
            ):
                if isinstance(item, MapProgress):
                    # Send progress event
                    data = {
                        "phase": item.phase,
                        "progress": item.progress,
                        "message": item.message,
                    }
                    yield f"event: progress\ndata: {json.dumps(data)}\n\n"
                elif isinstance(item, MapData3D):
                    # Send complete event with full map data
                    response = {
                        "nodes": [
                            {
                                "id": n.id,
                                "name": n.name,
                                "x": n.x,
                                "y": n.y,
                                "z": n.z,
                                "track_count": n.track_count,
                                "first_track_id": n.first_track_id,
                            }
                            for n in item.nodes
                        ],
                        "entity_type": item.entity_type,
                        "total_entities": item.total_entities,
                    }
                    yield f"event: complete\ndata: {json.dumps(response)}\n\n"
        except ImportError as e:
            logger.warning(f"3D map computation missing dependency: {e}")
            yield f"event: error\ndata: {create_sse_error('3d_map_missing_dependency', 'Required dependencies not available. Install umap-learn for map visualization.')}\n\n"
        except Exception as e:
            logger.error(f"3D map computation failed: {e}")
            yield f"event: error\ndata: {create_sse_error('3d_map_computation_failed', 'Failed to compute 3D library map. Please try again.')}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.get("/map/ego")
async def get_ego_centric_map(
    db: DbSession,
    center: str = Query(..., description="Artist name to center on"),
    limit: int = Query(200, ge=10, le=500, description="Number of similar artists"),
    mode: Literal["radial"] = Query("radial", description="Layout mode"),
) -> EgoMapResponse:
    """Get ego-centric map centered on an artist.

    Returns the center artist and surrounding artists positioned radially
    based on audio similarity. Distance from center indicates dissimilarity.

    The angle of each artist is stable (based on name hash), so when you
    recenter on a different artist, positions smoothly transition rather
    than completely reshuffling.
    """
    from app.services.ego_map import get_ego_map_service

    service = get_ego_map_service()

    try:
        data = await service.compute_ego_map(db, center=center, limit=limit, mode=mode)
    except ValueError as e:
        raise NotFoundError(sanitize_error_for_client(e, "Artist not found"))

    return EgoMapResponse(
        center=EgoMapCenterResponse(
            name=data.center.name,
            track_count=data.center.track_count,
            first_track_id=data.center.first_track_id,
        ),
        artists=[
            EgoMapArtistResponse(
                name=a.name,
                x=a.x,
                y=a.y,
                distance=a.distance,
                track_count=a.track_count,
                first_track_id=a.first_track_id,
            )
            for a in data.artists
        ],
        mode=data.mode,
        total_artists=data.total_artists,
    )
