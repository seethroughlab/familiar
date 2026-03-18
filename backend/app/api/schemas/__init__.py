"""Shared Pydantic schemas used across multiple route modules.

Centralising DTOs here breaks route-to-route import cycles.
"""

from app.api.schemas.common import CancelResponse
from app.api.schemas.tracks import (
    BatchTracksRequest,
    TrackDetailResponse,
    TrackFeaturesResponse,
    TrackIdsResponse,
    TrackListResponse,
    TrackResponse,
)

__all__ = [
    "BatchTracksRequest",
    "CancelResponse",
    "TrackDetailResponse",
    "TrackFeaturesResponse",
    "TrackIdsResponse",
    "TrackListResponse",
    "TrackResponse",
]
