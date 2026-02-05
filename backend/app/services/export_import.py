"""Data export/import service.

Handles exporting and importing user data (playcounts, playlists, favorites,
smart playlists, metadata corrections, external tracks, chat history) for
backup and migration purposes.

Also handles full library export/import for migration between machines.
"""

import gzip
import json
import logging
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any
from uuid import UUID

from rapidfuzz import fuzz
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ANALYSIS_VERSION, get_app_version
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
    TrackAnalysis,
)
from app.services.external_track_matcher import normalize_for_matching

logger = logging.getLogger(__name__)

# Export schema version - increment when making breaking changes
EXPORT_VERSION = 1


class TrackMatcher:
    """Matches track references to local library tracks.

    Used during import to find local tracks that correspond to exported
    track references based on ISRC, MusicBrainz ID, or fuzzy matching.
    """

    # Fuzzy matching threshold (0-100)
    FUZZY_THRESHOLD = 85

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._track_cache: dict[str, Track] | None = None

    async def _get_all_tracks(self) -> list[Track]:
        """Get all tracks from database (cached for batch matching)."""
        result = await self.db.execute(
            select(Track).where(
                Track.title.isnot(None),
                Track.artist.isnot(None),
            )
        )
        return list(result.scalars().all())

    async def _build_track_cache(self) -> None:
        """Build lookup caches for fast matching."""
        if self._track_cache is not None:
            return

        tracks = await self._get_all_tracks()
        self._track_cache = {}

        for track in tracks:
            # Index by ISRC
            if track.isrc:
                self._track_cache[f"isrc:{track.isrc}"] = track

            # Index by MusicBrainz ID
            if track.musicbrainz_track_id:
                self._track_cache[f"mbid:{track.musicbrainz_track_id}"] = track

            # Index by exact title+artist (lowercase)
            if track.title and track.artist:
                key = f"exact:{track.title.lower().strip()}:{track.artist.lower().strip()}"
                self._track_cache[key] = track

    async def match_track_ref(
        self,
        track_ref: dict[str, Any],
    ) -> tuple[Track | None, str | None, float | None]:
        """Match a track reference to a local track.

        Args:
            track_ref: Track reference dict with isrc, musicbrainz_id, title, artist, album, duration_seconds

        Returns:
            Tuple of (matched_track, match_method, confidence)
        """
        await self._build_track_cache()
        assert self._track_cache is not None

        isrc = track_ref.get("isrc")
        musicbrainz_id = track_ref.get("musicbrainz_id")
        title = track_ref.get("title", "")
        artist = track_ref.get("artist", "")
        album = track_ref.get("album")
        duration = track_ref.get("duration_seconds")

        # 1. Try ISRC match (most reliable)
        if isrc:
            track = self._track_cache.get(f"isrc:{isrc}")
            if track:
                return track, "isrc", 1.0

        # 2. Try MusicBrainz ID match
        if musicbrainz_id:
            track = self._track_cache.get(f"mbid:{musicbrainz_id}")
            if track:
                return track, "musicbrainz", 1.0

        # 3. Try exact title + artist match
        if title and artist:
            key = f"exact:{title.lower().strip()}:{artist.lower().strip()}"
            track = self._track_cache.get(key)
            if track:
                return track, "exact", 1.0

        # 4. Try fuzzy matching
        if title and artist:
            return await self._fuzzy_match(title, artist, album, duration)

        return None, None, None

    async def _fuzzy_match(
        self,
        title: str,
        artist: str,
        album: str | None,
        duration: float | None,
    ) -> tuple[Track | None, str | None, float | None]:
        """Fuzzy match against all tracks."""
        normalized_title = normalize_for_matching(title)
        normalized_artist = normalize_for_matching(artist)

        tracks = await self._get_all_tracks()
        best_match: Track | None = None
        best_score: float = 0.0

        for track in tracks:
            if not track.title or not track.artist:
                continue

            local_title = normalize_for_matching(track.title)
            local_artist = normalize_for_matching(track.artist)

            # Calculate fuzzy scores
            title_score = fuzz.ratio(normalized_title, local_title)
            artist_score = fuzz.ratio(normalized_artist, local_artist)

            # Combined score with weights (title matters more)
            combined = (title_score * 0.6) + (artist_score * 0.4)

            # Duration disambiguation: boost score if durations match closely
            if duration and track.duration_seconds:
                duration_diff = abs(duration - track.duration_seconds)
                if duration_diff < 3:  # Within 3 seconds
                    combined = min(100, combined + 5)
                elif duration_diff > 30:  # Very different duration
                    combined = combined * 0.9

            if combined >= self.FUZZY_THRESHOLD and combined > best_score:
                best_score = combined
                best_match = track

        if best_match:
            return best_match, "fuzzy", best_score / 100.0

        return None, None, None

    async def match_batch(
        self,
        track_refs: list[dict[str, Any]],
    ) -> list[tuple[dict[str, Any], Track | None, str | None, float | None]]:
        """Match a batch of track references.

        Returns list of (track_ref, matched_track, method, confidence) tuples.
        """
        await self._build_track_cache()

        results = []
        for ref in track_refs:
            track, method, confidence = await self.match_track_ref(ref)
            results.append((ref, track, method, confidence))

        return results


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
            "preview_url": ext.preview_url,
            "preview_source": ext.preview_source,
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
            "exported_at": datetime.utcnow().isoformat() + "Z",
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


