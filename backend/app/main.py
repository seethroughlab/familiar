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
from app.api.routes import api_router
from app.api.routes.compat import DeprecatedPathHeaders
from app.config import AUDIO_EXTENSIONS, MUSIC_LIBRARY_PATH, get_app_version
from app.config import settings as app_config
from app.logging_config import get_logger, setup_logging

# Configure structured logging
setup_logging()
logger = get_logger(__name__)


# Pure ASGI middleware for request ID + timing (avoids BaseHTTPMiddleware event-loop issues)
class RequestIDMiddleware:
    """Add unique request ID and request timing to each request."""

    _SKIP_TIMING_PREFIXES = ("/health", "/assets/", "/icons/", "/sw.js")

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


# ── The published index (ADR-0072 point 5) ────────────────────────────────────────────────────
#
# A newcomer's first read of this API should be the list of functional areas, not 249 operations
# in alphabetical order. `openapi_tags` gives every tag an ordered position and a description;
# `x-tagGroups` (added in `_openapi_with_global_security` below) gathers them into the seven areas
# the product actually has. `/redoc` renders both and always could — `main.py` simply set neither.
#
# The order here is the order they render in. It runs from what a listener touches to what an
# operator touches, which is also roughly most-used to least.
#
# **Every tag appears exactly once, and in exactly one group.** `scripts/lint_openapi.py` asserts
# it, because a tag added without a description silently renders as a bare heading, which is the
# failure this whole point exists to prevent.
OPENAPI_TAGS = [
    # Music — the collection itself.
    {"name": "library", "description":
        "The collection as a whole: artists, albums, aggregations, sync, import, duplicates and "
        "the map. The largest tag in the API, and deliberately whole — ADR-0007 point 2 accepted "
        "dead generated code rather than split it, and ADR-0073 is the proposal that revisits."},
    {"name": "map", "description":
        "The music map — 2D, 3D, ego-centric, and the SSE streams that report build progress. "
        "A view of the library rather than a way to change it."},
    {"name": "ingest", "description":
        "Getting music into the library and keeping it there: sync, import, and the missing-file "
        "reconciliation that follows when something moves on disk."},
    {"name": "duplicates", "description":
        "Duplicate detection. Preview only — no route merges or deletes anything."},
    {"name": "tracks", "description":
        "Individual tracks as things to play: listing, detail, streaming, artwork and lyrics. "
        "What a track *is*; what happens to it is `plays`, `metadata` or `discover`."},
    {"name": "plays", "description":
        "Listening events — started, played, skipped, rejected, playback errors — and the "
        "aggregate they feed. ADR-0004's event stream; the paths stay on the track, because the "
        "event genuinely belongs to it (ADR-0072 point 4)."},
    {"name": "metadata", "description":
        "Reading and editing track tags, one at a time or in bulk, plus external lookup."},
    {"name": "identification", "description":
        "Acoustic fingerprinting to work out what an unidentified file actually is."},
    {"name": "discover", "description":
        "Finding music to play from what is already here: the discover dashboard, similar tracks, "
        "per-track discovery, and new releases by artists in the library."},
    {"name": "visualizers", "description":
        "Per-track visualizer ranking (ADR-0064). One operation, and it earns its own tag: it is "
        "the only thing the embedded visualizer surface calls on its own behalf."},
    {"name": "analysis", "description":
        "Audio analysis — features, embeddings and melodic data — over one track or the whole "
        "library. Re-analysis happens only during a library sync; nothing is scheduled."},
    {"name": "artwork", "description":
        "Album and artist images: lookup, caching, regeneration and coverage reporting."},

    # Collections — the ways a listener groups music.
    {"name": "playlists", "description": "Hand-made playlists and their tracks."},
    {"name": "smart-playlists", "description":
        "Rule-driven playlists, evaluated server-side so every client sees the same result."},
    {"name": "mixtapes", "description":
        "Generated sequences with a stated shape, kept distinct from playlists because they are "
        "authored by the server rather than by hand."},
    {"name": "favorites", "description": "Per-profile favourites."},

    # Playback — what is playing, and where.
    {"name": "playback-session", "description":
        "The durable playback session — the queue a listener left behind, so another device can "
        "pick it up (ADR-0003, ADR-0028). The queue itself is a client concept; what the server "
        "keeps is the session, which is why neither this tag nor its path says \"queue\"."},
    {"name": "radio", "description":
        "What to play next: tracks ranked for this profile's taste and skip history, to slip into "
        "a queue already playing (ADR-0005)."},
    {"name": "offline", "description":
        "The precomputed offline ranking manifest (ADR-0006), so a client can rank without "
        "carrying a scorer."},
    {"name": "playback", "description":
        "Transport state reported by a client, so other surfaces can show what is playing."},
    {"name": "outputs", "description":
        "Network audio devices — Sonos, UPnP/DLNA, AirPlay, Chromecast — and casting to them "
        "(ADR-0031). Zone grouping was removed by ADR-0077."},
    {"name": "videos", "description":
        "Music videos as a way of playing a track, not as a visualizer (ADR-0085, ADR-0086)."},

    # Discovery — finding something that is not already in the collection.
    {"name": "lastfm", "description": "Last.fm scrobbling and the metadata it supplies."},
    {"name": "new-releases", "description": "New releases by artists in the library."},
    {"name": "external-albums", "description":
        "Albums found outside the library, offered as things to acquire."},

    # Curation — deciding what the collection should become.
    {"name": "pending-review", "description":
        "Tracks awaiting a decision before they enter the library, in groups and in bulk."},
    {"name": "proposed-changes", "description":
        "Metadata changes proposed by analysis or by the LLM tools, awaiting approval."},
    {"name": "organizer", "description":
        "File-organisation previews. Preview only: no route moves a file, so there is nothing to "
        "apply. Renamed from `Library Organization` by ADR-0072 point 3."},
    {"name": "artists", "description":
        "Artist-merge operations, named for what they act on. Was `admin`, a name promising a "
        "namespace two-thirds of this API would qualify for and only these three used. The "
        "`/admin/artists/` prefix has not moved with the tag — that needs ADR-0079's alias module, "
        "which is accepted and unbuilt."},

    # Transfer and backup — getting data out, and back.
    {"name": "backup", "description":
        "Durability — scheduled backup to S3-compatible storage, and restore from it. Paths stay "
        "under `/s3-backup/`; the tag names the activity, not the storage backend (ADR-0076)."},
    {"name": "transfer", "description":
        "Portability — moving a profile or a library between servers. The line against `backup` is "
        "durability versus portability, which is the line a user is already on when choosing a "
        "screen."},
    {"name": "exports", "description":
        "ZIP exports of playlists, track sets and analysis reports. Was `download`, which named a "
        "transport rather than what the operations produce."},

    # Server — operating the thing.
    {"name": "profiles", "description":
        "Listener profiles. Familiar has no traditional auth; the profile id in the request header "
        "is what scopes taste, history and favourites."},
    {"name": "auth", "description": "Server-token administration (ADR-0045)."},
    {"name": "settings", "description":
        "Server configuration — library paths, API keys, provider choice."},
    {"name": "system", "description":
        "The state of the running server: liveness, database and worker health, logs, metrics, "
        "background jobs and update checks. Four tags merged here under ADR-0076 — the paths did "
        "not move with them, because each already names its resource honestly (ADR-0072 point 4). "
        "`GET /api/v1/health` in particular is a container probe and stays where it is forever."},
]

