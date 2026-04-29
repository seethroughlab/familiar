"""Familiar API - Main FastAPI application."""

import logging
import multiprocessing
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

# Set start method to spawn for better compatibility with PyTorch (MPS) and cleaner memory usage on Linux
try:
    multiprocessing.set_start_method("spawn", force=True)
except RuntimeError:
    pass  # Context already set

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import SQLAlchemyError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.exceptions import FamiliarError
from app.api.ratelimit import limiter
from app.api.routes import (
    admin_artists,
    ambient,
    analysis,
    artwork,
    background,
    bandcamp,
    chat,
    diagnostics,
    download,
    export_import,
    external_albums,
    favorites,
    health,
    lastfm,
    library,
    mixtapes,
    new_releases,
    organizer,
    outputs,
    pending_review,
    playlists,
    profiles,
    proposed_changes,
    s3_backup,
    smart_playlists,
    spotify_import,
    tracks,
    updates,
    videos,
)
from app.api.routes import settings as settings_routes
from app.config import AUDIO_EXTENSIONS, MUSIC_LIBRARY_PATH, get_app_version
from app.config import settings as app_config
from app.logging_config import get_logger, setup_logging

# Configure structured logging
setup_logging()
logger = get_logger(__name__)


# Pure ASGI middleware for request ID + timing (avoids BaseHTTPMiddleware event-loop issues)
class RequestIDMiddleware:
    """Add unique request ID and request timing to each request."""

    _SKIP_TIMING_PREFIXES = ("/health", "/assets/", "/icons/", "/sw.js", "/manifest.json", "/workbox-")

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())[:8]
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id

        path = scope["path"]
        skip_timing = any(path.startswith(p) for p in self._SKIP_TIMING_PREFIXES)

        status_code = 500  # default in case send is never called with response

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        if skip_timing:
            await self.app(scope, receive, send_with_request_id)
            return

        from app.services.metrics import get_metrics_collector, get_query_count, reset_query_count
        reset_query_count()

        start = time.perf_counter()
        await self.app(scope, receive, send_with_request_id)
        duration_ms = (time.perf_counter() - start) * 1000

        query_count = get_query_count()

        route = scope.get("route")
        template = route.path if route else path
        method = scope.get("method", "?")

        logger.info(
            "request_completed",
            extra={
                "method": method,
                "route": template,
                "status_code": status_code,
                "duration_ms": round(duration_ms, 2),
                "query_count": query_count,
                "request_id": request_id,
            },
        )

        get_metrics_collector().record_request(method, template, status_code, duration_ms, query_count)


def create_error_response(
    status_code: int,
    message: str,
    detail: str | None = None,
    request_id: str | None = None,
) -> JSONResponse:
    """Create a consistent error response."""
    content = {
        "error": True,
        "status_code": status_code,
        "message": message,
    }
    if detail:
        content["detail"] = detail
    if request_id:
        content["request_id"] = request_id
    return JSONResponse(status_code=status_code, content=content)


