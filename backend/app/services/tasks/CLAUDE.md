# tasks/ — Background Job Orchestration

Owns background job orchestration: library sync, analysis pipeline.

## Public API (re-exported from `__init__.py`)

- **library_sync**: `run_library_sync`
- **library_sync_progress**: `SyncProgressReporter`, `get_sync_progress`, `clear_sync_progress`
- **analysis_pipeline**: `run_track_features`, `run_track_embedding`, `run_track_analysis`
- **analysis_queue**: `queue_tracks_for_*`, `queue_unanalyzed_tracks`
- **new_releases**: `run_new_releases_check`, `run_prioritized_new_releases_check`, `NewReleasesProgressReporter`, `get_new_releases_progress`, `clear_new_releases_progress`
- **common**: `get_redis`, failure tracking, memory logging

## Does NOT handle

- Task scheduling/triggering (callers do that via `background.py` or route handlers)
- Database session creation (uses `create_task_engine_session()` from `db/session.py`)
- Audio decoding, LLM interaction, frontend state
