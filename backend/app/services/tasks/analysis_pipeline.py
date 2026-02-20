"""Analysis pipeline: feature extraction, embedding generation, and queue management.

Contains run_track_features, run_track_embedding, run_track_analysis (deprecated),
and all queue_* functions for the background analysis pipeline.
"""

import gc
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm.exc import StaleDataError

from app.config import EMBEDDING_VERSION, FEATURES_VERSION, MELODIC_VERSION
from app.services.tasks.common import _record_task_failure, log_memory

logger = logging.getLogger(__name__)


def _ensure_track_analysis_row(db: Any, track_id: "UUID", version: int) -> None:
    """Create or update TrackAnalysis to record attempt version.

    Used for failures/skips so the queue logic (LEFT JOIN track_analysis)
    knows this track was already attempted at this version.
    """
    from sqlalchemy import select as _select

    from app.db.models import TrackAnalysis

    existing = db.execute(
        _select(TrackAnalysis).where(TrackAnalysis.track_id == track_id)
    ).scalar_one_or_none()
    if existing:
        existing.features_version = version
    else:
        db.add(TrackAnalysis(track_id=track_id, features_version=version))


def run_track_features(track_id: str) -> dict[str, Any]:
    """Extract audio features for a track - runs in subprocess via ProcessPoolExecutor.

    Phase 1 of analysis: artwork, librosa features, AcoustID, MusicBrainz.
    This is separated from embedding extraction to reduce peak memory usage.
    Each phase runs in its own subprocess that exits after completion.

    External Features Lookup:
    Before running expensive librosa analysis, checks if pre-computed features
    are available from external services (e.g., ReccoBeats via Spotify track ID).
    """
    # Configure logging for subprocess (spawned processes don't inherit parent's config)
    import asyncio
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s',
        force=True,  # Override any existing config
    )

    from sqlalchemy import select

    from app.db.models import ANALYSIS_FEATURE_COLUMNS, SpotifyFavorite, Track, TrackAnalysis
    from app.db.session import sync_session_maker
    from app.services.analysis import (
        AnalysisError,
        derive_features,
        generate_fingerprint,
        identify_track,
        precompute_shared,
    )
    from app.services.app_settings import get_app_settings_service
    from app.services.artwork import extract_and_save_artwork
    from app.services.community_cache import get_community_cache_service
    from app.services.external_features import get_external_features_service
    from app.services.track_analysis import run_cheap_sections

    log_memory("features_start")

    track_info = None
    try:
        with sync_session_maker() as db:
            result = db.execute(
                select(Track).where(Track.id == UUID(track_id))
            )
            track = result.scalar_one_or_none()

            if not track:
                return {"error": f"Track not found: {track_id}", "permanent": True}

            track_info = f"{track.artist} - {track.title}"
            file_path = Path(track.file_path)

            if not file_path.exists():
                # Mark as analyzed so it won't be re-queued (file is missing)
                _ensure_track_analysis_row(db, track.id, FEATURES_VERSION)
                track.analyzed_at = datetime.utcnow()
                track.analysis_error = "File not found"
                db.commit()
                return {"error": f"File not found: {track.file_path}", "permanent": True}

            # Skip tracks outside the "normal song" duration range
            # - Too short (<30s): intros, sound effects, samples
            # - Too long (>15min): DJ mixes, podcasts, audiobooks
            MIN_ANALYSIS_DURATION = 30  # seconds
            MAX_ANALYSIS_DURATION = 15 * 60  # 15 minutes
            if track.duration_seconds:
                skip_reason = None
                if track.duration_seconds < MIN_ANALYSIS_DURATION:
                    skip_reason = f"Track too short ({int(track.duration_seconds)}s)"
                elif track.duration_seconds > MAX_ANALYSIS_DURATION:
                    duration_mins = int(track.duration_seconds / 60)
                    skip_reason = f"Track too long ({duration_mins} min)"

                if skip_reason:
                    # Mark as analyzed so it won't be re-queued
                    _ensure_track_analysis_row(db, track.id, FEATURES_VERSION)
                    track.analyzed_at = datetime.utcnow()
                    track.analysis_error = skip_reason
                    db.commit()
                    return {
                        "error": skip_reason,
                        "status": "skipped",
                        "permanent": True,
                    }

            logger.info(f"Extracting features: {track.title} by {track.artist}")

            # Extract and save artwork
            artwork_hash = extract_and_save_artwork(
                file_path,
                artist=track.artist,
                album=track.album,
            )
            log_memory("after_artwork")

            # Generate AcoustID fingerprint first (needed for community cache)
            acoustid_fingerprint = None
            fp_result = generate_fingerprint(file_path)
            if fp_result:
                _, acoustid_fingerprint = fp_result

            # Try external feature lookup first (ReccoBeats via Spotify ID)
            features: dict[str, Any] = {}
            features_source = "local"
            app_settings = get_app_settings_service().get()

            if app_settings.external_features_enabled:
                # Look up Spotify track ID from SpotifyFavorite
                spotify_fav_result = db.execute(
                    select(SpotifyFavorite.spotify_track_id)
                    .where(SpotifyFavorite.matched_track_id == track.id)
                )
                spotify_fav = spotify_fav_result.scalar_one_or_none()

                if spotify_fav:
                    logger.info(f"Looking up external features for Spotify ID: {spotify_fav}")
                    try:
                        ext_service = get_external_features_service()
                        ext_features = asyncio.run(
                            ext_service.lookup_features(spotify_track_id=spotify_fav)
                        )
                        if ext_features:
                            # Convert ExternalFeatures to our features dict format
                            features = {
                                "bpm": ext_features.bpm,
                                "key": ext_features.key,
                                "energy": ext_features.energy,
                                "danceability": ext_features.danceability,
                                "valence": ext_features.valence,
                                "acousticness": ext_features.acousticness,
                                "instrumentalness": ext_features.instrumentalness,
                                "speechiness": ext_features.speechiness,
                                "liveness": ext_features.liveness,
                                "loudness": ext_features.loudness,
                            }
                            # Remove None values
                            features = {k: v for k, v in features.items() if v is not None}
                            features_source = ext_features.source  # "reccobeats"
                            logger.info(
                                f"External features found from {features_source}: "
                                f"BPM={ext_features.bpm}, Key={ext_features.key}"
                            )
                    except Exception as e:
                        logger.warning(f"External feature lookup failed: {e}")

            # Try community cache for features if no external features found
            deep_scalars: dict[str, Any] = {}
            if not features.get("bpm") and app_settings.community_cache_enabled and acoustid_fingerprint:
                try:
                    cache_service = get_community_cache_service(
                        cache_url=app_settings.community_cache_url
                    )
                    cached_features = asyncio.run(
                        cache_service.lookup_features(acoustid_fingerprint)
                    )
                    if cached_features:
                        # Basic features
                        features = {
                            "bpm": cached_features.bpm,
                            "key": cached_features.key,
                            "energy": cached_features.energy,
                            "danceability": cached_features.danceability,
                            "valence": cached_features.valence,
                            "acousticness": cached_features.acousticness,
                            "instrumentalness": cached_features.instrumentalness,
                            "speechiness": cached_features.speechiness,
                            "liveness": cached_features.liveness,
                            "loudness": cached_features.loudness,
                        }
                        features = {k: v for k, v in features.items() if v is not None}

                        # Deep analysis scalars from cache
                        _deep_from_cache = {
                            "harmonic_complexity": cached_features.harmonic_complexity,
                            "key_stability": cached_features.key_stability,
                            "modal_character": cached_features.modal_character,
                            "modal_confidence": cached_features.modal_confidence,
                            "swing_ratio": cached_features.swing_ratio,
                            "syncopation": cached_features.syncopation,
                            "tempo_character": cached_features.tempo_character,
                            "brightness": cached_features.brightness,
                            "dynamic_range_db": cached_features.dynamic_range_db,
                            "energy_shape": cached_features.energy_shape,
                            "section_count": cached_features.section_count,
                            "form_string": cached_features.form_string,
                            "avg_section_length": cached_features.avg_section_length,
                            "replaygain_track_gain": cached_features.replaygain_track_gain,
                            "track_peak": cached_features.track_peak,
                            "note_density": cached_features.note_density,
                            "interval_character": cached_features.interval_character,
                            "pitch_range": cached_features.pitch_range,
                        }
                        deep_scalars = {
                            k: v for k, v in _deep_from_cache.items() if v is not None
                        }

                        # Try to fetch analysis_detail from cache too
                        try:
                            cached_detail = asyncio.run(
                                cache_service.lookup_analysis_detail(acoustid_fingerprint)
                            )
                            if cached_detail:
                                analysis_detail = cached_detail.detail
                                logger.info(
                                    f"Community cache analysis detail hit for "
                                    f"{track.title}"
                                )
                        except Exception as e:
                            logger.debug(
                                f"Community cache analysis detail lookup failed: {e}"
                            )

                        features_source = "community_cache"
                        logger.info(
                            f"Community cache features hit for {track.title} "
                            f"(contributed by {cached_features.contributor_count} "
                            f"users, {len(deep_scalars)} deep scalars)"
                        )
                except Exception as e:
                    logger.warning(f"Community cache features lookup failed: {e}")

            # Fall back to local librosa extraction if no external/cached features
            computed_locally = False
            analysis_detail = None
            if not features.get("bpm"):
                # Use unified pipeline: shared precomputation → features + cheap sections
                y, sr, shared = precompute_shared(file_path)
                features = derive_features(y, sr, shared, file_path)
                features_source = "local"
                computed_locally = True

                # Run cheap analysis sections (harmonic, rhythmic, spectral, structural, energy)
                # Only if track is long enough for meaningful analysis
                if track.duration_seconds and track.duration_seconds >= 30:
                    try:
                        analysis_detail, deep_scalars, section_errors = run_cheap_sections(
                            y, sr, shared, str(file_path), track_id
                        )
                        if section_errors:
                            logger.warning(
                                f"Analysis section errors for {track.title}: {section_errors}"
                            )
                    except Exception as e:
                        logger.warning(f"Cheap sections failed for {track.title}: {e}")

                del y, shared
                gc.collect()

            # Contribute features to community cache if computed locally
            if (
                computed_locally
                and app_settings.community_cache_contribute
                and acoustid_fingerprint
                and features.get("bpm")
            ):
                try:
                    cache_service = get_community_cache_service(
                        cache_url=app_settings.community_cache_url
                    )
                    # Send all available features (basic + deep scalars)
                    all_cache_features = {**features, **deep_scalars}
                    asyncio.run(
                        cache_service.contribute_features(
                            acoustid_fingerprint, all_cache_features
                        )
                    )
                    # Also contribute analysis_detail if available
                    if analysis_detail:
                        asyncio.run(
                            cache_service.contribute_analysis_detail(
                                acoustid_fingerprint, analysis_detail
                            )
                        )
                except Exception as e:
                    logger.warning(
                        f"Failed to contribute features to community cache: {e}"
                    )

            log_memory("after_features")

            # Try to identify track via AcoustID
            acoustid_metadata = None
            musicbrainz_recording_id = None
            if acoustid_fingerprint:
                id_result = identify_track(file_path)
                if id_result.get("metadata"):
                    acoustid_metadata = id_result["metadata"]
                    musicbrainz_recording_id = acoustid_metadata.get("musicbrainz_recording_id")

            # Enrich with MusicBrainz metadata
            from app.services.musicbrainz import enrich_track
            enrich_track(
                title=track.title,
                artist=track.artist,
                album=track.album,
                musicbrainz_recording_id=musicbrainz_recording_id,
            )

            log_memory("after_metadata")

            # Merge all features: librosa + analysis scalars
            all_features = {**features, **deep_scalars}

            # Create or update analysis record (without embedding - that comes in phase 2)
            # Query by track_id only - NOT by version, to avoid creating duplicates
            # when FEATURES_VERSION is bumped
            existing = db.execute(
                select(TrackAnalysis)
                .where(TrackAnalysis.track_id == track.id)
            )
            existing_analysis = existing.scalar_one_or_none()

            if existing_analysis:
                # Set typed columns from features
                for col in ANALYSIS_FEATURE_COLUMNS:
                    val = all_features.get(col)
                    if val is not None:
                        setattr(existing_analysis, col, val)
                existing_analysis.features_source = features_source
                existing_analysis.acoustid = acoustid_fingerprint
                existing_analysis.features_version = FEATURES_VERSION
                if analysis_detail is not None:
                    existing_analysis.analysis_detail = analysis_detail
                # Keep existing embedding if present
            else:
                analysis = TrackAnalysis(
                    track_id=track.id,
                    features_version=FEATURES_VERSION,
                    features_source=features_source,
                    embedding=None,  # Embedding extracted in phase 2
                    acoustid=acoustid_fingerprint,
                    analysis_detail=analysis_detail,
                )
                # Set typed columns from features
                for col in ANALYSIS_FEATURE_COLUMNS:
                    val = all_features.get(col)
                    if val is not None:
                        setattr(analysis, col, val)
                db.add(analysis)

            # Update track analysis status
            track.analyzed_at = datetime.utcnow()
            track.analysis_error = None
            track.analysis_failed_at = None

            db.commit()
            log_memory("after_commit")

            logger.info(
                f"Features extracted for {track.title} (source={features_source}): "
                f"BPM={all_features.get('bpm')}, Key={all_features.get('key')}"
            )

            gc.collect()
            log_memory("features_end")

            return {
                "track_id": track_id,
                "file_path": str(file_path),
                "status": "success",
                "phase": "features",
                "artwork_extracted": artwork_hash is not None,
                "features_extracted": bool(all_features.get("bpm")),
                "features_source": features_source,
                "bpm": all_features.get("bpm"),
                "key": all_features.get("key"),
            }

    except AnalysisError as e:
        error_msg = str(e)[:500]
        logger.error(f"Feature extraction error for {track_id}: {error_msg}")
        _record_task_failure("extract_features", error_msg, track_info)

        # Mark track as failed in DB so it won't be retried immediately
        try:
            with sync_session_maker() as db:
                result = db.execute(
                    select(Track).where(Track.id == UUID(track_id))
                )
                track = result.scalar_one_or_none()
                if track:
                    track.analysis_error = error_msg
                    track.analysis_failed_at = datetime.utcnow()
                    track.analyzed_at = datetime.utcnow()
                    _ensure_track_analysis_row(db, track.id, FEATURES_VERSION)
                    db.commit()
        except Exception as db_error:
            logger.warning(f"Could not record analysis failure to DB: {db_error}")

        return {"error": error_msg, "status": "failed", "permanent": True}
    except StaleDataError:
        logger.info(f"Track {track_id} was deleted during analysis, skipping")
        return {"status": "skipped", "reason": "track_deleted"}
    except Exception as e:
        error_msg = str(e)[:500]
        logger.error(f"Error extracting features for {track_id}: {error_msg}")
        _record_task_failure("extract_features", error_msg, track_info)

        try:
            with sync_session_maker() as db:
                result = db.execute(
                    select(Track).where(Track.id == UUID(track_id))
                )
                track = result.scalar_one_or_none()
                if track:
                    track.analysis_error = error_msg
                    track.analysis_failed_at = datetime.utcnow()
                    track.analyzed_at = datetime.utcnow()
                    _ensure_track_analysis_row(db, track.id, FEATURES_VERSION)
                    db.commit()
        except Exception as db_error:
            logger.warning(f"Could not record analysis failure to DB: {db_error}")

        return {"error": error_msg, "status": "failed", "permanent": True}


