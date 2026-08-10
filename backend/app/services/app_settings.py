"""App settings service for user-configurable settings stored in a JSON file.

Configuration Precedence
========================
Settings can come from multiple sources. The precedence (highest to lowest) is:

1. **AppSettings (settings.json)** - User-configured via admin UI
2. **Environment variables** - Set in docker-compose or .env
3. **Defaults** - Hardcoded fallbacks

Use `get_app_settings_service().get_effective()` to get the resolved value
for any setting with proper precedence applied.

Settings by Source
------------------
**Admin UI only (settings.json)**:
- music_library_paths

**Admin UI with env fallback**:
- lastfm_api_key, lastfm_api_secret, acoustid_api_key
- s3_backup_access_key_id, s3_backup_secret_access_key
- s3_backup_bucket, s3_backup_region, s3_backup_prefix

**Environment only (infrastructure)**:
- database_url, redis_url, frontend_url
- art_path, videos_path, profiles_path
"""

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


class AppSettings(BaseModel):
    """User-configurable app settings."""

    # Music Library (deprecated - now configured via docker-compose volume mount)
    # Kept for backwards compatibility with existing settings.json files
    music_library_paths: list[str] = []

    # Last.fm
    lastfm_api_key: str | None = None
    lastfm_api_secret: str | None = None

    # Audio fingerprinting
    acoustid_api_key: str | None = None  # Get free key at https://acoustid.org/new-application

    # Analysis settings
    clap_embeddings_enabled: bool | None = None  # None = auto-detect based on RAM (6GB+ required)

    # External feature lookup (skip local librosa analysis when possible)
    external_features_enabled: bool = True  # Look up features from external services

    # Community embedding cache (share CLAP embeddings with other users)
    community_cache_enabled: bool = True  # Look up embeddings from community cache
    community_cache_contribute: bool = False  # Contribute computed embeddings (opt-in)
    community_cache_url: str = "https://familiar-cache.fly.dev"  # Cache server URL

    # Server-owned playback queue (ADR-0003). Off by default: this ships behind a flag and
    # is proven in the web app before the native client depends on it. Rejecting writes
    # when disabled is deliberate — a server that accepted them and did nothing visible
    # would look like a client bug.
    queue_sync_enabled: bool = False

    # Playlist generation mode
    # "library_only" - Only use local tracks (legacy behavior)
    # "suggest_missing" - Include local + suggest missing tracks user might acquire (DEFAULT)
    playlist_discovery_mode: str = "suggest_missing"

    # Volume normalization
    normalization_enabled: bool = False
    normalization_mode: str = "track"  # "track", "album", "auto"
    normalization_target_lufs: float = -14.0
    normalization_preamp: float = 0.0  # dB
    normalization_prevent_clipping: bool = True

    # S3 Glacier Deep Archive backup
    s3_backup_enabled: bool = False
    s3_backup_bucket: str | None = None
    s3_backup_region: str | None = None
    s3_backup_access_key_id: str | None = None
    s3_backup_secret_access_key: str | None = None
    s3_backup_prefix: str = ""
    s3_backup_schedule: str = "weekly"  # daily, weekly, monthly

    # Update notifications
    update_channel: str = "disabled"  # "disabled", "stable", "beta", "alpha"

    # Network audio outputs — LAN-reachable base URL (e.g. http://192.168.1.50:4400) that devices
    # (WiiM/Sonos/etc.) use to fetch the audio stream. Needed when the browser reaches the app over
    # a network the device can't (e.g. Tailscale). Falls back to DEVICE_STREAM_BASE_URL env var.
    device_stream_base_url: str | None = None

    # Inbound authentication (ADR-0045 point 1). The one credential in this file that is *inbound* —
    # every other secret here is something Familiar presents to somebody else. `None` means no token
    # is configured and the gate is off, which is the pre-ADR-0045 posture and is what lets this ship
    # before the clients can present one. See `app/api/auth.py` for why it is stored in the clear.
    access_token: str | None = None