def validate_library_path() -> None:
    """Validate library path on startup and log warnings for issues."""
    path = MUSIC_LIBRARY_PATH

    if not path.exists():
        logging.warning(
            f"⚠️  Library path does not exist: {path}. "
            "Configure MUSIC_LIBRARY_PATH in docker-compose.yml"
        )
        return

    if not path.is_dir():
        logging.warning(f"⚠️  Library path is not a directory: {path}")
        return

    # Check if directory has any audio files (quick check)
    try:
        has_audio = False
        for ext in AUDIO_EXTENSIONS:
            if any(path.rglob(f"*{ext}")):
                has_audio = True
                break
        if not has_audio:
            logging.warning(
                f"⚠️  Library path appears empty (no audio files): {path}. "
                "Check that MUSIC_LIBRARY_PATH in docker-compose.yml points to your music folder"
            )
    except PermissionError:
        logging.warning(f"⚠️  Cannot read library path (permission denied): {path}")

    # Zero-touch enforcement: library should be read-only
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(dir=path, delete=True):
            pass
        # If we got here, the directory is writable — warn
        logging.warning(
            "⚠️  Library path is writable: %s. "
            "For zero-touch safety, mount the music library as read-only (:ro in docker-compose).",
            path,
        )
    except OSError:
        # Expected — directory is read-only, which is what we want
        pass


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan events."""
    # Startup
    logger.info(f"Starting Familiar API (debug={app_config.debug})")

    # Validate library path and log warnings
    import asyncio
    await asyncio.to_thread(validate_library_path)

    # Validate DB migration state before serving requests.
    if app_config.migration_preflight_enabled:
        from app.db.migration_preflight import check_database_at_head

        ok, current, heads, reason = await asyncio.to_thread(check_database_at_head)
        if ok:
            logger.info("Migration preflight passed (revision=%s)", ",".join(current))
        else:
            message = (
                "Migration preflight failed. "
                f"reason={reason}; current={current}; heads={heads}. "
                "Run 'alembic upgrade head' before startup."
            )
            if app_config.migration_preflight_strict:
                raise RuntimeError(message)
            logger.warning(message)

    # Check analysis capabilities (warns if embeddings disabled)
    from app.services.analysis import check_analysis_capabilities
    check_analysis_capabilities()

    # Start background task manager
    from app.services.background import get_background_manager
    bg = get_background_manager()
    await bg.startup()
    logger.info("Background task manager started")

    yield

    # Shutdown
    logger.info("Shutting down Familiar API")
    await bg.shutdown()
    logger.info("Background task manager stopped")


app = FastAPI(
    title="Familiar",
    description="LLM-powered local music player API",
    version=get_app_version(),
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

# Request ID middleware (must be added first to wrap everything)
app.add_middleware(RequestIDMiddleware)

# CORS middleware for frontend
# Build allowed origins from FRONTEND_URL + localhost for development
def _get_cors_origins() -> list[str]:
    """Get CORS allowed origins from configuration."""
    origins = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:4400",
    ]
    # Add configured frontend URL (for production)
    if app_config.frontend_url:
        origins.append(app_config.frontend_url)
        # Also allow without trailing slash and with different protocols
        url = app_config.frontend_url.rstrip("/")
        if url not in origins:
            origins.append(url)
        # If http, also allow https variant
        if url.startswith("http://"):
            https_url = url.replace("http://", "https://", 1)
            if https_url not in origins:
                origins.append(https_url)
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    # Allow private network access: single-word hostnames and any IPv4 addresses
    allow_origin_regex=r"^(https?|capacitor)://([a-zA-Z0-9-]+|\d+\.\d+\.\d+\.\d+)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)


# Global exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic validation errors."""
    request_id = getattr(request.state, "request_id", None)
    errors = exc.errors()
    detail = "; ".join(
        f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in errors
    )
    logger.warning(f"[{request_id}] Validation error: {detail}")
    return create_error_response(
        status_code=422,
        message="Validation error",
        detail=detail,
        request_id=request_id,
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(
    request: Request, exc: SQLAlchemyError
) -> JSONResponse:
    """Handle database errors."""
    request_id = getattr(request.state, "request_id", None)
    logger.error(f"[{request_id}] Database error: {exc}", exc_info=True)
    return create_error_response(
        status_code=500,
        message="Database error",
        detail=str(exc) if app_config.debug else None,
        request_id=request_id,
    )


@app.exception_handler(FamiliarError)
async def familiar_exception_handler(
    request: Request, exc: FamiliarError
) -> JSONResponse:
    """Handle custom Familiar exceptions."""
    request_id = getattr(request.state, "request_id", None)
    # Only log 500-level errors at error level
    if exc.status_code >= 500:
        logger.error(f"[{request_id}] {exc.__class__.__name__}: {exc.message}", exc_info=True)
    else:
        logger.warning(f"[{request_id}] {exc.__class__.__name__}: {exc.message}")
    return create_error_response(
        status_code=exc.status_code,
        message=exc.message,
        detail=exc.detail,
        request_id=request_id,
    )



@app.exception_handler(HTTPException)
async def http_exception_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    """Normalize HTTPException responses to standard error envelope."""
    request_id = getattr(request.state, "request_id", None)
    if exc.status_code >= 500:
        logger.error(f"[{request_id}] HTTPException {exc.status_code}: {exc.detail}")
    else:
        logger.warning(f"[{request_id}] HTTPException {exc.status_code}: {exc.detail}")
    return create_error_response(
        status_code=exc.status_code,
        message=str(exc.detail) if exc.detail else "Request failed",
        request_id=request_id,
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions."""
    request_id = getattr(request.state, "request_id", None)
    logger.error(f"[{request_id}] Unhandled error: {exc}", exc_info=True)
    return create_error_response(
        status_code=500,
        message="Internal server error",
        detail=str(exc) if app_config.debug else None,
        request_id=request_id,
    )

# Include routers
app.include_router(health.router, prefix="/api/v1")
app.include_router(tracks.router, prefix="/api/v1")
app.include_router(library.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(videos.router, prefix="/api/v1")
app.include_router(lastfm.router, prefix="/api/v1")
app.include_router(settings_routes.router, prefix="/api/v1")
app.include_router(smart_playlists.router, prefix="/api/v1")
app.include_router(playlists.router, prefix="/api/v1")
app.include_router(mixtapes.router, prefix="/api/v1")
app.include_router(profiles.router, prefix="/api/v1")
app.include_router(favorites.router, prefix="/api/v1")
app.include_router(organizer.router, prefix="/api/v1")
app.include_router(proposed_changes.router, prefix="/api/v1")
app.include_router(bandcamp.router, prefix="/api/v1")
app.include_router(outputs.router, prefix="/api/v1")
app.include_router(artwork.router, prefix="/api/v1")
app.include_router(background.router, prefix="/api/v1")
app.include_router(diagnostics.router, prefix="/api/v1")
app.include_router(export_import.router, prefix="/api/v1")
app.include_router(s3_backup.router, prefix="/api/v1")
app.include_router(analysis.router, prefix="/api/v1")
app.include_router(download.router, prefix="/api/v1")
app.include_router(updates.router, prefix="/api/v1")
app.include_router(spotify_import.router, prefix="/api/v1")
app.include_router(ambient.router, prefix="/api/v1")
app.include_router(external_albums.router, prefix="/api/v1")
app.include_router(new_releases.router, prefix="/api/v1")
app.include_router(admin_artists.router, prefix="/api/v1")
app.include_router(pending_review.group_router, prefix="/api/v1")
app.include_router(pending_review.bulk_router, prefix="/api/v1")
app.include_router(pending_review.router, prefix="/api/v1")


# Serve frontend static files in production
# The static folder is created during Docker build
STATIC_DIR = Path(__file__).parent.parent / "static"
if STATIC_DIR.exists():
    # Serve static assets
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")
    app.mount("/icons", StaticFiles(directory=STATIC_DIR / "icons"), name="icons")

    # Serve PWA files
    @app.get("/manifest.json")
    async def manifest() -> FileResponse:
        return FileResponse(STATIC_DIR / "manifest.json")

    @app.get("/sw.js")
    async def service_worker() -> FileResponse:
        return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")

    @app.get("/registerSW.js")
    async def register_sw() -> FileResponse:
        return FileResponse(STATIC_DIR / "registerSW.js", media_type="application/javascript")

    @app.get("/workbox-{path:path}")
    async def workbox(path: str) -> FileResponse:
        return FileResponse(STATIC_DIR / f"workbox-{path}", media_type="application/javascript")

    # Serve index.html for root
    @app.get("/")
    async def serve_root() -> FileResponse:
        """Serve index.html for root path."""
        return FileResponse(STATIC_DIR / "index.html")

    # SPA fallback - serve index.html for all non-API routes
    @app.get("/{full_path:path}", response_model=None)
    async def spa_fallback(full_path: str) -> FileResponse | dict[str, Any]:
        """Serve index.html for SPA routing (catches all non-API routes)."""
        # Don't catch API or docs routes
        if full_path.startswith(("api/", "docs", "redoc", "openapi.json", "health")):
            return {"detail": "Not found"}
        return FileResponse(STATIC_DIR / "index.html")
else:
    # Development mode - just show API info
    @app.get("/")
    async def root() -> dict[str, Any]:
        """Root endpoint with API info."""
        return {
            "name": "Familiar",
            "version": "0.1.0",
            "docs": "/docs",
        }
