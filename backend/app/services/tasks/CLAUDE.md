# tasks/ — Background Job Orchestration

Owns background job orchestration: library sync, analysis pipeline, Spotify sync, new releases, metadata enrichment.

## Public API (re-exported from `__init__.py`)

- **library_sync**: `run_library_sync`, `SyncProgressReporter`, `get_sync_progress`, `clear_sync_progress`
- **analysis_pipeline**: `run_track_features`, `run_track_embedding`, `run_track_analysis`, `queue_tracks_for_*`, `queue_unanalyzed_tracks`
- **spotify_sync**: `run_spotify_sync`, `SpotifySyncProgressReporter`, `get_spotify_sync_progress`, `clear_spotify_sync_progress`, rate-limit helpers
- **new_releases**: `run_new_releases_check`, `run_prioritized_new_releases_check`, `NewReleasesProgressReporter`, progress getters/clearers
- **enrichment**: `run_track_enrichment`, `propose_enrichment_for_track`
- **common**: `get_redis`, failure tracking, memory logging

## Does NOT handle

- Task scheduling/triggering (callers do that via `background.py` or route handlers)
- Database session creation (uses `create_task_engine_session()` from `db/session.py`)
- Audio decoding, LLM interaction, frontend state