def _record_embedding_failure(track_id: str, error_msg: str) -> None:
    """Record embedding failure in TrackAnalysis so sync loop doesn't get stuck.

    This is called from exception handlers to mark embeddings as failed,
    allowing the sync progress query to count them as "done" (either success or failed).
    """
    from sqlalchemy import select

    from app.db.models import TrackAnalysis
    from app.db.session import sync_session_maker

    try:
        with sync_session_maker() as db:
            result = db.execute(
                select(TrackAnalysis)
                .where(TrackAnalysis.track_id == UUID(track_id))
            )
            analysis = result.scalar_one_or_none()

            if analysis:
                analysis.embedding_error = error_msg[:500]
                analysis.embedding_failed_at = datetime.utcnow()
                db.commit()
                logger.info(f"Recorded embedding failure for track {track_id}")
            else:
                logger.warning(f"No TrackAnalysis record to record embedding failure for {track_id}")
    except Exception as db_error:
        logger.warning(f"Could not record embedding failure to DB: {db_error}")


def run_track_embedding(track_id: str) -> dict[str, Any]:
    """Extract CLAP embedding for a track - runs in subprocess via ProcessPoolExecutor.

    Phase 2 of analysis: CLAP embedding for similarity search.
    This runs in a separate subprocess from feature extraction to reduce peak memory.
    The CLAP model uses ~2-3GB of memory, so isolating it prevents OOM kills.

    Community Cache:
    Before running expensive CLAP extraction, checks if embedding is available in
    the community cache (keyed by AcoustID fingerprint hash). If contribution is
    enabled and we compute locally, the embedding is shared with other users.
    """
    import asyncio
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s',
        force=True,
    )

    from sqlalchemy import select

    from app.db.models import Track, TrackAnalysis
    from app.db.session import sync_session_maker
    from app.services.analysis import AnalysisError, extract_embedding
    from app.services.app_settings import get_app_settings_service
    from app.services.community_cache import get_community_cache_service

    log_memory("embedding_start")

    try:
        with sync_session_maker() as db:
            result = db.execute(
                select(Track).where(Track.id == UUID(track_id))
            )
            track = result.scalar_one_or_none()

            if not track:
                return {"error": f"Track not found: {track_id}", "permanent": True}

            file_path = Path(track.file_path)

            if not file_path.exists():
                return {"error": f"File not found: {track.file_path}", "permanent": True}

            logger.info(f"Extracting embedding: {track.title} by {track.artist}")

            # Get app settings for community cache
            app_settings = get_app_settings_service().get()
            embedding_source = "local"
            embedding: list[float] | None = None
            acoustid_fingerprint: str | None = None

            # Get the analysis record to get AcoustID fingerprint
            analysis_result = db.execute(
                select(TrackAnalysis)
                .where(TrackAnalysis.track_id == track.id)
            )
            existing_analysis = analysis_result.scalar_one_or_none()

            if existing_analysis and existing_analysis.acoustid:
                acoustid_fingerprint = existing_analysis.acoustid

            # Try community cache first if enabled
            if app_settings.community_cache_enabled and acoustid_fingerprint:
                try:
                    cache_service = get_community_cache_service(
                        cache_url=app_settings.community_cache_url
                    )
                    cached = asyncio.run(
                        cache_service.lookup(acoustid_fingerprint)
                    )
                    if cached:
                        embedding = cached.embedding
                        embedding_source = "community_cache"
                        logger.info(
                            f"Community cache hit for {track.title} "
                            f"(contributed by {cached.contributor_count} users)"
                        )
                except Exception as e:
                    logger.warning(f"Community cache lookup failed: {e}")

            # Fall back to local CLAP extraction if no cache hit
            if embedding is None:
                embedding = extract_embedding(file_path)
                embedding_source = "local"
                gc.collect()

                # Contribute to community cache if enabled and we have a fingerprint
                if (
                    embedding is not None
                    and app_settings.community_cache_contribute
                    and acoustid_fingerprint
                ):
                    try:
                        cache_service = get_community_cache_service(
                            cache_url=app_settings.community_cache_url
                        )
                        asyncio.run(
                            cache_service.contribute(acoustid_fingerprint, embedding)
                        )
                    except Exception as e:
                        logger.debug(f"Community cache contribution failed: {e}")

            log_memory("after_embedding")

            if embedding is None:
                # Embeddings disabled or failed - not an error, just skip
                logger.info(f"No embedding generated for {track.title} (CLAP disabled or failed)")
                return {
                    "track_id": track_id,
                    "status": "success",
                    "phase": "embedding",
                    "embedding_generated": False,
                }

            # Update the existing analysis record with embedding
            # We already have existing_analysis from earlier fingerprint lookup
            if existing_analysis:
                existing_analysis.embedding = embedding
                existing_analysis.embedding_source = embedding_source
                existing_analysis.embedding_version = EMBEDDING_VERSION
                db.commit()
                logger.info(f"Embedding saved for {track.title} (source={embedding_source})")
            else:
                # No analysis record yet - this shouldn't happen if phase 1 ran first
                logger.warning(f"No analysis record found for {track_id}, skipping embedding save")
                return {
                    "track_id": track_id,
                    "status": "skipped",
                    "reason": "no_analysis_record",
                    "embedding_generated": True,
                }

            gc.collect()
            log_memory("embedding_end")

            return {
                "track_id": track_id,
                "status": "success",
                "phase": "embedding",
                "embedding_generated": True,
                "embedding_source": embedding_source,
            }

    except AnalysisError as e:
        error_msg = str(e)[:500]
        logger.error(f"Embedding extraction error for {track_id}: {error_msg}")
        # Record embedding failure in TrackAnalysis so sync doesn't get stuck
        _record_embedding_failure(track_id, error_msg)
        return {"error": error_msg, "status": "partial", "phase": "embedding"}
    except StaleDataError:
        logger.info(f"Track {track_id} was deleted during embedding, skipping")
        return {"status": "skipped", "reason": "track_deleted"}
    except Exception as e:
        error_msg = str(e)[:500]
        logger.error(f"Error extracting embedding for {track_id}: {error_msg}")
        # Record embedding failure in TrackAnalysis so sync doesn't get stuck
        _record_embedding_failure(track_id, error_msg)
        return {"error": error_msg, "status": "partial", "phase": "embedding"}


