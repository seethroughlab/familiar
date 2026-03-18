"""Playlist management endpoints — aggregated from sub-routers.

Root-path operations (list/create) are registered directly on the parent
router to avoid FastAPI's "prefix and path cannot both be empty" restriction.
"""

from fastapi import APIRouter, status

from app.api.routes.playlists.crud import (  # noqa: F401
    PlaylistDetailResponse,
    PlaylistResponse,
    create_playlist,
    list_playlists,
)
from app.api.routes.playlists.crud import (
    router as crud_router,
)
from app.api.routes.playlists.recommendations import router as recommendations_router
from app.api.routes.playlists.tracks import router as tracks_router

router = APIRouter(prefix="/playlists", tags=["playlists"])

# Register root-path endpoints directly (same pattern as tracks/__init__.py)
router.get("", response_model=list[PlaylistResponse])(list_playlists)
router.post("", response_model=PlaylistDetailResponse, status_code=status.HTTP_201_CREATED)(create_playlist)

router.include_router(crud_router)
router.include_router(tracks_router)
router.include_router(recommendations_router)
