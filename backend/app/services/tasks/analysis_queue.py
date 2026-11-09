"""Analysis queue management: queue_tracks_for_* functions.

Extracted from analysis_pipeline.py to keep pipeline execution and queue
management in separate modules.  All functions use _analysis_failure_cutoff()
from analysis_pipeline for consistent retry-window logic.
"""

import logging

from app.services.analysis_lifecycle import (
    backfill_queueable,
    embeddings_queueable,
    features_queueable,
    melodic_queueable,
    mood_tags_queueable,
)
from app.services.tasks.analysis_pipeline import _analysis_failure_cutoff

logger = logging.getLogger(__name__)


async def queue_tracks_for_features(limit: int | None = None) -> int:
    """Queue tracks that need feature extraction (Phase 1).

    This includes tracks that haven't been analyzed or have old analysis version.
    Returns the number of tracks queued.
    """
    if limit is None:
        from app.config import adaptive_queue_limit
        limit = adaptive_queue_limit()
    from sqlalchemy import select

    from app.db.models import Track, TrackAnalysis
    from app.db.session import async_session_maker
    from app.services.background import get_background_manager

    queued = 0
    async with async_session_maker() as db:
        failure_cutoff = _analysis_failure_cutoff()

        # Find tracks that need analysis:
        # 1. No TrackAnalysis row (never attempted)
        # 2. Outdated features_version
        # 3. Previously failed but 24h has passed (retry window open)
        # Only analyze ACTIVE tracks (not PENDING_REVIEW or SKIPPED)
        # ADR-0172: the same condition the sync loop counts by (`analysis_lifecycle`).
        result = await db.execute(
            select(Track.id)
            .outerjoin(TrackAnalysis, Track.id == TrackAnalysis.track_id)
            .where(features_queueable(failure_cutoff))
            .limit(limit)
        )
        track_ids = [str(row[0]) for row in result.fetchall()]

    if track_ids:
        manager = get_background_manager()
        for track_id in track_ids:
            await manager.run_analysis(track_id, phase="features")
            queued += 1

    return queued


async def queue_tracks_for_embeddings(limit: int | None = None) -> int:
    """Queue tracks that need embedding generation (Phase 2).

    This includes tracks with features extracted but no embedding.
    Returns the number of tracks queued.
    """
    if limit is None:
        from app.config import adaptive_queue_limit
        limit = adaptive_queue_limit()
    from sqlalchemy import select

    from app.db.models import Track, TrackAnalysis
    from app.db.session import async_session_maker
    from app.services.analysis import _models_missing
    from app.services.app_settings import get_app_settings_service
    from app.services.background import get_background_manager

    # Skip if CLAP is disabled via settings or env var, or its encoders are not on disk yet
    # (ADR-0132 point 8): queueing now would fail every track until they arrive.
    clap_enabled, _ = get_app_settings_service().is_clap_embeddings_enabled()
    if not clap_enabled or _models_missing():
        return 0

    queued = 0
    async with async_session_maker() as db:
        failure_cutoff = _analysis_failure_cutoff()

        # The condition is `analysis_lifecycle.embeddings_queueable`, which the sync loop also
        # counts by (ADR-0172). Two histories it encodes:
        #
        # - **Only tracks in the library.** On 2026-09-03 one missing file took the whole analysis
        #   pipeline down repeatedly: the worker died on it, and because the *process* died it
        #   never recorded `embedding_failed_at`, so it was requeued at once and killed the pool
        #   again. That track was `pending_deletion`: the features queue filtered on status and
        #   this one did not. The asymmetry was the bug, and one shared condition removes it.
        # - **A failure ends somewhere.** Retried after 24 hours, unless its reason is permanent
        #   (an undecodable file) or it has failed three times.
        result = await db.execute(
            select(Track.id)
            .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
            .where(embeddings_queueable(failure_cutoff))
            .limit(limit)
        )
        track_ids = [str(row[0]) for row in result.fetchall()]

    if track_ids:
        manager = get_background_manager()
        for track_id in track_ids:
            await manager.run_analysis(track_id, phase="embedding")
            queued += 1

    return queued


async def queue_tracks_for_melodic(limit: int | None = None) -> int:
    """Queue tracks that need melodic analysis (Phase 3).

    This includes tracks with analysis_detail but has_melodic=False.
    Returns the number of tracks queued.
    """
    if limit is None:
        from app.config import adaptive_queue_limit
        limit = adaptive_queue_limit()
    from sqlalchemy import select

    from app.db.models import Track, TrackAnalysis
    from app.db.session import async_session_maker
    from app.services.background import get_background_manager

    queued = 0
    async with async_session_maker() as db:
        result = await db.execute(
            select(TrackAnalysis.track_id)
            .join(Track, Track.id == TrackAnalysis.track_id)
            .where(melodic_queueable())  # ADR-0172: in the library only, as every phase
            .order_by(Track.duration_seconds.asc().nullsfirst())
            .limit(limit)
        )
        track_ids = [str(row[0]) for row in result.fetchall()]

    if track_ids:
        manager = get_background_manager()
        for track_id in track_ids:
            await manager.run_analysis(track_id, phase="melodic")
            queued += 1

    return queued