def run_track_analysis(track_id: str) -> dict[str, Any]:
    """Analyze a single track - runs in subprocess via ProcessPoolExecutor.

    DEPRECATED: This function is kept for backwards compatibility.
    New code should use run_track_features + run_track_embedding separately.

    This combined function may cause OOM on memory-constrained systems.
    """
    # Run features first
    result = run_track_features(track_id)
    if result.get("status") != "success":
        return result

    # Then run embedding in same process (not ideal for memory, but maintains compatibility)
    embedding_result = run_track_embedding(track_id)

    # Merge results
    return {
        **result,
        "embedding_generated": embedding_result.get("embedding_generated", False),
    }


async def queue_tracks_for_features(limit: int = 500) -> int:
    """Queue tracks that need feature extraction (Phase 1).

    This includes tracks that haven't been analyzed or have old analysis version.
    Returns the number of tracks queued.
    """
    from sqlalchemy import or_, select

    from app.db.models import Track, TrackAnalysis
    from app.db.session import async_session_maker
    from app.services.background import get_background_manager

    queued = 0
    async with async_session_maker() as db:
        failure_cutoff = datetime.utcnow() - timedelta(hours=24)

        # Find tracks that need analysis:
        # 1. No TrackAnalysis row (never attempted)
        # 2. Outdated features_version
        # 3. Previously failed but 24h has passed (retry window open)
        result = await db.execute(
            select(Track.id)
            .outerjoin(TrackAnalysis, Track.id == TrackAnalysis.track_id)
            .where(
                or_(
                    TrackAnalysis.id.is_(None),
                    TrackAnalysis.features_version < FEATURES_VERSION,
                ),
                or_(
                    Track.analysis_failed_at.is_(None),
                    Track.analysis_failed_at < failure_cutoff,
                ),
            )
            .limit(limit)
        )
        track_ids = [str(row[0]) for row in result.fetchall()]

    if track_ids:
        manager = get_background_manager()
        for track_id in track_ids:
            await manager.run_analysis(track_id, phase="features")
            queued += 1

    return queued


