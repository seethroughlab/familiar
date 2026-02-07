"""App settings endpoints for user-configurable settings."""

from typing import Any

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
    spotify_client_id: str | None
    spotify_client_secret: str | None
    lastfm_api_key: str | None
    lastfm_api_secret: str | None
    anthropic_api_key: str | None
    acoustid_api_key: str | None

    # Metadata enrichment
    auto_enrich_metadata: bool
    enrich_overwrite_existing: bool

    # Analysis settings
    clap_embeddings_enabled: bool | None  # None = auto-detect
    clap_status: ClapStatus

    # External features
    external_features_enabled: bool

    # Community cache
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

    # Computed status fields
    spotify_configured: bool
    lastfm_configured: bool
    anthropic_configured: bool
    acoustid_configured: bool
    s3_backup_configured: bool
    music_library_configured: bool


class SettingsUpdateRequest(BaseModel):
    """Request to update settings."""

    # API Credentials
    spotify_client_id: str | None = None
    spotify_client_secret: str | None = None
    lastfm_api_key: str | None = None
    lastfm_api_secret: str | None = None
    anthropic_api_key: str | None = None
    acoustid_api_key: str | None = None

    # Metadata enrichment
    auto_enrich_metadata: bool | None = None
    enrich_overwrite_existing: bool | None = None

    # Analysis settings
    clap_embeddings_enabled: bool | None = None

    # External features
    external_features_enabled: bool | None = None

    # Community cache
    community_cache_enabled: bool | None = None
    community_cache_contribute: bool | None = None
    community_cache_url: str | None = None

    # Playlist generation
    playlist_discovery_mode: str | None = None  # "library_only" or "suggest_missing"

    # S3 Backup
    s3_backup_enabled: bool | None = None
    s3_backup_bucket: str | None = None
    s3_backup_region: str | None = None
    s3_backup_prefix: str | None = None
    s3_backup_schedule: str | None = None


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

    # Get CLAP status
    clap_status_data = service.get_clap_status()

    return SettingsResponse(
        **masked,
        library_status=_get_library_status(),
        clap_status=ClapStatus(**clap_status_data),
        spotify_configured=service.has_spotify_credentials(),
        lastfm_configured=service.has_lastfm_credentials(),
        anthropic_configured=service.has_anthropic_key(),
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

    masked = service.get_masked()

    # Remove fields not in the response model
    masked.pop("music_library_paths", None)
    masked.pop("s3_backup_access_key_id", None)
    masked.pop("s3_backup_secret_access_key", None)

    # Get CLAP status
    clap_status_data = service.get_clap_status()

    return SettingsResponse(
        **masked,
        library_status=_get_library_status(),
        clap_status=ClapStatus(**clap_status_data),
        spotify_configured=service.has_spotify_credentials(),
        lastfm_configured=service.has_lastfm_credentials(),
        anthropic_configured=service.has_anthropic_key(),
        acoustid_configured=service.has_acoustid_key(),
        s3_backup_configured=service.has_s3_credentials(),
        music_library_configured=service.has_music_library_configured(),
    )


@router.delete("/spotify")
async def clear_spotify_settings() -> dict[str, Any]:
    """Clear Spotify credentials."""
    service = get_app_settings_service()
    service.update(spotify_client_id="", spotify_client_secret="")
    return {"status": "cleared", "message": "Spotify credentials cleared"}


@router.delete("/lastfm")
async def clear_lastfm_settings() -> dict[str, Any]:
    """Clear Last.fm credentials."""
    service = get_app_settings_service()
    service.update(lastfm_api_key="", lastfm_api_secret="")
    return {"status": "cleared", "message": "Last.fm credentials cleared"}
