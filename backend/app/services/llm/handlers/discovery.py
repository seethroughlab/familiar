"""Discovery tool handlers (bandcamp, similar artists, track identification, external similar tracks)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.db.models import Track, TrackStatus

if TYPE_CHECKING:
    from app.services.llm.executor import ToolExecutor

logger = logging.getLogger(__name__)


class DiscoveryHandlersMixin:
    """Mixin providing discovery-related tool handlers."""

    async def _search_bandcamp(
        self: "ToolExecutor",
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

    async def _recommend_bandcamp_purchases(self: "ToolExecutor", limit: int = 5) -> dict[str, Any]:
        """Recommend Bandcamp albums based on top artists in the library."""
        try:
            limit = int(float(limit)) if limit else 5
        except (ValueError, TypeError):
            limit = 5

        from app.services.bandcamp import BandcampService

        # Get top artists by track count
        result = await self.db.execute(
            select(Track.artist, func.count(Track.id).label("count"))
            .where(Track.active_filter(), Track.artist.isnot(None))
            .group_by(Track.artist)
            .order_by(func.count(Track.id).desc())
            .limit(limit * 2)
        )
        artists = [row[0] for row in result.all() if row[0]]

        if not artists:
            return {"recommendations": [], "message": "No artists in library to base recommendations on"}

        bc = BandcampService()
        recommendations = []
        seen_artists = set()

        try:
            for artist in artists:
                if artist.lower() in seen_artists:
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
                    })

                if len(recommendations) >= limit:
                    break
        finally:
            await bc.close()

        return {
            "recommendations": recommendations[:limit],
            "count": len(recommendations[:limit]),
            "note": "Albums recommended based on artists in your library",
        }

    async def _get_similar_artists_in_library(
        self: "ToolExecutor",
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
            .where(Track.active_filter(), Track.artist.ilike(f"%{artist}%"))
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
                .where(Track.active_filter(), func.lower(Track.artist) == similar_name.lower())
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

    async def _get_new_releases(
        self: "ToolExecutor",
        days_back: int = 90,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Find recent releases by the user's most-played artists via MusicBrainz."""
        from app.db.models import ArtistInfo, ProfilePlayHistory
        from app.services.metadata.musicbrainz import get_artist_releases_recent

        if not self.profile_id:
            return {"error": "Profile required for new releases lookup"}

        try:
            days_back = max(1, min(365, int(days_back)))
            limit = max(1, min(100, int(limit)))
        except (ValueError, TypeError):
            days_back, limit = 90, 20

        # Get top 15 artists by play count
        play_query = (
            select(
                func.lower(func.trim(Track.artist)).label("artist_normalized"),
                Track.artist,
                func.sum(ProfilePlayHistory.play_count).label("total_plays"),
            )
            .join(Track, ProfilePlayHistory.track_id == Track.id)
            .where(
                Track.artist.isnot(None),
                ProfilePlayHistory.profile_id == self.profile_id,
            )
            .group_by(func.lower(func.trim(Track.artist)), Track.artist)
            .order_by(func.sum(ProfilePlayHistory.play_count).desc())
            .limit(15)
        )
        play_result = await self.db.execute(play_query)
        top_artists = play_result.fetchall()

        if not top_artists:
            return {"releases": [], "artists_checked": 0, "note": "No play history found."}

        all_releases: list[dict[str, Any]] = []
        artists_checked = 0
        artists_skipped = 0

        for row in top_artists:
            cached = await self.db.get(ArtistInfo, row.artist_normalized)
            if not cached or not cached.musicbrainz_id:
                artists_skipped += 1
                continue

            artists_checked += 1
            releases = await asyncio.to_thread(
                get_artist_releases_recent,
                cached.musicbrainz_id,
                days_back,
            )

            for r in releases:
                all_releases.append({
                    "artist": row.artist,
                    "title": r["title"],
                    "type": r.get("release_type"),
                    "date": r["release_date"],
                    "in_library": False,
                })

        # Cross-reference with library
        if all_releases:
            album_pairs_query = (
                select(
                    func.lower(func.trim(Track.artist)),
                    func.lower(func.trim(Track.album)),
                )
                .where(
                    Track.artist.isnot(None),
                    Track.album.isnot(None),
                    Track.status == TrackStatus.ACTIVE,
                )
                .distinct()
            )
            album_result = await self.db.execute(album_pairs_query)
            library_albums = {(a, b) for a, b in album_result.fetchall()}

            for release in all_releases:
                key = (release["artist"].lower().strip(), release["title"].lower().strip())
                if key in library_albums:
                    release["in_library"] = True

        all_releases.sort(key=lambda r: r["date"], reverse=True)
        all_releases = all_releases[:limit]

        new_count = sum(1 for r in all_releases if not r["in_library"])
        return {
            "releases": all_releases,
            "artists_checked": artists_checked,
            "artists_skipped": artists_skipped,
            "count": len(all_releases),
            "new_releases_not_in_library": new_count,
            "note": f"Found {len(all_releases)} recent releases ({new_count} not in library) from {artists_checked} artists (last {days_back} days)."
            if all_releases
            else f"No recent releases found in the last {days_back} days.",
        }

    async def _get_discovery_recommendations(
        self: "ToolExecutor",
        include_in_library: bool = False,
        seed_artists: int = 5,
        limit: int = 8,
    ) -> dict[str, Any]:
        """Get recommended artists based on top-played artists, plus unheard tracks and deep cuts."""
        from app.db.models import ArtistInfo, ProfilePlayHistory
        from app.services.lastfm import get_lastfm_service
        from app.services.search_links import generate_artist_search_url

        if not self.profile_id:
            return {"error": "Profile required for discovery recommendations"}

        try:
            seed_artists = max(1, min(20, int(seed_artists)))
            limit = max(1, min(50, int(limit)))
        except (ValueError, TypeError):
            seed_artists, limit = 5, 8

        # Get top-played artists
        play_query = (
            select(
                func.lower(func.trim(Track.artist)).label("artist_normalized"),
                Track.artist,
                func.sum(ProfilePlayHistory.play_count).label("total_plays"),
            )
            .join(Track, ProfilePlayHistory.track_id == Track.id)
            .where(
                Track.artist.isnot(None),
                ProfilePlayHistory.profile_id == self.profile_id,
            )
            .group_by(func.lower(func.trim(Track.artist)), Track.artist)
            .order_by(func.sum(ProfilePlayHistory.play_count).desc())
            .limit(seed_artists)
        )
        play_result = await self.db.execute(play_query)
        top_artists = play_result.fetchall()

        if not top_artists:
            return {"recommended_artists": [], "unheard_tracks": [], "deep_cuts": [], "note": "No play history found."}

        # Collect similar artist candidates
        seen: set[str] = set()
        candidates: list[tuple[str, dict, str]] = []  # (normalized, similar_data, based_on)

        for row in top_artists:
            artist_name = row.artist
            artist_normalized = row.artist_normalized

            cached_info = await self.db.get(ArtistInfo, artist_normalized)
            if cached_info and cached_info.similar_artists:
                raw_similar = cached_info.similar_artists
            else:
                lastfm = get_lastfm_service()
                if lastfm.is_configured():
                    try:
                        info = await lastfm.get_artist_info(artist_name)
                        raw_similar = info.get("similar", {}).get("artist", []) if info else []
                    except Exception:
                        raw_similar = []
                else:
                    raw_similar = []

            for similar in raw_similar[:3]:
                name = similar.get("name", "")
                if not name:
                    continue
                normalized = name.lower().strip()
                if normalized in seen:
                    continue
                seen.add(normalized)
                candidates.append((normalized, similar, artist_name))

        # Batch check library counts
        all_normalized = [c[0] for c in candidates]
        lib_counts: dict[str, int] = {}
        if all_normalized:
            lib_result = await self.db.execute(
                select(
                    func.lower(func.trim(Track.artist)).label("n"),
                    func.count(Track.id).label("cnt"),
                )
                .where(
                    func.lower(func.trim(Track.artist)).in_(all_normalized),
                    Track.status == TrackStatus.ACTIVE,
                )
                .group_by(func.lower(func.trim(Track.artist)))
            )
            for r in lib_result.all():
                lib_counts[r.n] = r.cnt

        recommended: list[dict[str, Any]] = []
        for normalized, similar, based_on in candidates:
            tc = lib_counts.get(normalized, 0)
            in_library = tc > 0
            if not include_in_library and in_library:
                continue

            try:
                match_score = float(similar.get("match", 0))
            except (ValueError, TypeError):
                match_score = 0.0

            recommended.append({
                "name": similar.get("name", ""),
                "match_score": round(match_score, 2),
                "in_library": in_library,
                "track_count": tc if in_library else None,
                "bandcamp_url": generate_artist_search_url("bandcamp", similar.get("name", "")),
                "based_on": based_on,
            })

        recommended.sort(key=lambda a: a["match_score"], reverse=True)
        recommended = recommended[:limit]

        # Unheard tracks from top artists
        top_artist_names = [row.artist_normalized for row in top_artists if row.artist_normalized]
        unheard_tracks: list[dict[str, Any]] = []
        deep_cuts: list[dict[str, Any]] = []

        if top_artist_names:
            played_ids = (
                select(ProfilePlayHistory.track_id)
                .where(ProfilePlayHistory.profile_id == self.profile_id)
            )

            unheard_result = await self.db.execute(
                select(Track.id, Track.title, Track.artist, Track.album)
                .where(
                    func.lower(func.trim(Track.artist)).in_(top_artist_names),
                    Track.status == TrackStatus.ACTIVE,
                    Track.id.notin_(played_ids),
                )
                .order_by(func.random())
                .limit(10)
            )
            unheard_ids = set()
            for row in unheard_result.fetchall():
                unheard_ids.add(row.id)
                unheard_tracks.append({
                    "id": str(row.id),
                    "title": row.title,
                    "artist": row.artist,
                    "album": row.album,
                })

            deep_result = await self.db.execute(
                select(Track.id, Track.title, Track.artist, Track.album, ProfilePlayHistory.play_count)
                .join(ProfilePlayHistory, ProfilePlayHistory.track_id == Track.id)
                .where(
                    func.lower(func.trim(Track.artist)).in_(top_artist_names),
                    Track.status == TrackStatus.ACTIVE,
                    ProfilePlayHistory.profile_id == self.profile_id,
                    ProfilePlayHistory.play_count > 0,
                )
                .order_by(ProfilePlayHistory.play_count.asc())
                .limit(10)
            )
            for row in deep_result.fetchall():
                if row.id not in unheard_ids:
                    deep_cuts.append({
                        "id": str(row.id),
                        "title": row.title,
                        "artist": row.artist,
                        "album": row.album,
                        "play_count": row.play_count,
                    })

        return {
            "recommended_artists": recommended,
            "unheard_tracks": unheard_tracks,
            "deep_cuts": deep_cuts,
            "note": f"Found {len(recommended)} recommended artists, {len(unheard_tracks)} unheard tracks, and {len(deep_cuts)} deep cuts from your top artists."
            if recommended or unheard_tracks
            else "Not enough listening history for recommendations yet.",
        }

    async def _get_spotify_unmatched(
        self: "ToolExecutor",
        search: str | None = None,
        artist: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Find Spotify tracks not matched to local library, with summary stats."""
        from app.db.models import SpotifyImport
        from app.services.spotify_import import SpotifyImportService

        if not self.profile_id:
            return {"error": "Profile required for Spotify lookup"}

        try:
            limit = max(1, min(200, int(limit)))
        except (ValueError, TypeError):
            limit = 50

        # Get import
        result = await self.db.execute(
            select(SpotifyImport).where(SpotifyImport.profile_id == self.profile_id)
        )
        import_ = result.scalar_one_or_none()

        if not import_:
            return {"error": "No Spotify import found. Import your Spotify data first via Settings."}

        # Get stats from summary
        summary = import_.summary or {}
        stats = {
            "total_unique_tracks": summary.get("total_unique_tracks"),
            "total_matched": summary.get("total_matched", 0),
            "total_unmatched": summary.get("total_unmatched"),
            "match_rate": summary.get("match_rate"),
        }

        # Get unmatched tracks
        unique = SpotifyImportService._iter_unique_tracks(import_.favorites, import_.playlists)
        match_results = import_.match_results or {}
        unmatched = [v for k, v in unique.items() if k not in match_results]

        # Apply filters
        if search:
            s = search.lower()
            unmatched = [
                t for t in unmatched
                if s in t["artist"].lower() or s in t["track"].lower() or s in t["album"].lower()
            ]
        if artist:
            a = artist.lower()
            unmatched = [t for t in unmatched if a in t["artist"].lower()]

        unmatched.sort(key=lambda t: (t["artist"].lower(), t["track"].lower()))
        total_filtered = len(unmatched)
        page = unmatched[:limit]

        return {
            "stats": stats,
            "unmatched_tracks": [
                {"artist": t["artist"], "track": t["track"], "album": t["album"]}
                for t in page
            ],
            "total_unmatched_shown": len(page),
            "total_unmatched_matching_filter": total_filtered,
            "note": f"Showing {len(page)} of {total_filtered} unmatched Spotify tracks. Match rate: {stats.get('match_rate', 'unknown')}.",
        }

    async def _identify_track(
        self: "ToolExecutor",
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
            Track.active_filter(),
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
            Track.active_filter(),
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

        return {
            "in_library": False,
            "title": title,
            "artist": artist,
            "note": "Track not found in library. Use get_similar_artists_in_library to find related artists.",
            "bandcamp_search_url": f"https://bandcamp.com/search?q={artist.replace(' ', '+')}+{title.replace(' ', '+')}",
        }

    async def _get_similar_tracks_external(
        self: "ToolExecutor",
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
                Track.active_filter(),
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