async def queue_tracks_for_embeddings(limit: int = 500) -> int:
    """Queue tracks that need embedding generation (Phase 2).

    This includes tracks with features extracted but no embedding.
    Returns the number of tracks queued.
    """
    from sqlalchemy import and_, or_, select

    from app.db.models import Track, TrackAnalysis
    from app.db.session import async_session_maker
    from app.services.app_settings import get_app_settings_service
    from app.services.background import get_background_manager

    # Skip if CLAP is disabled via settings or env var
    clap_enabled, _ = get_app_settings_service().is_clap_embeddings_enabled()
    if not clap_enabled:
        return 0

    queued = 0
    async with async_session_maker() as db:
        failure_cutoff = datetime.utcnow() - timedelta(hours=24)

        # Find tracks with analysis record but outdated/missing embedding
        # Exclude tracks that recently failed embedding (within 24h) to avoid infinite retry
        result = await db.execute(
            select(Track.id)
            .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
            .where(
                and_(
                    TrackAnalysis.features_version >= FEATURES_VERSION,
                    TrackAnalysis.embedding_version < EMBEDDING_VERSION,
                    # Exclude recently-failed embeddings (use TrackAnalysis.embedding_failed_at)
                    or_(
                        TrackAnalysis.embedding_failed_at.is_(None),
                        TrackAnalysis.embedding_failed_at < failure_cutoff,
                    ),
                )
            )
            .limit(limit)
        )
        track_ids = [str(row[0]) for row in result.fetchall()]

    if track_ids:
        manager = get_background_manager()
        for track_id in track_ids:
            await manager.run_analysis(track_id, phase="embedding")
            queued += 1

    return queued


