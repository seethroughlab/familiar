"""Search-related tool handlers (search_library, find_similar_tracks, semantic_search, filter_tracks)."""

from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select

from app.db.models import (
    ProfileFavorite,
    ProfilePlayHistory,
    Track,
    TrackAnalysis,
)
from app.utils.time import utcnow

if TYPE_CHECKING:
    from app.services.llm.executor import ToolExecutor

logger = logging.getLogger(__name__)


class SearchHandlersMixin:
    """Mixin providing search tool handlers."""

    async def _search_library(self: "ToolExecutor", query: str, limit: int = 20) -> dict[str, Any]:
        """Search tracks by text query with diversity across artists/albums."""
        # Convert limit to int (LLM may pass string)
        try:
            limit = int(float(limit)) if limit else 20
        except (ValueError, TypeError):
            limit = 20

        variations = self._normalize_query_variations(query)

        conditions = []
        for var in variations:
            search_filter = f"%{var}%"
            conditions.extend([
                Track.title.ilike(search_filter),
                Track.artist.ilike(search_filter),
                Track.album.ilike(search_filter),
                Track.genre.ilike(search_filter),
            ])

        stmt = select(Track).where(Track.active_filter(), or_(*conditions)).limit(limit * 5)
        result = await self.db.execute(stmt)
        all_tracks = list(result.scalars().all())

        diverse_tracks = self._apply_diversity(all_tracks, max_per_artist=2, max_per_album=3)
        random.shuffle(diverse_tracks)
        selected = diverse_tracks[:limit]

        return {
            "tracks": [self._track_to_dict(t) for t in selected],
            "count": len(selected),
            "note": f"Selected from {len(all_tracks)} matches with artist/album diversity",
        }

    async def _find_similar_tracks(self: "ToolExecutor", track_id: str, limit: int = 10) -> dict[str, Any]:
        """Find similar tracks using embedding similarity."""
        # Convert limit to int (LLM may pass string)
        try:
            limit = int(float(limit)) if limit else 10
        except (ValueError, TypeError):
            limit = 10

        stmt = (
            select(TrackAnalysis.embedding)
            .where(TrackAnalysis.track_id == UUID(track_id))
        )
        result = await self.db.execute(stmt)
        embedding = result.scalar_one_or_none()

        if embedding is None:
            return {"error": "Track not analyzed yet", "tracks": []}

        similar_stmt = (
            select(Track)
            .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
            .where(Track.active_filter())
            .where(Track.id != UUID(track_id))
            .where(TrackAnalysis.embedding.isnot(None))
            .order_by(TrackAnalysis.embedding.cosine_distance(embedding))
            .limit(limit * 4)
        )
        result = await self.db.execute(similar_stmt)
        all_tracks = list(result.scalars().all())

        diverse_tracks = self._apply_diversity(all_tracks, max_per_artist=2, max_per_album=2)
        selected = diverse_tracks[:limit]

        return {
            "tracks": [self._track_to_dict(t) for t in selected],
            "count": len(selected),
            "note": f"Similar tracks from {len(set(t.artist for t in selected))} different artists",
        }

    async def _semantic_search(self: "ToolExecutor", description: str, limit: int = 20) -> dict[str, Any]:
        """Search for tracks using text-to-audio semantic similarity via CLAP embeddings."""
        from app.services.analysis import extract_text_embedding, get_analysis_capabilities

        # Convert limit to int (LLM may pass string)
        try:
            limit = int(float(limit)) if limit else 20
        except (ValueError, TypeError):
            limit = 20

        # Check if semantic search is available
        caps = get_analysis_capabilities()
        if not caps["embeddings_enabled"]:
            return {
                "error": f"Semantic search unavailable: {caps['embeddings_disabled_reason']}",
                "tracks": [],
                "fallback_suggestion": "Try search_library or filter_tracks_by_features instead",
            }

        # Get text embedding
        embedding = extract_text_embedding(description)
        if embedding is None:
            return {
                "error": "Failed to generate text embedding",
                "tracks": [],
                "fallback_suggestion": "Try search_library or filter_tracks_by_features instead",
            }

        # Query for similar tracks using cosine distance
        similar_stmt = (
            select(Track)
            .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
            .where(Track.active_filter())
            .where(TrackAnalysis.embedding.isnot(None))
            .order_by(TrackAnalysis.embedding.cosine_distance(embedding))
            .limit(limit * 4)  # Fetch extra for diversity filtering
        )
        result = await self.db.execute(similar_stmt)
        all_tracks = list(result.scalars().all())

        # Apply diversity filtering
        diverse_tracks = self._apply_diversity(all_tracks, max_per_artist=2, max_per_album=3)
        random.shuffle(diverse_tracks)
        selected = diverse_tracks[:limit]

        return {
            "tracks": [self._track_to_dict(t) for t in selected],
            "count": len(selected),
            "description": description,
            "note": f"Found {len(selected)} tracks matching '{description}' from {len(set(t.artist for t in selected))} artists",
        }

    async def _filter_tracks(
        self: "ToolExecutor",
        # Library criteria
        genre: str | None = None,
        artist: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        added_in_last_days: int | None = None,
        is_favorite: bool | None = None,
        min_play_count: int | None = None,
        max_play_count: int | None = None,
        played_in_last_days: int | None = None,
        not_played_in_days: int | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        # Audio feature criteria
        bpm_min: float | None = None,
        bpm_max: float | None = None,
        key: str | None = None,
        energy_min: float | None = None,
        energy_max: float | None = None,
        danceability_min: float | None = None,
        valence_min: float | None = None,
        valence_max: float | None = None,
        acousticness_min: float | None = None,
        instrumentalness_min: float | None = None,
        # Analysis feature criteria
        swing_min: float | None = None,
        swing_max: float | None = None,
        syncopation_min: float | None = None,
        brightness_min: float | None = None,
        brightness_max: float | None = None,
        dynamic_range_min: float | None = None,
        energy_shape: str | None = None,
        modal_character: str | None = None,
        key_stability: str | None = None,
        section_count_min: int | None = None,
        section_count_max: int | None = None,
        note_density_min: float | None = None,
        note_density_max: float | None = None,
        # New filter params
        harmonic_complexity_min: float | None = None,
        harmonic_complexity_max: float | None = None,
        speechiness_min: float | None = None,
        speechiness_max: float | None = None,
        tempo_character: str | None = None,
        pitch_range_min: int | None = None,
        pitch_range_max: int | None = None,
        mood_tag: str | None = None,
        tempo_cv_max: float | None = None,
        lyrics_language: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Filter tracks by library criteria and/or audio features."""
        from datetime import timedelta

        # --- Type coercion helpers (LLM may pass strings) ---
        def to_float(v: Any) -> float | None:
            if v is None:
                return None
            try:
                return float(v)
            except (ValueError, TypeError):
                return None

        def to_int(v: Any, default: int | None = None) -> int | None:
            if v is None:
                return default
            try:
                return int(float(v))
            except (ValueError, TypeError):
                return default

        def to_bool(v: Any) -> bool | None:
            if v is None:
                return None
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.lower() in ("true", "1", "yes")
            return bool(v)

        # Coerce all params
        bpm_min = to_float(bpm_min)
        bpm_max = to_float(bpm_max)
        energy_min = to_float(energy_min)
        energy_max = to_float(energy_max)
        danceability_min = to_float(danceability_min)
        valence_min = to_float(valence_min)
        valence_max = to_float(valence_max)
        acousticness_min = to_float(acousticness_min)
        instrumentalness_min = to_float(instrumentalness_min)
        year_min = to_int(year_min)
        year_max = to_int(year_max)
        added_in_last_days = to_int(added_in_last_days)
        is_favorite = to_bool(is_favorite)
        min_play_count = to_int(min_play_count)
        max_play_count = to_int(max_play_count)
        played_in_last_days = to_int(played_in_last_days)
        not_played_in_days = to_int(not_played_in_days)
        limit = to_int(limit, 20) or 20

        # --- Determine which joins are needed ---
        has_audio_features = any(v is not None for v in [
            bpm_min, bpm_max, key, energy_min, energy_max,
            danceability_min, valence_min, valence_max,
            acousticness_min, instrumentalness_min,
            # Deep analysis features
            swing_min, swing_max, syncopation_min,
            brightness_min, brightness_max, dynamic_range_min,
            energy_shape, modal_character, key_stability,
            section_count_min, section_count_max,
            note_density_min, note_density_max,
            harmonic_complexity_min, harmonic_complexity_max,
            speechiness_min, speechiness_max,
            tempo_character, pitch_range_min, pitch_range_max,
            mood_tag, tempo_cv_max,
        ])
        needs_play_history = any(v is not None for v in [
            min_play_count, max_play_count, played_in_last_days, not_played_in_days,
        ]) or (sort_by in ("play_count", "last_played"))

        # --- Build query ---
        stmt = select(Track).where(Track.active_filter())

        # Join TrackAnalysis only when audio feature filters are used
        if has_audio_features:
            stmt = stmt.join(TrackAnalysis, Track.id == TrackAnalysis.track_id)

        # Join ProfileFavorite when is_favorite filter is used
        if is_favorite and self.profile_id:
            stmt = stmt.join(
                ProfileFavorite,
                and_(
                    ProfileFavorite.track_id == Track.id,
                    ProfileFavorite.profile_id == self.profile_id,
                ),
            )

        # Left outer join ProfilePlayHistory when play history filters/sort are used
        if needs_play_history and self.profile_id:
            stmt = stmt.outerjoin(
                ProfilePlayHistory,
                and_(
                    ProfilePlayHistory.track_id == Track.id,
                    ProfilePlayHistory.profile_id == self.profile_id,
                ),
            )

        conditions: list[Any] = []

        # --- Library criteria ---
        if genre is not None:
            conditions.append(Track.genre.ilike(f"%{genre}%"))
        if artist is not None:
            conditions.append(Track.artist.ilike(f"%{artist}%"))
        if year_min is not None:
            conditions.append(Track.year >= year_min)
        if year_max is not None:
            conditions.append(Track.year <= year_max)
        if added_in_last_days is not None:
            cutoff = utcnow() - timedelta(days=added_in_last_days)
            conditions.append(Track.created_at >= cutoff)

        # Play count filters (require profile + play history join)
        if needs_play_history and self.profile_id:
            if min_play_count is not None:
                conditions.append(
                    func.coalesce(ProfilePlayHistory.play_count, 0) >= min_play_count
                )
            if max_play_count is not None:
                if max_play_count == 0:
                    # Never played = no play history row at all
                    conditions.append(ProfilePlayHistory.track_id.is_(None))
                else:
                    conditions.append(
                        func.coalesce(ProfilePlayHistory.play_count, 0) <= max_play_count
                    )
            if played_in_last_days is not None:
                cutoff = utcnow() - timedelta(days=played_in_last_days)
                conditions.append(ProfilePlayHistory.last_played_at >= cutoff)
            if not_played_in_days is not None:
                cutoff = utcnow() - timedelta(days=not_played_in_days)
                conditions.append(
                    or_(
                        ProfilePlayHistory.last_played_at.is_(None),
                        ProfilePlayHistory.last_played_at < cutoff,
                    )
                )

        # --- Audio feature criteria (typed columns on TrackAnalysis) ---
        if bpm_min is not None:
            conditions.append(TrackAnalysis.bpm >= bpm_min)
        if bpm_max is not None:
            conditions.append(TrackAnalysis.bpm <= bpm_max)
        if key is not None:
            key_normalized = key.strip()
            key_upper = key_normalized.upper()

            # Detect minor mode from input
            is_minor = False
            if key_upper.endswith("M") and not key_upper.endswith("#M"):
                is_minor = True
                key_upper = key_upper[:-1]
            elif "MINOR" in key_upper:
                is_minor = True
                key_upper = key_upper.replace("MINOR", "").strip()
            elif "MAJOR" in key_upper:
                key_upper = key_upper.replace("MAJOR", "").strip()

            # Normalize root note
            key_root = key_upper.split()[0]
            if "SHARP" in key_upper:
                key_root = key_root.rstrip("#") + "#"
            elif "FLAT" in key_upper:
                flat_to_sharp = {"BB": "A#", "EB": "D#", "AB": "G#", "DB": "C#", "GB": "F#"}
                clean = key_root.rstrip("B")
                lookup = clean + "B" if clean + "B" in flat_to_sharp else key_root
                if lookup in flat_to_sharp:
                    key_root = flat_to_sharp[lookup]
            else:
                flat_to_sharp = {"BB": "A#", "EB": "D#", "AB": "G#", "DB": "C#", "GB": "F#"}
                if key_root in flat_to_sharp:
                    key_root = flat_to_sharp[key_root]

            if is_minor:
                # Explicitly minor: match only "Am", "F#m", etc.
                conditions.append(TrackAnalysis.key == key_root + "m")
            elif key_normalized.endswith("m") and len(key_normalized) <= 4:
                # Short minor notation like "Am", "F#m"
                conditions.append(TrackAnalysis.key == key_normalized)
            else:
                # Plain key like "A" — match both major ("A") and minor ("Am")
                conditions.append(
                    or_(
                        TrackAnalysis.key == key_root,
                        TrackAnalysis.key == key_root + "m",
                    )
                )
        if energy_min is not None:
            conditions.append(TrackAnalysis.energy >= energy_min)
        if energy_max is not None:
            conditions.append(TrackAnalysis.energy <= energy_max)
        if danceability_min is not None:
            conditions.append(TrackAnalysis.danceability >= danceability_min)
        if valence_min is not None:
            conditions.append(TrackAnalysis.valence >= valence_min)
        if valence_max is not None:
            conditions.append(TrackAnalysis.valence <= valence_max)
        if acousticness_min is not None:
            conditions.append(TrackAnalysis.acousticness >= acousticness_min)
        if instrumentalness_min is not None:
            conditions.append(TrackAnalysis.instrumentalness >= instrumentalness_min)

        # --- Analysis feature criteria (coerce types) ---
        swing_min = to_float(swing_min)
        swing_max = to_float(swing_max)
        syncopation_min = to_float(syncopation_min)
        brightness_min = to_float(brightness_min)
        brightness_max = to_float(brightness_max)
        dynamic_range_min = to_float(dynamic_range_min)
        section_count_min = to_int(section_count_min)
        section_count_max = to_int(section_count_max)
        note_density_min = to_float(note_density_min)
        note_density_max = to_float(note_density_max)
        harmonic_complexity_min = to_float(harmonic_complexity_min)
        harmonic_complexity_max = to_float(harmonic_complexity_max)
        speechiness_min = to_float(speechiness_min)
        speechiness_max = to_float(speechiness_max)
        pitch_range_min = to_int(pitch_range_min)
        pitch_range_max = to_int(pitch_range_max)

        if swing_min is not None:
            conditions.append(TrackAnalysis.swing_ratio >= swing_min)
        if swing_max is not None:
            conditions.append(TrackAnalysis.swing_ratio <= swing_max)
        if syncopation_min is not None:
            conditions.append(TrackAnalysis.syncopation >= syncopation_min)
        if brightness_min is not None:
            conditions.append(TrackAnalysis.brightness >= brightness_min)
        if brightness_max is not None:
            conditions.append(TrackAnalysis.brightness <= brightness_max)
        if dynamic_range_min is not None:
            conditions.append(TrackAnalysis.dynamic_range_db >= dynamic_range_min)
        if energy_shape is not None:
            conditions.append(TrackAnalysis.energy_shape == energy_shape)
        if modal_character is not None:
            conditions.append(TrackAnalysis.modal_character.ilike(f"%{modal_character}%"))
            # Quality gate: only trust mode detection with reasonable confidence
            conditions.append(TrackAnalysis.modal_confidence >= 0.4)
        if key_stability is not None:
            conditions.append(TrackAnalysis.key_stability == key_stability)
        if section_count_min is not None:
            conditions.append(TrackAnalysis.section_count >= section_count_min)
        if section_count_max is not None:
            conditions.append(TrackAnalysis.section_count <= section_count_max)
        if note_density_min is not None:
            conditions.append(TrackAnalysis.note_density >= note_density_min)
        if note_density_max is not None:
            conditions.append(TrackAnalysis.note_density <= note_density_max)
        if harmonic_complexity_min is not None:
            conditions.append(TrackAnalysis.harmonic_complexity >= harmonic_complexity_min)
        if harmonic_complexity_max is not None:
            conditions.append(TrackAnalysis.harmonic_complexity <= harmonic_complexity_max)
        if speechiness_min is not None:
            conditions.append(TrackAnalysis.speechiness >= speechiness_min)
        if speechiness_max is not None:
            conditions.append(TrackAnalysis.speechiness <= speechiness_max)
        if tempo_character is not None:
            conditions.append(TrackAnalysis.tempo_character == tempo_character)
        if pitch_range_min is not None:
            conditions.append(TrackAnalysis.pitch_range >= pitch_range_min)
        if pitch_range_max is not None:
            conditions.append(TrackAnalysis.pitch_range <= pitch_range_max)
        if mood_tag is not None:
            # JSONB containment query: mood_tags @> '[{"tag": "dreamy"}]'
            import json
            conditions.append(
                TrackAnalysis.mood_tags.op("@>")(
                    json.dumps([{"tag": mood_tag.lower().strip()}])
                )
            )

        tempo_cv_max = to_float(tempo_cv_max)
        if tempo_cv_max is not None:
            conditions.append(TrackAnalysis.tempo_cv <= tempo_cv_max)

        if lyrics_language is not None:
            conditions.append(Track.lyrics_language == lyrics_language.strip().lower())

        for condition in conditions:
            stmt = stmt.where(condition)

        # --- Sorting ---
        use_random = sort_by is None or sort_by == "random"

        if not use_random:
            # Default sort directions per sort_by
            default_desc = {"play_count", "last_played", "recently_added"}
            effective_order = sort_order or ("desc" if sort_by in default_desc else "asc")
            is_desc = effective_order == "desc"

            sort_column: Any = None
            if sort_by == "play_count" and self.profile_id:
                sort_column = func.coalesce(ProfilePlayHistory.play_count, 0)
            elif sort_by == "last_played" and self.profile_id:
                sort_column = ProfilePlayHistory.last_played_at
            elif sort_by == "recently_added":
                sort_column = Track.created_at
            elif sort_by == "title":
                sort_column = Track.title
            elif sort_by == "artist":
                sort_column = Track.artist
            elif sort_by == "year":
                sort_column = Track.year

            if sort_column is not None:
                stmt = stmt.order_by(sort_column.desc() if is_desc else sort_column.asc())

        stmt = stmt.limit(limit * 5)
        result = await self.db.execute(stmt)
        all_tracks = list(result.scalars().all())

        diverse_tracks = self._apply_diversity(all_tracks, max_per_artist=2, max_per_album=3)

        if use_random:
            random.shuffle(diverse_tracks)

        selected = diverse_tracks[:limit]

        return {
            "tracks": [self._track_to_dict(t) for t in selected],
            "count": len(selected),
            "note": f"Selected from {len(all_tracks)} matches with artist/album diversity",
        }
