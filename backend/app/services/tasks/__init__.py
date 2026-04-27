"""Background tasks subpackage.

Re-exports all public names for backward compatibility so that
``from app.services.tasks import X`` continues to work unchanged.
"""

# common.py
# Re-export get_redis for any remaining consumers
from app.services.redis_client import get_redis

# analysis_pipeline.py
from app.services.tasks.analysis_pipeline import (
    run_track_analysis,
    run_track_embedding,
    run_track_features,
)

# analysis_queue.py
from app.services.tasks.analysis_queue import (
    queue_tracks_for_backfill,
    queue_tracks_for_embeddings,
    queue_tracks_for_features,
    queue_tracks_for_melodic,
    queue_unanalyzed_tracks,
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

# library_sync.py
from app.services.tasks.library_sync import run_library_sync

# library_sync_progress.py
from app.services.tasks.library_sync_progress import (
    SyncProgressReporter,
    clear_sync_progress,
    get_sync_progress,
)

# new_releases.py
from app.services.tasks.new_releases import (
    NewReleasesProgressReporter,
    clear_new_releases_progress,
    get_new_releases_progress,
    run_new_releases_check,
    run_prioritized_new_releases_check,
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
    "run_library_sync",
    # library_sync_progress
    "SyncProgressReporter",
    "get_sync_progress",
    "clear_sync_progress",
    # analysis_pipeline
    "run_track_features",
    "run_track_embedding",
    "run_track_analysis",
    # analysis_queue
    "queue_tracks_for_features",
    "queue_tracks_for_embeddings",
    "queue_tracks_for_melodic",
    "queue_tracks_for_backfill",
    "queue_unanalyzed_tracks",
    # new_releases
    "NewReleasesProgressReporter",
    "clear_new_releases_progress",
    "get_new_releases_progress",
    "run_new_releases_check",
    "run_prioritized_new_releases_check",
]