async def queue_tracks_for_melodic(limit: int = 500) -> int:
    """Queue tracks that need melodic analysis (Phase 3).

    This includes tracks with analysis_detail but has_melodic=False.
    Returns the number of tracks queued.
    """
    from sqlalchemy import and_, select

    from app.db.models import TrackAnalysis
    from app.db.session import async_session_maker
    from app.services.background import get_background_manager

    queued = 0
    async with async_session_maker() as db:
        result = await db.execute(
            select(TrackAnalysis.track_id)
            .where(
                and_(
                    TrackAnalysis.features_version >= FEATURES_VERSION,
                    TrackAnalysis.analysis_detail.is_not(None),
                    TrackAnalysis.melodic_version < MELODIC_VERSION,
                )
            )
            .limit(limit)
        )
        track_ids = [str(row[0]) for row in result.fetchall()]

    if track_ids:
        manager = get_background_manager()
        for track_id in track_ids:
            await manager.run_analysis(track_id, phase="melodic")
            queued += 1

    return queued


async def queue_tracks_for_backfill(limit: int = 500) -> int:
    """Queue tracks that need analysis backfill (deprecated, self-eliminating).

    Populates analysis_detail for tracks that have features but no structural data.
    Once all tracks have analysis_detail, this phase is a no-op.
    Remove after 2026-06-01.

    Returns the number of tracks queued.
    """
    from sqlalchemy import and_, select

    from app.db.models import TrackAnalysis
    from app.db.session import async_session_maker
    from app.services.background import get_background_manager

    queued = 0
    async with async_session_maker() as db:
        result = await db.execute(
            select(TrackAnalysis.track_id)
            .where(
                and_(
                    TrackAnalysis.features_version >= FEATURES_VERSION,
                    TrackAnalysis.analysis_detail.is_(None),
                )
            )
            .limit(limit)
        )
        track_ids = [str(row[0]) for row in result.fetchall()]

    if track_ids:
        manager = get_background_manager()
        for track_id in track_ids:
            await manager.run_analysis(track_id, phase="deep_backfill")
            queued += 1

    return queued


