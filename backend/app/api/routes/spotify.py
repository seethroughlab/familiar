"""Spotify integration endpoints."""

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import delete

from app.api.deps import CurrentProfile, DbSession, RequiredProfile
from app.api.exceptions import sanitize_error_for_client
from app.db.models import SpotifyFavorite, SpotifyProfile
from app.services.spotify import SpotifyPlaylistService, SpotifyService, SpotifySyncService
from app.services.tasks import get_spotify_sync_progress

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/spotify", tags=["spotify"])


class SpotifyStatusResponse(BaseModel):
    """Spotify connection status."""
    configured: bool
    connected: bool
    spotify_user_id: str | None = None
    last_sync: str | None = None
    stats: dict[str, Any] | None = None


class SyncResponse(BaseModel):
    """Sync operation response."""
    status: str
    message: str
    stats: dict[str, Any] | None = None


class SpotifySyncProgress(BaseModel):
    """Detailed Spotify sync progress."""
    phase: str = "idle"  # "connecting", "fetching", "matching", "complete"
    tracks_fetched: int = 0
    tracks_processed: int = 0
    tracks_total: int = 0
    new_favorites: int = 0
    matched: int = 0
    unmatched: int = 0
    current_track: str | None = None
    started_at: str | None = None
    errors: list[str] = []


class SpotifySyncStatus(BaseModel):
    """Spotify sync status response."""
    status: str  # "idle", "running", "completed", "error"
    message: str
    progress: SpotifySyncProgress | None = None


class StoreSearchLink(BaseModel):
    """Search link for a music store."""
    name: str
    url: str


class UnmatchedTrack(BaseModel):
    """Unmatched Spotify track with search links."""
    spotify_id: str
    name: str | None
    artist: str | None
    album: str | None
    added_at: str | None
    search_links: dict[str, StoreSearchLink] = {}


@router.get("/status", response_model=SpotifyStatusResponse)
async def get_spotify_status(
    db: DbSession,
    profile: CurrentProfile,
) -> SpotifyStatusResponse:
    """Check Spotify connection status.

    Requires X-Profile-ID header.
    """
    spotify_service = SpotifyService()  # type: ignore[no-untyped-call]

    if not spotify_service.is_configured():
        return SpotifyStatusResponse(
            configured=False,
            connected=False,
        )

    if not profile:
        return SpotifyStatusResponse(
            configured=True,
            connected=False,
        )

    # Check if profile has connected Spotify
    sync_service = SpotifySyncService(db)
    try:
        stats = await sync_service.get_sync_stats(profile.id)
        connected = stats.get("spotify_user_id") is not None
    except Exception as e:
        logger.debug(f"Failed to get Spotify sync stats for profile {profile.id}: {e}")
        connected = False
        stats = None

    return SpotifyStatusResponse(
        configured=True,
        connected=connected,
        spotify_user_id=stats.get("spotify_user_id") if stats else None,
        last_sync=stats.get("last_sync") if stats else None,
        stats=stats,
    )


@router.get("/auth")
async def spotify_auth(profile: CurrentProfile) -> dict[str, Any]:
    """Get Spotify OAuth authorization URL.

    Requires X-Profile-ID header.
    """
    if not profile:
        raise HTTPException(
            status_code=401,
            detail="Profile ID required - register at POST /profiles/register",
        )

    spotify_service = SpotifyService()  # type: ignore[no-untyped-call]

    if not spotify_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Spotify credentials not configured. Add them in Settings.",
        )

    auth_url, state = spotify_service.get_auth_url(profile.id)

    return {
        "auth_url": auth_url,
        "state": state,
    }


@router.get("/callback")
async def spotify_callback(
    db: DbSession,
    code: str = Query(...),
    state: str = Query(...),
    error: str | None = Query(None),
) -> RedirectResponse:
    """Handle Spotify OAuth callback.

    The profile_id is encoded in the state parameter from the auth request.
    """
    # Get frontend URL from settings
    from app.config import settings
    base_url = settings.frontend_url or "http://localhost:4400"
    base_url = base_url.rstrip('/')

    if error:
        # Redirect to frontend with error
        return RedirectResponse(
            url=f"{base_url}/settings?spotify_error={error}"
        )

    spotify_service = SpotifyService()  # type: ignore[no-untyped-call]

    try:
        logger.info(f"Processing OAuth callback with state={state[:20]}...")
        spotify_profile = await spotify_service.handle_callback(db, code, state)

        # Redirect to frontend with success
        redirect_url = f"{base_url}/settings?spotify_connected=true&spotify_user={spotify_profile.spotify_user_id}"
        logger.info(f"OAuth successful, redirecting to: {redirect_url}")
        return RedirectResponse(url=redirect_url, status_code=302)
    except ValueError as e:
        # State validation failed
        logger.error(f"OAuth callback failed (invalid state): {e}")
        return RedirectResponse(
            url=f"{base_url}/settings?spotify_error=invalid_state",
            status_code=302,
        )
    except Exception as e:
        # Token exchange or other error
        logger.error(f"OAuth callback failed: {e}")
        return RedirectResponse(
            url=f"{base_url}/settings?spotify_error=auth_failed",
            status_code=302,
        )


