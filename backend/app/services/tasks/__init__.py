"""Background tasks subpackage.

Re-exports all public names for backward compatibility so that
``from app.services.tasks import X`` continues to work unchanged.
"""

# common.py
# Re-export get_redis for any remaining consumers
from app.services.redis_client import get_redis

# analysis_pipeline.py
from app.services.tasks.analysis_pipeline import (
    queue_tracks_for_backfill,
    queue_tracks_for_embeddings,
    queue_tracks_for_features,
    queue_tracks_for_melodic,
    queue_unanalyzed_tracks,
    run_track_analysis,
    run_track_embedding,
    run_track_features,
)
from app.services.tasks.common import (
    MAX_FAILURES_STORED,
    SYNC_PROGRESS_KEY,
    TASK_FAILURES_KEY,
    _record_task_failure,
    clear_task_failures,
    get_memory_mb,
    get_recent_failures,
    log_memory,
)

# enrichment.py
from app.services.tasks.enrichment import (
    propose_enrichment_for_track,
    run_track_enrichment,
)

# library_sync.py
from app.services.tasks.library_sync import (
    SyncProgressReporter,
    clear_sync_progress,
    get_sync_progress,
    run_library_sync,
)

# new_releases.py
from app.services.tasks.new_releases import (
    NEW_RELEASES_PROGRESS_KEY,
    NewReleasesProgressReporter,
    clear_new_releases_progress,
    get_new_releases_progress,
    run_new_releases_check,
    run_prioritized_new_releases_check,
)

# spotify_sync.py
from app.services.tasks.spotify_sync import (
    SPOTIFY_RATE_LIMIT_KEY,
    SPOTIFY_SYNC_PROGRESS_KEY,
    SpotifySyncProgressReporter,
    clear_spotify_sync_progress,
    get_spotify_rate_limit,
    get_spotify_sync_progress,
    run_spotify_sync,
    set_spotify_rate_limit,
)

__all__ = [
    # common
    "get_memory_mb",
    "log_memory",
    "get_redis",
    "SYNC_PROGRESS_KEY",
    "TASK_FAILURES_KEY",
    "MAX_FAILURES_STORED",
    "_record_task_failure",
    "get_recent_failures",
    "clear_task_failures",
    # library_sync
    "SyncProgressReporter",
    "get_sync_progress",
    "clear_sync_progress",
    "run_library_sync",
    # analysis_pipeline
    "run_track_features",
    "run_track_embedding",
    "run_track_analysis",
    "queue_tracks_for_features",
    "queue_tracks_for_embeddings",
    "queue_tracks_for_melodic",
    "queue_tracks_for_backfill",
    "queue_unanalyzed_tracks",
    # spotify_sync
    "SPOTIFY_SYNC_PROGRESS_KEY",
    "SPOTIFY_RATE_LIMIT_KEY",
    "SpotifySyncProgressReporter",
    "get_spotify_sync_progress",
    "clear_spotify_sync_progress",
    "set_spotify_rate_limit",
    "get_spotify_rate_limit",
    "run_spotify_sync",
    # new_releases
    "NEW_RELEASES_PROGRESS_KEY",
    "NewReleasesProgressReporter",
    "get_new_releases_progress",
    "clear_new_releases_progress",
    "run_new_releases_check",
    "run_prioritized_new_releases_check",
    # enrichment
    "run_track_enrichment",
    "propose_enrichment_for_track",
]
