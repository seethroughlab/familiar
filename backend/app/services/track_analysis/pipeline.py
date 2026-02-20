"""Analysis pipeline entry points for track analysis.

Top-level picklable functions for ProcessPoolExecutor:
run_analysis, run_backfill, run_track_melodic, run_cheap_sections.

Also contains extract_feature_scalars and extract_melodic_scalars.
"""

import logging
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np

from app.config import MELODIC_VERSION
from app.services.track_analysis.analyzers import (
    _add_melodic_sketches,
    _analyze_energy,
    _analyze_harmonic,
    _analyze_melodic,
    _analyze_rhythmic,
    _analyze_spectral,
    _analyze_structural,
    _precompute_shared,
)
from app.services.track_analysis.constants import MIN_DURATION_SECONDS
from app.services.track_analysis.utils import _sanitize_for_json

logger = logging.getLogger(__name__)


# ─── Cheap section analysis (runs during Phase 1) ────────────────────────────

def run_cheap_sections(
    y: np.ndarray,
    sr: int,
    shared: dict[str, Any],
    file_path: str,
    track_id: str,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, str]]]:
    """Run the 5 cheap section analyzers (everything except melodic/basic-pitch).

    Returns (analysis_detail, feature_scalars, section_errors).
    - analysis_detail: full structured data for report generation
    - feature_scalars: typed column values for TrackAnalysis
    - section_errors: list of {section, error} for any failed sections
    """
    results: dict[str, Any] = {}
    section_errors: list[dict[str, str]] = []

    for section_name, analyzer in [
        ("harmonic", _analyze_harmonic),
        ("rhythmic", _analyze_rhythmic),
        ("spectral", _analyze_spectral),
        ("structural", _analyze_structural),
        ("energy", _analyze_energy),
    ]:
        try:
            results[section_name] = analyzer(y, sr, shared, file_path, track_id)
        except Exception as e:
            logger.error(f"Section '{section_name}' failed for {track_id}: {e}")
            section_errors.append({"section": section_name, "error": str(e)})
            results[section_name] = {"error": str(e)}

    # Post-processing: melodic sketches per section (uses chroma, not basic-pitch)
    try:
        _add_melodic_sketches(results, shared)
    except Exception as e:
        logger.warning(f"Melodic sketch generation failed: {e}")

    results = _sanitize_for_json(results)
    section_errors = _sanitize_for_json(section_errors)

    feature_scalars = extract_feature_scalars(results)
    return results, feature_scalars, section_errors


def extract_feature_scalars(results: dict[str, Any]) -> dict[str, Any]:
    """Extract typed column values from analysis results.

    Maps section result keys to TrackAnalysis column names.
    Returns a flat dict suitable for setattr() on TrackAnalysis.
    """
    scalars: dict[str, Any] = {}

    # Harmonic section
    harmonic = results.get("harmonic", {})
    if harmonic.get("harmonic_content"):
        scalars["harmonic_complexity"] = harmonic.get("harmonic_rhythm")
        scalars["key_stability"] = harmonic.get("key_stability")
        scalars["modal_character"] = harmonic.get("modal_character")
        scalars["modal_confidence"] = harmonic.get("modal_confidence")

    # Rhythmic section
    rhythmic = results.get("rhythmic", {})
    raw_swing = rhythmic.get("swing_ratio")
    if raw_swing is not None:
        # Normalize: analysis stores 0-100, typed column uses 0-1
        scalars["swing_ratio"] = raw_swing / 100.0 if raw_swing > 1 else raw_swing
    syncopation = rhythmic.get("syncopation_index")
    if syncopation is not None:
        scalars["syncopation"] = syncopation
    scalars["tempo_character"] = rhythmic.get("tempo_stability")

    # Spectral section
    spectral = results.get("spectral", {})
    centroid_hz = spectral.get("centroid_hz")
    if centroid_hz is not None:
        # Normalize centroid to 0-1 (8000 Hz = 1.0)
        scalars["brightness"] = min(centroid_hz / 8000.0, 1.0)
    else:
        # Fallback: map string brightness label to numeric
        br_label = spectral.get("brightness")
        if br_label == "dark":
            scalars["brightness"] = 0.1
        elif br_label == "neutral":
            scalars["brightness"] = 0.5
        elif br_label == "bright":
            scalars["brightness"] = 0.9

    # Energy section
    energy = results.get("energy", {})
    scalars["dynamic_range_db"] = energy.get("dynamic_range_db")
    raw_shape = energy.get("energy_shape")
    if raw_shape:
        # Normalize to underscore format
        scalars["energy_shape"] = raw_shape.replace(" ", "_").replace("-", "_")

    # Structural section
    structural = results.get("structural", {})
    scalars["section_count"] = structural.get("section_count")
    scalars["form_string"] = structural.get("form")
    scalars["avg_section_length"] = structural.get("avg_section_length")

    # Remove None values
    return {k: v for k, v in scalars.items() if v is not None}


