"""Data export/import endpoints — aggregated from sub-routers."""

from fastapi import APIRouter

from app.api.routes.export_import.backup import router as backup_router
from app.api.routes.export_import.library import router as library_router
from app.api.routes.export_import.profile import router as profile_router

router = APIRouter(prefix="/export-import", tags=["transfer"])
router.include_router(profile_router)
router.include_router(library_router)
router.include_router(backup_router)
