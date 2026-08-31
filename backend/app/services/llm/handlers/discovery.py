"""Discovery tool handlers (bandcamp, similar artists, new releases, track identification)."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.db.models import Artist, ArtistAlias, Track, TrackStatus
from app.services.external_albums_helpers import normalize_artist_name

if TYPE_CHECKING:
    from app.services.llm.executor import ToolExecutor

logger = logging.getLogger(__name__)


class DiscoveryHandlersMixin:
    """Mixin providing discovery-related tool handlers."""

    async def _get_recently_played(
        self: "ToolExecutor",
        limit: int = 20,
        days: int | None = None,
    ) -> dict[str, Any]:
        """What the listener has actually been playing, newest first.

        **Written against `PlayEvent` rather than reusing anything, because nothing existed.** No
        endpoint, service or query in this codebase orders listening by time — `get_play_stats`
        answers "most played", which `filter_tracks(sort_by="play_count")` already reaches. The gap
        was recency.

        `PlayEvent` is the right source: one row per play, and `ix_play_events_profile_started_at`
        is exactly this query. `ProfilePlayHistory.last_played_at` holds a single timestamp per
        track, so it would collapse a track played five times today into one line.
        """
        from app.db.models import PlayEvent
        from app.utils.time import utcnow

        if not self.profile_id:
            return {"error": "No profile is bound to this session."}

        query = (
            select(PlayEvent, Track)
            .join(Track, PlayEvent.track_id == Track.id)
            .where(
                PlayEvent.profile_id == self.profile_id,
                # A file that failed to play is not listening, and treating it as taste would be
                # actively wrong — the listener never heard it.
                PlayEvent.outcome != "errored",
            )
            .order_by(PlayEvent.started_at.desc())
            .limit(max(1, min(limit, 100)))
        )
        if days:
            cutoff = utcnow() - timedelta(days=days)
            query = query.where(PlayEvent.started_at >= cutoff)

        rows = (await self.db.execute(query)).all()
        plays = []
        for event, track in rows:
            entry = self._track_to_dict(track)
            # `started_at` is naive UTC in the column. Marked explicitly, or the model has no way
            # to know whether a bare timestamp is local or not.
            entry["played_at"] = event.started_at.isoformat() + "Z"
            entry["outcome"] = event.outcome
            entry["completion_ratio"] = round(event.completion_ratio or 0.0, 2)
            plays.append(entry)

        return {
            "plays": plays,
            "count": len(plays),
            "note": (
                "Newest first. `outcome` is 'completed' or 'skipped' — a skip is a weaker signal "
                "of taste than a completed play, and repeats of the same track appear separately."
            ),
        }

    async def _get_radio_suggestions(
        self: "ToolExecutor",
        seed_track_id: str,
        limit: int = 10,
        profile: str = "radio",
    ) -> dict[str, Any]:
        """Familiar's own recommender, seeded from one track.

        Distinct from `find_similar_tracks`, which is a bare cosine-distance neighbour search over
        the audio embeddings. This runs the ranking engine: the same similarity, **plus** the
        listener's taste and the negative signal of what they have skipped. It scores better, and
        the two tools are kept apart in their descriptions so the model is not choosing between
        them at random.

        Cheaper than it looks — roughly four queries and a 150-row vector search over precomputed
        embeddings, with no embedding inference and no model load.
        """
        from app.services.ambient import get_candidates
        from app.services.ranking_profiles import get_profile

        ids = self._safe_parse_uuids([seed_track_id])
        if not ids:
            return {"error": f"{seed_track_id!r} is not a valid track id."}

        ranking = get_profile(profile if profile in ("radio", "ambient") else "radio")
        candidates, pool_size, collapsed = await get_candidates(
            self.db,
            current_track_id=ids[0],
            limit=max(1, min(limit, 20)),
            profile=ranking,
            profile_id=self.profile_id,
        )
        if not candidates:
            return {
                "suggestions": [],
                "note": (
                    "The recommender found nothing from that seed. Usually it has no audio "
                    "embedding yet, so there is nothing to be similar to."
                ),
            }

        by_id = {
            t.id: t
            for t in (
                await self.db.execute(
                    select(Track).where(Track.id.in_([c.descriptor.track_id for c in candidates]))
                )
            )
            .scalars()
            .all()
        }
        suggestions = []
        for candidate in candidates:
            track = by_id.get(candidate.descriptor.track_id)
            if track is None:
                continue
            entry = self._track_to_dict(track)
            entry["score"] = round(candidate.compatibility_score, 4)
            suggestions.append(entry)

        result: dict[str, Any] = {
            "suggestions": suggestions,
            "count": len(suggestions),
            "pool_size": pool_size,
        }
        if collapsed:
            # Said plainly: without an embedding the pool is drawn at random, so the ordering
            # means nothing and presenting it as a recommendation would be a lie.
            result["note"] = (
                "The candidate pool collapsed — the seed has no embedding, so these are close to "
                "random rather than similar."
            )
        return result

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

        # Top canonical artists by track count.
        result = await self.db.execute(
            select(Artist.name, func.count(Track.id).label("count"))
            .join(Track, Track.canonical_artist_id == Artist.id)
            .where(Track.active_filter())
            .group_by(Artist.id, Artist.name)
            .order_by(func.count(Track.id).desc())
            .limit(limit * 2)
        )
        artists = [row[0] for row in result.all() if row[0]]

        if not artists:
            return {
                "recommendations": [],
                "message": "No artists in library to base recommendations on",
            }

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
                    recommendations.append(
                        {
                            "type": r.result_type,
                            "name": r.name,
                            "artist": r.artist,
                            "url": r.url,
                            "genre": r.genre,
                        }
                    )

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
        artist_in_library_stmt = select(func.count(Track.id)).where(
            Track.active_filter(), Track.artist.ilike(f"%{artist}%")
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
                "bandcamp_search_url": f"https://bandcamp.com/search?q={artist.replace(' ', '+')}"
                if not requested_artist_in_library
                else None,
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
                    (
                        float(a.get("match", 0))
                        for a in similar_artists
                        if a.get("name", "").lower() == similar_name.lower()
                    ),
                    0.0,
                )
                artists_in_library.append(
                    {
                        "name": row.artist,
                        "track_count": row.track_count,
                        "similarity": round(match_score, 2),
                    }
                )

        # Sort by similarity score
        artists_in_library.sort(key=lambda x: x["similarity"], reverse=True)
        artists_in_library = artists_in_library[:limit]

        return {
            "requested_artist": artist,
            "requested_artist_in_library": requested_artist_in_library,
            "similar_artists_in_library": artists_in_library,
            "count": len(artists_in_library),
            "bandcamp_search_url": f"https://bandcamp.com/search?q={artist.replace(' ', '+')}"
            if not requested_artist_in_library
            else None,
            "note": f"Found {len(artists_in_library)} similar artists in your library. Search for their tracks to build a playlist."
            if artists_in_library
            else "No similar artists found in library.",
        }

    async def _get_new_releases(
        self: "ToolExecutor",
        days_back: int = 90,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Recent releases by the user's artists, read from the discovery precompute.

        **This reads a table. It does not call MusicBrainz** (ADR-0099 point 1).

        It used to walk the top fifteen artists and query MusicBrainz live, on the
        tool-call path, which is what hung a host for 240 seconds on 2026-08-30 — the
        host reporting a bare "Tool execution failed" that pointed at the app rather
        than the upstream. Bounding that scan made the symptom survivable; moving the
        read to the cache the background job already fills removes it.
        """
        from app.services.new_releases import NewReleasesService

        if not self.profile_id:
            return {"error": "Profile required for new releases lookup"}

        try:
            days_back = max(1, min(365, int(days_back)))
            limit = max(1, min(100, int(limit)))
        except (ValueError, TypeError):
            days_back, limit = 90, 20

        service = NewReleasesService(self.db)
        return await service.get_new_releases_view(days_back=days_back, limit=limit)

    async def _get_discovery_recommendations(
        self: "ToolExecutor",
        include_in_library: bool = False,
        seed_artists: int = 5,
        limit: int = 8,
    ) -> dict[str, Any]:
        """Get recommended artists based on top-played artists, plus unheard tracks and deep cuts."""
        from app.db.models import ProfilePlayHistory
        from app.services.lastfm import get_lastfm_service
        from app.services.search_links import generate_artist_search_url

        if not self.profile_id:
            return {"error": "Profile required for discovery recommendations"}

        try:
            seed_artists = max(1, min(20, int(seed_artists)))
            limit = max(1, min(50, int(limit)))
        except (ValueError, TypeError):
            seed_artists, limit = 5, 8

        # Top-played canonical artists.
        play_query = (
            select(
                Artist.id.label("artist_id"),
                Artist.name.label("artist_name"),
                Artist.similar_artists.label("similar_cached"),
                func.sum(ProfilePlayHistory.play_count).label("total_plays"),
            )
            .join(Track, ProfilePlayHistory.track_id == Track.id)
            .join(Artist, Artist.id == Track.canonical_artist_id)
            .where(ProfilePlayHistory.profile_id == self.profile_id)
            .group_by(Artist.id, Artist.name, Artist.similar_artists)
            .order_by(func.sum(ProfilePlayHistory.play_count).desc())
            .limit(seed_artists)
        )
        play_result = await self.db.execute(play_query)
        top_artists = play_result.fetchall()
        top_artist_ids = [row.artist_id for row in top_artists]

        if not top_artists:
            return {
                "recommended_artists": [],
                "unheard_tracks": [],
                "deep_cuts": [],
                "note": "No play history found.",
            }

        # Similar-artist candidates from the canonical artists' cached data.
        seen: set[str] = set()
        candidates: list[tuple[str, dict, str]] = []  # (normalized, similar_data, based_on)

        for row in top_artists:
            artist_name = row.artist_name

            if row.similar_cached:
                raw_similar = row.similar_cached
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
                normalized = normalize_artist_name(name)
                if normalized in seen:
                    continue
                seen.add(normalized)
                candidates.append((normalized, similar, artist_name))

        # Library presence — alias-keyed so spelling variants count.
        all_normalized = [c[0] for c in candidates]
        lib_counts: dict[str, int] = {}
        if all_normalized:
            lib_result = await self.db.execute(
                select(
                    ArtistAlias.alias_normalized.label("n"),
                    func.count(Track.id).label("cnt"),
                )
                .join(Artist, Artist.id == ArtistAlias.artist_id)
                .join(Track, Track.canonical_artist_id == Artist.id)
                .where(
                    ArtistAlias.alias_normalized.in_(all_normalized),
                    Track.status == TrackStatus.ACTIVE,
                )
                .group_by(ArtistAlias.alias_normalized)
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

            recommended.append(
                {
                    "name": similar.get("name", ""),
                    "match_score": round(match_score, 2),
                    "in_library": in_library,
                    "track_count": tc if in_library else None,
                    "bandcamp_url": generate_artist_search_url("bandcamp", similar.get("name", "")),
                    "based_on": based_on,
                }
            )

        recommended.sort(key=lambda a: a["match_score"], reverse=True)
        recommended = recommended[:limit]

        # Unheard tracks + deep cuts from the top canonical artists.
        unheard_tracks: list[dict[str, Any]] = []
        deep_cuts: list[dict[str, Any]] = []

        if top_artist_ids:
            played_ids = select(ProfilePlayHistory.track_id).where(
                ProfilePlayHistory.profile_id == self.profile_id
            )

            unheard_result = await self.db.execute(
                select(Track.id, Track.title, Track.artist, Track.album)
                .where(
                    Track.canonical_artist_id.in_(top_artist_ids),
                    Track.status == TrackStatus.ACTIVE,
                    Track.id.notin_(played_ids),
                )
                .order_by(func.random())
                .limit(10)
            )
            unheard_ids = set()
            for row in unheard_result.fetchall():
                unheard_ids.add(row.id)
                unheard_tracks.append(
                    {
                        "id": str(row.id),
                        "title": row.title,
                        "artist": row.artist,
                        "album": row.album,
                    }
                )

            deep_result = await self.db.execute(
                select(
                    Track.id, Track.title, Track.artist, Track.album, ProfilePlayHistory.play_count
                )
                .join(ProfilePlayHistory, ProfilePlayHistory.track_id == Track.id)
                .where(
                    Track.canonical_artist_id.in_(top_artist_ids),
                    Track.status == TrackStatus.ACTIVE,
                    ProfilePlayHistory.profile_id == self.profile_id,
                    ProfilePlayHistory.play_count > 0,
                )
                .order_by(ProfilePlayHistory.play_count.asc())
                .limit(10)
            )
            for row in deep_result.fetchall():
                if row.id not in unheard_ids:
                    deep_cuts.append(
                        {
                            "id": str(row.id),
                            "title": row.title,
                            "artist": row.artist,
                            "album": row.album,
                            "play_count": row.play_count,
                        }
                    )

        return {
            "recommended_artists": recommended,
            "unheard_tracks": unheard_tracks,
            "deep_cuts": deep_cuts,
            "note": f"Found {len(recommended)} recommended artists, {len(unheard_tracks)} unheard tracks, and {len(deep_cuts)} deep cuts from your top artists."
            if recommended or unheard_tracks
            else "Not enough listening history for recommendations yet.",
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
        stmt = (
            select(Track)
            .where(
                Track.active_filter(),
                func.lower(Track.title) == title.lower(),
                func.lower(Track.artist) == artist.lower(),
            )
            .limit(1)
        )
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
        stmt = (
            select(Track)
            .where(
                Track.active_filter(),
                func.lower(Track.artist).contains(artist.lower()),
            )
            .limit(200)
        )
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