class ImportPreviewSession:
    """Stores preview results for an import session."""

    def __init__(
        self,
        session_id: str,
        import_data: dict[str, Any],
        matching_results: dict[str, Any],
        summary: dict[str, Any],
        warnings: list[str],
    ) -> None:
        self.session_id = session_id
        self.import_data = import_data
        self.matching_results = matching_results
        self.summary = summary
        self.warnings = warnings
        self.created_at = datetime.utcnow()


# In-memory session storage (in production, use Redis)
_import_sessions: dict[str, ImportPreviewSession] = {}


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
                        if favorited_at else datetime.utcnow()
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
            preview_url=ext_data.get("preview_url"),
            preview_source=ext_data.get("preview_source"),
            external_data=ext_data.get("external_data", {}),
            source=source,
        )
        self.db.add(ext_track)
        await self.db.flush()

        return ext_track


# ============================================================================
# Library Export/Import for Migration
# ============================================================================

# Library export schema version - separate from profile export
LIBRARY_EXPORT_VERSION = 2


class LibraryImportPreviewSession:
    """Stores preview results for a library import session."""

    def __init__(
        self,
        session_id: str,
        import_data: dict[str, Any],
        matching_results: dict[str, Any],
        summary: dict[str, Any],
        warnings: list[str],
    ) -> None:
        self.session_id = session_id
        self.import_data = import_data
        self.matching_results = matching_results
        self.summary = summary
        self.warnings = warnings
        self.created_at = datetime.utcnow()


