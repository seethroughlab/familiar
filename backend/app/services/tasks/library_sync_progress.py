"""Sync progress reporting: SyncProgressReporter and related helpers.

Extracted from library_sync.py to separate progress/guardrail concerns
from scan orchestration.
"""

import json
import logging
from collections import deque
from datetime import datetime
from typing import Any

from app.services.background.events import record_background_event
from app.services.redis_client import get_redis
from app.services.tasks.common import SYNC_PROGRESS_KEY

logger = logging.getLogger(__name__)

SYNC_GUARDRAIL_PHASES = ("features", "embeddings", "backfill", "melodic")
SYNC_QUEUE_CHURN_WINDOW_SECONDS = 300.0
SYNC_MAX_REQUEUE_ATTEMPTS_PER_WINDOW = 60


def _register_phase_requeue_attempt(
    attempts: deque[float],
    now: float,
    window_seconds: float = SYNC_QUEUE_CHURN_WINDOW_SECONDS,
    max_attempts: int = SYNC_MAX_REQUEUE_ATTEMPTS_PER_WINDOW,
) -> bool:
    """Track per-phase requeue attempts and return True when churn limit is exceeded."""
    while attempts and (now - attempts[0]) > window_seconds:
        attempts.popleft()
    attempts.append(now)
    return len(attempts) > max_attempts