class AppSettingsService:
    """Service for managing user-configurable app settings."""

    def __init__(self, settings_path: Path | None = None):
        self.settings_path = settings_path or Path("data/settings.json")
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self._settings: AppSettings | None = None

    def _load(self) -> AppSettings:
        """Load settings from file."""
        if self.settings_path.exists():
            try:
                with open(self.settings_path) as f:
                    data = json.load(f)
                return AppSettings(**data)
            except (json.JSONDecodeError, ValidationError) as e:
                logger.warning(f"Failed to load settings from {self.settings_path}: {e}")
            except Exception as e:
                logger.warning(f"Unexpected error loading settings from {self.settings_path}: {e}")
        return AppSettings()

    def _save(self, settings: AppSettings) -> None:
        """Save settings to file atomically."""
        from app.utils.atomic_write import atomic_write_text

        json_str = json.dumps(settings.model_dump(), indent=2)
        atomic_write_text(self.settings_path, json_str)

    def get(self) -> AppSettings:
        """Get current settings.

        Always reloads from file to ensure consistency across workers.
        The settings file is small so this is fine for performance.
        """
        return self._load()

    def update(self, **kwargs: Any) -> AppSettings:
        """Update settings with new values."""
        current = self.get()
        updated_data = current.model_dump()

        # Settings that accept None as a valid value (to reset to auto-detect)
        #
        # `access_token` is here because revoking it means setting it to None, and the default
        # branch below *skips* None — so `update(access_token=None)` would have been a silent no-op
        # that returned success while the old token kept working. A revoke that reports success and
        # does nothing is worse than one that fails loudly.
        nullable_settings = {"clap_embeddings_enabled", "access_token"}

        # Only update non-None values (allow explicit empty string to clear)
        # Exception: nullable_settings can be explicitly set to None
        for key, value in kwargs.items():
            if not hasattr(current, key):
                continue
            if key in nullable_settings:
                # Allow explicit None for these settings
                updated_data[key] = value if value != "" else None
            elif value is not None:
                updated_data[key] = value if value != "" else None

        self._settings = AppSettings(**updated_data)
        self._save(self._settings)
        return self._settings

    def get_masked(self) -> dict[str, Any]:
        """Get settings with secrets masked for frontend display."""
        settings = self.get()
        data = settings.model_dump()

        # Keys that contain secrets and should be masked.
        #
        # This set is an allowlist of things to hide, so a newly added secret field is exposed by
        # default until someone remembers to add it here — which is worth knowing before adding one.
        # `tests/test_inbound_auth.py::TestTheTokenIsNotLeaked` covers `access_token` specifically;
        # the general "any new secret is masked" property is not enforced anywhere.
        secret_keys = {
            "lastfm_api_key", "lastfm_api_secret",
            "acoustid_api_key",
            "s3_backup_access_key_id", "s3_backup_secret_access_key",
        }

        # Mask only secret values
        for key in secret_keys:
            if key in data and data[key]:
                # Show first 4 chars + masked remainder
                val = str(data[key])
                if len(val) > 8:
                    data[key] = val[:4] + "•" * 8
                else:
                    data[key] = "•" * len(val)

        # The inbound token (ADR-0045) is masked *completely* rather than showing a prefix. The
        # others are outbound credentials whose prefix helps an operator tell which key is loaded;
        # this one grants access to this server, and `GET /api/v1/auth/token` is the way to read it
        # — a path that requires already holding it.
        if data.get("access_token"):
            data["access_token"] = "•" * 8

        return data

    def has_lastfm_credentials(self) -> bool:
        """Check if Last.fm credentials are configured (from settings.json or env vars)."""
        api_key = self.get_effective("lastfm_api_key")
        api_secret = self.get_effective("lastfm_api_secret")
        return bool(api_key and api_secret)

    def has_acoustid_key(self) -> bool:
        """Check if AcoustID API key is configured (from settings.json or env vars)."""
        return bool(self.get_effective("acoustid_api_key"))

    def has_s3_credentials(self) -> bool:
        """Check if S3 backup credentials are configured (from settings.json or env vars)."""
        access_key = self.get_effective("s3_backup_access_key_id")
        secret_key = self.get_effective("s3_backup_secret_access_key")
        return bool(access_key and secret_key)

    def has_music_library_configured(self) -> bool:
        """Check if the music library is accessible at /music."""
        from app.config import MUSIC_LIBRARY_PATH

        return MUSIC_LIBRARY_PATH.exists() and MUSIC_LIBRARY_PATH.is_dir()

    def get_effective(self, key: str) -> Any:
        """Get the effective value for a setting with proper precedence.

        Precedence: AppSettings (JSON) > Environment variable > Default

        Args:
            key: Setting name (e.g., 'lastfm_api_key', 'acoustid_api_key')

        Returns:
            The effective value from the highest-priority source that has it set.
        """
        from app.config import settings as env_settings

        app_value = getattr(self.get(), key, None)
        env_value = getattr(env_settings, key, None)

        # AppSettings takes priority if set (non-None and non-empty)
        if app_value:
            return app_value

        # Fall back to environment variable
        if env_value:
            return env_value

        return None

    def get_all_effective(self) -> dict[str, Any]:
        """Get all settings with precedence applied.

        Returns a dict with the effective value for each setting,
        combining AppSettings and environment variables.
        """
        from app.config import settings as env_settings

        app = self.get()
        result = {}

        # Settings that can come from either source
        dual_source_keys = [
            "lastfm_api_key",
            "lastfm_api_secret",
            "acoustid_api_key",
            "s3_backup_access_key_id",
            "s3_backup_secret_access_key",
            "s3_backup_bucket",
            "s3_backup_region",
            "s3_backup_prefix",
        ]

        for key in dual_source_keys:
            result[key] = self.get_effective(key)

        # Settings from AppSettings only
        result["music_library_paths"] = app.music_library_paths

        # Settings from environment only
        result["database_url"] = env_settings.database_url
        result["redis_url"] = env_settings.redis_url
        result["frontend_url"] = env_settings.frontend_url

        return result

    def is_clap_embeddings_enabled(self) -> tuple[bool, str]:
        """Get effective CLAP embeddings enabled status.

        Returns:
            Tuple of (enabled: bool, reason: str)

        Precedence:
        1. DISABLE_CLAP_EMBEDDINGS env var (if set, overrides everything)
        2. AppSettings clap_embeddings_enabled (if explicitly set)
        3. Auto-detect based on RAM (6GB minimum)
        """
        import os

        # Check environment variable override first (backwards compat)
        env_disabled = os.environ.get("DISABLE_CLAP_EMBEDDINGS", "").lower() in ("1", "true", "yes")
        if env_disabled:
            return (False, "Disabled via DISABLE_CLAP_EMBEDDINGS environment variable")

        # Check explicit setting
        settings = self.get()
        if settings.clap_embeddings_enabled is not None:
            if settings.clap_embeddings_enabled:
                return (True, "Enabled via settings")
            else:
                return (False, "Disabled via settings")

        # Auto-detect based on RAM
        ram_gb = get_system_ram_gb()
        if ram_gb is None:
            # Can't detect RAM (e.g., in container without psutil) - default to enabled
            # Most systems have enough RAM, better to try than silently disable
            return (True, "Auto-enabled (RAM detection unavailable, assuming sufficient)")

        if ram_gb >= 6.0:
            return (True, f"Auto-enabled ({ram_gb:.1f}GB RAM detected, 6GB+ required)")
        else:
            return (False, f"Auto-disabled (only {ram_gb:.1f}GB RAM, 6GB+ required)")

    def get_clap_status(self) -> dict[str, Any]:
        """Get detailed CLAP embeddings status for UI."""
        import os

        enabled, reason = self.is_clap_embeddings_enabled()
        ram_gb = get_system_ram_gb()

        return {
            "enabled": enabled,
            "reason": reason,
            "ram_gb": ram_gb,
            "ram_sufficient": ram_gb is not None and ram_gb >= 6.0,
            "env_override": os.environ.get("DISABLE_CLAP_EMBEDDINGS", "").lower() in ("1", "true", "yes"),
            "explicit_setting": self.get().clap_embeddings_enabled,
        }


def get_system_ram_gb() -> float | None:
    """Get total system RAM in GB. Returns None if unable to detect."""
    try:
        import psutil
        return psutil.virtual_memory().total / (1024**3)
    except ImportError:
        return None
    except Exception:
        return None


# Singleton instance
_app_settings_service: AppSettingsService | None = None


def get_app_settings_service() -> AppSettingsService:
    """Get or create the app settings service singleton."""
    global _app_settings_service
    if _app_settings_service is None:
        _app_settings_service = AppSettingsService()
    return _app_settings_service