@router.post("/sync", response_model=SpotifySyncStatus)
async def start_spotify_sync(
    profile: CurrentProfile,
    include_top_tracks: bool = Query(True),
    favorite_matched: bool = Query(False, description="Auto-favorite matched tracks in local library"),
) -> SpotifySyncStatus:
    """Start Spotify sync.

    The sync runs in the background, so this returns immediately.
    Progress is stored in Redis and can be retrieved via GET /spotify/sync/status.

    Requires X-Profile-ID header.
    """
    import asyncio

    from app.services.background import get_background_manager

    if not profile:
        raise HTTPException(
            status_code=401,
            detail="Profile ID required",
        )

    # Check if a sync is already running
    progress = get_spotify_sync_progress()
    if progress and progress.get("status") == "running":
        return SpotifySyncStatus(
            status="already_running",
            message="A sync is already in progress",
            progress=SpotifySyncProgress(**{k: progress.get(k, v) for k, v in SpotifySyncProgress().model_dump().items()}),
        )

    # Start sync in background
    bg = get_background_manager()
    asyncio.create_task(
        bg.run_spotify_sync(
            profile_id=str(profile.id),
            include_top_tracks=include_top_tracks,
            favorite_matched=favorite_matched,
        )
    )

    return SpotifySyncStatus(
        status="started",
        message="Sync started",
    )


@router.get("/sync/status", response_model=SpotifySyncStatus)
async def get_sync_status() -> SpotifySyncStatus:
    """Get current Spotify sync status with detailed progress from Redis."""
    from datetime import datetime, timedelta

    from app.services.tasks import clear_spotify_sync_progress

    progress = get_spotify_sync_progress()

    if not progress:
        return SpotifySyncStatus(
            status="idle",
            message="No sync running",
            progress=None,
        )

    # Check if the sync is stale (no heartbeat for 5 minutes)
    status = progress.get("status", "idle")
    if status == "running":
        last_heartbeat = progress.get("last_heartbeat")
        if last_heartbeat:
            try:
                heartbeat_time = datetime.fromisoformat(last_heartbeat)
                if datetime.now() - heartbeat_time > timedelta(minutes=5):
                    # Sync is stale - worker probably died
                    clear_spotify_sync_progress()
                    return SpotifySyncStatus(
                        status="interrupted",
                        message="Sync was interrupted (worker stopped responding)",
                        progress=None,
                    )
            except (ValueError, TypeError):
                pass

    # Convert Redis progress to SpotifySyncProgress model
    sync_progress = SpotifySyncProgress(
        phase=progress.get("phase", "idle"),
        tracks_fetched=progress.get("tracks_fetched", 0),
        tracks_processed=progress.get("tracks_processed", 0),
        tracks_total=progress.get("tracks_total", 0),
        new_favorites=progress.get("new_favorites", 0),
        matched=progress.get("matched", 0),
        unmatched=progress.get("unmatched", 0),
        current_track=progress.get("current_track"),
        started_at=progress.get("started_at"),
        errors=progress.get("errors", []),
    )

    return SpotifySyncStatus(
        status=status,
        message=progress.get("message", ""),
        progress=sync_progress if status != "idle" else None,
    )


@router.get("/unmatched", response_model=list[UnmatchedTrack])
async def get_unmatched_tracks(
    db: DbSession,
    profile: CurrentProfile,
    limit: int = Query(50, ge=1, le=200),
    sort_by: str = Query("added_at", enum=["added_at"]),
) -> list[UnmatchedTrack]:
    """Get Spotify favorites that don't have local matches.

    Requires X-Profile-ID header.
    Sorted by date added (most recent first).
    Includes search links for Bandcamp, Discogs, Qobuz, etc.
    """
    if not profile:
        raise HTTPException(
            status_code=401,
            detail="Profile ID required",
        )

    from app.services.search_links import generate_search_urls

    sync_service = SpotifySyncService(db)

    try:
        unmatched = await sync_service.get_unmatched_favorites(profile.id, limit)

        # Generate search links and sort by preference
        result = []
        for track in unmatched:
            artist = track.get("artist") or "Unknown Artist"
            name = track.get("name") or "Unknown Track"
            album = track.get("album")

            # Generate search links for all stores
            links = generate_search_urls(artist, name, album)
            search_links = {
                key: StoreSearchLink(name=val["name"], url=val["url"])
                for key, val in links.items()
            }

            result.append(UnmatchedTrack(
                spotify_id=track["spotify_id"],
                name=name,
                artist=artist,
                album=album,
                added_at=track.get("added_at"),
                search_links=search_links,
            ))

        # Sort by date added (most recent first)
        result.sort(key=lambda t: t.added_at or "", reverse=True)

        return result
    except Exception:
        logger.exception("Error retrieving unmatched tracks")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve unmatched tracks",
        )