# The seven areas, in render order. Point 5 says the areas are published rather than implied; this
# is where they are stated. ADR-0073, ADR-0074 and ADR-0076 all move tags between these, so expect
# to edit this list when they land — that is the intended cost, and it is cheap.
OPENAPI_TAG_GROUPS = [
    {"name": "Music", "tags": ["library", "tracks", "map", "analysis", "artwork"]},
    {"name": "Collections", "tags": ["playlists", "smart-playlists", "mixtapes", "favorites"]},
    {"name": "Playback", "tags": [
        "playback-session", "radio", "offline", "playback", "plays", "outputs", "videos",
        "visualizers"]},
    {"name": "Discovery", "tags": ["discover", "lastfm", "new-releases", "external-albums"]},
    {"name": "Curation", "tags": [
        "ingest", "metadata", "identification", "duplicates",
        "pending-review", "proposed-changes", "organizer", "artists"]},
    {"name": "Transfer and backup", "tags": ["backup", "transfer", "exports"]},
    {"name": "Server", "tags": ["profiles", "auth", "settings", "system"]},
]


app = FastAPI(
    title="Familiar",
    description="LLM-powered local music player API",
    version=get_app_version(),
    lifespan=lifespan,
    generate_unique_id_function=custom_generate_unique_id,
    openapi_tags=OPENAPI_TAGS,
)

