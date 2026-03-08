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

    # Development
    debug: bool = False  # Must be explicitly enabled for development
    log_level: str = "INFO"
    migration_preflight_enabled: bool = True
    migration_preflight_strict: bool = True

    @property
    def sync_database_url(self) -> str:
        """Synchronous database URL for Alembic or sync operations."""
        return self.database_url.replace("+asyncpg", "")


# Per-phase analysis version constants
# Bump ONLY the phase that changed; other phases won't re-run
#
# Features history:
#   v1: Placeholder features only
#   v2: Real librosa features
#   v3: Fixed energy normalization (dB scale) and valence (key-aware chroma)
#   v4: Improved valence with multi-feature approach
#   v5: Re-extract (psutil fix enabled proper RAM detection)
#   v6: Added loudness measurement (EBU R128 / ReplayGain)
#   v7: Tightened section labeling thresholds, fixed key timeline overlaps
#   v8: KK key profiles with mode, MFCC acousticness, silero-vad instrumentalness/speechiness, valence harmonic tension
FEATURES_VERSION = 8

# Embedding history:
#   v2: First CLAP 512-dim embeddings
#   v5: Re-extract (psutil fix)
#   v6: Matched features version at loudness addition
EMBEDDING_VERSION = 6

# Melodic history:
#   v5: basic-pitch MIDI transcription + melodic feature extraction
#   v6: Density phrase fallback, fixed-window register movement, no-unison intervals
MELODIC_VERSION = 6

# Generative art history:
#   v1: Layered composition (gradient, geometry, flow field, texture)
#   v2: Added vinyl label overlay (arc text, initials)
#   v3: Heavy blur for color-wash background, label after post-process, dark backdrop
#   v4: Larger label radius for text padding, artist-only initials
GENERATIVE_ART_VERSION = 4

# Mood tags history:
#   v1: CLAP-based mood/genre/instrumentation/energy tags
MOOD_TAGS_VERSION = 1

# Supported audio formats
AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".wav", ".aiff", ".aif"}

# Global settings instance
settings = Settings()
