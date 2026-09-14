"""Music import endpoints — aggregated from sub-routers.

`quick.py` (`GET /import/scan-path`) was removed by ADR-0117: it listed the `/imports-incoming`
mount for a copy-based import that zero-touch (`5fe90d7a`) had already deleted, and no client
called it. The folder it listed is now mounted inside the library as `/music/Inbox`, where the
scanner finds it without being asked.
"""

from fastapi import APIRouter

from app.api.routes.library_import.preview import router as preview_router

router = APIRouter(tags=["ingest"])
router.include_router(preview_router)
