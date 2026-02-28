"""Profile data export/import service.

Handles exporting and importing user data (playcounts, playlists, favorites,
smart playlists, metadata corrections, external tracks, chat history) for
backup and migration purposes.
"""

import logging
from datetime import datetime
from app.utils.time import utcnow
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_app_version
from app.db.models import (
    ExternalTrack,
    ExternalTrackSource,
    Playlist,
    PlaylistTrack,
    Profile,
    ProfileFavorite,
    ProfilePlayHistory,
    ProposedChange,
    SmartPlaylist,
    Track,
)
from app.services.export_import.matching import (
    ImportPreviewSession,
    TrackMatcher,
    _import_sessions,
)

logger = logging.getLogger(__name__)

# Export schema version - increment when making breaking changes
EXPORT_VERSION = 1


class ExportImportService:
    """Service for exporting and importing user data."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _build_track_ref(self, track: Track) -> dict[str, Any]:
        """Build a track reference for export."""
        return {
            "isrc": track.isrc,
            "musicbrainz_id": track.musicbrainz_track_id,
            "title": track.title,
            "artist": track.artist,
            "album": track.album,
            "duration_seconds": track.duration_seconds,
        }

    def _build_external_track_ref(self, ext: ExternalTrack) -> dict[str, Any]:
        """Build an external track export dict."""
        return {
            "title": ext.title,
            "artist": ext.artist,
            "album": ext.album,
            "duration_seconds": ext.duration_seconds,
            "track_number": ext.track_number,
            "year": ext.year,
            "isrc": ext.isrc,
            "spotify_id": ext.spotify_id,
            "musicbrainz_recording_id": ext.musicbrainz_recording_id,
            "deezer_id": ext.deezer_id,
            "external_data": ext.external_data,
            "source": ext.source.value if ext.source else None,
        }

    async def export_profile(
        self,
        profile: Profile,
        include_play_history: bool = True,
        include_favorites: bool = True,
        include_playlists: bool = True,
        include_smart_playlists: bool = True,
        include_proposed_changes: bool = True,
        include_external_tracks: bool = True,
        chat_history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Export all data for a profile.

        Args:
            profile: The profile to export
            include_*: Flags for what to include
            chat_history: Chat history from frontend (passed through)

        Returns:
            Export data dict
        """
        export_data: dict[str, Any] = {
            "version": EXPORT_VERSION,
            "exported_at": utcnow().isoformat() + "Z",
            "familiar_version": get_app_version(),
            "profile": {
                "name": profile.name,
                "color": profile.color,
                "settings": profile.settings or {},
            },
        }

        if include_play_history:
            export_data["play_history"] = await self._export_play_history(profile.id)

        if include_favorites:
            export_data["favorites"] = await self._export_favorites(profile.id)

        if include_playlists:
            export_data["playlists"] = await self._export_playlists(profile.id)

        if include_smart_playlists:
            export_data["smart_playlists"] = await self._export_smart_playlists(profile.id)

        if include_proposed_changes:
            export_data["proposed_changes"] = await self._export_proposed_changes()
            export_data["user_overrides"] = await self._export_user_overrides()

        if include_external_tracks:
            export_data["external_tracks"] = await self._export_external_tracks()

        if chat_history:
            export_data["chat_history"] = chat_history

        return export_data

    async def _export_play_history(self, profile_id: UUID) -> list[dict[str, Any]]:
        """Export play history for a profile."""
        result = await self.db.execute(
            select(ProfilePlayHistory, Track)
            .join(Track, ProfilePlayHistory.track_id == Track.id)
            .where(ProfilePlayHistory.profile_id == profile_id)
        )
        rows = result.all()

        history = []
        for ph, track in rows:
            history.append({
                "track_ref": self._build_track_ref(track),
                "play_count": ph.play_count,
                "last_played_at": ph.last_played_at.isoformat() + "Z" if ph.last_played_at else None,
                "total_play_seconds": ph.total_play_seconds,
            })

        return history

    async def _export_favorites(self, profile_id: UUID) -> list[dict[str, Any]]:
        """Export favorites for a profile."""
        result = await self.db.execute(
            select(ProfileFavorite, Track)
            .join(Track, ProfileFavorite.track_id == Track.id)
            .where(ProfileFavorite.profile_id == profile_id)
        )
        rows = result.all()

        favorites = []
        for fav, track in rows:
            favorites.append({
                "track_ref": self._build_track_ref(track),
                "favorited_at": fav.favorited_at.isoformat() + "Z" if fav.favorited_at else None,
            })

        return favorites

    async def _export_playlists(self, profile_id: UUID) -> list[dict[str, Any]]:
        """Export playlists for a profile."""
        result = await self.db.execute(
            select(Playlist).where(Playlist.profile_id == profile_id)
        )
        playlists = result.scalars().all()

        exported = []
        for playlist in playlists:
            # Get playlist tracks with their data
            tracks_result = await self.db.execute(
                select(PlaylistTrack)
                .where(PlaylistTrack.playlist_id == playlist.id)
                .order_by(PlaylistTrack.position)
            )
            playlist_tracks = tracks_result.scalars().all()

            tracks_data = []
            for pt in playlist_tracks:
                if pt.track_id:
                    # Local track
                    track = await self.db.get(Track, pt.track_id)
                    if track:
                        tracks_data.append({
                            "type": "local",
                            "track_ref": self._build_track_ref(track),
                            "position": pt.position,
                        })
                elif pt.external_track_id:
                    # External track
                    ext = await self.db.get(ExternalTrack, pt.external_track_id)
                    if ext:
                        tracks_data.append({
                            "type": "external",
                            "external_track": self._build_external_track_ref(ext),
                            "position": pt.position,
                        })

            exported.append({
                "name": playlist.name,
                "description": playlist.description,
                "is_auto_generated": playlist.is_auto_generated,
                "is_wishlist": playlist.is_wishlist,
                "generation_prompt": playlist.generation_prompt,
                "tracks": tracks_data,
                "created_at": playlist.created_at.isoformat() + "Z" if playlist.created_at else None,
            })

        return exported

    async def _export_smart_playlists(self, profile_id: UUID) -> list[dict[str, Any]]:
        """Export smart playlists for a profile."""
        result = await self.db.execute(
            select(SmartPlaylist).where(SmartPlaylist.profile_id == profile_id)
        )
        smart_playlists = result.scalars().all()

        exported = []
        for sp in smart_playlists:
            exported.append({
                "name": sp.name,
                "description": sp.description,
                "rules": sp.rules,
                "match_mode": sp.match_mode,
                "order_by": sp.order_by,
                "order_direction": sp.order_direction,
                "max_tracks": sp.max_tracks,
            })

        return exported

    async def _export_proposed_changes(self) -> list[dict[str, Any]]:
        """Export pending proposed changes."""
        result = await self.db.execute(
            select(ProposedChange).where(ProposedChange.status == "pending")
        )
        changes = result.scalars().all()

        exported = []
        for change in changes:
            # Get track refs for targets
            target_refs = []
            for target_id in change.target_ids:
                try:
                    track = await self.db.get(Track, UUID(target_id))
                    if track:
                        target_refs.append(self._build_track_ref(track))
                except (ValueError, TypeError):
                    continue

            if target_refs:
                exported.append({
                    "change_type": change.change_type,
                    "target_type": change.target_type,
                    "target_refs": target_refs,
                    "field": change.field,
                    "old_value": change.old_value,
                    "new_value": change.new_value,
                    "source": change.source.value if change.source else None,
                    "source_detail": change.source_detail,
                    "confidence": change.confidence,
                    "reason": change.reason,
                    "scope": change.scope.value if change.scope else None,
                })

        return exported

    async def _export_user_overrides(self) -> list[dict[str, Any]]:
        """Export user overrides from tracks."""
        result = await self.db.execute(
            select(Track).where(Track.user_overrides != {})
        )
        tracks = result.scalars().all()

        exported = []
        for track in tracks:
            if track.user_overrides:
                exported.append({
                    "track_ref": self._build_track_ref(track),
                    "overrides": track.user_overrides,
                })

        return exported

    async def _export_external_tracks(self) -> list[dict[str, Any]]:
        """Export external tracks (wishlist items, unmatched tracks)."""
        result = await self.db.execute(select(ExternalTrack))
        external_tracks = result.scalars().all()

        return [self._build_external_track_ref(ext) for ext in external_tracks]