# In-memory session storage for library imports
_library_import_sessions: dict[str, LibraryImportPreviewSession] = {}


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
            select(func.count(TrackAnalysis.id)).where(TrackAnalysis.version == ANALYSIS_VERSION)
        )
        tracks_with_analysis = analysis_count_result.scalar() or 0

        embedding_count_result = await self.db.execute(
            select(func.count(TrackAnalysis.id)).where(
                TrackAnalysis.version == ANALYSIS_VERSION,
                TrackAnalysis.embedding.isnot(None),
            )
        )
        tracks_with_embeddings = embedding_count_result.scalar() or 0

        # Build header
        header = {
            "version": LIBRARY_EXPORT_VERSION,
            "export_type": "library",
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "familiar_version": get_app_version(),
            "analysis_version": ANALYSIS_VERSION,
            "stats": {
                "total_tracks": total_tracks,
                "tracks_with_analysis": tracks_with_analysis,
                "tracks_with_embeddings": tracks_with_embeddings,
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
                    (TrackAnalysis.track_id == Track.id) & (TrackAnalysis.version == ANALYSIS_VERSION),
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
                "version": analysis.version,
                "features": analysis.features or {},
            }

            if include_embeddings and analysis.embedding is not None:
                # Convert numpy array to list for JSON serialization
                embedding_list = analysis.embedding.tolist() if hasattr(analysis.embedding, "tolist") else list(analysis.embedding)
                analysis_export["embedding"] = embedding_list

            if include_acoustid:
                if analysis.acoustid:
                    analysis_export["acoustid"] = analysis.acoustid
                if analysis.acoustid_lookup:
                    analysis_export["acoustid_lookup"] = analysis.acoustid_lookup

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
                            TrackAnalysis.version == ANALYSIS_VERSION,
                        )
                    )
                    analysis = analysis_result.scalar_one_or_none()

                    export_analysis = export_track.get("analysis", {})

                    # Apply analysis features
                    if apply_analysis and export_analysis.get("features"):
                        if not analysis:
                            analysis = TrackAnalysis(
                                track_id=track_id,
                                version=ANALYSIS_VERSION,
                                features={},
                            )
                            self.db.add(analysis)

                        # Merge features (imported values fill gaps)
                        existing_features = analysis.features or {}
                        imported_features = export_analysis.get("features", {})
                        if not existing_features or mode == "replace":
                            analysis.features = imported_features
                        else:
                            # Only fill missing features
                            for key, value in imported_features.items():
                                if key not in existing_features:
                                    existing_features[key] = value
                            analysis.features = existing_features

                        analysis.features_source = "library_import"
                        analysis_imported += 1

                        # Update track analysis status
                        if not track.analyzed_at:
                            track.analyzed_at = datetime.utcnow()
                            track.analysis_version = ANALYSIS_VERSION

                    # Apply embeddings
                    if apply_embeddings and export_analysis.get("embedding"):
                        if analysis:
                            if analysis.embedding is None or mode == "replace":
                                analysis.embedding = export_analysis["embedding"]
                                analysis.embedding_source = "library_import"
                                embeddings_imported += 1

                    # Apply acoustid
                    if export_analysis.get("acoustid") and analysis:
                        if not analysis.acoustid:
                            analysis.acoustid = export_analysis["acoustid"]
                        if export_analysis.get("acoustid_lookup") and not analysis.acoustid_lookup:
                            analysis.acoustid_lookup = export_analysis["acoustid_lookup"]

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

            # Try ±1 second buckets
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


# ============================================================================
# Backup/Restore Service
# ============================================================================

# Backup format version
BACKUP_VERSION = 2


class BackupPreviewSession:
    """Stores preview results for a backup import session."""

    def __init__(
        self,
        session_id: str,
        import_data: dict[str, Any],
        profile_matching_results: dict[str, Any] | None,
        library_matching_results: dict[str, Any] | None,
        summary: dict[str, Any],
        warnings: list[str],
    ) -> None:
        self.session_id = session_id
        self.import_data = import_data
        self.profile_matching_results = profile_matching_results
        self.library_matching_results = library_matching_results
        self.summary = summary
        self.warnings = warnings
        self.created_at = datetime.utcnow()


