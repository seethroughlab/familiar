"""Music import endpoints — aggregated from sub-routers."""

from fastapi import APIRouter

from app.api.routes.library_import.preview import router as preview_router
from app.api.routes.library_import.quick import router as quick_router

router = APIRouter(tags=["library"])
router.include_router(quick_router)
router.include_router(preview_router)