@router.post("/disconnect")
async def disconnect_spotify(
    db: DbSession,
    profile: CurrentProfile,
) -> dict[str, Any]:
    """Disconnect Spotify account.

    Requires X-Profile-ID header.
    """
    if not profile:
        raise HTTPException(
            status_code=401,
            detail="Profile ID required",
        )

    # Delete favorites first (foreign key)
    await db.execute(
        delete(SpotifyFavorite).where(SpotifyFavorite.profile_id == profile.id)
    )

    # Delete Spotify profile
    await db.execute(
        delete(SpotifyProfile).where(SpotifyProfile.profile_id == profile.id)
    )

    await db.commit()

    return {"status": "disconnected"}


# ============================================================================
# Spotify Playlist Import
# ============================================================================


class SpotifyPlaylistInfo(BaseModel):
    """Spotify playlist information."""

    id: str
    name: str
    description: str | None
    track_count: int
    image_url: str | None
    external_url: str | None
    owner: str | None
    public: bool | None


class SpotifyPlaylistTrack(BaseModel):
    """Track from a Spotify playlist."""

    spotify_id: str
    title: str
    artist: str | None
    album: str | None
    duration_ms: int | None
    in_library: bool
    local_track_id: str | None


class SpotifyPlaylistTracksResponse(BaseModel):
    """Response for Spotify playlist tracks."""

    playlist_name: str
    playlist_description: str | None
    tracks: list[SpotifyPlaylistTrack]
    total: int
    in_library: int
    missing: int
    match_rate: str


class PlaylistImportRequest(BaseModel):
    """Request to import a Spotify playlist."""

    name: str | None = None
    description: str | None = None
    include_missing: bool = True


class ImportedPlaylistResponse(BaseModel):
    """Response for imported playlist."""

    id: str
    name: str
    description: str | None
    track_count: int


@router.get("/playlists", response_model=list[SpotifyPlaylistInfo])
async def list_spotify_playlists(
    db: DbSession,
    profile: RequiredProfile,
    limit: int = Query(50, ge=1, le=100),
) -> list[SpotifyPlaylistInfo]:
    """List user's Spotify playlists.

    Returns playlists available for import with track counts.
    Requires Spotify to be connected.
    """
    service = SpotifyPlaylistService(db)

    try:
        playlists = await service.list_playlists(profile.id, limit=limit)
        return [SpotifyPlaylistInfo(**p) for p in playlists]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=sanitize_error_for_client(e, "Invalid playlist request"))
    except Exception as e:
        logger.error(f"Error listing Spotify playlists: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch playlists")