# MCP (ADR-0043). Mounted here rather than beside the API routers because the SPA catch-all is
# registered last and would swallow it — and asymmetrically: streamable HTTP uses POST for requests
# and GET for the server-initiated stream, so a late mount leaves POST working while GET quietly
# returns index.html. `mcp` is in NON_SPA_PREFIXES for the same reason.
from app.mcp.server import MCPDispatch  # noqa: E402
from app.mcp.server import build_asgi_app as _build_mcp_app  # noqa: E402

_mcp_asgi_app = _build_mcp_app()
app.add_middleware(MCPDispatch, mcp_app=_mcp_asgi_app)

# Inbound authentication (ADR-0045 point 1).
#
# **The position in this file is the whole design.** `add_middleware` prepends, so the *last* one
# added is the outermost. Adding this immediately after `MCPDispatch` and before `RequestIDMiddleware`
# and CORS puts it:
#   - *inside* CORS, so a preflight is answered with CORS headers rather than an opaque 401;
#   - *inside* `RequestIDMiddleware`, so a refusal carries the `x-request-id` that correlates it;
#   - *outside* `MCPDispatch`, which is the load-bearing one — `MCPDispatch` answers `/mcp` before
#     the router is ever reached, so a router dependency would protect all 264 REST operations and
#     leave the MCP endpoint, the one ADR-0043 exists to expose, as the only open door.
#
# It is inert until a token is configured; see `TokenAuthMiddleware`.
from app.api.auth import TokenAuthMiddleware  # noqa: E402

app.add_middleware(TokenAuthMiddleware)


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

# Include routers — every one of them, in a single call (ADR-0072 point 6). The list lives in
# `app/api/routes/__init__.py`; see that module for why it is there and which part of its order is
# load-bearing.
#
# `DEFAULT_ERROR_RESPONSES` is attached to the aggregate router rather than to 249 individual
# routes (ADR-0007). Without it the schema documents only 200 and FastAPI's automatic 422 — and
# that 422 is the wrong shape, since `validation_exception_handler` below emits the Familiar
# envelope instead. Declaring 422 explicitly replaces FastAPI's `HTTPValidationError` with the
# shape the server actually sends. Routes add their own statuses on top where one is real control
# flow.
app.include_router(api_router, prefix="/api/v1")

# Moved paths announce themselves (ADR-0079 point 3). Registered as middleware rather than as a
# route dependency because the headers must survive an error response — see the class docstring.
app.add_middleware(DeprecatedPathHeaders)


