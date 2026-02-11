"""Spotify data export import service.

Parses Spotify "Download your data" exports (GDPR zip) and imports
saved tracks, playlists, and streaming history into Familiar.
"""

import json
import logging
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Playlist,
    PlaylistTrack,
    SpotifyFavorite,
    Track,
)

logger = logging.getLogger(__name__)


class SpotifyExportParser:
    """Parses Spotify data export files."""

    @staticmethod
    def parse_zip(file_path: str) -> dict[str, Any]:
        """Extract and identify JSON files from a Spotify data export zip.

        Returns:
            Dict with keys: library_tracks, playlists, streaming_history
        """
        result: dict[str, Any] = {
            "library_tracks": [],
            "playlists": [],
            "streaming_history": [],
            "files_found": [],
        }

        with zipfile.ZipFile(file_path, "r") as zf:
            for name in zf.namelist():
                if not name.endswith(".json"):
                    continue

                basename = Path(name).name
                result["files_found"].append(basename)

                try:
                    data = json.loads(zf.read(name))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    logger.warning(f"Failed to parse {name}")
                    continue

                if basename == "YourLibrary.json":
                    result["library_tracks"] = SpotifyExportParser.parse_library(data)
                elif basename.startswith("Playlist"):
                    result["playlists"].extend(
                        SpotifyExportParser.parse_playlists(data)
                    )
                elif basename.startswith("Streaming_History_Audio"):
                    result["streaming_history"].extend(
                        SpotifyExportParser.parse_streaming_history(data)
                    )

        return result

    @staticmethod
    def parse_json_file(file_path: str, filename: str) -> dict[str, Any]:
        """Parse a single JSON file from a Spotify data export.

        Identifies the file type by name and parses accordingly.
        """
        result: dict[str, Any] = {
            "library_tracks": [],
            "playlists": [],
            "streaming_history": [],
            "files_found": [filename],
        }

        with open(file_path) as f:
            data = json.load(f)

        if filename == "YourLibrary.json":
            result["library_tracks"] = SpotifyExportParser.parse_library(data)
        elif filename.startswith("Playlist"):
            result["playlists"] = SpotifyExportParser.parse_playlists(data)
        elif filename.startswith("Streaming_History_Audio"):
            result["streaming_history"] = SpotifyExportParser.parse_streaming_history(
                data
            )

        return result

    @staticmethod
    def parse_library(data: dict[str, Any]) -> list[dict[str, str]]:
        """Parse YourLibrary.json -> list of {artist, album, track, uri}."""
        tracks = []
        for item in data.get("tracks", []):
            tracks.append(
                {
                    "artist": item.get("artist", ""),
                    "album": item.get("album", ""),
                    "track": item.get("track", ""),
                    "uri": item.get("uri", ""),
                }
            )
        return tracks

    @staticmethod
    def parse_playlists(data: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse Playlist*.json -> list of playlists with tracks."""
        playlists = []
        for playlist in data.get("playlists", []):
            tracks = []
            for item in playlist.get("items", []):
                track_data = item.get("track", {})
                if track_data:
                    tracks.append(
                        {
                            "track": track_data.get("trackName", ""),
                            "artist": track_data.get("artistName", ""),
                            "album": track_data.get("albumName", ""),
                            "uri": track_data.get("trackUri", ""),
                        }
                    )

            playlists.append(
                {
                    "name": playlist.get("name", "Untitled Playlist"),
                    "last_modified": playlist.get("lastModifiedDate"),
                    "tracks": tracks,
                }
            )
        return playlists

    @staticmethod
    def parse_streaming_history(
        data: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Parse Streaming_History_Audio_*.json -> aggregated play counts per track."""
        # Data is a list of stream events, not a dict
        aggregated: dict[str, dict[str, Any]] = {}

        for entry in data:
            uri = entry.get("spotify_track_uri", "")
            if not uri:
                continue

            if uri not in aggregated:
                aggregated[uri] = {
                    "uri": uri,
                    "track": entry.get("master_metadata_track_name", ""),
                    "artist": entry.get(
                        "master_metadata_album_artist_name", ""
                    ),
                    "album": entry.get(
                        "master_metadata_album_album_name", ""
                    ),
                    "play_count": 0,
                    "total_ms_played": 0,
                }

            aggregated[uri]["play_count"] += 1
            aggregated[uri]["total_ms_played"] += entry.get("ms_played", 0)

        return list(aggregated.values())


class SpotifyImportPreviewSession:
    """Stores preview results for a Spotify import session."""

    def __init__(
        self,
        session_id: str,
        parsed_data: dict[str, Any],
        match_results: dict[str, Any],
        summary: dict[str, Any],
    ) -> None:
        self.session_id = session_id
        self.parsed_data = parsed_data
        self.match_results = match_results
        self.summary = summary
        self.created_at = datetime.utcnow()


# In-memory session storage
_spotify_import_sessions: dict[str, SpotifyImportPreviewSession] = {}


class SpotifyExportImporter:
    """Imports parsed Spotify export data into Familiar."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_preview_session(
        self,
        parsed_data: dict[str, Any],
        profile_id: str,
    ) -> tuple[str, dict[str, Any]]:
        """Match tracks to local library and return preview statistics.

        Returns:
            Tuple of (session_id, summary)
        """
        session_id = str(uuid.uuid4())

        # Match library tracks
        library_matches = await self._match_tracks(parsed_data.get("library_tracks", []))

        # Match playlist tracks
        playlist_matches = []
        for playlist in parsed_data.get("playlists", []):
            matches = await self._match_tracks(playlist.get("tracks", []))
            matched_count = sum(1 for m in matches if m["local_track_id"])
            playlist_matches.append(
                {
                    "name": playlist.get("name", "Untitled"),
                    "total_tracks": len(playlist.get("tracks", [])),
                    "matched": matched_count,
                    "match_rate": (
                        round(matched_count / len(playlist["tracks"]) * 100, 1)
                        if playlist.get("tracks")
                        else 0
                    ),
                }
            )

        # Match streaming history tracks
        history_matches = await self._match_tracks(
            parsed_data.get("streaming_history", [])
        )

        match_results = {
            "library": library_matches,
            "playlists": playlist_matches,
            "streaming_history": history_matches,
            "profile_id": profile_id,
        }

        library_matched = sum(1 for m in library_matches if m["local_track_id"])
        history_matched = sum(1 for m in history_matches if m["local_track_id"])

        summary = {
            "session_id": session_id,
            "files_found": parsed_data.get("files_found", []),
            "library_tracks": {
                "total": len(library_matches),
                "matched": library_matched,
                "unmatched": len(library_matches) - library_matched,
                "match_rate": (
                    round(library_matched / len(library_matches) * 100, 1)
                    if library_matches
                    else 0
                ),
            },
            "playlists": {
                "total": len(parsed_data.get("playlists", [])),
                "details": playlist_matches,
            },
            "streaming_history": {
                "total_tracks": len(history_matches),
                "matched": history_matched,
                "total_streams": sum(
                    e.get("play_count", 0)
                    for e in parsed_data.get("streaming_history", [])
                ),
            },
        }

        # Store session
        session = SpotifyImportPreviewSession(
            session_id=session_id,
            parsed_data=parsed_data,
            match_results=match_results,
            summary=summary,
        )
        _spotify_import_sessions[session_id] = session

        return session_id, summary

    async def get_preview(self, session_id: str) -> dict[str, Any]:
        """Get detailed preview for a session."""
        session = _spotify_import_sessions.get(session_id)
        if not session:
            raise ValueError(f"Import session {session_id} not found or expired")

        return {
            "session_id": session_id,
            "summary": session.summary,
            "matched_tracks": [
                m
                for m in session.match_results.get("library", [])
                if m["local_track_id"]
            ],
            "unmatched_tracks": [
                m
                for m in session.match_results.get("library", [])
                if not m["local_track_id"]
            ],
            "playlists": session.match_results.get("playlists", []),
        }

    async def execute_import(
        self,
        session_id: str,
        options: dict[str, bool],
    ) -> dict[str, Any]:
        """Execute import from a previewed session.

        Options:
            import_favorites: Create SpotifyFavorite records for library tracks
            import_playlists: Create playlists from export playlists
            favorite_matched: Add matched tracks to local favorites
        """
        session = _spotify_import_sessions.get(session_id)
        if not session:
            raise ValueError(f"Import session {session_id} not found or expired")

        profile_id = session.match_results.get("profile_id")
        if not profile_id:
            raise ValueError("No profile associated with this session")

        results: dict[str, Any] = {
            "favorites_imported": 0,
            "playlists_created": 0,
            "tracks_favorited": 0,
            "errors": [],
        }

        try:
            # Import library tracks as SpotifyFavorite records
            if options.get("import_favorites", True):
                count = await self._import_favorites(
                    session.parsed_data.get("library_tracks", []),
                    session.match_results.get("library", []),
                    profile_id,
                )
                results["favorites_imported"] = count

            # Import playlists
            if options.get("import_playlists", True):
                count = await self._import_playlists(
                    session.parsed_data.get("playlists", []),
                    profile_id,
                )
                results["playlists_created"] = count

            # Favorite matched tracks in local library
            if options.get("favorite_matched", False):
                count = await self._favorite_matched(
                    session.match_results.get("library", []),
                    profile_id,
                )
                results["tracks_favorited"] = count

            await self.db.commit()
        except Exception as e:
            logger.error(f"Error during Spotify export import: {e}")
            results["errors"].append(str(e))
            await self.db.rollback()
        finally:
            # Clean up session
            _spotify_import_sessions.pop(session_id, None)

        return results

    async def _match_tracks(
        self, tracks: list[dict[str, str]]
    ) -> list[dict[str, Any]]:
        """Match a list of export tracks to local library.

        Uses exact artist+title match, then fuzzy matching.
        """
        from rapidfuzz import fuzz

        results = []

        for track_data in tracks:
            track_name = (track_data.get("track") or "").lower().strip()
            artist_name = (track_data.get("artist") or "").lower().strip()

            if not track_name or not artist_name:
                results.append(
                    {
                        "track": track_data.get("track", ""),
                        "artist": track_data.get("artist", ""),
                        "album": track_data.get("album", ""),
                        "uri": track_data.get("uri", ""),
                        "local_track_id": None,
                        "match_method": None,
                    }
                )
                continue

            local_match = None
            match_method = None

            # 1. Exact artist + title match
            result = await self.db.execute(
                select(Track)
                .where(
                    func.lower(Track.title) == track_name,
                    func.lower(Track.artist) == artist_name,
                )
                .limit(1)
            )
            match = result.scalars().first()
            if match:
                local_match = match
                match_method = "exact"

            # 2. Contains match
            if not local_match:
                result = await self.db.execute(
                    select(Track)
                    .where(
                        func.lower(Track.title).contains(track_name),
                        func.lower(Track.artist).contains(artist_name),
                    )
                    .limit(1)
                )
                match = result.scalars().first()
                if match:
                    local_match = match
                    match_method = "contains"

            # 3. Fuzzy match
            if not local_match:
                # Get candidates - cache would be better for large imports
                result = await self.db.execute(
                    select(Track)
                    .where(Track.title.isnot(None), Track.artist.isnot(None))
                    .limit(5000)
                )
                candidates = result.scalars().all()

                best_score = 0.0
                threshold = 85

                for candidate in candidates:
                    if not candidate.title or not candidate.artist:
                        continue

                    title_score = fuzz.ratio(
                        track_name, candidate.title.lower()
                    )
                    artist_score = fuzz.ratio(
                        artist_name, candidate.artist.lower()
                    )
                    combined = (title_score * 0.6) + (artist_score * 0.4)

                    if combined >= threshold and combined > best_score:
                        best_score = combined
                        local_match = candidate
                        match_method = "fuzzy"

            results.append(
                {
                    "track": track_data.get("track", ""),
                    "artist": track_data.get("artist", ""),
                    "album": track_data.get("album", ""),
                    "uri": track_data.get("uri", ""),
                    "local_track_id": str(local_match.id) if local_match else None,
                    "local_track_title": local_match.title if local_match else None,
                    "local_track_artist": local_match.artist if local_match else None,
                    "match_method": match_method,
                }
            )

        return results

    async def _import_favorites(
        self,
        library_tracks: list[dict[str, str]],
        match_results: list[dict[str, Any]],
        profile_id: str,
    ) -> int:
        """Create SpotifyFavorite records for library tracks."""
        from uuid import UUID

        count = 0
        profile_uuid = UUID(profile_id)

        for track_data, match in zip(library_tracks, match_results):
            # Extract spotify track ID from URI (spotify:track:XXX)
            uri = track_data.get("uri", "")
            spotify_id = uri.split(":")[-1] if uri.startswith("spotify:track:") else None

            if not spotify_id:
                continue

            # Check if already exists
            existing = await self.db.execute(
                select(SpotifyFavorite).where(
                    SpotifyFavorite.profile_id == profile_uuid,
                    SpotifyFavorite.spotify_track_id == spotify_id,
                )
            )
            if existing.scalar_one_or_none():
                continue

            matched_track_id = None
            if match.get("local_track_id"):
                matched_track_id = UUID(match["local_track_id"])

            favorite = SpotifyFavorite(
                profile_id=profile_uuid,
                spotify_track_id=spotify_id,
                matched_track_id=matched_track_id,
                track_data={
                    "name": track_data.get("track"),
                    "artist": track_data.get("artist"),
                    "album": track_data.get("album"),
                    "external_url": f"https://open.spotify.com/track/{spotify_id}" if spotify_id else None,
                },
            )
            self.db.add(favorite)
            count += 1

        await self.db.flush()
        return count

    async def _import_playlists(
        self,
        playlists: list[dict[str, Any]],
        profile_id: str,
    ) -> int:
        """Create playlists from export data."""
        from uuid import UUID

        count = 0
        profile_uuid = UUID(profile_id)

        for playlist_data in playlists:
            playlist_tracks = playlist_data.get("tracks", [])
            if not playlist_tracks:
                continue

            playlist = Playlist(
                profile_id=profile_uuid,
                name=playlist_data.get("name", "Imported Playlist"),
                description=f"Imported from Spotify data export",
                is_auto_generated=False,
            )
            self.db.add(playlist)
            await self.db.flush()

            position = 0
            for track_ref in playlist_tracks:
                # Try to match each track
                track_name = (track_ref.get("track") or "").lower().strip()
                artist_name = (track_ref.get("artist") or "").lower().strip()

                if not track_name or not artist_name:
                    continue

                # Quick exact match
                result = await self.db.execute(
                    select(Track)
                    .where(
                        func.lower(Track.title) == track_name,
                        func.lower(Track.artist) == artist_name,
                    )
                    .limit(1)
                )
                local_track = result.scalars().first()

                if local_track:
                    pt = PlaylistTrack(
                        playlist_id=playlist.id,
                        track_id=local_track.id,
                        position=position,
                    )
                    self.db.add(pt)
                    position += 1

            count += 1

        await self.db.flush()
        return count

    async def _favorite_matched(
        self,
        match_results: list[dict[str, Any]],
        profile_id: str,
    ) -> int:
        """Add matched tracks to the user's local favorites."""
        from uuid import UUID

        from app.db.models import ProfileFavorite

        count = 0
        profile_uuid = UUID(profile_id)

        for match in match_results:
            local_track_id = match.get("local_track_id")
            if not local_track_id:
                continue

            track_uuid = UUID(local_track_id)

            # Check if already favorited
            existing = await self.db.execute(
                select(ProfileFavorite).where(
                    ProfileFavorite.profile_id == profile_uuid,
                    ProfileFavorite.track_id == track_uuid,
                )
            )
            if existing.scalar_one_or_none():
                continue

            fav = ProfileFavorite(
                profile_id=profile_uuid,
                track_id=track_uuid,
            )
            self.db.add(fav)
            count += 1

        await self.db.flush()
        return count


def save_upload_to_temp(content: bytes, suffix: str) -> str:
    """Save uploaded file content to a temp file. Returns the path."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        return tmp.name
