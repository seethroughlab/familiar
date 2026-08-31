"""App settings endpoints for user-configurable settings."""

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import AUDIO_EXTENSIONS, MUSIC_LIBRARY_PATH
from app.services.app_settings import get_app_settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


class ClapStatus(BaseModel):
    """CLAP embeddings status details."""

    enabled: bool
    reason: str
    ram_gb: float | None
    ram_sufficient: bool
    env_override: bool
    explicit_setting: bool | None


class LibraryStatus(BaseModel):
    """Library mount status details."""

    path: str
    exists: bool
    readable: bool
    audio_file_count: int | None = None
    error: str | None = None


class SettingsResponse(BaseModel):
    """Settings response with masked secrets."""

    # Music Library (fixed at /music, configured via docker-compose)
    library_status: LibraryStatus

    # API Credentials
    lastfm_api_key: str | None
    lastfm_api_secret: str | None
    acoustid_api_key: str | None


    # Analysis settings
    clap_embeddings_enabled: bool | None  # None = auto-detect
    clap_status: ClapStatus

    # External features
    external_features_enabled: bool

    # Server-owned playback queue (ADR-0003). A rollout gate rather than a preference:
    # clients also opt in per device, and this rejects session traffic when off.
    queue_sync_enabled: bool

    # Community cache
    discovery_enabled: bool
    discovery_musicbrainz_enabled: bool
    discovery_listenbrainz_enabled: bool
    community_cache_enabled: bool
    community_cache_contribute: bool
    community_cache_url: str

    # Playlist generation
    playlist_discovery_mode: str  # "library_only" or "suggest_missing"

    # S3 Backup
    s3_backup_enabled: bool
    s3_backup_bucket: str | None
    s3_backup_region: str
    s3_backup_prefix: str
    s3_backup_schedule: str

    # Update notifications
    update_channel: str

    # Computed status fields
    lastfm_configured: bool
    acoustid_configured: bool
    s3_backup_configured: bool
    music_library_configured: bool


class SettingsUpdateRequest(BaseModel):
    """Request to update settings."""

    # API Credentials
    lastfm_api_key: str | None = None
    lastfm_api_secret: str | None = None
    acoustid_api_key: str | None = None


    # Analysis settings
    clap_embeddings_enabled: bool | None = None

    # External features
    external_features_enabled: bool | None = None

    # Server-owned playback queue (ADR-0003)
    queue_sync_enabled: bool | None = None

    # Community cache
    discovery_enabled: bool | None = None
    discovery_musicbrainz_enabled: bool | None = None
    discovery_listenbrainz_enabled: bool | None = None
    community_cache_enabled: bool | None = None
    community_cache_contribute: bool | None = None
    community_cache_url: str | None = None

    # Playlist generation
    playlist_discovery_mode: str | None = None  # "library_only" or "suggest_missing"

    # S3 Backup
    s3_backup_enabled: bool | None = None
    s3_backup_schedule: str | None = None

    # Update notifications
    update_channel: str | None = None

    # Network audio outputs — LAN base URL devices use to fetch the stream
    device_stream_base_url: str | None = None


def _get_library_status() -> LibraryStatus:
    """Get current library mount status."""
    path = MUSIC_LIBRARY_PATH
    exists = path.exists()
    readable = False
    audio_count = None
    error = None

    if not exists:
        error = "Library path not mounted. Configure MUSIC_LIBRARY_PATH in docker-compose.yml"
    elif not path.is_dir():
        error = "Path exists but is not a directory"
    else:
        try:
            # Check if readable by listing directory
            list(path.iterdir())
            readable = True
            # Count audio files (quick scan, max 10000 to avoid timeout)
            count = 0
            for ext in AUDIO_EXTENSIONS:
                for _ in path.rglob(f"*{ext}"):
                    count += 1
                    if count >= 10000:
                        break
                if count >= 10000:
                    break
            audio_count = count
        except PermissionError:
            error = "Permission denied - cannot read directory"

    return LibraryStatus(
        path=str(path),
        exists=exists,
        readable=readable,
        audio_file_count=audio_count,
        error=error,
    )


@router.get("", response_model=SettingsResponse)
async def get_settings() -> SettingsResponse:
    """Get current app settings (secrets are masked)."""
    service = get_app_settings_service()
    masked = service.get_masked()

    # Remove fields not in the response model
    masked.pop("music_library_paths", None)
    masked.pop("s3_backup_access_key_id", None)
    masked.pop("s3_backup_secret_access_key", None)

    # Use effective values for S3 bucket/region/prefix (env var fallback)
    masked["s3_backup_bucket"] = service.get_effective("s3_backup_bucket")
    masked["s3_backup_region"] = service.get_effective("s3_backup_region") or "us-east-1"
    masked["s3_backup_prefix"] = service.get_effective("s3_backup_prefix") or ""

    # Get CLAP status
    clap_status_data = service.get_clap_status()

    return SettingsResponse(
        **masked,
        library_status=await asyncio.to_thread(_get_library_status),
        clap_status=ClapStatus(**clap_status_data),
        lastfm_configured=service.has_lastfm_credentials(),
        acoustid_configured=service.has_acoustid_key(),
        s3_backup_configured=service.has_s3_credentials(),
        music_library_configured=service.has_music_library_configured(),
    )


@router.put("", response_model=SettingsResponse)
async def update_settings(request: SettingsUpdateRequest) -> SettingsResponse:
    """Update app settings."""
    service = get_app_settings_service()

    # Filter out None values (only update provided fields)
    # Note: clap_embeddings_enabled can be explicitly set to None to reset to auto
    updates = {}
    for k, v in request.model_dump().items():
        if k == "clap_embeddings_enabled":
            # Allow explicit None to reset to auto-detect
            if request.clap_embeddings_enabled is not None or "clap_embeddings_enabled" in request.model_fields_set:
                updates[k] = v
        elif v is not None:
            updates[k] = v

    service.update(**updates)

    # Re-register S3 backup schedule if relevant settings changed
    s3_schedule_keys = {"s3_backup_enabled", "s3_backup_schedule"}
    if s3_schedule_keys & updates.keys():
        from app.services.background import get_background_manager

        get_background_manager()._register_s3_backup_schedule()

    masked = service.get_masked()

    # Remove fields not in the response model
    masked.pop("music_library_paths", None)
    masked.pop("s3_backup_access_key_id", None)
    masked.pop("s3_backup_secret_access_key", None)

    # Use effective values for S3 bucket/region/prefix (env var fallback)
    masked["s3_backup_bucket"] = service.get_effective("s3_backup_bucket")
    masked["s3_backup_region"] = service.get_effective("s3_backup_region") or "us-east-1"
    masked["s3_backup_prefix"] = service.get_effective("s3_backup_prefix") or ""

    # Get CLAP status
    clap_status_data = service.get_clap_status()

    return SettingsResponse(
        **masked,
        library_status=await asyncio.to_thread(_get_library_status),
        clap_status=ClapStatus(**clap_status_data),
        lastfm_configured=service.has_lastfm_credentials(),
        acoustid_configured=service.has_acoustid_key(),
        s3_backup_configured=service.has_s3_credentials(),
        music_library_configured=service.has_music_library_configured(),
    )


class ClearSettingsResponse(BaseModel):
    status: str
    message: str


@router.delete("/lastfm", response_model=ClearSettingsResponse)
async def clear_lastfm_settings() -> ClearSettingsResponse:
    """Clear Last.fm credentials."""
    service = get_app_settings_service()
    service.update(lastfm_api_key="", lastfm_api_secret="")
    return ClearSettingsResponse(status="cleared", message="Last.fm credentials cleared")