# In-memory session storage for backup imports
_backup_import_sessions: dict[str, BackupPreviewSession] = {}


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
            "exported_at": datetime.utcnow().isoformat() + "Z",
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
    ) -> dict[str, Any]:
        """Build library data section for export."""
        # Get counts
        count_result = await self.db.execute(select(func.count(Track.id)))
        total_tracks = count_result.scalar() or 0

        analysis_count_result = await self.db.execute(
            select(func.count(TrackAnalysis.id)).where(TrackAnalysis.version == ANALYSIS_VERSION)
        )
        tracks_with_analysis = analysis_count_result.scalar() or 0

        embedding_count_result = await self.db.execute(
            select(func.count(TrackAnalysis.id)).where(
                TrackAnalysis.version == ANALYSIS_VERSION,
                TrackAnalysis.embedding.isnot(None),
            )
        )
        tracks_with_embeddings = embedding_count_result.scalar() or 0

        library_data: dict[str, Any] = {
            "analysis_version": ANALYSIS_VERSION,
            "stats": {
                "total_tracks": total_tracks,
                "tracks_with_analysis": tracks_with_analysis,
                "tracks_with_embeddings": tracks_with_embeddings,
            },
            "tracks": [],
        }

        # Export all tracks with analysis
        batch_size = 500
        offset = 0
        while True:
            result = await self.db.execute(
                select(Track, TrackAnalysis)
                .outerjoin(
                    TrackAnalysis,
                    (TrackAnalysis.track_id == Track.id) & (TrackAnalysis.version == ANALYSIS_VERSION),
                )
                .order_by(Track.id)
                .offset(offset)
                .limit(batch_size)
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
                )
                library_data["tracks"].append(track_export)

            offset += batch_size

        return library_data

    def _build_track_export(
        self,
        track: Track,
        analysis: TrackAnalysis | None,
        include_embeddings: bool,
        include_acoustid: bool,
    ) -> dict[str, Any]:
        """Build export dict for a single track (library section)."""
        export: dict[str, Any] = {
            "file_hash": track.file_hash,
            "isrc": track.isrc,
            "musicbrainz_track_id": track.musicbrainz_track_id,
            "title": track.title,
            "artist": track.artist,
            "album": track.album,
            "duration_seconds": track.duration_seconds,
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

        if track.user_overrides:
            export["user_overrides"] = track.user_overrides

        if analysis:
            analysis_export: dict[str, Any] = {
                "version": analysis.version,
                "features": analysis.features or {},
            }

            if include_embeddings and analysis.embedding is not None:
                embedding_list = analysis.embedding.tolist() if hasattr(analysis.embedding, "tolist") else list(analysis.embedding)
                analysis_export["embedding"] = embedding_list

            if include_acoustid:
                if analysis.acoustid:
                    analysis_export["acoustid"] = analysis.acoustid
                if analysis.acoustid_lookup:
                    analysis_export["acoustid_lookup"] = analysis.acoustid_lookup

            export["analysis"] = analysis_export

        return export


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
                        TrackAnalysis.version == ANALYSIS_VERSION,
                    )
                )
                analysis = analysis_result.scalar_one_or_none()

                export_analysis = export_track.get("analysis", {})

                # Apply analysis features
                if apply_analysis and export_analysis.get("features"):
                    if not analysis:
                        analysis = TrackAnalysis(
                            track_id=track_id,
                            version=ANALYSIS_VERSION,
                            features={},
                        )
                        self.db.add(analysis)

                    existing_features = analysis.features or {}
                    imported_features = export_analysis.get("features", {})
                    if not existing_features or mode == "replace":
                        analysis.features = imported_features
                    else:
                        for key, value in imported_features.items():
                            if key not in existing_features:
                                existing_features[key] = value
                        analysis.features = existing_features

                    analysis.features_source = "library_import"
                    analysis_imported += 1

                    if not track.analyzed_at:
                        track.analyzed_at = datetime.utcnow()
                        track.analysis_version = ANALYSIS_VERSION

                # Apply embeddings
                if apply_embeddings and export_analysis.get("embedding"):
                    if analysis:
                        if analysis.embedding is None or mode == "replace":
                            analysis.embedding = export_analysis["embedding"]
                            analysis.embedding_source = "library_import"
                            embeddings_imported += 1

                # Apply acoustid
                if export_analysis.get("acoustid") and analysis:
                    if not analysis.acoustid:
                        analysis.acoustid = export_analysis["acoustid"]
                    if export_analysis.get("acoustid_lookup") and not analysis.acoustid_lookup:
                        analysis.acoustid_lookup = export_analysis["acoustid_lookup"]

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
