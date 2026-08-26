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
    mixtapes_path: Path = Path("data/mixtapes")

    # Analysis
    analysis_version: int = 1

    # MCP (ADR-0043). Comma-separated hosts this server is reached by, e.g.
    # "localhost:4400,myserver:4400". Set it and DNS-rebinding protection is enabled for /mcp;
    # leave it empty and the protection is off, with a warning at startup. The SDK ships no default
    # allowlist, so enabling it without naming your host rejects every request with a 421.
    mcp_allowed_hosts: str = ""

    # API Keys (Phase 3+)
    frontend_url: str | None = None  # Base URL for OAuth callbacks (e.g., http://myserver:4400)
    lastfm_api_key: str | None = None
    lastfm_api_secret: str | None = None
    acoustid_api_key: str | None = None

    # Network audio outputs (Sonos / WiiM / AirPlay / Chromecast).
    # DEVICE_STREAM_BASE_URL: LAN-reachable base URL (e.g. http://192.168.1.50:4400) that network
    # devices use to fetch the audio stream. Needed when the browser reaches the app via a network
    # the device can't (e.g. Tailscale), since the frontend builds stream URLs from its own origin.
    device_stream_base_url: str | None = None

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
    executor_auto_recovery_enabled: bool = False
    executor_auto_recovery_backoff_seconds: int = 900
    executor_auto_recovery_max_attempts: int = 3

    # Analysis worker pool size (default 1 for memory safety; increase with CPU headroom)
    max_analysis_workers: int = 1

    # When True, the scanner runs a strict MusicBrainz artist lookup at scan
    # time for unknown tags so it can attach a canonical MBID immediately.
    # Off by default — MB is rate-limited at 1 RPS and would dominate scan
    # latency. The backfill CLI flips this on for its one-shot pass.
    scanner_mb_artist_lookup: bool = False

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
#   v5: Keyed by Album.id rather than the tag hash (ADR-0052). Nothing about the drawing
#       changed — but the key *is* the random seed, so every generated cover comes out
#       different, and the features are now aggregated across the whole album instead of
#       only the tracks sharing one artist string. The bump exists so
#       /artwork/regenerate-stale repaints them; it only touches files carrying a
#       `.generated` marker, so real and hand-uploaded art is left alone.
GENERATIVE_ART_VERSION = 5

# Mood tags history:
#   v1: CLAP-based mood/genre/instrumentation/energy tags
MOOD_TAGS_VERSION = 1

# Where the kernel exposes this cgroup's CPU quota. Module-level so tests can point them
# at synthetic files instead of depending on the host they run on.
CGROUP_V2_CPU_MAX = Path("/sys/fs/cgroup/cpu.max")
CGROUP_V1_CPU_QUOTA = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
CGROUP_V1_CPU_PERIOD = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")


def _cgroup_cpu_quota() -> float | None:
    """This cgroup's CPU quota in cores, or None if unlimited or not in a cgroup."""
    try:
        # cgroup v2: "<quota> <period>", where quota may be the literal "max".
        if CGROUP_V2_CPU_MAX.exists():
            quota_s, _, period_s = CGROUP_V2_CPU_MAX.read_text().strip().partition(" ")
            if quota_s and quota_s != "max":
                period = float(period_s)
                if period > 0:
                    return float(quota_s) / period

        # cgroup v1: two files, with -1 meaning unlimited.
        if CGROUP_V1_CPU_QUOTA.exists() and CGROUP_V1_CPU_PERIOD.exists():
            quota = float(CGROUP_V1_CPU_QUOTA.read_text().strip())
            period = float(CGROUP_V1_CPU_PERIOD.read_text().strip())
            if quota > 0 and period > 0:
                return quota / period
    except (OSError, ValueError):
        # An unreadable or unexpected /sys must not take the process down; the host
        # count is a safe, if generous, answer.
        pass
    return None


def available_cpu_count() -> int:
    """CPUs this process can actually use, honouring the container's CPU quota.

    ``os.cpu_count()`` reports the *host's* CPUs and knows nothing about cgroups. On the
    NAS that is 8 against a 2.0-CPU container limit, so anything sized off it overshoots
    by 4x — see ``adaptive_queue_limit``, which was returning its 500 ceiling regardless
    of the real limit.

    Never returns less than 1, and never more than the host physically has.
    """
    host = os.cpu_count() or 2
    quota = _cgroup_cpu_quota()
    if quota is None:
        return max(1, host)
    return max(1, min(host, int(quota)))


def adaptive_queue_limit(base: int = 100) -> int:
    """Scale queue burst by usable CPU count, clamped to [50, 500]."""
    return max(50, min(available_cpu_count() * base, 500))


# Supported audio formats
AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".aiff", ".aif"}

# Global settings instance
settings = Settings()