async def queue_unanalyzed_tracks(limit: int = 500) -> int:
    """Queue analysis for tracks that need analysis.

    DEPRECATED: Use queue_tracks_for_features() and queue_tracks_for_embeddings()
    for better memory efficiency and progress tracking.

    This function is kept for backwards compatibility and queues for full analysis.
    """
    from sqlalchemy import and_, or_, select

    from app.db.models import Track, TrackAnalysis
    from app.db.session import async_session_maker
    from app.services.analysis import get_analysis_capabilities
    from app.services.background import get_background_manager

    caps = get_analysis_capabilities()
    embeddings_enabled = caps["embeddings_enabled"]

    queued = 0
    async with async_session_maker() as db:
        failure_cutoff = datetime.utcnow() - timedelta(hours=24)

        result = await db.execute(
            select(Track.id)
            .outerjoin(TrackAnalysis, Track.id == TrackAnalysis.track_id)
            .where(
                or_(
                    TrackAnalysis.id.is_(None),
                    TrackAnalysis.features_version < FEATURES_VERSION,
                ),
                or_(
                    Track.analysis_failed_at.is_(None),
                    Track.analysis_failed_at < failure_cutoff,
                ),
            )
            .limit(limit)
        )
        track_ids = set(str(row[0]) for row in result.fetchall())

        # If embeddings are now enabled, also get tracks missing embeddings
        if embeddings_enabled and len(track_ids) < limit:
            remaining_limit = limit - len(track_ids)
            result = await db.execute(
                select(Track.id)
                .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
                .where(
                    and_(
                        TrackAnalysis.features_version >= FEATURES_VERSION,
                        TrackAnalysis.embedding_version < EMBEDDING_VERSION,
                        or_(
                            Track.analysis_failed_at.is_(None),
                            Track.analysis_failed_at < failure_cutoff,
                        ),
                    )
                )
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