class SyncProgressReporter:
    """Reports unified sync progress to Redis for API consumption.

    This class provides a single progress view that encompasses:
    - File discovery (finding audio files)
    - Metadata reading (extracting tags from files)
    - Audio analysis (feature extraction, embeddings)
    """

    def __init__(self):
        self.redis = get_redis()
        self.started_at = datetime.now().isoformat()
        self.errors: list[str] = []
        self.phase_requeue_attempts: dict[str, int] = {phase: 0 for phase in SYNC_GUARDRAIL_PHASES}
        self.phase_stall_recoveries: dict[str, int] = {phase: 0 for phase in SYNC_GUARDRAIL_PHASES}
        self.phase_forced_exit_reasons: dict[str, str | None] = {
            phase: None for phase in SYNC_GUARDRAIL_PHASES
        }
        self._last_phase_emitted: str | None = None
        self._update({
            "status": "running",
            "phase": "starting",
            "phase_message": "Starting library sync...",
            "files_discovered": 0,
            "files_processed": 0,
            "files_total": 0,
            "new_tracks": 0,
            "updated_tracks": 0,
            "unchanged_tracks": 0,
            "relocated_tracks": 0,
            "marked_missing": 0,
            "recovered": 0,
            "tracks_analyzed": 0,
            "tracks_pending_analysis": 0,
            "tracks_total": 0,
            "analysis_percent": 0,
            "current_item": None,
            "started_at": self.started_at,
            "last_heartbeat": datetime.now().isoformat(),
            "errors": [],
        })

    def _update(self, data: dict[str, Any]) -> None:
        """Update progress in Redis with heartbeat."""
        phase = data.get("phase")
        # Defensive fallback for partially initialized reporter instances.
        last_phase = getattr(self, "_last_phase_emitted", None)
        if phase and phase != last_phase:
            record_background_event("phase_transition", {"phase": phase})
            self._last_phase_emitted = phase
        errors = getattr(self, "errors", [])
        phase_requeue_attempts = getattr(
            self,
            "phase_requeue_attempts",
            {phase_name: 0 for phase_name in SYNC_GUARDRAIL_PHASES},
        )
        phase_stall_recoveries = getattr(
            self,
            "phase_stall_recoveries",
            {phase_name: 0 for phase_name in SYNC_GUARDRAIL_PHASES},
        )
        phase_forced_exit_reasons = getattr(
            self,
            "phase_forced_exit_reasons",
            {phase_name: None for phase_name in SYNC_GUARDRAIL_PHASES},
        )

        # Backfill any missing instance fields to keep later updates consistent.
        self.errors = errors
        self.phase_requeue_attempts = phase_requeue_attempts
        self.phase_stall_recoveries = phase_stall_recoveries
        self.phase_forced_exit_reasons = phase_forced_exit_reasons
        data["last_heartbeat"] = datetime.now().isoformat()
        data["errors"] = errors
        data["phase_requeue_attempts"] = phase_requeue_attempts
        data["phase_stall_recoveries"] = phase_stall_recoveries
        data["phase_forced_exit_reasons"] = phase_forced_exit_reasons
        self.redis.set(SYNC_PROGRESS_KEY, json.dumps(data), ex=3600)

    def record_requeue_attempt(self, phase: str) -> None:
        self.phase_requeue_attempts[phase] = self.phase_requeue_attempts.get(phase, 0) + 1

    def record_stall_recovery(self, phase: str) -> None:
        self.phase_stall_recoveries[phase] = self.phase_stall_recoveries.get(phase, 0) + 1

    def set_forced_exit_reason(self, phase: str, reason: str) -> None:
        self.phase_forced_exit_reasons[phase] = reason

    def set_discovering(self, dirs_scanned: int, files_found: int) -> None:
        """Phase 1: File discovery."""
        self._update({
            "status": "running",
            "phase": "discovering",
            "phase_message": f"Discovering files... ({dirs_scanned} dirs, {files_found} files)",
            "files_discovered": files_found,
            "files_processed": 0,
            "files_total": 0,
            "new_tracks": 0,
            "updated_tracks": 0,
            "unchanged_tracks": 0,
            "relocated_tracks": 0,
            "marked_missing": 0,
            "recovered": 0,
            "tracks_analyzed": 0,
            "tracks_pending_analysis": 0,
            "tracks_total": 0,
            "analysis_percent": 0,
            "current_item": None,
            "started_at": self.started_at,
        })

    def set_reading(
        self,
        processed: int,
        total: int,
        new: int,
        updated: int,
        unchanged: int,
        current: str | None = None,
        recovered: int = 0,
    ) -> None:
        """Phase 2: Reading metadata from files."""
        pct = int(processed / total * 100) if total > 0 else 0
        self._update({
            "status": "running",
            "phase": "reading",
            "phase_message": f"Reading metadata... {processed}/{total} ({pct}%)",
            "files_discovered": total,
            "files_processed": processed,
            "files_total": total,
            "new_tracks": new,
            "updated_tracks": updated,
            "unchanged_tracks": unchanged,
            "relocated_tracks": 0,
            "marked_missing": 0,
            "recovered": recovered,
            "tracks_analyzed": 0,
            "tracks_pending_analysis": 0,
            "tracks_total": 0,
            "analysis_percent": 0,
            "current_item": current,
            "started_at": self.started_at,
        })

    def set_features(
        self,
        analyzed: int,
        pending: int,
        total: int,
        scan_stats: dict[str, int] | None = None,
    ) -> None:
        """Phase 3: Feature extraction (librosa, artwork, AcoustID)."""
        pct = int(analyzed / total * 100) if total > 0 else 0
        stats = scan_stats or {}

        self._update({
            "status": "running",
            "phase": "features",
            "phase_message": f"Extracting features... {analyzed}/{total} ({pct}%)",
            "files_discovered": stats.get("files_total", 0),
            "files_processed": stats.get("files_total", 0),
            "files_total": stats.get("files_total", 0),
            "new_tracks": stats.get("new_tracks", 0),
            "updated_tracks": stats.get("updated_tracks", 0),
            "unchanged_tracks": stats.get("unchanged_tracks", 0),
            "relocated_tracks": stats.get("relocated_tracks", 0),
            "marked_missing": stats.get("marked_missing", 0),
            "recovered": stats.get("recovered", 0),
            "tracks_analyzed": analyzed,
            "tracks_pending_analysis": pending,
            "tracks_total": total,
            "analysis_percent": pct,
            "current_item": None,
            "started_at": self.started_at,
        })

    def set_embeddings(
        self,
        analyzed: int,
        pending: int,
        total: int,
        scan_stats: dict[str, int] | None = None,
    ) -> None:
        """Phase 4: Embedding generation (CLAP model)."""
        pct = int(analyzed / total * 100) if total > 0 else 0
        stats = scan_stats or {}

        self._update({
            "status": "running",
            "phase": "embeddings",
            "phase_message": f"Generating embeddings... {analyzed}/{total} ({pct}%)",
            "files_discovered": stats.get("files_total", 0),
            "files_processed": stats.get("files_total", 0),
            "files_total": stats.get("files_total", 0),
            "new_tracks": stats.get("new_tracks", 0),
            "updated_tracks": stats.get("updated_tracks", 0),
            "unchanged_tracks": stats.get("unchanged_tracks", 0),
            "relocated_tracks": stats.get("relocated_tracks", 0),
            "marked_missing": stats.get("marked_missing", 0),
            "recovered": stats.get("recovered", 0),
            "tracks_analyzed": analyzed,
            "tracks_pending_analysis": pending,
            "tracks_total": total,
            "analysis_percent": pct,
            "current_item": None,
            "started_at": self.started_at,
        })

    def set_melodic(
        self,
        analyzed: int,
        pending: int,
        total: int,
        scan_stats: dict[str, int] | None = None,
    ) -> None:
        """Phase 5: Melodic analysis (basic-pitch MIDI transcription)."""
        pct = int(analyzed / total * 100) if total > 0 else 0
        stats = scan_stats or {}

        self._update({
            "status": "running",
            "phase": "melodic",
            "phase_message": f"Melodic analysis... {analyzed}/{total} ({pct}%)",
            "files_discovered": stats.get("files_total", 0),
            "files_processed": stats.get("files_total", 0),
            "files_total": stats.get("files_total", 0),
            "new_tracks": stats.get("new_tracks", 0),
            "updated_tracks": stats.get("updated_tracks", 0),
            "unchanged_tracks": stats.get("unchanged_tracks", 0),
            "relocated_tracks": stats.get("relocated_tracks", 0),
            "marked_missing": stats.get("marked_missing", 0),
            "recovered": stats.get("recovered", 0),
            "tracks_analyzed": analyzed,
            "tracks_pending_analysis": pending,
            "tracks_total": total,
            "analysis_percent": pct,
            "current_item": None,
            "started_at": self.started_at,
        })

    def complete(
        self,
        new: int = 0,
        updated: int = 0,
        unchanged: int = 0,
        relocated: int = 0,
        marked_missing: int = 0,
        recovered: int = 0,
        analyzed: int = 0,
        total_tracks: int = 0,
    ) -> None:
        """Mark sync as complete."""
        self._update({
            "status": "completed",
            "phase": "complete",
            "phase_message": f"Complete: {new} new, {updated} updated, {analyzed} analyzed",
            "files_discovered": 0,
            "files_processed": 0,
            "files_total": 0,
            "new_tracks": new,
            "updated_tracks": updated,
            "unchanged_tracks": unchanged,
            "relocated_tracks": relocated,
            "marked_missing": marked_missing,
            "recovered": recovered,
            "tracks_analyzed": analyzed,
            "tracks_pending_analysis": 0,
            "tracks_total": total_tracks,
            "analysis_percent": 100 if total_tracks > 0 else 0,
            "current_item": None,
            "started_at": self.started_at,
        })

    def error(self, msg: str) -> None:
        """Mark sync as failed."""
        self.errors.append(msg)
        self._update({
            "status": "error",
            "phase": "error",
            "phase_message": msg,
            "files_discovered": 0,
            "files_processed": 0,
            "files_total": 0,
            "new_tracks": 0,
            "updated_tracks": 0,
            "unchanged_tracks": 0,
            "relocated_tracks": 0,
            "marked_missing": 0,
            "recovered": 0,
            "tracks_analyzed": 0,
            "tracks_pending_analysis": 0,
            "tracks_total": 0,
            "analysis_percent": 0,
            "current_item": None,
            "started_at": self.started_at,
        })


def get_sync_progress() -> dict[str, Any] | None:
    """Get current sync progress from Redis."""
    try:
        r = get_redis()
        data: bytes | None = r.get(SYNC_PROGRESS_KEY)  # type: ignore[assignment]
        if data:
            return json.loads(data)
    except Exception as e:
        logger.error(f"Failed to get sync progress: {e}")
    return None


def clear_sync_progress() -> None:
    """Clear sync progress from Redis."""
    try:
        r = get_redis()
        r.delete(SYNC_PROGRESS_KEY)
    except Exception as e:
        logger.error(f"Failed to clear sync progress: {e}")