class ImportService:
    """Service for importing user data."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.matcher = TrackMatcher(db)

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
        if version > EXPORT_VERSION:
            warnings.append(f"Export version {version} is newer than supported version {EXPORT_VERSION}")

        # Collect all track refs from the import
        all_track_refs: list[dict[str, Any]] = []
        track_ref_sources: list[str] = []

        # Play history track refs
        play_history = import_data.get("play_history", [])
        for entry in play_history:
            if "track_ref" in entry:
                all_track_refs.append(entry["track_ref"])
                track_ref_sources.append("play_history")

        # Favorites track refs
        favorites = import_data.get("favorites", [])
        for entry in favorites:
            if "track_ref" in entry:
                all_track_refs.append(entry["track_ref"])
                track_ref_sources.append("favorites")

        # Playlist track refs (local tracks only)
        playlists = import_data.get("playlists", [])
        for playlist in playlists:
            for track in playlist.get("tracks", []):
                if track.get("type") == "local" and "track_ref" in track:
                    all_track_refs.append(track["track_ref"])
                    track_ref_sources.append("playlists")

        # User overrides track refs
        user_overrides = import_data.get("user_overrides", [])
        for entry in user_overrides:
            if "track_ref" in entry:
                all_track_refs.append(entry["track_ref"])
                track_ref_sources.append("user_overrides")

        # Proposed changes track refs
        proposed_changes = import_data.get("proposed_changes", [])
        for change in proposed_changes:
            for ref in change.get("target_refs", []):
                all_track_refs.append(ref)
                track_ref_sources.append("proposed_changes")

        # Match all track refs
        match_results = await self.matcher.match_batch(all_track_refs)

        # Build matching statistics
        matched_count = sum(1 for _, track, _, _ in match_results if track is not None)
        unmatched_count = len(match_results) - matched_count

        # Categorize by method
        method_counts = {"isrc": 0, "musicbrainz": 0, "exact": 0, "fuzzy": 0}
        for _, track, method, _ in match_results:
            if track and method:
                method_counts[method] = method_counts.get(method, 0) + 1

        # Get sample unmatched tracks
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

        # Build summary
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

        # Store matching results for later use
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

        # Store session
        session = ImportPreviewSession(
            session_id=session_id,
            import_data=import_data,
            matching_results=matching_results,
            summary=summary,
            warnings=warnings,
        )
        _import_sessions[session_id] = session

        return session_id, {
            "session_id": session_id,
            "summary": summary,
            "matching": {
                "total": len(match_results),
                "matched": matched_count,
                "unmatched": unmatched_count,
                "by_method": method_counts,
                "unmatched_samples": unmatched_samples,
            },
            "warnings": warnings,
            "exported_at": import_data.get("exported_at"),
            "familiar_version": import_data.get("familiar_version"),
            "profile_name": import_data.get("profile", {}).get("name"),
        }

    async def execute_import(
        self,
        session_id: str,
        profile: Profile,
        mode: str = "merge",
        import_play_history: bool = True,
        import_favorites: bool = True,
        import_playlists: bool = True,
        import_smart_playlists: bool = True,
        import_proposed_changes: bool = True,
        import_user_overrides: bool = True,
        import_external_tracks: bool = True,
    ) -> dict[str, Any]:
        """Execute an import from a previewed session.

        Args:
            session_id: Session ID from preview
            profile: Profile to import into
            mode: "merge" or "overwrite"
            import_*: Flags for what to import

        Returns:
            Import results
        """
        session = _import_sessions.get(session_id)
        if not session:
            raise ValueError(f"Import session {session_id} not found or expired")

        import_data = session.import_data
        matching_results = session.matching_results

        # Build track_id lookup from matching results
        track_id_lookup: dict[str, UUID] = {}
        for result in matching_results.get("results", []):
            if result.get("track_id"):
                ref = result["ref"]
                # Create a hashable key from the ref
                ref_key = self._ref_to_key(ref)
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

        try:
            if import_play_history:
                results["play_history"] = await self._import_play_history(
                    profile.id, import_data.get("play_history", []),
                    track_id_lookup, mode,
                )

            if import_favorites:
                results["favorites"] = await self._import_favorites(
                    profile.id, import_data.get("favorites", []),
                    track_id_lookup, mode,
                )

            if import_playlists:
                results["playlists"] = await self._import_playlists(
                    profile.id, import_data.get("playlists", []),
                    track_id_lookup, mode,
                )

            if import_smart_playlists:
                results["smart_playlists"] = await self._import_smart_playlists(
                    profile.id, import_data.get("smart_playlists", []), mode,
                )

            if import_user_overrides:
                results["user_overrides"] = await self._import_user_overrides(
                    import_data.get("user_overrides", []), track_id_lookup,
                )

            if import_external_tracks:
                results["external_tracks"] = await self._import_external_tracks(
                    import_data.get("external_tracks", []),
                )

            await self.db.commit()

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Import failed: {e}", exc_info=True)
            raise

        finally:
            # Clean up session
            _import_sessions.pop(session_id, None)

        return {
            "status": "completed",
            "results": results,
        }

    def _ref_to_key(self, ref: dict[str, Any]) -> str:
        """Convert a track ref to a hashable key."""
        return f"{ref.get('isrc', '')}:{ref.get('title', '')}:{ref.get('artist', '')}".lower()

    async def _import_play_history(
        self,
        profile_id: UUID,
        play_history: list[dict[str, Any]],
        track_id_lookup: dict[str, UUID],
        mode: str,
    ) -> dict[str, Any]:
        """Import play history."""
        imported = 0
        skipped = 0
        errors: list[str] = []

        for entry in play_history:
            try:
                ref = entry.get("track_ref", {})
                ref_key = self._ref_to_key(ref)
                track_id = track_id_lookup.get(ref_key)

                if not track_id:
                    skipped += 1
                    continue

                # Check for existing record
                existing = await self.db.execute(
                    select(ProfilePlayHistory).where(
                        ProfilePlayHistory.profile_id == profile_id,
                        ProfilePlayHistory.track_id == track_id,
                    )
                )
                existing_record = existing.scalar_one_or_none()

                if existing_record:
                    if mode == "merge":
                        # Add play counts together
                        existing_record.play_count += entry.get("play_count", 0)
                        existing_record.total_play_seconds += entry.get("total_play_seconds", 0)
                        # Use latest last_played_at
                        import_last_played = entry.get("last_played_at")
                        if import_last_played:
                            import_dt = datetime.fromisoformat(import_last_played.replace("Z", "+00:00"))
                            if existing_record.last_played_at is None or import_dt > existing_record.last_played_at:
                                existing_record.last_played_at = import_dt
                        imported += 1
                    else:  # overwrite
                        existing_record.play_count = entry.get("play_count", 0)
                        existing_record.total_play_seconds = entry.get("total_play_seconds", 0)
                        last_played = entry.get("last_played_at")
                        existing_record.last_played_at = (
                            datetime.fromisoformat(last_played.replace("Z", "+00:00"))
                            if last_played else None
                        )
                        imported += 1
                else:
                    # Create new record
                    last_played = entry.get("last_played_at")
                    record = ProfilePlayHistory(
                        profile_id=profile_id,
                        track_id=track_id,
                        play_count=entry.get("play_count", 0),
                        total_play_seconds=entry.get("total_play_seconds", 0),
                        last_played_at=(
                            datetime.fromisoformat(last_played.replace("Z", "+00:00"))
                            if last_played else None
                        ),
                    )
                    self.db.add(record)
                    imported += 1

            except Exception as e:
                errors.append(f"Error importing play history entry: {e}")

        return {"imported": imported, "skipped": skipped, "errors": errors}

    async def _import_favorites(
        self,
        profile_id: UUID,
        favorites: list[dict[str, Any]],
        track_id_lookup: dict[str, UUID],
        mode: str,
    ) -> dict[str, Any]:
        """Import favorites."""
        imported = 0
        skipped = 0
        errors: list[str] = []

        for entry in favorites:
            try:
                ref = entry.get("track_ref", {})
                ref_key = self._ref_to_key(ref)
                track_id = track_id_lookup.get(ref_key)

                if not track_id:
                    skipped += 1
                    continue

                # Check for existing
                existing = await self.db.execute(
                    select(ProfileFavorite).where(
                        ProfileFavorite.profile_id == profile_id,
                        ProfileFavorite.track_id == track_id,
                    )
                )
                if existing.scalar_one_or_none():
                    skipped += 1
                    continue

                # Create new favorite
                favorited_at = entry.get("favorited_at")
                fav = ProfileFavorite(
                    profile_id=profile_id,
                    track_id=track_id,
                    favorited_at=(
                        datetime.fromisoformat(favorited_at.replace("Z", "+00:00"))
                        if favorited_at else utcnow()
                    ),
                )
                self.db.add(fav)
                imported += 1

            except Exception as e:
                errors.append(f"Error importing favorite: {e}")

        return {"imported": imported, "skipped": skipped, "errors": errors}

    async def _import_playlists(
        self,
        profile_id: UUID,
        playlists: list[dict[str, Any]],
        track_id_lookup: dict[str, UUID],
        mode: str,
    ) -> dict[str, Any]:
        """Import playlists."""
        imported = 0
        skipped = 0
        errors: list[str] = []

        for playlist_data in playlists:
            try:
                name = playlist_data.get("name", "Imported Playlist")
                is_wishlist = playlist_data.get("is_wishlist", False)

                # For wishlist, find or create
                if is_wishlist:
                    existing = await self.db.execute(
                        select(Playlist).where(
                            Playlist.profile_id == profile_id,
                            Playlist.is_wishlist.is_(True),
                        )
                    )
                    playlist = existing.scalar_one_or_none()
                    if not playlist:
                        playlist = Playlist(
                            profile_id=profile_id,
                            name=name,
                            description=playlist_data.get("description"),
                            is_wishlist=True,
                        )
                        self.db.add(playlist)
                        await self.db.flush()
                else:
                    # Check for existing playlist by name
                    existing = await self.db.execute(
                        select(Playlist).where(
                            Playlist.profile_id == profile_id,
                            Playlist.name == name,
                            Playlist.is_wishlist.is_(False),
                        )
                    )
                    if existing.scalar_one_or_none() and mode == "merge":
                        skipped += 1
                        continue

                    # Create new playlist
                    playlist = Playlist(
                        profile_id=profile_id,
                        name=name,
                        description=playlist_data.get("description"),
                        is_auto_generated=playlist_data.get("is_auto_generated", False),
                        generation_prompt=playlist_data.get("generation_prompt"),
                    )
                    self.db.add(playlist)
                    await self.db.flush()

                # Add tracks
                tracks_data = playlist_data.get("tracks", [])
                for track_entry in tracks_data:
                    position = track_entry.get("position", 0)

                    if track_entry.get("type") == "local":
                        ref = track_entry.get("track_ref", {})
                        ref_key = self._ref_to_key(ref)
                        track_id = track_id_lookup.get(ref_key)

                        if track_id:
                            pt = PlaylistTrack(
                                playlist_id=playlist.id,
                                track_id=track_id,
                                position=position,
                            )
                            self.db.add(pt)

                    elif track_entry.get("type") == "external":
                        ext_data = track_entry.get("external_track", {})
                        # Create or find external track
                        ext_track = await self._get_or_create_external_track(ext_data)
                        if ext_track:
                            pt = PlaylistTrack(
                                playlist_id=playlist.id,
                                external_track_id=ext_track.id,
                                position=position,
                            )
                            self.db.add(pt)

                imported += 1

            except Exception as e:
                errors.append(f"Error importing playlist '{playlist_data.get('name', 'unknown')}': {e}")

        return {"imported": imported, "skipped": skipped, "errors": errors}

    async def _import_smart_playlists(
        self,
        profile_id: UUID,
        smart_playlists: list[dict[str, Any]],
        mode: str,
    ) -> dict[str, Any]:
        """Import smart playlists."""
        imported = 0
        skipped = 0
        errors: list[str] = []

        for sp_data in smart_playlists:
            try:
                name = sp_data.get("name", "Imported Smart Playlist")

                # Check for existing by name
                existing = await self.db.execute(
                    select(SmartPlaylist).where(
                        SmartPlaylist.profile_id == profile_id,
                        SmartPlaylist.name == name,
                    )
                )
                if existing.scalar_one_or_none() and mode == "merge":
                    skipped += 1
                    continue

                # Create new smart playlist
                sp = SmartPlaylist(
                    profile_id=profile_id,
                    name=name,
                    description=sp_data.get("description"),
                    rules=sp_data.get("rules", []),
                    match_mode=sp_data.get("match_mode", "all"),
                    order_by=sp_data.get("order_by", "title"),
                    order_direction=sp_data.get("order_direction", "asc"),
                    max_tracks=sp_data.get("max_tracks"),
                )
                self.db.add(sp)
                imported += 1

            except Exception as e:
                errors.append(f"Error importing smart playlist '{sp_data.get('name', 'unknown')}': {e}")

        return {"imported": imported, "skipped": skipped, "errors": errors}

    async def _import_user_overrides(
        self,
        user_overrides: list[dict[str, Any]],
        track_id_lookup: dict[str, UUID],
    ) -> dict[str, Any]:
        """Import user overrides to tracks."""
        imported = 0
        skipped = 0
        errors: list[str] = []

        for entry in user_overrides:
            try:
                ref = entry.get("track_ref", {})
                ref_key = self._ref_to_key(ref)
                track_id = track_id_lookup.get(ref_key)

                if not track_id:
                    skipped += 1
                    continue

                track = await self.db.get(Track, track_id)
                if track:
                    overrides = entry.get("overrides", {})
                    # Merge overrides (imported values win)
                    track.user_overrides = {**track.user_overrides, **overrides}
                    imported += 1
                else:
                    skipped += 1

            except Exception as e:
                errors.append(f"Error importing user override: {e}")

        return {"imported": imported, "skipped": skipped, "errors": errors}

    async def _import_external_tracks(
        self,
        external_tracks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Import external tracks."""
        imported = 0
        skipped = 0
        errors: list[str] = []

        for ext_data in external_tracks:
            try:
                ext_track = await self._get_or_create_external_track(ext_data)
                if ext_track:
                    imported += 1
                else:
                    skipped += 1
            except Exception as e:
                errors.append(f"Error importing external track: {e}")

        return {"imported": imported, "skipped": skipped, "errors": errors}

    async def _get_or_create_external_track(
        self,
        ext_data: dict[str, Any],
    ) -> ExternalTrack | None:
        """Get or create an external track."""
        spotify_id = ext_data.get("spotify_id")

        # Check if exists by spotify_id
        if spotify_id:
            existing = await self.db.execute(
                select(ExternalTrack).where(ExternalTrack.spotify_id == spotify_id)
            )
            ext = existing.scalar_one_or_none()
            if ext:
                return ext

        # Create new
        source_str = ext_data.get("source", "manual")
        try:
            source = ExternalTrackSource(source_str)
        except (ValueError, KeyError):
            source = ExternalTrackSource.MANUAL

        ext_track = ExternalTrack(
            title=ext_data.get("title", "Unknown"),
            artist=ext_data.get("artist", "Unknown"),
            album=ext_data.get("album"),
            duration_seconds=ext_data.get("duration_seconds"),
            track_number=ext_data.get("track_number"),
            year=ext_data.get("year"),
            isrc=ext_data.get("isrc"),
            spotify_id=spotify_id,
            musicbrainz_recording_id=ext_data.get("musicbrainz_recording_id"),
            deezer_id=ext_data.get("deezer_id"),
            external_data=ext_data.get("external_data", {}),
            source=source,
        )
        self.db.add(ext_track)
        await self.db.flush()

        return ext_track
