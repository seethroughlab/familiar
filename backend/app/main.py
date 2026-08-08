"""Familiar API - Main FastAPI application."""

import asyncio
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
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import SQLAlchemyError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.exceptions import FamiliarError, NotFoundError
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
    queue,
    s3_backup,
    smart_playlists,
    spotify_import,
    tracks,
    updates,
    videos,
)
from app.api.routes import settings as settings_routes
from app.api.schemas.common import error_responses
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
        response_started = False
        is_transfer = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started, is_transfer
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_started = True
                headers = list(message.get("headers", []))
                # An audio or video body takes as long as it takes to push the bytes,
                # and the client reads it at playback speed or hangs up mid-track. That
                # elapsed time is transfer, not latency — see `MetricsCollector`.
                for name, value in headers:
                    if name.lower() == b"content-type":
                        is_transfer = value.lower().startswith((b"audio/", b"video/"))
                        break
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        if skip_timing:
            await self.app(scope, receive, send_with_request_id)
            return

        from app.services.metrics import (
            OUTCOME_CLIENT_DISCONNECT,
            OUTCOME_COMPLETED,
            OUTCOME_ERROR,
            get_metrics_collector,
            get_query_count,
            reset_query_count,
        )
        reset_query_count()

        outcome = OUTCOME_COMPLETED
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_with_request_id)
        except BaseException as exc:
            # Catches `BaseException`, not `Exception`, so that `CancelledError` — which
            # is not an `Exception` — is recorded too. Without any of this, an unhandled
            # exception propagated straight past the logging below and the request was
            # never recorded at all: the log showed only successes. That is not
            # hypothetical. While diagnosing #13 the absence of non-2xx entries in this
            # very log was read as evidence the server was healthy.
            #
            # Note that a *client disconnect* does not arrive here under uvicorn: its
            # `send` silently no-ops once the socket is gone (`if self.disconnected:
            # return`), so `FileResponse` reads on to EOF and returns normally. The
            # disconnect case is handled by classifying transfers instead — see
            # `is_transfer` above.
            outcome = (
                OUTCOME_CLIENT_DISCONNECT
                if isinstance(exc, asyncio.CancelledError)
                else OUTCOME_ERROR
            )
            # Only claim a 500 if nothing was sent. A response that already delivered a
            # 206 and real bytes was not a server error.
            if not response_started:
                status_code = 500
            raise
        finally:
            # Never swallow: `CancelledError` must reach uvicorn for connection teardown,
            # and an unhandled exception must reach `ServerErrorMiddleware`, which is what
            # actually produces the 500 body.
            duration_ms = (time.perf_counter() - start) * 1000
            query_count = get_query_count()

            route = scope.get("route")
            template = route.path if route else path
            method = scope.get("method", "?")

            log_at = logger.warning if outcome == OUTCOME_ERROR else logger.info
            log_at(
                "request_completed",
                extra={
                    "method": method,
                    "route": template,
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 2),
                    "query_count": query_count,
                    "request_id": request_id,
                    "outcome": outcome,
                    "response_started": response_started,
                    "transfer": is_transfer,
                },
            )

            get_metrics_collector().record_request(
                method, template, status_code, duration_ms, query_count,
                outcome=outcome, transfer=is_transfer,
            )


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
    # Also as a header. Starlette hoists the `@app.exception_handler(Exception)` catch-all
    # into `ServerErrorMiddleware`, which sits *outside* `RequestIDMiddleware` — so the
    # 500 it emits never passes through `send_with_request_id` and would otherwise be the
    # one response with no `x-request-id` to correlate against the log.
    headers = {"x-request-id": request_id} if request_id else None
    return JSONResponse(status_code=status_code, content=content, headers=headers)


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

    # The MCP session manager must be running or every /mcp request fails at *request* time with
    # "Task group is not initialized", not at startup — so it looks like a runtime bug rather than
    # missing wiring (ADR-0043 point 1).
    async with _mcp_session_manager_running(app):
        yield

    # Shutdown
    logger.info("Shutting down Familiar API")
    await bg.shutdown()
    logger.info("Background task manager stopped")


def custom_generate_unique_id(route: APIRoute) -> str:
    """Build a short, readable operationId from the route's tag and function name.

    FastAPI's default derives the id from function name + path + method, producing
    names up to 95 characters — `get_playlist_external_albums_api_v1_playlists__
    playlist_id__recommendations_external_albums_get` — which a generated client turns
    into an unusable method name (ADR-0007).

    `{tag}_{name}` keeps them short and stable. Only three function names repeat across
    the API (`list_tracks`, `update_track_metadata`, `get_stats`) and the tag prefix
    separates all three. Uniqueness is not guaranteed by construction, so
    `scripts/lint_openapi.py` asserts it.

    Also improves auto-generated multipart body models, which FastAPI names after the
    operationId (`Body_upload_avatar_api_v1_profiles__profile_id__avatar_post`).
    """
    tag = str(route.tags[0]).lower().replace(" ", "-") if route.tags else "root"
    return f"{tag}_{route.name}"


