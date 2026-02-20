"""Discovery tool handlers (bandcamp, similar artists, track identification, external similar tracks)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.db.models import (
    SpotifyFavorite,
    Track,
)

if TYPE_CHECKING:
    from app.services.llm.executor import ToolExecutor

logger = logging.getLogger(__name__)


class DiscoveryHandlersMixin:
    """Mixin providing discovery-related tool handlers."""

    async def _search_bandcamp(
        self: ToolExecutor,
        query: str,
        item_type: str = "album",
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search Bandcamp for albums/tracks."""
        try:
            limit = int(float(limit)) if limit else 10
        except (ValueError, TypeError):
            limit = 10

        from app.services.bandcamp import BandcampService

        type_map = {"album": "a", "track": "t", "artist": "b"}
        api_type = type_map.get(item_type, "a")

        bc = BandcampService()
        try:
            results = await bc.search(query, item_type=api_type, limit=limit)
            return {
                "results": [
                    {
                        "type": r.result_type,
                        "name": r.name,
                        "artist": r.artist,
                        "url": r.url,
                        "genre": r.genre,
                        "release_date": r.release_date,
                    }
                    for r in results
                ],
                "count": len(results),
                "query": query,
            }
        finally:
            await bc.close()

    async def _recommend_bandcamp_purchases(self: ToolExecutor, limit: int = 5) -> dict[str, Any]:
        """Recommend Bandcamp albums based on unmatched Spotify favorites."""
        try:
            limit = int(float(limit)) if limit else 5
        except (ValueError, TypeError):
            limit = 5

        from app.services.bandcamp import BandcampService

        if not self.profile_id:
            return {"recommendations": [], "message": "No profile ID provided"}

        result = await self.db.execute(
            select(SpotifyFavorite)
            .where(
                SpotifyFavorite.profile_id == self.profile_id,
                SpotifyFavorite.matched_track_id.is_(None),
            )
            .order_by(SpotifyFavorite.added_at.desc())
            .limit(limit * 2)
        )
        favorites = result.scalars().all()

        if not favorites:
            return {
                "recommendations": [],
                "message": "No unmatched Spotify favorites to base recommendations on",
            }

        bc = BandcampService()
        recommendations = []
        seen_artists = set()

        try:
            for f in favorites:
                data = f.track_data or {}
                artist = data.get("artist")
                if not artist or artist.lower() in seen_artists:
                    continue

                seen_artists.add(artist.lower())
                results = await bc.search(artist, item_type="a", limit=2)

                for r in results:
                    recommendations.append({
                        "type": r.result_type,
                        "name": r.name,
                        "artist": r.artist,
                        "url": r.url,
                        "genre": r.genre,
                        "based_on": {
                            "spotify_track": data.get("name"),
                            "spotify_artist": artist,
                        },
                    })

                if len(recommendations) >= limit:
                    break
        finally:
            await bc.close()

        return {
            "recommendations": recommendations[:limit],
            "count": len(recommendations[:limit]),
            "note": "Albums recommended based on your Spotify favorites",
        }

    async def _get_similar_artists_in_library(
        self: ToolExecutor,
        artist: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Find artists similar to the given artist that exist in the library.

        Uses Last.fm to get similar artists, then checks which ones are in the library.
        Also returns Bandcamp search URL for the requested artist if not in library.
        """
        from app.services.lastfm import get_lastfm_service

        try:
            limit = int(float(limit)) if limit else 20
        except (ValueError, TypeError):
            limit = 20

        lastfm = get_lastfm_service()

        # Check if the requested artist is in the library
        artist_in_library_stmt = (
            select(func.count(Track.id))
            .where(Track.artist.ilike(f"%{artist}%"))
        )
        artist_count = await self.db.scalar(artist_in_library_stmt) or 0
        requested_artist_in_library = artist_count > 0

        # Get similar artists from Last.fm
        similar_artists = await lastfm.get_similar_artists(artist, limit=50)

        if not similar_artists:
            return {
                "requested_artist": artist,
                "requested_artist_in_library": requested_artist_in_library,
                "similar_artists_in_library": [],
                "count": 0,
                "bandcamp_search_url": f"https://bandcamp.com/search?q={artist.replace(' ', '+')}" if not requested_artist_in_library else None,
                "note": "Could not find similar artists via Last.fm. Try semantic_search instead.",
            }

        # Check which similar artists are in the library
        similar_names = [a.get("name", "") for a in similar_artists if a.get("name")]

        # Query library for matching artists
        artists_in_library: list[dict[str, Any]] = []
        for similar_name in similar_names:
            stmt = (
                select(Track.artist, func.count(Track.id).label("track_count"))
                .where(func.lower(Track.artist) == similar_name.lower())
                .group_by(Track.artist)
            )
            result = await self.db.execute(stmt)
            row = result.first()
            if row:
                # Find the match score from Last.fm data
                match_score = next(
                    (float(a.get("match", 0)) for a in similar_artists
                     if a.get("name", "").lower() == similar_name.lower()),
                    0.0
                )
                artists_in_library.append({
                    "name": row.artist,
                    "track_count": row.track_count,
                    "similarity": round(match_score, 2),
                })

        # Sort by similarity score
        artists_in_library.sort(key=lambda x: x["similarity"], reverse=True)
        artists_in_library = artists_in_library[:limit]

        return {
            "requested_artist": artist,
            "requested_artist_in_library": requested_artist_in_library,
            "similar_artists_in_library": artists_in_library,
            "count": len(artists_in_library),
            "bandcamp_search_url": f"https://bandcamp.com/search?q={artist.replace(' ', '+')}" if not requested_artist_in_library else None,
            "note": f"Found {len(artists_in_library)} similar artists in your library. Search for their tracks to build a playlist." if artists_in_library else "No similar artists found in library.",
        }

    async def _identify_track(
        self: ToolExecutor,
        title: str,
        artist: str,
    ) -> dict[str, Any]:
        """Identify a track by title and artist.

        Returns track info if found in library, or external info if not.
        Use this when user says "based on [song] by [artist]" to determine
        whether to use find_similar_tracks or external discovery tools.
        """
        from rapidfuzz import fuzz

        title = title.strip()
        artist = artist.strip()

        if not title or not artist:
            return {"error": "Both title and artist are required"}

        # Search local library for exact match first
        stmt = select(Track).where(
            func.lower(Track.title) == title.lower(),
            func.lower(Track.artist) == artist.lower(),
        ).limit(1)
        result = await self.db.execute(stmt)
        track = result.scalar_one_or_none()

        if track:
            return {
                "in_library": True,
                "track_id": str(track.id),
                "title": track.title,
                "artist": track.artist,
                "album": track.album,
                "note": "Track found in library. Use find_similar_tracks with this track_id.",
            }

        # Try fuzzy match on local library
        stmt = select(Track).where(
            func.lower(Track.artist).contains(artist.lower()),
        ).limit(200)
        result = await self.db.execute(stmt)
        candidates = list(result.scalars().all())

        best_match = None
        best_score = 0.0
        title_lower = title.lower()

        for t in candidates:
            if t.title:
                score = fuzz.ratio(title_lower, t.title.lower())
                if score > best_score and score >= 85:
                    best_score = score
                    best_match = t

        if best_match:
            return {
                "in_library": True,
                "track_id": str(best_match.id),
                "title": best_match.title,
                "artist": best_match.artist,
                "album": best_match.album,
                "match_score": round(best_score, 1),
                "note": "Track found in library (fuzzy match). Use find_similar_tracks with this track_id.",
            }

        # Not in library - try to get external info from Spotify if configured
        external_info: dict[str, Any] = {
            "title": title,
            "artist": artist,
        }

        if self.profile_id:
            from app.services.spotify import SpotifyService

            spotify_service = SpotifyService()
            if spotify_service.is_configured():
                client = await spotify_service.get_client(self.db, self.profile_id)
                if client:
                    try:
                        results = client.search(
                            q=f"track:{title} artist:{artist}",
                            type="track",
                            limit=1,
                        )
                        items = results.get("tracks", {}).get("items", [])
                        if items:
                            spotify_track = items[0]
                            external_info.update({
                                "album": spotify_track.get("album", {}).get("name"),
                                "spotify_id": spotify_track.get("id"),
                                "spotify_url": spotify_track.get("external_urls", {}).get("spotify"),
                            })
                    except Exception as e:
                        logger.warning(f"Spotify search failed for identify_track: {e}")

        return {
            "in_library": False,
            "external_info": external_info,
            "note": "Track not found in library. Use get_similar_artists_in_library and get_similar_tracks_external to build a similar playlist.",
            "bandcamp_search_url": f"https://bandcamp.com/search?q={artist.replace(' ', '+')}+{title.replace(' ', '+')}",
        }

    async def _get_similar_tracks_external(
        self: ToolExecutor,
        artist: str,
        track: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Get similar tracks from Last.fm.

        Returns tracks that may not be in the library.
        Use when building discovery playlists or when reference track isn't in library.
        """
        from app.services.lastfm import get_lastfm_service

        try:
            limit = int(float(limit)) if limit else 10
        except (ValueError, TypeError):
            limit = 10

        lastfm = get_lastfm_service()

        if not lastfm.is_configured():
            return {
                "tracks": [],
                "count": 0,
                "error": "Last.fm API not configured. Add Last.fm API key in Settings.",
            }

        # Get similar tracks from Last.fm
        similar_tracks = await lastfm.get_similar_tracks(artist, track, limit=limit * 2)

        if not similar_tracks:
            return {
                "reference_track": {"artist": artist, "track": track},
                "tracks": [],
                "count": 0,
                "note": "No similar tracks found via Last.fm.",
            }

        # Check which similar tracks are in the local library
        tracks_with_status: list[dict[str, Any]] = []

        for similar in similar_tracks[:limit]:
            similar_name = similar.get("name", "")
            similar_artist_data = similar.get("artist", {})
            similar_artist = similar_artist_data.get("name", "") if isinstance(similar_artist_data, dict) else str(similar_artist_data)

            if not similar_name or not similar_artist:
                continue

            # Check if in local library
            stmt = select(Track).where(
                func.lower(Track.title) == similar_name.lower(),
                func.lower(Track.artist) == similar_artist.lower(),
            ).limit(1)
            result = await self.db.execute(stmt)
            local_track = result.scalar_one_or_none()

            track_info: dict[str, Any] = {
                "title": similar_name,
                "artist": similar_artist,
                "match_score": round(float(similar.get("match", 0)), 2),
                "lastfm_url": similar.get("url"),
            }

            if local_track:
                track_info["in_library"] = True
                track_info["local_track_id"] = str(local_track.id)
                track_info["album"] = local_track.album
            else:
                track_info["in_library"] = False

            tracks_with_status.append(track_info)

        in_library_count = sum(1 for t in tracks_with_status if t.get("in_library"))

        return {
            "reference_track": {"artist": artist, "track": track},
            "tracks": tracks_with_status,
            "count": len(tracks_with_status),
            "in_library": in_library_count,
            "missing": len(tracks_with_status) - in_library_count,
            "note": f"Found {len(tracks_with_status)} similar tracks ({in_library_count} in library, {len(tracks_with_status) - in_library_count} not in library).",
        }