def extract_melodic_scalars(melodic_results: dict[str, Any]) -> dict[str, Any]:
    """Extract typed column values from melodic analysis results."""
    scalars: dict[str, Any] = {}

    if melodic_results.get("degraded"):
        return scalars

    scalars["note_density"] = melodic_results.get("note_density_per_beat")
    scalars["interval_character"] = melodic_results.get("interval_character")

    pitch_range = melodic_results.get("pitch_range")
    if isinstance(pitch_range, dict):
        low = pitch_range.get("low")
        high = pitch_range.get("high")
        if low is not None and high is not None:
            scalars["pitch_range"] = high - low

    return {k: v for k, v in scalars.items() if v is not None}


# ─── Entry point (top-level picklable for ProcessPoolExecutor) ─────────────

def run_analysis(track_id: str) -> dict[str, Any]:
    """Run analysis for a single track (on-demand, all 6 sections).

    Creates its own sync DB session (same pattern as run_track_features).
    Returns a summary dict with status.
    """
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s", force=True)

    from sqlalchemy import select

    from app.db.models import Track, TrackAnalysis
    from app.db.session import sync_session_maker

    start_time = time.time()

    try:
        with sync_session_maker() as db:
            # Load track
            result = db.execute(select(Track).where(Track.id == UUID(track_id)))
            track = result.scalar_one_or_none()

            if not track:
                return {"status": "error", "error": f"Track not found: {track_id}"}

            file_path = Path(track.file_path)
            if not file_path.exists():
                return {"status": "error", "error": f"File not found: {file_path}"}

            # Check duration
            if track.duration_seconds and track.duration_seconds < MIN_DURATION_SECONDS:
                return {"status": "skipped", "reason": "Track too short for analysis"}

            # Get latest analysis row
            analysis = db.execute(
                select(TrackAnalysis)
                .where(TrackAnalysis.track_id == UUID(track_id))
            ).scalar_one_or_none()

            if not analysis:
                return {"status": "error", "error": "No analysis row exists \u2014 run Phase 1 first"}

            # Check cache: if analysis_detail exists, has melodic, and version is current
            if (analysis.analysis_detail and analysis.has_melodic
                    and "melodic" in analysis.analysis_detail
                    and (analysis.melodic_version or 0) >= MELODIC_VERSION):
                return {"status": "cached", "track_id": track_id}

            # Load audio
            import librosa
            y, sr = librosa.load(str(file_path), sr=22050, mono=True)

            # Check for near-silence
            rms_all = librosa.feature.rms(y=y)[0]
            if np.mean(rms_all) < 1e-6:
                return {"status": "skipped", "reason": "Track is near-silence"}

            # Pre-compute shared representations
            shared = _precompute_shared(y, sr)

            need_cheap = analysis.analysis_detail is None
            need_melodic = (
                not analysis.has_melodic
                or (analysis.analysis_detail is not None and "melodic" not in analysis.analysis_detail)
                or (analysis.melodic_version or 0) < MELODIC_VERSION
            )

            results = dict(analysis.analysis_detail) if analysis.analysis_detail else {}
            section_errors: list[dict[str, str]] = []

            # Run cheap sections if needed
            if need_cheap:
                cheap_results, feature_scalars, section_errors = run_cheap_sections(
                    y, sr, shared, str(file_path), track_id
                )
                results.update(cheap_results)
                for col, val in feature_scalars.items():
                    setattr(analysis, col, val)

            # Run melodic analysis if needed
            if need_melodic:
                try:
                    melodic_result = _analyze_melodic(y, sr, shared, str(file_path), track_id)
                    results["melodic"] = _sanitize_for_json(melodic_result)

                    melodic_scalars = extract_melodic_scalars(results["melodic"])
                    for col, val in melodic_scalars.items():
                        setattr(analysis, col, val)

                    midi_path = results["melodic"].get("midi_path")
                    if midi_path:
                        analysis.midi_path = midi_path
                    analysis.has_melodic = not results["melodic"].get("degraded", False)
                except Exception as e:
                    logger.error(f"Melodic analysis failed for {track_id}: {e}")
                    section_errors.append({"section": "melodic", "error": str(e)})
                    results["melodic"] = {"error": str(e)}

            elapsed = time.time() - start_time

            analysis.analysis_detail = results
            analysis.melodic_version = MELODIC_VERSION
            db.commit()

            logger.info(
                f"Analysis complete for {track.artist} - {track.title} "
                f"({elapsed:.1f}s, {len(section_errors)} section errors)"
            )

            return {
                "status": "success",
                "track_id": track_id,
                "duration_seconds": elapsed,
                "section_errors": section_errors,
            }

    except Exception as e:
        logger.error(f"Analysis failed for {track_id}: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


def run_backfill(track_id: str) -> dict[str, Any]:
    """Backfill analysis for existing tracks (cheap sections only).

    Top-level picklable function for ProcessPoolExecutor.
    For tracks that already have Phase 1 features but no analysis_detail.
    """
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s", force=True)

    from sqlalchemy import select

    from app.db.models import Track, TrackAnalysis
    from app.db.session import sync_session_maker

    start_time = time.time()

    try:
        with sync_session_maker() as db:
            result = db.execute(select(Track).where(Track.id == UUID(track_id)))
            track = result.scalar_one_or_none()

            if not track:
                return {"status": "error", "error": f"Track not found: {track_id}"}

            file_path = Path(track.file_path)
            if not file_path.exists():
                return {"status": "error", "error": f"File not found: {file_path}"}

            if track.duration_seconds and track.duration_seconds < MIN_DURATION_SECONDS:
                return {"status": "skipped", "reason": "Track too short"}

            analysis = db.execute(
                select(TrackAnalysis)
                .where(TrackAnalysis.track_id == UUID(track_id))
            ).scalar_one_or_none()

            if not analysis:
                return {"status": "error", "error": "No analysis row"}

            if analysis.analysis_detail is not None:
                return {"status": "cached", "track_id": track_id}

            import librosa
            y, sr = librosa.load(str(file_path), sr=22050, mono=True)

            rms_all = librosa.feature.rms(y=y)[0]
            if np.mean(rms_all) < 1e-6:
                return {"status": "skipped", "reason": "Near-silence"}

            shared = _precompute_shared(y, sr)
            results, feature_scalars, section_errors = run_cheap_sections(
                y, sr, shared, str(file_path), track_id
            )

            analysis.analysis_detail = results
            for col, val in feature_scalars.items():
                setattr(analysis, col, val)
            db.commit()

            elapsed = time.time() - start_time
            logger.info(
                f"Deep backfill complete for {track.artist} - {track.title} ({elapsed:.1f}s)"
            )
            return {
                "status": "success",
                "track_id": track_id,
                "duration_seconds": elapsed,
                "section_errors": section_errors,
            }

    except Exception as e:
        logger.error(f"Deep backfill failed for {track_id}: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


def run_track_melodic(track_id: str) -> dict[str, Any]:
    """Run Phase 3 melodic analysis for a single track.

    Top-level picklable function for ProcessPoolExecutor.
    Runs basic-pitch MIDI transcription + melodic feature extraction.
    """
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s", force=True)

    from sqlalchemy import select

    from app.db.models import Track, TrackAnalysis
    from app.db.session import sync_session_maker

    start_time = time.time()

    try:
        with sync_session_maker() as db:
            result = db.execute(select(Track).where(Track.id == UUID(track_id)))
            track = result.scalar_one_or_none()

            if not track:
                return {"status": "error", "error": f"Track not found: {track_id}"}

            file_path = Path(track.file_path)
            if not file_path.exists():
                return {"status": "error", "error": f"File not found: {file_path}"}

            if track.duration_seconds and track.duration_seconds < MIN_DURATION_SECONDS:
                return {"status": "skipped", "reason": "Track too short"}

            analysis = db.execute(
                select(TrackAnalysis)
                .where(TrackAnalysis.track_id == UUID(track_id))
            ).scalar_one_or_none()

            if not analysis:
                return {"status": "error", "error": "No analysis row"}

            if analysis.melodic_version >= MELODIC_VERSION:
                return {"status": "cached", "track_id": track_id}

            import librosa
            y, sr = librosa.load(str(file_path), sr=22050, mono=True)

            rms_all = librosa.feature.rms(y=y)[0]
            if np.mean(rms_all) < 1e-6:
                return {"status": "skipped", "reason": "Near-silence"}

            shared = _precompute_shared(y, sr)

            try:
                melodic_result = _analyze_melodic(y, sr, shared, str(file_path), track_id)
                melodic_result = _sanitize_for_json(melodic_result)
            except Exception as e:
                logger.error(f"Melodic analysis failed for {track_id}: {e}")
                return {"status": "error", "error": str(e)}

            # Merge melodic into analysis_detail
            detail = dict(analysis.analysis_detail) if analysis.analysis_detail else {}
            detail["melodic"] = melodic_result
            analysis.analysis_detail = detail

            # Set typed columns
            melodic_scalars = extract_melodic_scalars(melodic_result)
            for col, val in melodic_scalars.items():
                setattr(analysis, col, val)

            midi_path = melodic_result.get("midi_path")
            if midi_path:
                analysis.midi_path = midi_path
            analysis.has_melodic = not melodic_result.get("degraded", False)
            analysis.melodic_version = MELODIC_VERSION
            db.commit()

            elapsed = time.time() - start_time
            logger.info(
                f"Melodic analysis complete for {track.artist} - {track.title} ({elapsed:.1f}s)"
            )
            return {"status": "success", "track_id": track_id, "duration_seconds": elapsed}

    except Exception as e:
        logger.error(f"Melodic analysis failed for {track_id}: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}
