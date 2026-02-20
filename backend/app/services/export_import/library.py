"""Library export/import service for migration between machines.

Handles exporting and importing full library data including tracks,
analysis features, embeddings, and fingerprints.
"""

import base64
import gzip
import json
import logging
from collections.abc import AsyncGenerator
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from rapidfuzz import fuzz
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import EMBEDDING_VERSION, FEATURES_VERSION, MELODIC_VERSION, get_app_version
from app.db.models import Track, TrackAnalysis
from app.services.export_import.matching import (
    LibraryImportPreviewSession,
    _library_import_sessions,
)
from app.services.external_track_matcher import normalize_for_matching

logger = logging.getLogger(__name__)

# Library export schema version - separate from profile export
LIBRARY_EXPORT_VERSION = 3


class LibraryExportService:
    """Export full library data for migration to another machine.

    Exports tracks with:
    - File identifiers (file_hash, acoustid)
    - External IDs (isrc, musicbrainz)
    - Metadata (title, artist, album, etc.)
    - Analysis (features, embeddings)
    - User overrides
    """

    BATCH_SIZE = 500

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def export_library(
        self,
        include_embeddings: bool = True,
        include_acoustid: bool = True,
        include_midi: bool = True,
        include_ssm: bool = True,
        compress: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        """Stream library export as JSON (optionally gzipped).

        Yields chunks of data for streaming response.
        """
        # Get total track count
        count_result = await self.db.execute(select(func.count(Track.id)))
        total_tracks = count_result.scalar() or 0

        # Get analysis counts
        analysis_count_result = await self.db.execute(
            select(func.count(TrackAnalysis.id)).where(TrackAnalysis.features_version == FEATURES_VERSION)
        )
        tracks_with_analysis = analysis_count_result.scalar() or 0

        embedding_count_result = await self.db.execute(
            select(func.count(TrackAnalysis.id)).where(
                TrackAnalysis.features_version == FEATURES_VERSION,
                TrackAnalysis.embedding.isnot(None),
            )
        )
        tracks_with_embeddings = embedding_count_result.scalar() or 0

        melodic_count_result = await self.db.execute(
            select(func.count(TrackAnalysis.id)).where(
                TrackAnalysis.features_version == FEATURES_VERSION,
                TrackAnalysis.has_melodic.is_(True),
            )
        )
        tracks_with_melodic = melodic_count_result.scalar() or 0

        # Build header
        header = {
            "version": LIBRARY_EXPORT_VERSION,
            "export_type": "library",
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "familiar_version": get_app_version(),
            "analysis_version": FEATURES_VERSION,
            "embedding_version": EMBEDDING_VERSION,
            "melodic_version": MELODIC_VERSION,
            "stats": {
                "total_tracks": total_tracks,
                "tracks_with_analysis": tracks_with_analysis,
                "tracks_with_embeddings": tracks_with_embeddings,
                "tracks_with_melodic": tracks_with_melodic,
            },
            "options": {
                "include_embeddings": include_embeddings,
                "include_acoustid": include_acoustid,
            },
        }

        # Build full export data
        tracks_list: list[dict[str, Any]] = []
        export_data: dict[str, Any] = {**header, "tracks": tracks_list}

        # Fetch all tracks with analysis in batches
        offset = 0
        while True:
            result = await self.db.execute(
                select(Track, TrackAnalysis)
                .outerjoin(
                    TrackAnalysis,
                    (TrackAnalysis.track_id == Track.id) & (TrackAnalysis.features_version == FEATURES_VERSION),
                )
                .order_by(Track.id)
                .offset(offset)
                .limit(self.BATCH_SIZE)
            )
            rows = result.all()

            if not rows:
                break

            for track, analysis in rows:
                track_export = self._build_track_export(
                    track,
                    analysis,
                    include_embeddings=include_embeddings,
                    include_acoustid=include_acoustid,
                    include_midi=include_midi,
                    include_ssm=include_ssm,
                )
                tracks_list.append(track_export)

            offset += self.BATCH_SIZE

        # Serialize to JSON
        json_bytes = json.dumps(export_data, ensure_ascii=False).encode("utf-8")

        if compress:
            # Compress with gzip
            compressed = gzip.compress(json_bytes, compresslevel=6)
            yield compressed
        else:
            yield json_bytes

    def _build_track_export(
        self,
        track: Track,
        analysis: TrackAnalysis | None,
        include_embeddings: bool,
        include_acoustid: bool,
        include_midi: bool = True,
        include_ssm: bool = True,
    ) -> dict[str, Any]:
        """Build export dict for a single track."""
        export: dict[str, Any] = {
            # Matching identifiers (priority order)
            "file_hash": track.file_hash,
            "isrc": track.isrc,
            "musicbrainz_track_id": track.musicbrainz_track_id,
            # Basic metadata
            "title": track.title,
            "artist": track.artist,
            "album": track.album,
            "duration_seconds": track.duration_seconds,
            # Extended metadata
            "metadata": {
                "album_artist": track.album_artist,
                "track_number": track.track_number,
                "disc_number": track.disc_number,
                "year": track.year,
                "genre": track.genre,
                "musicbrainz_artist_id": track.musicbrainz_artist_id,
                "musicbrainz_album_id": track.musicbrainz_album_id,
                "composer": track.composer,
                "conductor": track.conductor,
                "lyricist": track.lyricist,
            },
        }

        # User overrides (if any)
        if track.user_overrides:
            export["user_overrides"] = track.user_overrides

        # Analysis data
        if analysis:
            analysis_export: dict[str, Any] = {
                "features_version": analysis.features_version,
                "features": analysis.to_features_dict(),
            }

            # Full analysis detail (melodic, harmonic, rhythmic, spectral, structural, energy)
            if analysis.analysis_detail:
                analysis_export["analysis_detail"] = analysis.analysis_detail
            if analysis.has_melodic:
                analysis_export["has_melodic"] = True
                analysis_export["melodic_version"] = analysis.melodic_version

            if include_embeddings and analysis.embedding is not None:
                # Convert numpy array to list for JSON serialization
                embedding_list = analysis.embedding.tolist() if hasattr(analysis.embedding, "tolist") else list(analysis.embedding)
                analysis_export["embedding"] = embedding_list
                analysis_export["embedding_version"] = analysis.embedding_version

            if include_acoustid:
                if analysis.acoustid:
                    analysis_export["acoustid"] = analysis.acoustid
                if analysis.acoustid_lookup:
                    analysis_export["acoustid_lookup"] = analysis.acoustid_lookup

            # MIDI file content
            if include_midi and analysis.midi_path:
                midi_file = Path(analysis.midi_path)
                if midi_file.exists():
                    analysis_export["midi_data"] = base64.b64encode(midi_file.read_bytes()).decode("ascii")
                    analysis_export["midi_path"] = analysis.midi_path

            # SSM PNG content
            if include_ssm and analysis.analysis_detail:
                ssm_path_str = (analysis.analysis_detail.get("structural") or {}).get("self_similarity_png_path")
                if ssm_path_str:
                    ssm_file = Path(ssm_path_str)
                    if ssm_file.exists():
                        analysis_export["ssm_data"] = base64.b64encode(ssm_file.read_bytes()).decode("ascii")

            export["analysis"] = analysis_export

        return export


class LibraryImportService:
    """Import library data with intelligent track matching.

    Matching priority:
    1. file_hash - SHA-256 of first/last chunks (exact same file)
    2. acoustid - Audio fingerprint (works across encodings)
    3. isrc - Industry standard recording ID
    4. musicbrainz_track_id - MusicBrainz recording UUID
    5. title + artist + duration - Exact match with duration within 3s
    6. title + artist (fuzzy) - RapidFuzz at 85% threshold
    """

    FUZZY_THRESHOLD = 85
    DURATION_TOLERANCE = 3.0  # seconds

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def preview_import(
        self,
        import_data: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        """Preview an import and return matching statistics.

        Args:
            import_data: Parsed export JSON

        Returns:
            Tuple of (session_id, preview_result)
        """
        import uuid as uuid_module

        session_id = str(uuid_module.uuid4())
        warnings: list[str] = []

        # Validate version
        version = import_data.get("version", 0)
        if version > LIBRARY_EXPORT_VERSION:
            warnings.append(
                f"Export version {version} is newer than supported version {LIBRARY_EXPORT_VERSION}"
            )

        export_type = import_data.get("export_type")
        if export_type != "library":
            warnings.append(f"Unexpected export type: {export_type}")

        # Build indexes for local library
        indexes = await self._build_local_indexes()

        # Match all exported tracks
        exported_tracks = import_data.get("tracks", [])
        matching_results: list[dict[str, Any]] = []
        method_counts: dict[str, int] = {
            "file_hash": 0,
            "acoustid": 0,
            "isrc": 0,
            "musicbrainz": 0,
            "exact_with_duration": 0,
            "fuzzy": 0,
        }
        unmatched_samples: list[dict[str, Any]] = []

        for export_track in exported_tracks:
            track_id, method, confidence = await self._match_track(export_track, indexes)

            matching_results.append({
                "file_hash": export_track.get("file_hash"),
                "title": export_track.get("title"),
                "artist": export_track.get("artist"),
                "matched_track_id": str(track_id) if track_id else None,
                "method": method,
                "confidence": confidence,
            })

            if track_id and method:
                method_counts[method] = method_counts.get(method, 0) + 1
            elif len(unmatched_samples) < 10:
                unmatched_samples.append({
                    "title": export_track.get("title"),
                    "artist": export_track.get("artist"),
                    "album": export_track.get("album"),
                })

        # Calculate stats
        matched_count = sum(1 for r in matching_results if r["matched_track_id"])
        unmatched_count = len(matching_results) - matched_count

        if unmatched_count > 0:
            warnings.append(f"{unmatched_count} track(s) could not be matched to your library")

        # Count what data is available
        tracks_with_analysis = sum(1 for t in exported_tracks if t.get("analysis"))
        tracks_with_embeddings = sum(
            1 for t in exported_tracks
            if t.get("analysis", {}).get("embedding")
        )
        tracks_with_user_overrides = sum(
            1 for t in exported_tracks if t.get("user_overrides")
        )

        summary = {
            "total_tracks": len(exported_tracks),
            "tracks_with_analysis": tracks_with_analysis,
            "tracks_with_embeddings": tracks_with_embeddings,
            "tracks_with_user_overrides": tracks_with_user_overrides,
            "analysis_version": import_data.get("analysis_version"),
        }

        # Store session
        session = LibraryImportPreviewSession(
            session_id=session_id,
            import_data=import_data,
            matching_results={"results": matching_results},
            summary=summary,
            warnings=warnings,
        )
        _library_import_sessions[session_id] = session

        return session_id, {
            "session_id": session_id,
            "summary": summary,
            "matching": {
                "total": len(matching_results),
                "matched": matched_count,
                "unmatched": unmatched_count,
                "by_method": method_counts,
                "unmatched_samples": unmatched_samples,
            },
            "warnings": warnings,
            "exported_at": import_data.get("exported_at"),
            "familiar_version": import_data.get("familiar_version"),
        }

    async def execute_import(
        self,
        session_id: str,
        mode: str = "match_only",
        apply_metadata: bool = False,
        apply_analysis: bool = True,
        apply_embeddings: bool = True,
        apply_user_overrides: bool = True,
    ) -> dict[str, Any]:
        """Execute an import from a previewed session.

        Args:
            session_id: Session ID from preview
            mode: Import mode - "match_only", "merge", or "replace"
            apply_metadata: Whether to update track metadata
            apply_analysis: Whether to import analysis features
            apply_embeddings: Whether to import embeddings
            apply_user_overrides: Whether to import user overrides

        Returns:
            Import results
        """
        session = _library_import_sessions.get(session_id)
        if not session:
            raise ValueError(f"Import session {session_id} not found or expired")

        import_data = session.import_data
        matching_results = session.matching_results.get("results", [])

        # Build lookup from matching results
        export_tracks = import_data.get("tracks", [])
        track_id_by_hash: dict[str, UUID] = {}
        for result in matching_results:
            if result.get("matched_track_id"):
                file_hash = result.get("file_hash")
                if file_hash:
                    track_id_by_hash[file_hash] = UUID(result["matched_track_id"])

        # Track import statistics
        analysis_imported = 0
        embeddings_imported = 0
        user_overrides_imported = 0
        metadata_updated = 0
        skipped = 0
        errors: list[str] = []

        try:
            for export_track in export_tracks:
                file_hash = export_track.get("file_hash")
                track_id = track_id_by_hash.get(file_hash) if file_hash else None

                if not track_id:
                    skipped += 1
                    continue

                try:
                    # Get track and its analysis
                    track = await self.db.get(Track, track_id)
                    if not track:
                        skipped += 1
                        continue

                    # Get or create analysis record
                    analysis_result = await self.db.execute(
                        select(TrackAnalysis).where(
                            TrackAnalysis.track_id == track_id,
                            TrackAnalysis.features_version == FEATURES_VERSION,
                        )
                    )
                    analysis = analysis_result.scalar_one_or_none()

                    export_analysis = export_track.get("analysis", {})

                    # Apply analysis features
                    if apply_analysis and export_analysis.get("features"):
                        if not analysis:
                            analysis = TrackAnalysis(
                                track_id=track_id,
                                features_version=FEATURES_VERSION,
                            )
                            self.db.add(analysis)

                        # Merge features (imported values fill gaps in typed columns)
                        from app.db.models import ANALYSIS_FEATURE_COLUMNS

                        imported_features = export_analysis.get("features", {})
                        for col in ANALYSIS_FEATURE_COLUMNS:
                            imported_val = imported_features.get(col)
                            if imported_val is not None:
                                existing_val = getattr(analysis, col, None)
                                if existing_val is None or mode == "replace":
                                    setattr(analysis, col, imported_val)

                        analysis.features_source = "library_import"
                        analysis_imported += 1

                        # Update track analysis status
                        if not track.analyzed_at:
                            track.analyzed_at = datetime.utcnow()

                    # Apply analysis_detail JSONB
                    imported_detail = export_analysis.get("analysis_detail")
                    if imported_detail and analysis:
                        if mode == "replace" or not analysis.analysis_detail:
                            analysis.analysis_detail = imported_detail
                        else:
                            # Merge: imported sections fill gaps
                            merged = {**imported_detail, **analysis.analysis_detail}
                            analysis.analysis_detail = merged

                    # Apply melodic metadata
                    if export_analysis.get("has_melodic") and analysis:
                        if not analysis.has_melodic or mode == "replace":
                            analysis.has_melodic = True
                            analysis.melodic_version = export_analysis.get("melodic_version", 0)

                    # Apply embeddings
                    if apply_embeddings and export_analysis.get("embedding"):
                        if analysis:
                            if analysis.embedding is None or mode == "replace":
                                analysis.embedding = export_analysis["embedding"]
                                analysis.embedding_version = export_analysis.get("embedding_version", EMBEDDING_VERSION)
                                analysis.embedding_source = "library_import"
                                embeddings_imported += 1

                    # Apply acoustid
                    if export_analysis.get("acoustid") and analysis:
                        if not analysis.acoustid:
                            analysis.acoustid = export_analysis["acoustid"]
                        if export_analysis.get("acoustid_lookup") and not analysis.acoustid_lookup:
                            analysis.acoustid_lookup = export_analysis["acoustid_lookup"]

                    # Apply MIDI file
                    midi_data = export_analysis.get("midi_data")
                    if midi_data and analysis:
                        from app.services.track_analysis import MIDI_DATA_DIR
                        MIDI_DATA_DIR.mkdir(parents=True, exist_ok=True)
                        midi_file = MIDI_DATA_DIR / f"{track_id}.mid"
                        midi_file.write_bytes(base64.b64decode(midi_data))
                        analysis.midi_path = str(midi_file)

                    # Apply SSM PNG
                    ssm_data = export_analysis.get("ssm_data")
                    if ssm_data and analysis:
                        from app.services.track_analysis import MIDI_DATA_DIR
                        MIDI_DATA_DIR.mkdir(parents=True, exist_ok=True)
                        ssm_file = MIDI_DATA_DIR / f"{track_id}_similarity.png"
                        ssm_file.write_bytes(base64.b64decode(ssm_data))
                        if analysis.analysis_detail and "structural" in analysis.analysis_detail:
                            analysis.analysis_detail = {
                                **analysis.analysis_detail,
                                "structural": {
                                    **analysis.analysis_detail["structural"],
                                    "self_similarity_png_path": str(ssm_file),
                                },
                            }

                    # Apply user overrides
                    if apply_user_overrides and export_track.get("user_overrides"):
                        existing_overrides = track.user_overrides or {}
                        imported_overrides = export_track["user_overrides"]
                        if mode == "replace":
                            track.user_overrides = imported_overrides
                        else:
                            # Merge (imported wins on conflict)
                            track.user_overrides = {**existing_overrides, **imported_overrides}
                        user_overrides_imported += 1

                    # Apply metadata (optional, usually not needed for same library)
                    if apply_metadata:
                        metadata = export_track.get("metadata", {})
                        # Only update fields that are missing locally
                        if mode != "replace":
                            if not track.musicbrainz_artist_id and metadata.get("musicbrainz_artist_id"):
                                track.musicbrainz_artist_id = metadata["musicbrainz_artist_id"]
                            if not track.musicbrainz_album_id and metadata.get("musicbrainz_album_id"):
                                track.musicbrainz_album_id = metadata["musicbrainz_album_id"]
                            if not track.isrc and export_track.get("isrc"):
                                track.isrc = export_track["isrc"]
                            if not track.musicbrainz_track_id and export_track.get("musicbrainz_track_id"):
                                track.musicbrainz_track_id = export_track["musicbrainz_track_id"]
                        metadata_updated += 1

                except Exception as e:
                    errors.append(
                        f"Error importing track {export_track.get('title', 'unknown')}: {e}"
                    )

            await self.db.commit()

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Library import failed: {e}", exc_info=True)
            raise

        finally:
            # Clean up session
            _library_import_sessions.pop(session_id, None)

        return {
            "status": "completed",
            "results": {
                "analysis_imported": analysis_imported,
                "embeddings_imported": embeddings_imported,
                "user_overrides_imported": user_overrides_imported,
                "metadata_updated": metadata_updated,
                "skipped": skipped,
                "errors": errors,
            },
        }

    async def _build_local_indexes(self) -> dict[str, dict[str, UUID]]:
        """Build lookup indexes from local library."""
        indexes: dict[str, dict[str, UUID]] = {
            "file_hash": {},
            "acoustid": {},
            "isrc": {},
            "musicbrainz": {},
            "exact": {},  # title:artist:duration key
        }

        # Index tracks
        result = await self.db.execute(
            select(
                Track.id,
                Track.file_hash,
                Track.isrc,
                Track.musicbrainz_track_id,
                Track.title,
                Track.artist,
                Track.duration_seconds,
            )
        )
        rows = result.all()

        for row in rows:
            track_id = row.id

            if row.file_hash:
                indexes["file_hash"][row.file_hash] = track_id

            if row.isrc:
                indexes["isrc"][row.isrc] = track_id

            if row.musicbrainz_track_id:
                indexes["musicbrainz"][row.musicbrainz_track_id] = track_id

            if row.title and row.artist:
                # Exact key with duration bucket
                duration_bucket = int(row.duration_seconds or 0)
                exact_key = f"{row.title.lower().strip()}:{row.artist.lower().strip()}:{duration_bucket}"
                indexes["exact"][exact_key] = track_id

        # Index acoustid from analysis
        analysis_result = await self.db.execute(
            select(TrackAnalysis.track_id, TrackAnalysis.acoustid).where(
                TrackAnalysis.acoustid.isnot(None)
            )
        )
        for analysis_row in analysis_result.all():
            if analysis_row.acoustid:
                # Use first 100 chars as key (fingerprints are long)
                acoustid_key = analysis_row.acoustid[:100]
                indexes["acoustid"][acoustid_key] = analysis_row.track_id

        return indexes

    async def _match_track(
        self,
        export_track: dict[str, Any],
        indexes: dict[str, dict[str, UUID]],
    ) -> tuple[UUID | None, str | None, float | None]:
        """Match an exported track to local library.

        Returns (track_id, method, confidence) or (None, None, None).
        """
        # 1. file_hash (confidence 1.0)
        file_hash = export_track.get("file_hash")
        if file_hash and file_hash in indexes["file_hash"]:
            return indexes["file_hash"][file_hash], "file_hash", 1.0

        # 2. acoustid (confidence 0.95)
        acoustid = export_track.get("analysis", {}).get("acoustid")
        if acoustid:
            acoustid_key = acoustid[:100]
            if acoustid_key in indexes["acoustid"]:
                return indexes["acoustid"][acoustid_key], "acoustid", 0.95

        # 3. isrc (confidence 0.95)
        isrc = export_track.get("isrc")
        if isrc and isrc in indexes["isrc"]:
            return indexes["isrc"][isrc], "isrc", 0.95

        # 4. musicbrainz_track_id (confidence 0.95)
        mb_id = export_track.get("musicbrainz_track_id")
        if mb_id and mb_id in indexes["musicbrainz"]:
            return indexes["musicbrainz"][mb_id], "musicbrainz", 0.95

        # 5. title + artist + duration (confidence 0.90)
        title = export_track.get("title")
        artist = export_track.get("artist")
        duration = export_track.get("duration_seconds")

        if title and artist and duration:
            # Try exact duration bucket
            duration_bucket = int(duration)
            exact_key = f"{title.lower().strip()}:{artist.lower().strip()}:{duration_bucket}"
            if exact_key in indexes["exact"]:
                return indexes["exact"][exact_key], "exact_with_duration", 0.90

            # Try +/-1 second buckets
            for offset in [-1, 1]:
                alt_key = f"{title.lower().strip()}:{artist.lower().strip()}:{duration_bucket + offset}"
                if alt_key in indexes["exact"]:
                    return indexes["exact"][alt_key], "exact_with_duration", 0.90

        # 6. Fuzzy matching (confidence 0.70-0.84)
        if title and artist:
            return await self._fuzzy_match(title, artist, duration)

        return None, None, None

    async def _fuzzy_match(
        self,
        title: str,
        artist: str,
        duration: float | None,
    ) -> tuple[UUID | None, str | None, float | None]:
        """Fuzzy match against all tracks."""
        normalized_title = normalize_for_matching(title)
        normalized_artist = normalize_for_matching(artist)

        # Get all tracks for fuzzy matching
        result = await self.db.execute(
            select(Track.id, Track.title, Track.artist, Track.duration_seconds).where(
                Track.title.isnot(None),
                Track.artist.isnot(None),
            )
        )
        tracks = result.all()

        best_match: UUID | None = None
        best_score: float = 0.0

        for track in tracks:
            if not track.title or not track.artist:
                continue

            local_title = normalize_for_matching(track.title)
            local_artist = normalize_for_matching(track.artist)

            # Calculate fuzzy scores
            title_score = fuzz.ratio(normalized_title, local_title)
            artist_score = fuzz.ratio(normalized_artist, local_artist)

            # Combined score with weights
            combined = (title_score * 0.6) + (artist_score * 0.4)

            # Duration disambiguation
            if duration and track.duration_seconds:
                duration_diff = abs(duration - track.duration_seconds)
                if duration_diff < self.DURATION_TOLERANCE:
                    combined = min(100, combined + 5)
                elif duration_diff > 30:
                    combined = combined * 0.9

            if combined >= self.FUZZY_THRESHOLD and combined > best_score:
                best_score = combined
                best_match = track.id

        if best_match:
            # Scale to 0.70-0.84 range
            confidence = 0.70 + (best_score - self.FUZZY_THRESHOLD) / 100 * 0.14
            return best_match, "fuzzy", min(confidence, 0.84)

        return None, None, None
