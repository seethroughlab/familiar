"""Playlist tool handlers (select_diverse, fetch_webpage, create_playlist_from_items, search_for_item, save_as_playlist)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import func, select

from app.db.models import (
    Playlist,
    PlaylistTrack,
    Track,
)

if TYPE_CHECKING:
    from app.services.llm.executor import ToolExecutor

logger = logging.getLogger(__name__)


class PlaylistHandlersMixin:
    """Mixin providing playlist-related tool handlers."""

    async def _select_diverse_tracks(
        self: "ToolExecutor",
        track_ids: list[str],
        limit: int = 20,
        max_per_artist: int = 2,
        max_per_album: int = 2,
    ) -> dict[str, Any]:
        """Select a diverse subset from given track IDs."""
        # Convert params to int (LLM may pass strings)
        def safe_int(v: Any, default: int) -> int:
            try:
                return int(float(v)) if v else default
            except (ValueError, TypeError):
                return default

        limit = safe_int(limit, 20)
        max_per_artist = safe_int(max_per_artist, 2)
        max_per_album = safe_int(max_per_album, 2)

        if not track_ids:
            return {"tracks": [], "count": 0, "note": "No tracks provided"}

        valid_uuids = self._safe_parse_uuids(track_ids)
        if not valid_uuids:
            return {"tracks": [], "count": 0, "note": "No valid track IDs provided"}
        stmt = select(Track).where(Track.active_filter(), Track.id.in_(valid_uuids))
        result = await self.db.execute(stmt)
        tracks = list(result.scalars().all())

        if not tracks:
            return {"tracks": [], "count": 0, "note": "No matching tracks found"}

        diverse_tracks = self._apply_diversity(
            tracks,
            max_per_artist=max_per_artist,
            max_per_album=max_per_album,
        )

        selected = diverse_tracks[:limit]
        unique_artists = len(set(t.artist for t in selected if t.artist))

        return {
            "tracks": [self._track_to_dict(t) for t in selected],
            "count": len(selected),
            "unique_artists": unique_artists,
            "note": f"Selected {len(selected)} tracks from {unique_artists} different artists",
        }

    async def _fetch_webpage(self: "ToolExecutor", url: str) -> dict[str, Any]:
        """Fetch a web page and extract readable content.

        Uses curl_cffi for TLS fingerprint impersonation to bypass bot detection
        on sites like Discogs, Pitchfork, RateYourMusic that block httpx.
        """
        from urllib.parse import urlparse

        import trafilatura
        from curl_cffi.requests import AsyncSession

        # Validate URL
        if not url or not url.startswith(("http://", "https://")):
            return {"error": "Invalid URL. Must start with http:// or https://"}

        # Extract domain for Referer header
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        try:
            async with AsyncSession() as session:
                response = await session.get(
                    url,
                    impersonate="chrome",  # Latest Chrome TLS fingerprint
                    timeout=30,
                    headers={
                        # Minimal headers - let curl_cffi set browser-appropriate defaults
                        # Referer suggests we came from the site itself (not a bot)
                        "Referer": base_url + "/",
                    },
                    allow_redirects=True,
                )
                response.raise_for_status()
                html = response.text
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"fetch_webpage failed for {url}: {error_msg}")
            if "timeout" in error_msg.lower():
                return {"error": "Request timed out"}
            if "403" in error_msg:
                return {"error": "Access denied (403) - site is blocking automated access"}
            return {"error": f"Failed to fetch page: {error_msg}"}

        # Extract readable content with trafilatura
        content = trafilatura.extract(
            html,
            favor_recall=True,
            include_links=False,
            include_images=False,
            include_tables=True,
        )

        if not content:
            return {
                "error": "Could not extract readable content from page",
                "url": url,
            }

        # Truncate if too long (to fit in context)
        max_chars = 15000
        if len(content) > max_chars:
            content = content[:max_chars] + "\n\n[Content truncated...]"

        return {
            "url": url,
            "content": content,
            "char_count": len(content),
        }

    async def _create_playlist_from_items(
        self: "ToolExecutor",
        name: str,
        items: list[dict[str, Any]],
        description: str | None = None,
        tracks_per_album: int = 3,
    ) -> dict[str, Any]:
        """Create a playlist from extracted music items.

        Matches items to local library. Items not found in the library are reported but not added.
        """
        if not self.profile_id:
            return {"error": "No profile ID - cannot create playlist", "created": False}

        if not items:
            return {"error": "No items provided", "created": False}

        # Validate tracks_per_album
        try:
            tracks_per_album = int(float(tracks_per_album)) if tracks_per_album else 3
            tracks_per_album = max(1, min(tracks_per_album, 10))  # Clamp 1-10
        except (ValueError, TypeError):
            tracks_per_album = 3

        # Create the playlist
        playlist = Playlist(
            profile_id=self.profile_id,
            name=name,
            description=description,
            is_auto_generated=True,
            generation_prompt=self.user_message,
        )
        self.db.add(playlist)
        await self.db.flush()

        position = 0
        local_tracks_added = 0
        missing_tracks_added = 0
        found_items: list[dict[str, Any]] = []
        missing_items: list[dict[str, Any]] = []

        for item in items:
            artist = item.get("artist", "").strip()
            album = item.get("album", "").strip() if item.get("album") else None
            track_name = item.get("track", "").strip() if item.get("track") else None
            year = item.get("year")

            if not artist:
                continue

            # Search for matching tracks in library
            matched_tracks = await self._search_for_item(
                artist=artist,
                album=album,
                track=track_name,
                limit=tracks_per_album if album and not track_name else 1,
            )

            if matched_tracks:
                # Add local tracks to playlist
                for track in matched_tracks:
                    playlist_track = PlaylistTrack(
                        playlist_id=playlist.id,
                        track_id=track.id,
                        position=position,
                    )
                    self.db.add(playlist_track)
                    position += 1
                    local_tracks_added += 1

                found_items.append({
                    "artist": artist,
                    "album": album,
                    "track": track_name,
                    "matched_count": len(matched_tracks),
                })
            else:
                missing_tracks_added += 1
                missing_items.append({
                    "artist": artist,
                    "album": album,
                    "track": track_name,
                    "year": year,
                })

        await self.db.commit()

        total_tracks = local_tracks_added

        return {
            "created": True,
            "playlist_id": str(playlist.id),
            "playlist_name": name,
            "total_tracks": total_tracks,
            "local_tracks": local_tracks_added,
            "missing_tracks": missing_tracks_added,
            "found_items": found_items,
            "missing_items": missing_items,
            "message": f"Created playlist '{name}' with {total_tracks} tracks ({missing_tracks_added} not found in library).",
        }

    async def _search_for_item(
        self: "ToolExecutor",
        artist: str,
        album: str | None = None,
        track: str | None = None,
        limit: int = 3,
    ) -> list[Track]:
        """Search local library for matching tracks.

        Priority:
        1. If track specified: exact track match
        2. If album specified: tracks from that album
        3. Otherwise: any tracks by artist
        """
        if track:
            # Search for specific track
            stmt = select(Track).where(
                Track.active_filter(),
                func.lower(Track.artist).contains(artist.lower()),
                func.lower(Track.title).contains(track.lower()),
            ).limit(1)
            result = await self.db.execute(stmt)
            tracks = list(result.scalars().all())
            if tracks:
                return tracks

            # Try fuzzy match on title
            stmt = select(Track).where(
                Track.active_filter(),
                func.lower(Track.artist).contains(artist.lower()),
            ).limit(100)
            result = await self.db.execute(stmt)
            candidates = list(result.scalars().all())

            # Use rapidfuzz for title matching
            from rapidfuzz import fuzz
            track_lower = track.lower()
            best_match = None
            best_score = 0.0

            for t in candidates:
                if t.title:
                    score = fuzz.ratio(track_lower, t.title.lower())
                    if score > best_score and score >= 80:
                        best_score = score
                        best_match = t

            if best_match:
                return [best_match]

        if album:
            # Search for album tracks
            stmt = select(Track).where(
                Track.active_filter(),
                func.lower(Track.artist).contains(artist.lower()),
                func.lower(Track.album).contains(album.lower()),
            ).order_by(Track.disc_number, Track.track_number).limit(limit)
            result = await self.db.execute(stmt)
            tracks = list(result.scalars().all())
            if tracks:
                return tracks

            # Try album_artist match
            stmt = select(Track).where(
                Track.active_filter(),
                func.lower(Track.album_artist).contains(artist.lower()),
                func.lower(Track.album).contains(album.lower()),
            ).order_by(Track.disc_number, Track.track_number).limit(limit)
            result = await self.db.execute(stmt)
            tracks = list(result.scalars().all())
            if tracks:
                return tracks

        # Fall back to any tracks by artist
        stmt = select(Track).where(
            Track.active_filter(),
            func.lower(Track.artist).contains(artist.lower()),
        ).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def _save_as_playlist(
        self: "ToolExecutor",
        name: str,
        track_ids: list[str],
        description: str | None = None,
    ) -> dict[str, Any]:
        """Save tracks as an AI-generated playlist."""
        if not self.profile_id:
            return {"error": "No profile ID - cannot save playlist", "saved": False}

        if not track_ids:
            return {"error": "No tracks provided", "saved": False}

        playlist = Playlist(
            profile_id=self.profile_id,
            name=name,
            description=description,
            is_auto_generated=True,
            generation_prompt=self.user_message,
        )
        self.db.add(playlist)
        await self.db.flush()

        tracks_added = 0
        for position, track_id_str in enumerate(track_ids):
            try:
                track_id = UUID(track_id_str)
            except ValueError:
                continue

            track = await self.db.get(Track, track_id)
            if not track:
                continue

            playlist_track = PlaylistTrack(
                playlist_id=playlist.id,
                track_id=track_id,
                position=position,
            )
            self.db.add(playlist_track)
            tracks_added += 1

        await self.db.commit()

        return {
            "saved": True,
            "playlist_id": str(playlist.id),
            "playlist_name": name,
            "tracks_saved": tracks_added,
            "message": f"Saved {tracks_added} tracks as '{name}'",
        }
