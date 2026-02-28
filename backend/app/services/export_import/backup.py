"""Backup/restore service for combined profile and library data.

Creates unified backup files that include both profile data (playlists,
favorites, play history) and library analysis data (features, embeddings).
"""

import base64
import gzip
import json
import logging
from collections.abc import AsyncGenerator
from datetime import datetime
from app.utils.time import utcnow
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import EMBEDDING_VERSION, FEATURES_VERSION, MELODIC_VERSION, get_app_version
from app.db.models import Profile, Track, TrackAnalysis
from app.services.export_import.library import LibraryExportService, LibraryImportService
from app.services.export_import.matching import (
    BackupPreviewSession,
    TrackMatcher,
    _backup_import_sessions,
)
from app.services.export_import.profile import ExportImportService, ImportService

logger = logging.getLogger(__name__)

# Backup format version
BACKUP_VERSION = 2


class BackupService:
    """Backup service for profile and library data.

    Creates a single backup file that can include:
    - Profile data (playlists, favorites, play history, etc.)
    - Library analysis data (features, embeddings, fingerprints)
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.profile_export = ExportImportService(db)
        self.library_export = LibraryExportService(db)

    async def create_backup(
        self,
        profile: Profile,
        # Profile data options
        include_play_history: bool = True,
        include_favorites: bool = True,
        include_playlists: bool = True,
        include_smart_playlists: bool = True,
        include_proposed_changes: bool = True,
        include_external_tracks: bool = True,
        # Library data options
        include_library_analysis: bool = False,
        include_embeddings: bool = True,
        include_acoustid: bool = True,
        include_midi: bool = True,
        include_ssm: bool = True,
        # Output options
        compress: bool = True,
        chat_history: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[bytes, None]:
        """Create a unified backup file.

        Yields chunks of data for streaming response.
        """
        # Build the backup structure
        export_data: dict[str, Any] = {
            "version": BACKUP_VERSION,
            "export_type": "backup",
            "exported_at": utcnow().isoformat() + "Z",
            "familiar_version": get_app_version(),
            "includes": {
                "profile_data": any([
                    include_play_history,
                    include_favorites,
                    include_playlists,
                    include_smart_playlists,
                    include_proposed_changes,
                    include_external_tracks,
                ]),
                "library_analysis": include_library_analysis,
            },
        }

        # Add profile data
        profile_data_included = export_data["includes"]["profile_data"]
        if profile_data_included:
            profile_export = await self.profile_export.export_profile(
                profile=profile,
                include_play_history=include_play_history,
                include_favorites=include_favorites,
                include_playlists=include_playlists,
                include_smart_playlists=include_smart_playlists,
                include_proposed_changes=include_proposed_changes,
                include_external_tracks=include_external_tracks,
                chat_history=chat_history,
            )

            # Copy profile data fields (excluding version/timestamp which we already have)
            export_data["profile"] = profile_export.get("profile")
            if include_play_history:
                export_data["play_history"] = profile_export.get("play_history", [])
            if include_favorites:
                export_data["favorites"] = profile_export.get("favorites", [])
            if include_playlists:
                export_data["playlists"] = profile_export.get("playlists", [])
            if include_smart_playlists:
                export_data["smart_playlists"] = profile_export.get("smart_playlists", [])
            if include_proposed_changes:
                export_data["proposed_changes"] = profile_export.get("proposed_changes", [])
                export_data["user_overrides"] = profile_export.get("user_overrides", [])
            if include_external_tracks:
                export_data["external_tracks"] = profile_export.get("external_tracks", [])
            if chat_history:
                export_data["chat_history"] = chat_history

        # Add library data
        if include_library_analysis:
            # Build library data structure
            library_data = await self._build_library_data(
                include_embeddings=include_embeddings,
                include_acoustid=include_acoustid,
                include_midi=include_midi,
                include_ssm=include_ssm,
            )
            export_data["library"] = library_data

        # Serialize to JSON
        json_bytes = json.dumps(export_data, ensure_ascii=False).encode("utf-8")

        if compress:
            # Compress with gzip
            compressed = gzip.compress(json_bytes, compresslevel=6)
            yield compressed
        else:
            yield json_bytes

    async def _build_library_data(
        self,
        include_embeddings: bool,
        include_acoustid: bool,
        include_midi: bool = True,
        include_ssm: bool = True,
    ) -> dict[str, Any]:
        """Build library data section for export."""
        # Get counts
        count_result = await self.db.execute(select(func.count(Track.id)))
        total_tracks = count_result.scalar() or 0

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

        library_data: dict[str, Any] = {
            "analysis_version": FEATURES_VERSION,
            "embedding_version": EMBEDDING_VERSION,
            "melodic_version": MELODIC_VERSION,
            "stats": {
                "total_tracks": total_tracks,
                "tracks_with_analysis": tracks_with_analysis,
                "tracks_with_embeddings": tracks_with_embeddings,
                "tracks_with_melodic": tracks_with_melodic,
            },
            "tracks": [],
        }

        # Export all tracks with analysis — delegate to LibraryExportService
        batch_size = 500
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
                .limit(batch_size)
            )
            rows = result.all()

            if not rows:
                break

            for track, analysis in rows:
                track_export = self.library_export._build_track_export(
                    track,
                    analysis,
                    include_embeddings=include_embeddings,
                    include_acoustid=include_acoustid,
                    include_midi=include_midi,
                    include_ssm=include_ssm,
                )
                library_data["tracks"].append(track_export)

            offset += batch_size

        return library_data


class RestoreService:
    """Service for restoring from backup files."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.profile_import = ImportService(db)
        self.library_import = LibraryImportService(db)

    async def preview_import(
        self,
        import_data: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        """Preview an import and return matching statistics."""
        import uuid as uuid_module

        session_id = str(uuid_module.uuid4())
        warnings: list[str] = []

        # Validate format
        export_type = import_data.get("export_type")
        if export_type != "backup":
            raise ValueError(f"Invalid backup file: expected export_type 'backup', got '{export_type}'")

        # Validate version
        version = import_data.get("version", 0)
        if version > BACKUP_VERSION:
            warnings.append(f"Backup version {version} is newer than supported version {BACKUP_VERSION}")

        includes = import_data.get("includes", {})
        summary: dict[str, Any] = {
            "has_profile_data": includes.get("profile_data", False),
            "has_library_data": includes.get("library_analysis", False),
        }

        profile_matching_results: dict[str, Any] | None = None
        library_matching_results: dict[str, Any] | None = None
        profile_summary: dict[str, Any] = {}
        library_summary: dict[str, Any] = {}
        profile_matching: dict[str, Any] = {}
        library_matching: dict[str, Any] = {}

        # Process profile data if present
        if summary["has_profile_data"]:
            profile_preview = await self._preview_profile_data(import_data)
            profile_summary = profile_preview["summary"]
            profile_matching = profile_preview["matching"]
            profile_matching_results = profile_preview["matching_results"]
            warnings.extend(profile_preview["warnings"])

        # Process library data if present
        if summary["has_library_data"]:
            library_data = import_data.get("library", {})
            library_preview = await self._preview_library_data(library_data)
            library_summary = library_preview["summary"]
            library_matching = library_preview["matching"]
            library_matching_results = library_preview["matching_results"]
            warnings.extend(library_preview["warnings"])

        # Build combined summary
        summary["profile"] = profile_summary
        summary["library"] = library_summary

        # Store session
        session = BackupPreviewSession(
            session_id=session_id,
            import_data=import_data,
            profile_matching_results=profile_matching_results,
            library_matching_results=library_matching_results,
            summary=summary,
            warnings=warnings,
        )
        _backup_import_sessions[session_id] = session

        return session_id, {
            "session_id": session_id,
            "summary": summary,
            "profile_matching": profile_matching,
            "library_matching": library_matching,
            "warnings": warnings,
            "exported_at": import_data.get("exported_at"),
            "familiar_version": import_data.get("familiar_version"),
            "profile_name": import_data.get("profile", {}).get("name"),
        }

    async def _preview_profile_data(
        self,
        import_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Preview profile data portion of import."""
        matcher = TrackMatcher(self.db)
        warnings: list[str] = []

        # Collect all track refs
        all_track_refs: list[dict[str, Any]] = []
        track_ref_sources: list[str] = []

        play_history = import_data.get("play_history", [])
        for entry in play_history:
            if "track_ref" in entry:
                all_track_refs.append(entry["track_ref"])
                track_ref_sources.append("play_history")

        favorites = import_data.get("favorites", [])
        for entry in favorites:
            if "track_ref" in entry:
                all_track_refs.append(entry["track_ref"])
                track_ref_sources.append("favorites")

        playlists = import_data.get("playlists", [])
        for playlist in playlists:
            for track in playlist.get("tracks", []):
                if track.get("type") == "local" and "track_ref" in track:
                    all_track_refs.append(track["track_ref"])
                    track_ref_sources.append("playlists")

        user_overrides = import_data.get("user_overrides", [])
        for entry in user_overrides:
            if "track_ref" in entry:
                all_track_refs.append(entry["track_ref"])
                track_ref_sources.append("user_overrides")

        proposed_changes = import_data.get("proposed_changes", [])
        for change in proposed_changes:
            for ref in change.get("target_refs", []):
                all_track_refs.append(ref)
                track_ref_sources.append("proposed_changes")

        # Match all track refs
        match_results = await matcher.match_batch(all_track_refs)

        matched_count = sum(1 for _, track, _, _ in match_results if track is not None)
        unmatched_count = len(match_results) - matched_count

        method_counts = {"isrc": 0, "musicbrainz": 0, "exact": 0, "fuzzy": 0}
        for _, track, method, _ in match_results:
            if track and method:
                method_counts[method] = method_counts.get(method, 0) + 1

        unmatched_samples: list[dict[str, Any]] = []
        for ref, track, _, _ in match_results:
            if track is None and len(unmatched_samples) < 10:
                unmatched_samples.append({
                    "title": ref.get("title"),
                    "artist": ref.get("artist"),
                    "album": ref.get("album"),
                })

        if unmatched_count > 0:
            warnings.append(f"{unmatched_count} track(s) could not be matched to your library")

        summary = {
            "play_history_count": len(play_history),
            "favorites_count": len(favorites),
            "playlists_count": len(playlists),
            "smart_playlists_count": len(import_data.get("smart_playlists", [])),
            "proposed_changes_count": len(proposed_changes),
            "user_overrides_count": len(user_overrides),
            "external_tracks_count": len(import_data.get("external_tracks", [])),
            "chat_history_count": len(import_data.get("chat_history", [])),
        }

        matching_results = {
            "results": [
                {
                    "ref": ref,
                    "track_id": str(track.id) if track else None,
                    "method": method,
                    "confidence": confidence,
                }
                for ref, track, method, confidence in match_results
            ],
            "sources": track_ref_sources,
        }

        return {
            "summary": summary,
            "matching": {
                "total": len(match_results),
                "matched": matched_count,
                "unmatched": unmatched_count,
                "by_method": method_counts,
                "unmatched_samples": unmatched_samples,
            },
            "matching_results": matching_results,
            "warnings": warnings,
        }

    async def _preview_library_data(
        self,
        library_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Preview library data portion of import."""
        warnings: list[str] = []

        # Build indexes for local library
        indexes = await self.library_import._build_local_indexes()

        exported_tracks = library_data.get("tracks", [])
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
            track_id, method, confidence = await self.library_import._match_track(export_track, indexes)

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

        matched_count = sum(1 for r in matching_results if r["matched_track_id"])
        unmatched_count = len(matching_results) - matched_count

        if unmatched_count > 0:
            warnings.append(f"{unmatched_count} track(s) could not be matched to your library")

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
            "analysis_version": library_data.get("analysis_version"),
        }

        return {
            "summary": summary,
            "matching": {
                "total": len(matching_results),
                "matched": matched_count,
                "unmatched": unmatched_count,
                "by_method": method_counts,
                "unmatched_samples": unmatched_samples,
            },
            "matching_results": {"results": matching_results},
            "warnings": warnings,
        }

    async def execute_import(
        self,
        session_id: str,
        profile: Profile,
        # Profile import options
        mode: str = "merge",
        import_play_history: bool = True,
        import_favorites: bool = True,
        import_playlists: bool = True,
        import_smart_playlists: bool = True,
        import_proposed_changes: bool = True,
        import_user_overrides: bool = True,
        import_external_tracks: bool = True,
        # Library import options
        library_mode: str = "match_only",
        apply_analysis: bool = True,
        apply_embeddings: bool = True,
        apply_library_user_overrides: bool = True,
    ) -> dict[str, Any]:
        """Execute a restore from a previewed session."""
        session = _backup_import_sessions.get(session_id)
        if not session:
            raise ValueError(f"Import session {session_id} not found or expired")

        import_data = session.import_data

        results: dict[str, Any] = {
            "profile": None,
            "library": None,
        }

        try:
            # Import profile data
            if session.summary.get("has_profile_data", False) and session.profile_matching_results:
                profile_results = await self._execute_profile_import(
                    import_data=import_data,
                    profile=profile,
                    matching_results=session.profile_matching_results,
                    mode=mode,
                    import_play_history=import_play_history,
                    import_favorites=import_favorites,
                    import_playlists=import_playlists,
                    import_smart_playlists=import_smart_playlists,
                    import_proposed_changes=import_proposed_changes,
                    import_user_overrides=import_user_overrides,
                    import_external_tracks=import_external_tracks,
                )
                results["profile"] = profile_results

            # Import library data
            if session.summary.get("has_library_data", False) and session.library_matching_results:
                library_data = import_data.get("library", {})
                library_results = await self._execute_library_import(
                    library_data=library_data,
                    matching_results=session.library_matching_results,
                    mode=library_mode,
                    apply_analysis=apply_analysis,
                    apply_embeddings=apply_embeddings,
                    apply_user_overrides=apply_library_user_overrides,
                )
                results["library"] = library_results

            await self.db.commit()

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Restore failed: {e}", exc_info=True)
            raise

        finally:
            _backup_import_sessions.pop(session_id, None)

        return {
            "status": "completed",
            "results": results,
        }

    async def _execute_profile_import(
        self,
        import_data: dict[str, Any],
        profile: Profile,
        matching_results: dict[str, Any],
        mode: str,
        import_play_history: bool,
        import_favorites: bool,
        import_playlists: bool,
        import_smart_playlists: bool,
        import_proposed_changes: bool,
        import_user_overrides: bool,
        import_external_tracks: bool,
    ) -> dict[str, Any]:
        """Execute the profile data import portion."""
        from uuid import UUID

        # Build track_id lookup from matching results
        track_id_lookup: dict[str, UUID] = {}
        for result in matching_results.get("results", []):
            if result.get("track_id"):
                ref = result["ref"]
                ref_key = self.profile_import._ref_to_key(ref)
                track_id_lookup[ref_key] = UUID(result["track_id"])

        results: dict[str, Any] = {
            "play_history": {"imported": 0, "skipped": 0, "errors": []},
            "favorites": {"imported": 0, "skipped": 0, "errors": []},
            "playlists": {"imported": 0, "skipped": 0, "errors": []},
            "smart_playlists": {"imported": 0, "skipped": 0, "errors": []},
            "proposed_changes": {"imported": 0, "skipped": 0, "errors": []},
            "user_overrides": {"imported": 0, "skipped": 0, "errors": []},
            "external_tracks": {"imported": 0, "skipped": 0, "errors": []},
            "chat_history": import_data.get("chat_history", []),
        }

        if import_play_history:
            results["play_history"] = await self.profile_import._import_play_history(
                profile.id, import_data.get("play_history", []),
                track_id_lookup, mode,
            )

        if import_favorites:
            results["favorites"] = await self.profile_import._import_favorites(
                profile.id, import_data.get("favorites", []),
                track_id_lookup, mode,
            )

        if import_playlists:
            results["playlists"] = await self.profile_import._import_playlists(
                profile.id, import_data.get("playlists", []),
                track_id_lookup, mode,
            )

        if import_smart_playlists:
            results["smart_playlists"] = await self.profile_import._import_smart_playlists(
                profile.id, import_data.get("smart_playlists", []), mode,
            )

        if import_user_overrides:
            results["user_overrides"] = await self.profile_import._import_user_overrides(
                import_data.get("user_overrides", []), track_id_lookup,
            )

        if import_external_tracks:
            results["external_tracks"] = await self.profile_import._import_external_tracks(
                import_data.get("external_tracks", []),
            )

        return results

    async def _execute_library_import(
        self,
        library_data: dict[str, Any],
        matching_results: dict[str, Any],
        mode: str,
        apply_analysis: bool,
        apply_embeddings: bool,
        apply_user_overrides: bool,
    ) -> dict[str, Any]:
        """Execute the library data import portion."""
        from uuid import UUID

        # Build lookup from matching results
        export_tracks = library_data.get("tracks", [])
        track_id_by_hash: dict[str, UUID] = {}
        for result in matching_results.get("results", []):
            if result.get("matched_track_id"):
                file_hash = result.get("file_hash")
                if file_hash:
                    track_id_by_hash[file_hash] = UUID(result["matched_track_id"])

        analysis_imported = 0
        embeddings_imported = 0
        user_overrides_imported = 0
        skipped = 0
        errors: list[str] = []

        for export_track in export_tracks:
            file_hash = export_track.get("file_hash")
            track_id = track_id_by_hash.get(file_hash) if file_hash else None

            if not track_id:
                skipped += 1
                continue

            try:
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

                    # Merge features into typed columns
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

                    if not track.analyzed_at:
                        track.analyzed_at = utcnow()

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
                        track.user_overrides = {**existing_overrides, **imported_overrides}
                    user_overrides_imported += 1

            except Exception as e:
                errors.append(
                    f"Error importing track {export_track.get('title', 'unknown')}: {e}"
                )

        return {
            "analysis_imported": analysis_imported,
            "embeddings_imported": embeddings_imported,
            "user_overrides_imported": user_overrides_imported,
            "skipped": skipped,
            "errors": errors,
        }
