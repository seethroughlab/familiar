import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Library path - defaults to /music (Docker), can be overridden via MUSIC_LIBRARY_PATH env var
MUSIC_LIBRARY_PATH = Path(os.environ.get("MUSIC_LIBRARY_PATH", "/music"))


def get_app_version() -> str:
    """Get app version from VERSION file (set at Docker build time) or fallback."""
    version_file = Path("/app/VERSION")
    if version_file.exists():
        return version_file.read_text().strip()
    # Fallback for local development
    return "dev"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://familiar:familiar@localhost:5432/familiar"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    @property
    def music_library_paths(self) -> list[Path]:
        """Fixed music library path at /music.

        Configure host path via docker-compose volume mount.
        """
        return [MUSIC_LIBRARY_PATH]

    # Data paths
    art_path: Path = Path("data/art")
    videos_path: Path = Path("data/videos")
    profiles_path: Path = Path("data/profiles")

    # Analysis
    analysis_version: int = 1

    # API Keys (Phase 3+)
    anthropic_api_key: str | None = None
    spotify_client_id: str | None = None
    spotify_client_secret: str | None = None
    frontend_url: str | None = None  # Base URL for OAuth callbacks (e.g., http://myserver:4400)
    lastfm_api_key: str | None = None
    lastfm_api_secret: str | None = None
    acoustid_api_key: str | None = None

    # S3 Backup
    s3_backup_access_key_id: str | None = None
    s3_backup_secret_access_key: str | None = None
    s3_backup_bucket: str | None = None
    s3_backup_region: str = "us-east-1"
    s3_backup_prefix: str = ""

    # WebRTC TURN server (optional, for NAT traversal in corporate networks)
    turn_server_url: str | None = None  # e.g. "turn:turn.example.com:3478"
    turn_server_username: str | None = None
    turn_server_credential: str | None = None

    # Development
    debug: bool = False  # Must be explicitly enabled for development
    log_level: str = "INFO"

    @property
    def sync_database_url(self) -> str:
        """Synchronous database URL for Alembic or sync operations."""
        return self.database_url.replace("+asyncpg", "")


# Analysis version constant - bump when analysis pipeline changes
# v1: Placeholder features only
# v2: Real CLAP embeddings + librosa features
# v3: Fixed energy normalization (dB scale) and valence (key-aware chroma)
# v4: Improved valence with multi-feature approach (mode, brightness, tempo, contrast, dynamics)
# v5: Re-extract CLAP embeddings (psutil fix enabled proper RAM detection)
# v6: Added loudness measurement (EBU R128 / ReplayGain) for volume normalization
ANALYSIS_VERSION = 6

# Supported audio formats
AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".wav", ".aiff", ".aif"}

# Global settings instance
settings = Settings()
