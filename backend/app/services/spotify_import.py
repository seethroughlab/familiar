"""Spotify data export import service.

Parses the ZIP from Spotify's "Download your data" page,
runs TrackMatcher to find local matches, and stores everything
in a single JSONB-heavy row per profile.
"""

import io
import json
import logging
import zipfile
from collections import Counter
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SpotifyImport
from app.services.export_import.matching import TrackMatcher, normalize_for_matching
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

# Spotify ZIP files may have a directory prefix
SPOTIFY_DIR_PREFIXES = [
    "Spotify Account Data/",
    "my_spotify_data/",
    "MyData/",
    "",
]


class SpotifyImportService:
    """Parses Spotify data exports and matches against local library."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def parse_and_save(
        self,
        profile_id: UUID,
        zip_bytes: bytes,
        include_favorites: bool = True,
        include_playlists: bool = True,
        include_streaming: bool = True,
    ) -> SpotifyImport:
        """Parse a Spotify data export ZIP and store results immediately.

        Matching is deferred — the returned import has match_results={}
        and summary.matching_status='pending'.
        """
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            prefix = self._detect_prefix(zf)
            favorites = self._parse_favorites(zf, prefix) if include_favorites else []
            playlists = self._parse_playlists(zf, prefix) if include_playlists else []
            streaming_stats = (
                self._aggregate_streaming_history(zf, prefix)
                if include_streaming
                else {"top_artists": [], "top_tracks": [], "total_ms": 0, "date_range": None}
            )
            username = self._extract_username(zf, prefix)

        summary = self._compute_summary(
            favorites, playlists, streaming_stats, {}, matching_status="pending"
        )

        await self.db.execute(
            delete(SpotifyImport).where(SpotifyImport.profile_id == profile_id)
        )

        import_ = SpotifyImport(
            profile_id=profile_id,
            imported_at=utcnow(),
            spotify_username=username,
            favorites=favorites,
            playlists=playlists,
            streaming_stats=streaming_stats,
            match_results={},
            summary=summary,
        )
        self.db.add(import_)
        await self.db.commit()
        await self.db.refresh(import_)
        return import_

    async def update_matches(
        self,
        profile_id: UUID,
        progress_cb: Callable[[str, int, int], None] | None = None,
    ) -> SpotifyImport | None:
        """Run matching against current library and update the stored import."""
        result = await self.db.execute(
            select(SpotifyImport).where(SpotifyImport.profile_id == profile_id)
        )
        import_ = result.scalar_one_or_none()
        if not import_:
            return None

        if progress_cb:
            progress_cb("Matching tracks...", 0, 0)

        match_results = await self._match_all(
            import_.favorites, import_.playlists, import_.streaming_stats, progress_cb=progress_cb
        )

        if progress_cb:
            progress_cb("Saving results...", 0, 0)

        summary = self._compute_summary(
            import_.favorites, import_.playlists, import_.streaming_stats, match_results
        )

        import_.match_results = match_results
        import_.summary = summary
        import_.imported_at = utcnow()
        await self.db.commit()
        await self.db.refresh(import_)
        return import_

    async def rematch(
        self,
        profile_id: UUID,
        progress_cb: Callable[[str, int, int], None] | None = None,
    ) -> SpotifyImport | None:
        """Re-run matching against current library without re-uploading."""
        return await self.update_matches(profile_id, progress_cb=progress_cb)

    async def get_import(self, profile_id: UUID) -> SpotifyImport | None:
        """Get the current Spotify import for a profile."""
        result = await self.db.execute(
            select(SpotifyImport).where(SpotifyImport.profile_id == profile_id)
        )
        return result.scalar_one_or_none()

    async def delete_import(self, profile_id: UUID) -> bool:
        """Delete the Spotify import for a profile."""
        result = await self.db.execute(
            delete(SpotifyImport).where(SpotifyImport.profile_id == profile_id)
        )
        await self.db.commit()
        return result.rowcount > 0  # type: ignore[attr-defined]

    # ---- ZIP parsing ----

    def _detect_prefix(self, zf: zipfile.ZipFile) -> str:
        """Detect directory prefix inside the ZIP."""
        names = zf.namelist()
        for prefix in SPOTIFY_DIR_PREFIXES:
            if any(n.startswith(prefix + "YourLibrary") for n in names):
                return prefix
            if any(n.startswith(prefix + "Playlist") for n in names):
                return prefix
        # Fallback: check for any json at root
        return ""

    def _read_json(
        self, zf: zipfile.ZipFile, prefix: str, filename: str
    ) -> Any | None:
        """Read and parse a JSON file from the ZIP, returning None if missing."""
        path = prefix + filename
        try:
            with zf.open(path) as f:
                return json.loads(f.read())
        except KeyError:
            return None

    def _find_files(
        self, zf: zipfile.ZipFile, prefix: str, pattern: str
    ) -> list[str]:
        """Find files matching a prefix pattern in the ZIP."""
        target = prefix + pattern
        return [n for n in zf.namelist() if n.startswith(target) and n.endswith(".json")]

    def _extract_username(self, zf: zipfile.ZipFile, prefix: str) -> str | None:
        """Extract Spotify username from Userdata.json if present."""
        data = self._read_json(zf, prefix, "Userdata.json")
        if data and isinstance(data, dict):
            return data.get("username")
        # Also try Identity.json
        data = self._read_json(zf, prefix, "Identity.json")
        if data and isinstance(data, dict):
            return data.get("displayName")
        return None

    def _parse_favorites(
        self, zf: zipfile.ZipFile, prefix: str
    ) -> list[dict[str, Any]]:
        """Parse saved tracks from YourLibrary.json or YourLibrary1.json."""
        favorites: list[dict[str, Any]] = []

        # Try YourLibrary.json (older format)
        data = self._read_json(zf, prefix, "YourLibrary.json")
        if data and isinstance(data, dict):
            tracks = data.get("tracks", [])
            for t in tracks:
                favorites.append({
                    "artist": t.get("artist", ""),
                    "album": t.get("album", ""),
                    "track": t.get("track", ""),
                    "uri": t.get("uri", ""),
                })
            return favorites

        # Try newer numbered format (YourLibrary1.json, etc.)
        for filename in sorted(self._find_files(zf, prefix, "YourLibrary")):
            data = self._read_json(zf, "", filename)
            if data and isinstance(data, list):
                for t in data:
                    favorites.append({
                        "artist": t.get("artist", t.get("artistName", "")),
                        "album": t.get("album", t.get("albumName", "")),
                        "track": t.get("track", t.get("trackName", "")),
                        "uri": t.get("uri", t.get("trackUri", "")),
                    })

        return favorites

    def _parse_playlists(
        self, zf: zipfile.ZipFile, prefix: str
    ) -> list[dict[str, Any]]:
        """Parse playlists from Playlist*.json files."""
        playlists: list[dict[str, Any]] = []

        for filename in sorted(self._find_files(zf, prefix, "Playlist")):
            data = self._read_json(zf, "", filename)
            if not data:
                continue

            # Handle: array of playlists, {"playlists": [...]}, or single playlist object
            if isinstance(data, list):
                playlist_list = data
            elif isinstance(data, dict) and "playlists" in data:
                playlist_list = data["playlists"]
            else:
                playlist_list = [data]
            for pl in playlist_list:
                if not isinstance(pl, dict):
                    continue
                items_raw = pl.get("items", [])
                items = []
                for item in items_raw[:500]:  # Cap to avoid bloat
                    track_data = item.get("track", item)
                    if isinstance(track_data, dict):
                        items.append({
                            "artist": track_data.get("artistName", track_data.get("artist", "")),
                            "album": track_data.get("albumName", track_data.get("album", "")),
                            "track": track_data.get("trackName", track_data.get("track", "")),
                            "uri": track_data.get("trackUri", track_data.get("uri", "")),
                        })

                playlists.append({
                    "name": pl.get("name", "Untitled"),
                    "lastModifiedDate": pl.get("lastModifiedDate", ""),
                    "track_count": len(items),
                    "items": items,
                })

        return playlists

    def _aggregate_streaming_history(
        self, zf: zipfile.ZipFile, prefix: str
    ) -> dict[str, Any]:
        """Parse streaming history and aggregate to top artists/tracks."""
        artist_ms: Counter[str] = Counter()
        track_ms: Counter[tuple[str, str]] = Counter()
        total_ms = 0
        min_date: str | None = None
        max_date: str | None = None

        # Find all streaming history files
        history_files = (
            self._find_files(zf, prefix, "StreamingHistory_music_")
            + self._find_files(zf, prefix, "StreamingHistory")
            + self._find_files(zf, prefix, "endsong_")
        )
        # Deduplicate
        history_files = sorted(set(history_files))

        for filename in history_files:
            data = self._read_json(zf, "", filename)
            if not data or not isinstance(data, list):
                continue

            for entry in data:
                artist = entry.get("artistName", entry.get("master_metadata_album_artist_name", ""))
                track = entry.get("trackName", entry.get("master_metadata_track_name", ""))
                ms = entry.get("msPlayed", entry.get("ms_played", 0))
                date = entry.get("endTime", entry.get("ts", ""))

                if not artist or not track:
                    continue

                artist_ms[artist] += ms
                track_ms[(artist, track)] += ms
                total_ms += ms

                if date:
                    if min_date is None or date < min_date:
                        min_date = date
                    if max_date is None or date > max_date:
                        max_date = date

        # Top 50 artists, top 100 tracks
        top_artists = [
            {"artist": artist, "ms_played": ms}
            for artist, ms in artist_ms.most_common(50)
        ]
        top_tracks = [
            {"artist": artist, "track": track, "ms_played": ms}
            for (artist, track), ms in track_ms.most_common(100)
        ]

        return {
            "top_artists": top_artists,
            "top_tracks": top_tracks,
            "total_ms": total_ms,
            "date_range": {
                "start": min_date,
                "end": max_date,
            } if min_date else None,
        }

    # ---- Matching ----

    @staticmethod
    def _iter_unique_tracks(
        favorites: list[dict[str, Any]],
        playlists: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Deduplicate tracks across favorites+playlists, tracking sources.

        Returns dict keyed by normalized "artist:track" with values:
            {"artist": str, "track": str, "album": str, "sources": list[str]}
        """
        result: dict[str, dict[str, Any]] = {}

        def add(artist: str, track: str, album: str, source: str) -> None:
            if not artist or not track:
                return
            key = f"{normalize_for_matching(artist)}:{normalize_for_matching(track)}"
            if key not in result:
                result[key] = {
                    "artist": artist,
                    "track": track,
                    "album": album,
                    "sources": [source],
                }
            elif source not in result[key]["sources"]:
                result[key]["sources"].append(source)

        for fav in favorites:
            add(fav.get("artist", ""), fav.get("track", ""), fav.get("album", ""), "favorites")

        for pl in playlists:
            pl_name = pl.get("name", "Untitled")
            for item in pl.get("items", []):
                add(item.get("artist", ""), item.get("track", ""), item.get("album", ""), pl_name)

        return result

    async def _match_all(
        self,
        favorites: list[dict[str, Any]],
        playlists: list[dict[str, Any]],
        streaming_stats: dict[str, Any],
        progress_cb: Callable[[str, int, int], None] | None = None,
    ) -> dict[str, Any]:
        """Deduplicate all tracks and run TrackMatcher once."""
        # Collect unique (artist, track) pairs
        seen: set[str] = set()
        track_refs: list[dict[str, str]] = []

        def add_track(artist: str, title: str) -> None:
            key = f"{normalize_for_matching(artist)}:{normalize_for_matching(title)}"
            if key not in seen and artist and title:
                seen.add(key)
                track_refs.append({"artist": artist, "title": title})

        for fav in favorites:
            add_track(fav.get("artist", ""), fav.get("track", ""))

        for pl in playlists:
            for item in pl.get("items", []):
                add_track(item.get("artist", ""), item.get("track", ""))

        for t in streaming_stats.get("top_tracks", []):
            add_track(t.get("artist", ""), t.get("track", ""))

        logger.info(f"Matching {len(track_refs)} unique Spotify tracks against library")

        def _on_progress(processed: int, total: int) -> None:
            if progress_cb:
                progress_cb("Matching tracks...", processed, total)

        matcher = TrackMatcher(self.db)
        results = await matcher.match_batch(
            track_refs,
            on_progress=_on_progress if progress_cb else None,
        )

        match_dict: dict[str, Any] = {}
        for ref, track, method, confidence in results:
            key = f"{normalize_for_matching(ref['artist'])}:{normalize_for_matching(ref['title'])}"
            if track:
                match_dict[key] = {
                    "track_id": str(track.id),
                    "method": method,
                    "confidence": confidence,
                }

        logger.info(f"Matched {len(match_dict)}/{len(track_refs)} tracks")
        return match_dict

    def _compute_summary(
        self,
        favorites: list[dict[str, Any]],
        playlists: list[dict[str, Any]],
        streaming_stats: dict[str, Any],
        match_results: dict[str, Any],
        matching_status: str = "complete",
    ) -> dict[str, Any]:
        """Compute summary statistics."""

        def count_matched(items: list[dict[str, Any]]) -> int:
            count = 0
            for item in items:
                artist = item.get("artist", "")
                track = item.get("track", "")
                key = f"{normalize_for_matching(artist)}:{normalize_for_matching(track)}"
                if key in match_results:
                    count += 1
            return count

        matched_favorites = count_matched(favorites)

        total_playlist_tracks = sum(len(pl.get("items", [])) for pl in playlists)
        matched_playlist_tracks = sum(
            count_matched(pl.get("items", [])) for pl in playlists
        )

        top_tracks = streaming_stats.get("top_tracks", [])
        matched_top_tracks = count_matched(
            [{"artist": t["artist"], "track": t["track"]} for t in top_tracks]
        )

        # Count unique tracks the same way _match_all does
        seen: set[str] = set()
        for fav in favorites:
            a, t = fav.get("artist", ""), fav.get("track", "")
            if a and t:
                seen.add(f"{normalize_for_matching(a)}:{normalize_for_matching(t)}")
        for pl in playlists:
            for item in pl.get("items", []):
                a, t = item.get("artist", ""), item.get("track", "")
                if a and t:
                    seen.add(f"{normalize_for_matching(a)}:{normalize_for_matching(t)}")
        for tr in streaming_stats.get("top_tracks", []):
            a, t = tr.get("artist", ""), tr.get("track", "")
            if a and t:
                seen.add(f"{normalize_for_matching(a)}:{normalize_for_matching(t)}")

        total_unique = len(seen)
        total_matched = len(match_results)

        return {
            "total_favorites": len(favorites),
            "matched_favorites": matched_favorites,
            "total_playlists": len(playlists),
            "total_playlist_tracks": total_playlist_tracks,
            "matched_playlist_tracks": matched_playlist_tracks,
            "total_top_tracks": len(top_tracks),
            "matched_top_tracks": matched_top_tracks,
            "total_top_artists": len(streaming_stats.get("top_artists", [])),
            "total_matched": total_matched,
            "total_unique_tracks": total_unique,
            "total_unmatched": total_unique - total_matched,
            "match_rate": round(total_matched / total_unique * 100, 1) if total_unique else 0.0,
            "matching_status": matching_status,
        }