@router.get(
    "/playlists/{spotify_playlist_id}/tracks",
    response_model=SpotifyPlaylistTracksResponse,
)
async def get_spotify_playlist_tracks(
    spotify_playlist_id: str,
    db: DbSession,
    profile: RequiredProfile,
    limit: int = Query(100, ge=1, le=200),
) -> SpotifyPlaylistTracksResponse:
    """Get tracks from a Spotify playlist with local match info.

    Shows which tracks exist locally vs missing.
    Use this to preview before importing.
    """
    service = SpotifyPlaylistService(db)

    try:
        result = await service.get_playlist_tracks(
            profile.id,
            spotify_playlist_id,
            limit=limit,
        )
        return SpotifyPlaylistTracksResponse(
            playlist_name=result["playlist_name"],
            playlist_description=result.get("playlist_description"),
            tracks=[SpotifyPlaylistTrack(**t) for t in result["tracks"]],
            total=result["total"],
            in_library=result["in_library"],
            missing=result["missing"],
            match_rate=result["match_rate"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=sanitize_error_for_client(e, "Invalid playlist request"))
    except Exception as e:
        logger.error(f"Error getting Spotify playlist tracks: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch playlist tracks")


@router.post(
    "/playlists/{spotify_playlist_id}/import",
    response_model=ImportedPlaylistResponse,
)
async def import_spotify_playlist(
    spotify_playlist_id: str,
    db: DbSession,
    profile: RequiredProfile,
    request: PlaylistImportRequest | None = None,
) -> ImportedPlaylistResponse:
    """Import a Spotify playlist to Familiar.

    Creates a local playlist with:
    - Matched local tracks (playable immediately)
    - External track placeholders for missing tracks

    Set include_missing=false to only import tracks that exist locally.
    """
    service = SpotifyPlaylistService(db)

    try:
        req = request or PlaylistImportRequest()
        playlist = await service.import_playlist(
            profile_id=profile.id,
            spotify_playlist_id=spotify_playlist_id,
            name=req.name,
            description=req.description,
            include_missing=req.include_missing,
        )

        # Get track count
        from sqlalchemy import func, select

        from app.db.models import PlaylistTrack
        count_result = await db.execute(
            select(func.count(PlaylistTrack.id)).where(
                PlaylistTrack.playlist_id == playlist.id
            )
        )
        track_count = count_result.scalar() or 0

        return ImportedPlaylistResponse(
            id=str(playlist.id),
            name=playlist.name,
            description=playlist.description,
            track_count=track_count,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=sanitize_error_for_client(e, "Invalid import request"))
    except Exception as e:
        logger.error(f"Error importing Spotify playlist: {e}")
        raise HTTPException(status_code=500, detail="Failed to import playlist")


# ============================================================================
# Spotify Data Export Import
# ============================================================================


class SpotifyExportImportOptions(BaseModel):
    """Options for executing a Spotify export import."""
    import_favorites: bool = True
    import_playlists: bool = True
    favorite_matched: bool = False


@router.post("/import/upload")
async def upload_spotify_export(
    file: UploadFile,
    db: DbSession,
    profile: RequiredProfile,
) -> dict[str, Any]:
    """Upload a Spotify data export file (zip or JSON).

    Accepts:
    - .zip files from Spotify's "Download your data" feature
    - Individual .json files (YourLibrary.json, Playlist*.json, Streaming_History_Audio_*.json)

    Returns a session_id and preview summary.
    Max file size: 50MB.
    """
    from app.services.spotify_import import (
        SpotifyExportImporter,
        SpotifyExportParser,
        save_upload_to_temp,
    )

    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    filename = file.filename.lower()
    if not (filename.endswith(".zip") or filename.endswith(".json")):
        raise HTTPException(
            status_code=400,
            detail="File must be a .zip or .json file",
        )

    # Read file content (limit to 50MB)
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 50MB)")

    try:
        if filename.endswith(".zip"):
            suffix = ".zip"
        else:
            suffix = ".json"

        temp_path = save_upload_to_temp(content, suffix)

        try:
            # Parse the file
            if filename.endswith(".zip"):
                parsed_data = SpotifyExportParser.parse_zip(temp_path)
            else:
                parsed_data = SpotifyExportParser.parse_json_file(
                    temp_path, file.filename or ""
                )

            if not any([
                parsed_data.get("library_tracks"),
                parsed_data.get("playlists"),
                parsed_data.get("streaming_history"),
            ]):
                raise HTTPException(
                    status_code=400,
                    detail="No recognizable Spotify data found in file",
                )

            # Create preview session
            importer = SpotifyExportImporter(db)
            session_id, summary = await importer.create_preview_session(
                parsed_data, str(profile.id)
            )

            return summary
        finally:
            # Clean up temp file
            os.unlink(temp_path)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing Spotify export: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to process Spotify export file",
        )


@router.get("/import/preview/{session_id}")
async def get_spotify_import_preview(
    session_id: str,
    db: DbSession,
    profile: RequiredProfile,
) -> dict[str, Any]:
    """Get detailed preview for a Spotify export import session.

    Returns matched and unmatched tracks, playlist details.
    """
    from app.services.spotify_import import SpotifyExportImporter

    importer = SpotifyExportImporter(db)

    try:
        return await importer.get_preview(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/import/execute/{session_id}")
async def execute_spotify_import(
    session_id: str,
    db: DbSession,
    profile: RequiredProfile,
    options: SpotifyExportImportOptions | None = None,
) -> dict[str, Any]:
    """Execute a Spotify export import from a previewed session.

    Options control what gets imported:
    - import_favorites: Create SpotifyFavorite records for library tracks
    - import_playlists: Create playlists from export playlists
    - favorite_matched: Add matched tracks to local favorites
    """
    from app.services.spotify_import import SpotifyExportImporter

    importer = SpotifyExportImporter(db)
    opts = options or SpotifyExportImportOptions()

    try:
        return await importer.execute_import(session_id, opts.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error executing Spotify import: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to execute import",
        )