app = FastAPI(
    title="Familiar",
    description="LLM-powered local music player API",
    version=get_app_version(),
    lifespan=lifespan,
    generate_unique_id_function=custom_generate_unique_id,
)

# MCP (ADR-0043). Mounted here rather than beside the API routers because the SPA catch-all is
# registered last and would swallow it — and asymmetrically: streamable HTTP uses POST for requests
# and GET for the server-initiated stream, so a late mount leaves POST working while GET quietly
# returns index.html. `mcp` is in NON_SPA_PREFIXES for the same reason.
from app.mcp.server import MCPDispatch  # noqa: E402
from app.mcp.server import build_asgi_app as _build_mcp_app  # noqa: E402

_mcp_asgi_app = _build_mcp_app()
app.add_middleware(MCPDispatch, mcp_app=_mcp_asgi_app)


@asynccontextmanager
async def _mcp_session_manager_running(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Run the MCP session manager for the lifetime of the app."""
    async with _mcp_asgi_app.router.lifespan_context(_mcp_asgi_app):
        yield


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

# Include routers.
#
# `DEFAULT_ERROR_RESPONSES` is attached to every router rather than to 260 individual routes
# (ADR-0007). Without it the schema documents only 200 and FastAPI's automatic 422 — and that 422
# is the wrong shape, since `validation_exception_handler` below emits the Familiar envelope
# instead. Declaring 422 explicitly replaces FastAPI's `HTTPValidationError` with the shape the
# server actually sends. Routes add their own statuses on top where one is real control flow.
DEFAULT_ERROR_RESPONSES = error_responses(400, 401, 404, 422, 500)

app.include_router(health.router, prefix="/api/v1")
app.include_router(tracks.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(library.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(chat.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(videos.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(lastfm.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(settings_routes.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(smart_playlists.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(playlists.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(mixtapes.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(profiles.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(favorites.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(organizer.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(proposed_changes.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(bandcamp.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(outputs.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(artwork.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(background.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(diagnostics.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(export_import.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(s3_backup.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(analysis.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(download.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(updates.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(spotify_import.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(ambient.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(queue.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(external_albums.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(new_releases.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(admin_artists.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(pending_review.group_router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(pending_review.bulk_router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)
app.include_router(pending_review.router, prefix="/api/v1", responses=DEFAULT_ERROR_RESPONSES)


# Serve frontend static files in production
# The static folder is created during Docker build
STATIC_DIR = Path(__file__).parent.parent / "static"

# Prefixes the single-page app must never swallow. A miss inside these belongs to the API, and the
# answer to it is a 404 rather than an HTML document.
NON_SPA_PREFIXES = ("api/", "docs", "redoc", "openapi.json", "health", "mcp")


async def serve_embed() -> FileResponse:
    """Serve the embedded surface's own document (ADR-0017).

    A second entry point, not a route inside the single-page app. The Mac app points a `WKWebView`
    here (ADR-0016 point 2), and the document it gets registers a **null audio engine** — so a play
    path the bridge fails to intercept is inert rather than a second `WebAudioEngine` competing for
    the audio session. Serving `index.html` here instead would hand the web view the full app,
    engine and all, which is the one thing this must not do.

    Defined at module scope for the reason `spa_fallback` records below: as a closure inside the
    `if STATIC_DIR.exists()` block it would be unreachable from the suite, and that is how a bug this
    visible survived once already.
    """
    embed = STATIC_DIR / "embed.html"
    if not embed.exists():
        # A server built before this existed. A typed 404 is better than a `FileResponse` for a
        # missing path, which surfaces as a 500 with a stack trace in the log and nothing useful in
        # the web view.
        raise NotFoundError("This server has no embedded surface build.")
    return FileResponse(embed)


async def spa_fallback(full_path: str) -> FileResponse:
    """Serve index.html for SPA routing (catches all non-API routes).

    **Raises rather than returns** for an unmatched API path. Returning `{"detail": "Not found"}`
    made FastAPI serialise it as a normal response body with **HTTP 200**, so every mistyped,
    renamed or unaddressable `/api/` route answered success-shaped. A generated client
    ([ADR-0007](../../docs/decisions/ADR-0007-clients-are-generated-from-openapi.md)) then failed
    while *decoding* a 200 instead of handling a typed 404, and route drift stayed invisible.

    Found while building the Apple client's artist pages: the detail endpoints are path-keyed, and
    the 79 artists whose names contain a slash produced exactly this — HTTP 200, undecodable body.

    Defined at module scope, and registered below only when `static/` exists, so it is importable by
    a test. As a closure inside that `if` it was unreachable from the suite, which is why a bug this
    visible in production survived: tests run without a static directory, where FastAPI's own 404
    applies and the handler never runs at all.
    """
    if full_path.startswith(NON_SPA_PREFIXES):
        raise NotFoundError("Not found")
    return FileResponse(STATIC_DIR / "index.html")


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

    # Registered before the catch-all below, which would otherwise swallow it and hand the web view
    # the full app.
    app.get("/embed", response_model=None)(serve_embed)

    # SPA fallback - serve index.html for all non-API routes
    app.get("/{full_path:path}", response_model=None)(spa_fallback)
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