async def queue_tracks_for_backfill(limit: int | None = None) -> int:
    """Queue tracks that need analysis backfill (deprecated, self-eliminating).

    Populates analysis_detail for tracks that have features but no structural data.
    Once all tracks have analysis_detail, this phase is a no-op.
    Remove after 2026-06-01.

    Returns the number of tracks queued.
    """
    if limit is None:
        from app.config import adaptive_queue_limit
        limit = adaptive_queue_limit()
    from sqlalchemy import select

    from app.db.models import Track, TrackAnalysis
    from app.db.session import async_session_maker
    from app.services.background import get_background_manager

    queued = 0
    async with async_session_maker() as db:
        result = await db.execute(
            select(TrackAnalysis.track_id)
            .join(Track, Track.id == TrackAnalysis.track_id)
            .where(backfill_queueable())  # ADR-0172: in the library only, as every phase
            .order_by(Track.duration_seconds.asc().nullsfirst())
            .limit(limit)
        )
        track_ids = [str(row[0]) for row in result.fetchall()]

    if track_ids:
        manager = get_background_manager()
        for track_id in track_ids:
            await manager.run_analysis(track_id, phase="deep_backfill")
            queued += 1

    return queued


async def queue_unanalyzed_tracks(limit: int | None = None) -> int:
    """Queue analysis for tracks that need analysis.

    DEPRECATED: Use queue_tracks_for_features() and queue_tracks_for_embeddings()
    for better memory efficiency and progress tracking.

    This function is kept for backwards compatibility and queues for full analysis.
    """
    if limit is None:
        from app.config import adaptive_queue_limit
        limit = adaptive_queue_limit()
    from sqlalchemy import select

    from app.db.models import Track, TrackAnalysis
    from app.db.session import async_session_maker
    from app.services.analysis import get_analysis_capabilities
    from app.services.background import get_background_manager

    caps = get_analysis_capabilities()
    embeddings_enabled = caps["embeddings_enabled"]

    queued = 0
    async with async_session_maker() as db:
        failure_cutoff = _analysis_failure_cutoff()

        result = await db.execute(
            select(Track.id)
            .outerjoin(TrackAnalysis, Track.id == TrackAnalysis.track_id)
            .where(features_queueable(failure_cutoff))
            .limit(limit)
        )
        track_ids = set(str(row[0]) for row in result.fetchall())

        # If embeddings are now enabled, also get tracks missing embeddings
        if embeddings_enabled and len(track_ids) < limit:
            remaining_limit = limit - len(track_ids)
            result = await db.execute(
                select(Track.id)
                .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
                # This branch had no status filter and no embedding-failure check, the same
                # asymmetry `queue_tracks_for_embeddings` records (ADR-0172).
                .where(embeddings_queueable(failure_cutoff))
                .limit(remaining_limit)
            )
            missing_embedding_ids = set(str(row[0]) for row in result.fetchall())

            if missing_embedding_ids:
                logger.info(
                    f"Found {len(missing_embedding_ids)} tracks with missing embeddings "
                    "(embeddings now enabled)"
                )
                # Queue embedding-only tasks instead of resetting to re-analyze everything
                # This preserves existing features and just adds embeddings
                bg = get_background_manager()
                for track_id in missing_embedding_ids:
                    await bg.run_analysis(track_id, phase="embedding")
                    queued += 1
                # Don't add to track_ids - we already queued them for embedding-only

        if not track_ids:
            logger.info("No tracks need analysis")
            return queued

        # Queue each track for analysis
        bg = get_background_manager()
        for track_id in track_ids:
            await bg.run_analysis(track_id)
            queued += 1

        logger.info(f"Queued {queued} tracks for analysis")

    return queued


async def queue_tracks_for_mood_tags(limit: int | None = None) -> int:
    """Queue tracks that need mood tag computation (Phase 4).

    Selects tracks with CLAP embeddings but outdated/missing mood_tags_version.
    Returns the number of tracks queued.
    """
    if limit is None:
        from app.config import adaptive_queue_limit
        limit = adaptive_queue_limit()
    from sqlalchemy import select

    from app.db.models import Track, TrackAnalysis
    from app.db.session import async_session_maker
    from app.services.background import get_background_manager

    queued = 0
    async with async_session_maker() as db:
        result = await db.execute(
            select(TrackAnalysis.track_id)
            .join(Track, Track.id == TrackAnalysis.track_id)
            .where(mood_tags_queueable())  # ADR-0172: in the library only, as every phase
            .limit(limit)
        )
        track_ids = [str(row[0]) for row in result.fetchall()]

    if track_ids:
        manager = get_background_manager()
        for track_id in track_ids:
            await manager.run_analysis(track_id, phase="mood_tags")
            queued += 1

    return queued