def _openapi_with_global_security() -> dict[str, Any]:
    """Publish the server token as a global security requirement (ADR-0045 point 2).

    Point 2 says *"every operation carries a security requirement, and the allowlist goes to zero"*,
    and cites 158 operations with none. That number is real — it is 160 today, having grown by two
    since the ADR was written, which is the ADR's own argument about permanent allowlists making
    itself. But the count conflates two axes that this codebase keeps separate:

    - **Authentication** — does the caller hold the server token? That is not a property of an
      individual operation here. `TokenAuthMiddleware` gates every `/api/` path and `/mcp` at once,
      so the honest OpenAPI expression is a *global* `security` block, which the spec has never had
      (`security` was absent entirely). One block covers all 264.
    - **Profile scoping** — which profile may a request act as? That is per-operation, it is what
      `lint_profile_contracts.py`'s 30-module allowlist tracks, and it is the genuinely large half
      of point 2. It is untouched here and is a later phase.

    Conflating them would let this look finished while the second half had not started, so the two
    are separated deliberately rather than quietly.
    """
    if app.openapi_schema:
        return app.openapi_schema

    from fastapi.openapi.utils import get_openapi

    from app.api.auth import TOKEN_HEADER

    # `tags=` must be passed explicitly. `get_openapi` does not read it off the app, so the
    # `openapi_tags` given to `FastAPI(...)` is silently dropped by any custom `openapi` hook that
    # forgets it — the descriptions render as nothing and no error is raised anywhere.
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
    )
    components = schema.setdefault("components", {})
    schemes = components.setdefault("securitySchemes", {})
    schemes["FamiliarToken"] = {
        "type": "apiKey",
        "in": "header",
        "name": TOKEN_HEADER,
        "description": (
            "Server token (ADR-0045). Issue one at POST /api/v1/auth/token. When no token is "
            "configured the server accepts unauthenticated requests, so generated clients must "
            "treat this as optional-but-expected rather than required."
        ),
    }
    # Applies to every operation, including the ones that declare `ProfileHeader`: the two are
    # different questions, and an operation can require both.
    schema["security"] = [{"FamiliarToken": []}]

    # The functional areas, grouped (ADR-0072 point 5). `x-tagGroups` is a ReDoc extension rather
    # than core OpenAPI, which is why it is set here instead of on the `FastAPI(...)` call — there
    # is no constructor argument for it. `/redoc` renders it as the left-hand navigation; a
    # generator that does not understand the key ignores it, which is the intended failure mode.
    schema["x-tagGroups"] = OPENAPI_TAG_GROUPS

    app.openapi_schema = schema
    return schema


app.openapi = _openapi_with_global_security  # type: ignore[method-assign]


# Serve frontend static files in production
# The static folder is created during Docker build
STATIC_DIR = Path(__file__).parent.parent / "static"

# Prefixes the single-page app must never swallow. A miss inside these belongs to the API, and the
# answer to it is a 404 rather than an HTML document.
NON_SPA_PREFIXES = (
    "api/",
    "docs",
    "redoc",
    "openapi.json",
    "health",
    "mcp",
    # An MCP host probes these before connecting, to find out whether the server has an
    # authorisation server. **A 404 is the answer that means "no, connect anonymously."** Served by
    # the SPA they returned `200 text/html`, which reads as "yes, here it is" — so Claude Desktop
    # tried to register a client against an HTML page and reported *"Couldn't register with
    # Familiar's sign-in service"*, which points at authentication rather than at this line.
    ".well-known",
    # An MCP host probes these before connecting, to find out whether the server has an
    # authorisation server. **A 404 is the answer that means "no, connect anonymously."** Served by
    # the SPA they returned `200 text/html`, which reads as "yes, here it is" — so Claude Desktop
    # tried to register a client against an HTML page and reported *"Couldn't register with
    # Familiar's sign-in service"*, which points at authentication rather than at this line.
)


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
    # The served path, not the route template. `request_completed` logs `/{full_path:path}` for
    # everything that lands here, which is useless precisely when it matters: an MCP host probing
    # for an authorisation server gets `index.html` with a 200, reads it as "yes, here it is", and
    # reports a sign-in failure that names nothing about routing.
    logger.info("spa_fallback_served", extra={"path": full_path})
    return FileResponse(STATIC_DIR / "index.html")


if STATIC_DIR.exists():
    # Serve static assets
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")
    app.mount("/icons", StaticFiles(directory=STATIC_DIR / "icons"), name="icons")


    # The PWA is retired (ADR-0059) — no manifest, no `registerSW.js`, no `workbox-*` chunks.
    #
    # `/sw.js` stays, and must. It now serves a tombstone worker whose whole job is to unregister
    # the Workbox worker earlier versions installed. Letting this 404 would fall through to the SPA
    # catch-all and answer with `index.html`, and a browser told its service worker is now an HTML
    # document behaves less predictably than one handed a script that removes itself. See
    # `packages/web/public/sw.js`.
    @app.get("/sw.js")
    async def service_worker() -> FileResponse:
        return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")

    # Serve index.html for root
    @app.get("/")
    async def serve_root() -> FileResponse:
        """Serve index.html for root path."""
        return FileResponse(STATIC_DIR / "index.html")

    # Registered before the catch-all below, which would otherwise swallow them and hand the web
    # view the full app.
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
