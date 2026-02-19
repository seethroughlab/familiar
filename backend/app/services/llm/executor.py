"""Tool executor for LLM service."""

import logging
import random
import re
from typing import Any
from uuid import UUID

import anthropic
import httpx
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ChangeScope,
    ChangeSource,
    ChangeStatus,
    ExternalTrackSource,
    Playlist,
    PlaylistTrack,
    ProfileFavorite,
    ProfilePlayHistory,
    ProposedChange,
    SpotifyFavorite,
    SpotifyProfile,
    Track,
    TrackAnalysis,
)
from app.services.app_settings import get_app_settings_service
from app.services.external_track_matcher import ExternalTrackMatcher
from app.services.metadata_lookup import get_metadata_lookup_service

# Timeout for LLM calls (shorter for playlist name generation)
_PLAYLIST_NAME_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Executes tools called by the LLM."""

    def __init__(
        self,
        db: AsyncSession,
        profile_id: UUID | None = None,
        user_message: str = "",
        visible_track_ids: list[str] | None = None,
    ) -> None:
        self.db = db
        self.profile_id = profile_id
        self.user_message = user_message
        self.visible_track_ids = visible_track_ids or []
        self._queued_tracks: list[dict[str, Any]] = []
        self._clear_queue: bool = True  # Default to clearing queue for new requests
        self._playback_action: str | None = None
        self._auto_saved_playlist: dict[str, Any] | None = None

    async def execute(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool and return the result."""
        logger.info(f"Executing tool: {tool_name}")
        handlers = {
            "search_library": self._search_library,
            "find_similar_tracks": self._find_similar_tracks,
            "semantic_search": self._semantic_search,
            "filter_tracks": self._filter_tracks,
            "filter_tracks_by_features": self._filter_tracks,  # backwards compat alias
            "get_library_stats": self._get_library_stats,
            "get_library_genres": self._get_library_genres,
            "queue_tracks": self._queue_tracks,
            "control_playback": self._control_playback,
            "get_track_details": self._get_track_details,
            "get_spotify_status": self._get_spotify_status,
            "get_spotify_favorites": self._get_spotify_favorites,
            "get_unmatched_spotify_favorites": self._get_unmatched_spotify_favorites,
            "get_spotify_sync_stats": self._get_spotify_sync_stats,
            "search_bandcamp": self._search_bandcamp,
            "recommend_bandcamp_purchases": self._recommend_bandcamp_purchases,
            "select_diverse_tracks": self._select_diverse_tracks,
            # Metadata correction tools
            "lookup_correct_metadata": self._lookup_correct_metadata,
            "propose_metadata_change": self._propose_metadata_change,
            "get_album_tracks": self._get_album_tracks,
            "mark_album_as_compilation": self._mark_album_as_compilation,
            "propose_album_artwork": self._propose_album_artwork,
            # Duplicate detection tools
            "find_duplicate_artists": self._find_duplicate_artists,
            "merge_duplicate_artists": self._merge_duplicate_artists,
            # View context tools
            "get_visible_tracks": self._get_visible_tracks,
            # Discovery tools
            "get_similar_artists_in_library": self._get_similar_artists_in_library,
            # Spotify playlist tools
            "list_spotify_playlists": self._list_spotify_playlists,
            "get_spotify_playlist_tracks": self._get_spotify_playlist_tracks,
            "import_spotify_playlist": self._import_spotify_playlist,
            # Web page reading tools
            "fetch_webpage": self._fetch_webpage,
            "create_playlist_from_items": self._create_playlist_from_items,
            # Track identification tools
            "identify_track": self._identify_track,
            "get_similar_tracks_external": self._get_similar_tracks_external,
            # Deep analysis tools
            "get_track_analysis": self._get_track_analysis,
        }

        handler = handlers.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            # Handle methods that take no args vs those that do
            if tool_name in ("get_library_stats", "get_spotify_status", "get_spotify_sync_stats", "get_visible_tracks"):
                return await handler()  # type: ignore[operator]
            return await handler(**tool_input)  # type: ignore[operator]
        except Exception as e:
            logger.exception(f"Tool {tool_name} failed")
            try:
                await self.db.rollback()
            except Exception:
                pass
            error_detail = str(e)[:200] if str(e) else "no details"
            return {"error": f"Tool '{tool_name}' failed ({type(e).__name__}): {error_detail}"}

    def get_queued_tracks(self) -> tuple[list[dict[str, Any]], bool]:
        """Get tracks that were queued during this conversation turn.

        Returns (tracks, should_clear_queue).
        """
        return self._queued_tracks, self._clear_queue

    def get_playback_action(self) -> str | None:
        """Get playback action requested during this conversation turn."""
        return self._playback_action

    def get_auto_saved_playlist(self) -> dict[str, Any] | None:
        """Get the auto-saved playlist created during this conversation turn."""
        return self._auto_saved_playlist

    # --- Helper methods ---

    def _safe_parse_uuids(self, ids: list[str]) -> list[UUID]:
        """Parse a list of string IDs to UUIDs, skipping invalid ones."""
        valid = []
        for id_str in ids:
            try:
                valid.append(UUID(id_str))
            except (ValueError, AttributeError):
                logger.warning(f"Skipping invalid UUID: {id_str!r}")
        return valid

    async def _generate_playlist_name_llm(self, tracks: list[dict[str, Any]]) -> str:
        """Generate a creative playlist name using the LLM."""
        from datetime import datetime

        logger.info(f"Generating playlist name for {len(tracks)} tracks, user_message='{self.user_message}'")

        if not tracks:
            return f"AI Playlist - {datetime.now().strftime('%b %d %H:%M')}"

        artists = list(set(t.get("artist", "") for t in tracks[:10] if t.get("artist")))
        genres = list(set(t.get("genre", "") for t in tracks[:10] if t.get("genre")))

        prompt = f"""Generate a short, creative playlist name (2-5 words max).

User's request: "{self.user_message or 'curated selection'}"
Artists included: {', '.join(artists[:5]) or 'Various'}
Genres: {', '.join(genres[:3]) or 'Mixed'}
Track count: {len(tracks)}

Rules:
- Be creative and evocative, not literal
- Don't just repeat the user's words
- Avoid generic names like "Chill Vibes" or "Good Music"
- No quotes, colons, or special characters
- Examples of good names: "Midnight Drive", "Sunday Morning Coffee", "Electric Dreams"

Respond with ONLY the playlist name, nothing else."""

        try:
            api_key = get_app_settings_service().get_effective("anthropic_api_key")
            if not api_key:
                raise ValueError("No API key")

            anthropic_client = anthropic.Anthropic(api_key=api_key, timeout=_PLAYLIST_NAME_TIMEOUT)
            message = anthropic_client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=50,
                messages=[{"role": "user", "content": prompt}],
            )
            name = ""
            if message.content:
                first_block = message.content[0]
                if hasattr(first_block, "text"):
                    name = first_block.text.strip()

            name = name.strip('"\'').strip()
            logger.info(f"LLM generated playlist name: '{name}'")
            if name and len(name) <= 50 and not any(c in name for c in [":", "\n", '"']):
                return name
            else:
                logger.warning(f"Generated name rejected (empty, too long, or invalid chars): '{name}'")

        except Exception as e:
            logger.warning(f"LLM playlist name generation failed: {e}")

        return self._generate_playlist_name_fallback()

    def _generate_playlist_name_fallback(self) -> str:
        """Fallback playlist name from user message or timestamp."""
        from datetime import datetime

        if self.user_message:
            name = self.user_message[:50].strip()
            if len(self.user_message) > 50:
                name += "..."
            return name
        return f"AI Playlist - {datetime.now().strftime('%b %d %H:%M')}"

    def _normalize_query_variations(self, query: str) -> list[str]:
        """Generate search variations to handle number padding, etc."""
        variations = [query]

        padded = re.sub(r"(\s)(\d)(\s|$)", r"\g<1>0\2\3", query)
        if padded != query:
            variations.append(padded)

        unpadded = re.sub(r"(\s)0(\d)(\s|$)", r"\g<1>\2\3", query)
        if unpadded != query:
            variations.append(unpadded)

        return variations

    def _apply_diversity(
        self,
        tracks: list[Track],
        max_per_artist: int = 2,
        max_per_album: int = 3,
    ) -> list[Track]:
        """Filter tracks to ensure diversity across artists and albums."""
        shuffled = list(tracks)
        random.shuffle(shuffled)

        artist_counts: dict[str, int] = {}
        album_counts: dict[str, int] = {}
        diverse: list[Track] = []

        for track in shuffled:
            artist_key = (track.artist or "").lower().strip()
            album_key = f"{artist_key}:{(track.album or '').lower().strip()}"

            artist_count = artist_counts.get(artist_key, 0)
            album_count = album_counts.get(album_key, 0)

            if artist_count >= max_per_artist or album_count >= max_per_album:
                continue

            diverse.append(track)
            artist_counts[artist_key] = artist_count + 1
            album_counts[album_key] = album_count + 1

        return diverse

    def _track_to_dict(self, track: Track) -> dict[str, Any]:
        """Convert track to dictionary."""
        return {
            "id": str(track.id),
            "title": track.title,
            "artist": track.artist,
            "album": track.album,
            "genre": track.genre,
            "duration_seconds": track.duration_seconds,
            "year": track.year,
        }

    # --- Tool implementations ---

    async def _search_library(self, query: str, limit: int = 20) -> dict[str, Any]:
        """Search tracks by text query with diversity across artists/albums."""
        # Convert limit to int (LLM may pass string)
        try:
            limit = int(float(limit)) if limit else 20
        except (ValueError, TypeError):
            limit = 20

        variations = self._normalize_query_variations(query)

        conditions = []
        for var in variations:
            search_filter = f"%{var}%"
            conditions.extend([
                Track.title.ilike(search_filter),
                Track.artist.ilike(search_filter),
                Track.album.ilike(search_filter),
                Track.genre.ilike(search_filter),
            ])

        stmt = select(Track).where(or_(*conditions)).limit(limit * 5)
        result = await self.db.execute(stmt)
        all_tracks = list(result.scalars().all())

        diverse_tracks = self._apply_diversity(all_tracks, max_per_artist=2, max_per_album=3)
        random.shuffle(diverse_tracks)
        selected = diverse_tracks[:limit]

        return {
            "tracks": [self._track_to_dict(t) for t in selected],
            "count": len(selected),
            "note": f"Selected from {len(all_tracks)} matches with artist/album diversity",
        }

    async def _find_similar_tracks(self, track_id: str, limit: int = 10) -> dict[str, Any]:
        """Find similar tracks using embedding similarity."""
        # Convert limit to int (LLM may pass string)
        try:
            limit = int(float(limit)) if limit else 10
        except (ValueError, TypeError):
            limit = 10

        stmt = (
            select(TrackAnalysis.embedding)
            .where(TrackAnalysis.track_id == UUID(track_id))
            .order_by(TrackAnalysis.version.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        embedding = result.scalar_one_or_none()

        if embedding is None:
            return {"error": "Track not analyzed yet", "tracks": []}

        similar_stmt = (
            select(Track)
            .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
            .where(Track.id != UUID(track_id))
            .where(TrackAnalysis.embedding.isnot(None))
            .order_by(TrackAnalysis.embedding.cosine_distance(embedding))
            .limit(limit * 4)
        )
        result = await self.db.execute(similar_stmt)
        all_tracks = list(result.scalars().all())

        diverse_tracks = self._apply_diversity(all_tracks, max_per_artist=2, max_per_album=2)
        selected = diverse_tracks[:limit]

        return {
            "tracks": [self._track_to_dict(t) for t in selected],
            "count": len(selected),
            "note": f"Similar tracks from {len(set(t.artist for t in selected))} different artists",
        }

    async def _semantic_search(self, description: str, limit: int = 20) -> dict[str, Any]:
        """Search for tracks using text-to-audio semantic similarity via CLAP embeddings."""
        from app.services.analysis import extract_text_embedding, get_analysis_capabilities

        # Convert limit to int (LLM may pass string)
        try:
            limit = int(float(limit)) if limit else 20
        except (ValueError, TypeError):
            limit = 20

        # Check if semantic search is available
        caps = get_analysis_capabilities()
        if not caps["embeddings_enabled"]:
            return {
                "error": f"Semantic search unavailable: {caps['embeddings_disabled_reason']}",
                "tracks": [],
                "fallback_suggestion": "Try search_library or filter_tracks_by_features instead",
            }

        # Get text embedding
        embedding = extract_text_embedding(description)
        if embedding is None:
            return {
                "error": "Failed to generate text embedding",
                "tracks": [],
                "fallback_suggestion": "Try search_library or filter_tracks_by_features instead",
            }

        # Query for similar tracks using cosine distance
        similar_stmt = (
            select(Track)
            .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
            .where(TrackAnalysis.embedding.isnot(None))
            .order_by(TrackAnalysis.embedding.cosine_distance(embedding))
            .limit(limit * 4)  # Fetch extra for diversity filtering
        )
        result = await self.db.execute(similar_stmt)
        all_tracks = list(result.scalars().all())

        # Apply diversity filtering
        diverse_tracks = self._apply_diversity(all_tracks, max_per_artist=2, max_per_album=3)
        random.shuffle(diverse_tracks)
        selected = diverse_tracks[:limit]

        return {
            "tracks": [self._track_to_dict(t) for t in selected],
            "count": len(selected),
            "description": description,
            "note": f"Found {len(selected)} tracks matching '{description}' from {len(set(t.artist for t in selected))} artists",
        }

    async def _filter_tracks(
        self,
        # Library criteria
        genre: str | None = None,
        artist: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        added_in_last_days: int | None = None,
        is_favorite: bool | None = None,
        min_play_count: int | None = None,
        max_play_count: int | None = None,
        played_in_last_days: int | None = None,
        not_played_in_days: int | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        # Audio feature criteria
        bpm_min: float | None = None,
        bpm_max: float | None = None,
        key: str | None = None,
        energy_min: float | None = None,
        energy_max: float | None = None,
        danceability_min: float | None = None,
        valence_min: float | None = None,
        valence_max: float | None = None,
        acousticness_min: float | None = None,
        instrumentalness_min: float | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Filter tracks by library criteria and/or audio features."""
        from datetime import UTC, datetime, timedelta

        # --- Type coercion helpers (LLM may pass strings) ---
        def to_float(v: Any) -> float | None:
            if v is None:
                return None
            try:
                return float(v)
            except (ValueError, TypeError):
                return None

        def to_int(v: Any, default: int | None = None) -> int | None:
            if v is None:
                return default
            try:
                return int(float(v))
            except (ValueError, TypeError):
                return default

        def to_bool(v: Any) -> bool | None:
            if v is None:
                return None
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.lower() in ("true", "1", "yes")
            return bool(v)

        # Coerce all params
        bpm_min = to_float(bpm_min)
        bpm_max = to_float(bpm_max)
        energy_min = to_float(energy_min)
        energy_max = to_float(energy_max)
        danceability_min = to_float(danceability_min)
        valence_min = to_float(valence_min)
        valence_max = to_float(valence_max)
        acousticness_min = to_float(acousticness_min)
        instrumentalness_min = to_float(instrumentalness_min)
        year_min = to_int(year_min)
        year_max = to_int(year_max)
        added_in_last_days = to_int(added_in_last_days)
        is_favorite = to_bool(is_favorite)
        min_play_count = to_int(min_play_count)
        max_play_count = to_int(max_play_count)
        played_in_last_days = to_int(played_in_last_days)
        not_played_in_days = to_int(not_played_in_days)
        limit = to_int(limit, 20) or 20

        # --- Determine which joins are needed ---
        has_audio_features = any(v is not None for v in [
            bpm_min, bpm_max, key, energy_min, energy_max,
            danceability_min, valence_min, valence_max,
            acousticness_min, instrumentalness_min,
        ])
        needs_play_history = any(v is not None for v in [
            min_play_count, max_play_count, played_in_last_days, not_played_in_days,
        ]) or (sort_by in ("play_count", "last_played"))

        # --- Build query ---
        stmt = select(Track)

        # Join TrackAnalysis only when audio feature filters are used
        if has_audio_features:
            stmt = stmt.join(TrackAnalysis, Track.id == TrackAnalysis.track_id)

        # Join ProfileFavorite when is_favorite filter is used
        if is_favorite and self.profile_id:
            stmt = stmt.join(
                ProfileFavorite,
                and_(
                    ProfileFavorite.track_id == Track.id,
                    ProfileFavorite.profile_id == self.profile_id,
                ),
            )

        # Left outer join ProfilePlayHistory when play history filters/sort are used
        if needs_play_history and self.profile_id:
            stmt = stmt.outerjoin(
                ProfilePlayHistory,
                and_(
                    ProfilePlayHistory.track_id == Track.id,
                    ProfilePlayHistory.profile_id == self.profile_id,
                ),
            )

        conditions: list[Any] = []

        # --- Library criteria ---
        if genre is not None:
            conditions.append(Track.genre.ilike(f"%{genre}%"))
        if artist is not None:
            conditions.append(Track.artist.ilike(f"%{artist}%"))
        if year_min is not None:
            conditions.append(Track.year >= year_min)
        if year_max is not None:
            conditions.append(Track.year <= year_max)
        if added_in_last_days is not None:
            cutoff = datetime.now(UTC) - timedelta(days=added_in_last_days)
            conditions.append(Track.created_at >= cutoff)

        # Play count filters (require profile + play history join)
        if needs_play_history and self.profile_id:
            if min_play_count is not None:
                conditions.append(
                    func.coalesce(ProfilePlayHistory.play_count, 0) >= min_play_count
                )
            if max_play_count is not None:
                if max_play_count == 0:
                    # Never played = no play history row at all
                    conditions.append(ProfilePlayHistory.track_id.is_(None))
                else:
                    conditions.append(
                        func.coalesce(ProfilePlayHistory.play_count, 0) <= max_play_count
                    )
            if played_in_last_days is not None:
                cutoff = datetime.now(UTC) - timedelta(days=played_in_last_days)
                conditions.append(ProfilePlayHistory.last_played_at >= cutoff)
            if not_played_in_days is not None:
                cutoff = datetime.now(UTC) - timedelta(days=not_played_in_days)
                conditions.append(
                    or_(
                        ProfilePlayHistory.last_played_at.is_(None),
                        ProfilePlayHistory.last_played_at < cutoff,
                    )
                )

        # --- Audio feature criteria ---
        if bpm_min is not None:
            conditions.append(
                text("(features->>'bpm')::float >= :bpm_min").bindparams(bpm_min=bpm_min)
            )
        if bpm_max is not None:
            conditions.append(
                text("(features->>'bpm')::float <= :bpm_max").bindparams(bpm_max=bpm_max)
            )
        if key is not None:
            key_normalized = key.strip().upper()
            key_root = key_normalized.split()[0].rstrip("M")
            if "SHARP" in key_normalized:
                key_root = key_root.rstrip("#") + "#"
            elif "FLAT" in key_normalized or "B" in key_normalized.split()[-1:]:
                flat_to_sharp = {"BB": "A#", "EB": "D#", "AB": "G#", "DB": "C#", "GB": "F#"}
                if key_root + "B" in flat_to_sharp:
                    key_root = flat_to_sharp[key_root + "B"]
                elif key_root in flat_to_sharp:
                    key_root = flat_to_sharp[key_root]
            conditions.append(
                text("features->>'key' = :key_value").bindparams(key_value=key_root)
            )
        if energy_min is not None:
            conditions.append(
                text("(features->>'energy')::float >= :energy_min").bindparams(
                    energy_min=energy_min
                )
            )
        if energy_max is not None:
            conditions.append(
                text("(features->>'energy')::float <= :energy_max").bindparams(
                    energy_max=energy_max
                )
            )
        if danceability_min is not None:
            conditions.append(
                text("(features->>'danceability')::float >= :danceability_min").bindparams(
                    danceability_min=danceability_min
                )
            )
        if valence_min is not None:
            conditions.append(
                text("(features->>'valence')::float >= :valence_min").bindparams(
                    valence_min=valence_min
                )
            )
        if valence_max is not None:
            conditions.append(
                text("(features->>'valence')::float <= :valence_max").bindparams(
                    valence_max=valence_max
                )
            )
        if acousticness_min is not None:
            conditions.append(
                text("(features->>'acousticness')::float >= :acousticness_min").bindparams(
                    acousticness_min=acousticness_min
                )
            )
        if instrumentalness_min is not None:
            conditions.append(
                text("(features->>'instrumentalness')::float >= :instrumentalness_min").bindparams(
                    instrumentalness_min=instrumentalness_min
                )
            )

        for condition in conditions:
            stmt = stmt.where(condition)

        # --- Sorting ---
        use_random = sort_by is None or sort_by == "random"

        if not use_random:
            # Default sort directions per sort_by
            default_desc = {"play_count", "last_played", "recently_added"}
            effective_order = sort_order or ("desc" if sort_by in default_desc else "asc")
            is_desc = effective_order == "desc"

            sort_column: Any = None
            if sort_by == "play_count" and self.profile_id:
                sort_column = func.coalesce(ProfilePlayHistory.play_count, 0)
            elif sort_by == "last_played" and self.profile_id:
                sort_column = ProfilePlayHistory.last_played_at
            elif sort_by == "recently_added":
                sort_column = Track.created_at
            elif sort_by == "title":
                sort_column = Track.title
            elif sort_by == "artist":
                sort_column = Track.artist
            elif sort_by == "year":
                sort_column = Track.year

            if sort_column is not None:
                stmt = stmt.order_by(sort_column.desc() if is_desc else sort_column.asc())

        stmt = stmt.limit(limit * 5)
        result = await self.db.execute(stmt)
        all_tracks = list(result.scalars().all())

        diverse_tracks = self._apply_diversity(all_tracks, max_per_artist=2, max_per_album=3)

        if use_random:
            random.shuffle(diverse_tracks)

        selected = diverse_tracks[:limit]

        return {
            "tracks": [self._track_to_dict(t) for t in selected],
            "count": len(selected),
            "note": f"Selected from {len(all_tracks)} matches with artist/album diversity",
        }

    async def _get_library_stats(self) -> dict[str, Any]:
        """Get library statistics."""
        total_result = await self.db.execute(select(func.count(Track.id)))
        total_tracks = total_result.scalar() or 0

        artists_result = await self.db.execute(
            select(func.count(func.distinct(Track.artist)))
        )
        total_artists = artists_result.scalar() or 0

        albums_result = await self.db.execute(
            select(func.count(func.distinct(Track.album)))
        )
        total_albums = albums_result.scalar() or 0

        genres_result = await self.db.execute(
            select(Track.genre, func.count(Track.id).label("count"))
            .where(Track.genre.isnot(None))
            .group_by(Track.genre)
            .order_by(text("count DESC"))
            .limit(10)
        )
        top_genres = [{"genre": r[0], "count": r[1]} for r in genres_result.all()]

        return {
            "total_tracks": total_tracks,
            "total_artists": total_artists,
            "total_albums": total_albums,
            "top_genres": top_genres,
        }

    async def _get_visible_tracks(self) -> dict[str, Any]:
        """Get the tracks currently visible in the user's library view.

        Returns the tracks that the user can see right now in the UI.
        Use this when the user refers to 'these tracks', 'this list',
        'what I'm looking at', or wants to queue/analyze the current view.
        """
        if not self.visible_track_ids:
            return {
                "tracks": [],
                "count": 0,
                "message": "No tracks currently visible in the library view.",
            }

        # Fetch track details from database
        result = await self.db.execute(
            select(Track).where(Track.id.in_(self.visible_track_ids))
        )
        tracks = result.scalars().all()

        # Build a map to preserve order
        track_map = {str(t.id): t for t in tracks}

        # Return in the same order as visible_track_ids
        ordered_tracks = []
        for track_id in self.visible_track_ids:
            if track_id in track_map:
                t = track_map[track_id]
                ordered_tracks.append({
                    "id": str(t.id),
                    "title": t.title,
                    "artist": t.artist or "Unknown Artist",
                    "album": t.album or "Unknown Album",
                    "duration_seconds": t.duration_seconds,
                    "genre": t.genre,
                })

        return {
            "tracks": ordered_tracks,
            "count": len(ordered_tracks),
            "message": f"Found {len(ordered_tracks)} tracks in the current view.",
        }

    async def _get_library_genres(self, limit: int = 50) -> dict[str, Any]:
        """Get all genres in the library with track counts."""
        try:
            limit = int(float(limit)) if limit else 50
        except (ValueError, TypeError):
            limit = 50

        genres_result = await self.db.execute(
            select(Track.genre, func.count(Track.id).label("count"))
            .where(Track.genre.isnot(None))
            .where(Track.genre != "")
            .group_by(Track.genre)
            .order_by(text("count DESC"))
            .limit(limit)
        )
        genres = [{"genre": r[0], "count": r[1]} for r in genres_result.all()]

        return {
            "genres": genres,
            "total": len(genres),
            "hint": "Use these genre names in search_library to find tracks.",
        }

    async def _queue_tracks(
        self,
        track_ids: list[str],
        clear_existing: bool = False,
        suggested_tracks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Queue tracks for playback and return ephemeral playlist metadata.

        The playlist is NOT automatically saved - instead we return metadata
        for the frontend to store ephemerally. User must explicitly save.

        Args:
            track_ids: List of local track UUIDs to queue for playback
            clear_existing: Whether to clear the current queue
            suggested_tracks: External tracks to suggest (stored with ephemeral metadata)
        """
        logger.info(f"_queue_tracks called with {len(track_ids)} tracks, {len(suggested_tracks or [])} suggested")

        # Get local tracks for playback queue
        valid_uuids = self._safe_parse_uuids(track_ids)
        if not valid_uuids:
            return {"queued": 0, "clear_existing": clear_existing, "tracks": [], "note": "No valid track IDs provided"}
        stmt = select(Track).where(Track.id.in_(valid_uuids))
        result = await self.db.execute(stmt)
        tracks = result.scalars().all()

        self._queued_tracks = [self._track_to_dict(t) for t in tracks]

        # Generate playlist name for ephemeral metadata (no DB save)
        playlist_name = ""
        if tracks and self.profile_id:
            playlist_name = await self._generate_playlist_name_llm(self._queued_tracks)

        # Build ephemeral playlist metadata for frontend to store temporarily
        self._auto_saved_playlist = {
            "ephemeral": True,
            "name": playlist_name,
            "generation_prompt": self.user_message,
            "track_ids": track_ids,
            "tracks": self._queued_tracks,
            "suggested_tracks": suggested_tracks or [],
        }

        response: dict[str, Any] = {
            "queued": len(tracks),
            "clear_existing": clear_existing,
            "tracks": self._queued_tracks,
        }

        return response

    async def _control_playback(self, action: str) -> dict[str, Any]:
        """Control playback."""
        self._playback_action = action
        return {"action": action, "status": "ok"}

    async def _get_track_details(self, track_id: str) -> dict[str, Any]:
        """Get detailed track info including features."""
        stmt = select(Track).where(Track.id == UUID(track_id))
        result = await self.db.execute(stmt)
        track = result.scalar_one_or_none()

        if not track:
            return {"error": "Track not found"}

        analysis_stmt = (
            select(TrackAnalysis)
            .where(TrackAnalysis.track_id == UUID(track_id))
            .order_by(TrackAnalysis.version.desc())
            .limit(1)
        )
        analysis_result = await self.db.execute(analysis_stmt)
        analysis = analysis_result.scalar_one_or_none()

        track_dict = self._track_to_dict(track)
        if analysis:
            track_dict["features"] = analysis.features

        return track_dict

    async def _get_spotify_status(self) -> dict[str, Any]:
        """Check if Spotify is connected."""
        if not self.profile_id:
            return {
                "connected": False,
                "message": "No profile ID provided. User can connect via Settings.",
            }

        result = await self.db.execute(
            select(SpotifyProfile).where(SpotifyProfile.profile_id == self.profile_id)
        )
        profile = result.scalar_one_or_none()

        if not profile:
            return {
                "connected": False,
                "message": "Spotify not connected. User can connect via Settings.",
            }

        return {
            "connected": True,
            "spotify_user_id": profile.spotify_user_id,
            "last_sync": profile.last_sync_at.isoformat() if profile.last_sync_at else None,
        }

    async def _get_spotify_favorites(self, limit: int = 50) -> dict[str, Any]:
        """Get Spotify favorites that are matched to local library."""
        try:
            limit = int(float(limit)) if limit else 50
        except (ValueError, TypeError):
            limit = 50

        if not self.profile_id:
            return {"tracks": [], "count": 0, "note": "No profile ID provided"}

        result = await self.db.execute(
            select(SpotifyFavorite, Track)
            .join(Track, SpotifyFavorite.matched_track_id == Track.id)
            .where(
                SpotifyFavorite.profile_id == self.profile_id,
                SpotifyFavorite.matched_track_id.isnot(None),
            )
            .order_by(SpotifyFavorite.added_at.desc())
            .limit(limit)
        )
        rows = result.all()

        tracks = []
        for favorite, track in rows:
            track_dict = self._track_to_dict(track)
            track_dict["spotify_added_at"] = (
                favorite.added_at.isoformat() if favorite.added_at else None
            )
            tracks.append(track_dict)

        return {
            "tracks": tracks,
            "count": len(tracks),
            "note": "These are Spotify favorites that match tracks in your local library",
        }

    async def _get_unmatched_spotify_favorites(self, limit: int = 50) -> dict[str, Any]:
        """Get Spotify favorites that don't have local matches."""
        try:
            limit = int(float(limit)) if limit else 50
        except (ValueError, TypeError):
            limit = 50

        if not self.profile_id:
            return {"tracks": [], "count": 0, "note": "No profile ID provided"}

        result = await self.db.execute(
            select(SpotifyFavorite)
            .where(
                SpotifyFavorite.profile_id == self.profile_id,
                SpotifyFavorite.matched_track_id.is_(None),
            )
            .order_by(SpotifyFavorite.added_at.desc())
            .limit(limit)
        )
        favorites = result.scalars().all()

        unmatched = []
        for f in favorites:
            data = f.track_data or {}
            unmatched.append({
                "spotify_id": f.spotify_track_id,
                "name": data.get("name"),
                "artist": data.get("artist"),
                "album": data.get("album"),
                "added_at": f.added_at.isoformat() if f.added_at else None,
                "spotify_url": data.get("external_url"),
            })

        return {
            "tracks": unmatched,
            "count": len(unmatched),
            "note": "These are Spotify favorites you don't have in your local library",
        }

    async def _get_spotify_sync_stats(self) -> dict[str, Any]:
        """Get Spotify sync statistics."""
        if not self.profile_id:
            return {
                "total_favorites": 0,
                "matched": 0,
                "unmatched": 0,
                "match_rate": 0,
                "last_sync": None,
                "connected": False,
            }

        total = (
            await self.db.scalar(
                select(func.count(SpotifyFavorite.id)).where(
                    SpotifyFavorite.profile_id == self.profile_id
                )
            )
            or 0
        )

        matched = (
            await self.db.scalar(
                select(func.count(SpotifyFavorite.id)).where(
                    SpotifyFavorite.profile_id == self.profile_id,
                    SpotifyFavorite.matched_track_id.isnot(None),
                )
            )
            or 0
        )

        profile_result = await self.db.execute(
            select(SpotifyProfile).where(SpotifyProfile.profile_id == self.profile_id)
        )
        profile = profile_result.scalar_one_or_none()

        return {
            "total_favorites": total,
            "matched": matched,
            "unmatched": total - matched,
            "match_rate": round(matched / total * 100, 1) if total > 0 else 0,
            "last_sync": (
                profile.last_sync_at.isoformat() if profile and profile.last_sync_at else None
            ),
            "connected": profile is not None,
        }

    async def _search_bandcamp(
        self,
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

    async def _recommend_bandcamp_purchases(self, limit: int = 5) -> dict[str, Any]:
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

    async def _save_as_playlist(
        self,
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

    async def _select_diverse_tracks(
        self,
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
        stmt = select(Track).where(Track.id.in_(valid_uuids))
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

    # --- Metadata correction tools ---

    async def _lookup_correct_metadata(self, track_id: str) -> dict[str, Any]:
        """Look up correct metadata from external sources."""
        try:
            track_uuid = UUID(track_id)
        except ValueError:
            return {"error": "Invalid track ID"}

        stmt = select(Track).where(Track.id == track_uuid)
        result = await self.db.execute(stmt)
        track = result.scalar_one_or_none()

        if not track:
            return {"error": "Track not found"}

        lookup_service = get_metadata_lookup_service()
        candidates = await lookup_service.lookup_track(
            title=track.title or "",
            artist=track.artist or "",
            album=track.album,
            duration_ms=int(track.duration_seconds * 1000) if track.duration_seconds else None,
        )

        return {
            "track": {
                "id": str(track.id),
                "title": track.title,
                "artist": track.artist,
                "album": track.album,
                "album_artist": track.album_artist,
                "year": track.year,
                "genre": track.genre,
            },
            "candidates": [
                {
                    "source": c.source,
                    "confidence": round(c.confidence, 2),
                    "metadata": c.metadata,
                    "match_details": c.match_details,
                }
                for c in candidates[:5]
            ],
            "note": "Use propose_metadata_change to suggest corrections based on these results",
        }

    async def _propose_metadata_change(
        self,
        track_ids: list[str],
        field: str,
        new_value: str,
        reason: str,
        source: str = "user_request",
    ) -> dict[str, Any]:
        """Create a proposed change for user review."""
        if not track_ids:
            return {"error": "No track IDs provided"}

        valid_fields = ["title", "artist", "album", "album_artist", "year", "genre"]
        if field not in valid_fields:
            return {"error": f"Invalid field. Must be one of: {', '.join(valid_fields)}"}

        # Get current values for all tracks
        valid_uuids = self._safe_parse_uuids(track_ids)
        if not valid_uuids:
            return {"error": "No valid track IDs provided"}
        stmt = select(Track).where(Track.id.in_(valid_uuids))
        result = await self.db.execute(stmt)
        tracks = list(result.scalars().all())

        if not tracks:
            return {"error": "No tracks found with those IDs"}

        # Build old_value map
        old_values = {}
        for track in tracks:
            current_value = getattr(track, field, None)
            old_values[str(track.id)] = current_value

        # Convert year to int if needed
        final_new_value: Any = new_value
        if field == "year":
            try:
                final_new_value = int(new_value)
            except ValueError:
                return {"error": f"Invalid year value: {new_value}"}

        # Determine source enum
        source_enum = ChangeSource.USER_REQUEST
        if source == "llm_suggestion":
            source_enum = ChangeSource.LLM_SUGGESTION

        # Create the proposed change
        change = ProposedChange(
            change_type="metadata",
            target_type="track",
            target_ids=track_ids,
            field=field,
            old_value=old_values,
            new_value=final_new_value,
            source=source_enum,
            source_detail="LLM tool call",
            confidence=1.0 if source == "user_request" else 0.9,
            reason=reason,
            scope=ChangeScope.DB_ONLY,
            status=ChangeStatus.PENDING,
        )
        self.db.add(change)
        await self.db.commit()
        await self.db.refresh(change)

        logger.info(f"Created proposed change {change.id}: {field} -> {new_value} for {len(track_ids)} tracks")

        return {
            "status": "proposed",
            "change_id": str(change.id),
            "field": field,
            "new_value": final_new_value,
            "tracks_affected": len(tracks),
            "message": f"Proposed changing '{field}' to '{new_value}' for {len(tracks)} track(s). Opening the Proposed Changes view for review.",
            "_navigate": "proposed-changes",  # Triggers frontend navigation
        }

    async def _get_album_tracks(
        self,
        album: str,
        artist: str | None = None,
    ) -> dict[str, Any]:
        """Get all tracks from a specific album."""
        stmt = select(Track).where(Track.album.ilike(f"%{album}%"))

        if artist:
            stmt = stmt.where(
                or_(
                    Track.artist.ilike(f"%{artist}%"),
                    Track.album_artist.ilike(f"%{artist}%"),
                )
            )

        stmt = stmt.order_by(Track.disc_number, Track.track_number)
        result = await self.db.execute(stmt)
        tracks = list(result.scalars().all())

        if not tracks:
            return {"tracks": [], "count": 0, "note": f"No tracks found for album '{album}'"}

        # Group info
        artists_on_album = list(set(t.artist for t in tracks if t.artist))
        album_artist = tracks[0].album_artist

        return {
            "album": tracks[0].album,
            "album_artist": album_artist,
            "artists_on_album": artists_on_album,
            "is_multi_artist": len(artists_on_album) > 1,
            "tracks": [
                {
                    "id": str(t.id),
                    "title": t.title,
                    "artist": t.artist,
                    "track_number": t.track_number,
                    "disc_number": t.disc_number,
                }
                for t in tracks
            ],
            "count": len(tracks),
            "track_ids": [str(t.id) for t in tracks],
            "note": "Use propose_metadata_change with track_ids to suggest changes for all these tracks",
        }

    async def _mark_album_as_compilation(
        self,
        album: str,
        album_artist: str,
        reason: str,
    ) -> dict[str, Any]:
        """Mark an album as a compilation by setting album_artist for all tracks."""
        # First get all tracks for this album
        album_result = await self._get_album_tracks(album)

        if album_result.get("count", 0) == 0:
            return {"error": f"No tracks found for album '{album}'"}

        track_ids = album_result.get("track_ids", [])

        # Propose the album_artist change
        return await self._propose_metadata_change(
            track_ids=track_ids,
            field="album_artist",
            new_value=album_artist,
            reason=reason,
            source="user_request",
        )

    async def _propose_album_artwork(
        self,
        artist: str,
        album: str,
        reason: str,
    ) -> dict[str, Any]:
        """Search for album artwork and propose a change."""
        # First get the tracks for this album to get their IDs
        album_result = await self._get_album_tracks(album, artist)

        if album_result.get("count", 0) == 0:
            return {"error": f"No tracks found for album '{album}' by '{artist}'"}

        track_ids = album_result.get("track_ids", [])

        # Search for artwork options
        lookup_service = get_metadata_lookup_service()
        artwork_options = await lookup_service.search_artwork(artist, album, limit=5)

        if not artwork_options:
            return {
                "error": f"No artwork found for '{album}' by '{artist}'",
                "note": "Try searching for the album on Cover Art Archive manually",
            }

        # Use the best match
        best_option = artwork_options[0]

        # Create the proposed change
        change = ProposedChange(
            change_type="artwork",
            target_type="album",
            target_ids=track_ids,
            field="artwork_url",
            old_value=None,
            new_value={
                "url": best_option["url"],
                "source": best_option["source"],
                "source_id": best_option.get("source_id"),
                "album": best_option.get("album"),
                "artist": best_option.get("artist"),
            },
            source=ChangeSource.USER_REQUEST,
            source_detail=f"Cover Art Archive: {best_option.get('source_id', 'unknown')}",
            confidence=best_option.get("confidence", 0.8),
            reason=reason,
            scope=ChangeScope.DB_ONLY,
            status=ChangeStatus.PENDING,
        )
        self.db.add(change)
        await self.db.commit()
        await self.db.refresh(change)

        logger.info(f"Created artwork proposed change {change.id} for album '{album}'")

        return {
            "status": "proposed",
            "change_id": str(change.id),
            "artwork_url": best_option["url"],
            "source": best_option["source"],
            "tracks_affected": len(track_ids),
            "artwork_options_found": len(artwork_options),
            "message": f"Found artwork for '{album}' and proposed the change. User can review in Settings > Proposed Changes.",
        }

    def _normalize_artist_for_comparison(self, artist: str) -> str:
        """Normalize artist name for duplicate detection.

        Handles common variations:
        - Case: "Artist Name" vs "artist name"
        - Separators: "_" vs " ", "-" vs " "
        - Conjunctions: "and" vs "&" vs "+"
        - Whitespace: extra spaces
        """
        if not artist:
            return ""

        s = artist.lower().strip()

        # Normalize separators to spaces
        s = s.replace("_", " ")
        s = s.replace("-", " ")

        # Normalize conjunctions
        s = s.replace(" & ", " and ")
        s = s.replace(" + ", " and ")
        s = s.replace("&", " and ")
        s = s.replace("+", " and ")

        # Collapse whitespace
        s = " ".join(s.split())

        return s

    async def _find_duplicate_artists(
        self,
        artist_hint: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Find artists that are likely duplicates based on normalized names."""
        from collections import defaultdict

        # Get all distinct artists
        stmt = (
            select(Track.artist, func.count(Track.id).label("track_count"))
            .where(Track.artist.isnot(None), Track.artist != "")
            .group_by(Track.artist)
            .order_by(func.count(Track.id).desc())
        )
        result = await self.db.execute(stmt)
        artists = [(row.artist, row.track_count) for row in result.all()]

        # Group by normalized name
        normalized_groups: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for artist, count in artists:
            normalized = self._normalize_artist_for_comparison(artist)
            normalized_groups[normalized].append((artist, count))

        # Find groups with more than one variant
        duplicates = []
        for normalized, variants in normalized_groups.items():
            if len(variants) > 1:
                # If artist_hint provided, only include groups that match
                if artist_hint:
                    hint_normalized = self._normalize_artist_for_comparison(artist_hint)
                    if hint_normalized != normalized:
                        continue

                # Sort by track count (most common first)
                variants.sort(key=lambda x: x[1], reverse=True)
                total_tracks = sum(v[1] for v in variants)

                duplicates.append({
                    "canonical": variants[0][0],  # Most common spelling
                    "variants": [{"name": v[0], "track_count": v[1]} for v in variants],
                    "total_tracks": total_tracks,
                })

        # Sort by total tracks and limit (total_tracks is always int)
        duplicates.sort(key=lambda x: x["total_tracks"], reverse=True)  # type: ignore[arg-type, return-value]
        duplicates = duplicates[:limit]

        if not duplicates:
            if artist_hint:
                return {
                    "found": 0,
                    "message": f"No duplicates found for artist '{artist_hint}'",
                }
            return {
                "found": 0,
                "message": "No duplicate artists found in the library",
            }

        return {
            "found": len(duplicates),
            "duplicates": duplicates,
            "message": f"Found {len(duplicates)} artist(s) with duplicate spellings. Use merge_duplicate_artists to propose merging them.",
        }

    async def _merge_duplicate_artists(
        self,
        source_artist: str,
        target_artist: str,
        reason: str,
    ) -> dict[str, Any]:
        """Propose merging duplicate artists by changing the artist field."""
        # Find all tracks with the source artist
        stmt = select(Track).where(
            func.lower(Track.artist) == source_artist.lower()
        )
        result = await self.db.execute(stmt)
        tracks = list(result.scalars().all())

        if not tracks:
            return {"error": f"No tracks found with artist '{source_artist}'"}

        track_ids = [str(t.id) for t in tracks]

        # Use the existing propose_metadata_change
        return await self._propose_metadata_change(
            track_ids=track_ids,
            field="artist",
            new_value=target_artist,
            reason=reason,
            source="llm_suggestion",
        )

    # --- Discovery tools ---

    async def _get_similar_artists_in_library(
        self,
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

    # --- Track identification tools ---

    async def _identify_track(
        self,
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
        self,
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

    # --- Deep analysis tools ---

    async def _get_track_analysis(
        self,
        track_ids: list[str],
        include_comparative: bool = True,
    ) -> dict[str, Any]:
        """Get deep musical analysis for one or more tracks.

        Checks cache first, triggers analysis if needed.
        Returns markdown report content for LLM consumption.
        """
        import asyncio

        from app.db.models import TrackDeepAnalysis
        from app.services.background import get_background_manager
        from app.services.deep_analysis import (
            DEEP_ANALYSIS_VERSION,
            generate_comparative_report,
            generate_report,
        )

        if not track_ids:
            return {"error": "No track IDs provided"}

        if len(track_ids) > 10:
            return {"error": "Maximum 10 tracks per analysis request"}

        bg = get_background_manager()
        analyses = []
        track_metas = []
        errors = []

        for tid in track_ids:
            try:
                # Check cache
                cached = (
                    await self.db.execute(
                        select(TrackDeepAnalysis).where(
                            TrackDeepAnalysis.track_id == UUID(tid),
                            TrackDeepAnalysis.version == DEEP_ANALYSIS_VERSION,
                        )
                    )
                ).scalar_one_or_none()

                if not cached:
                    # Trigger analysis and wait for it
                    await bg.run_deep_analysis(tid)
                    # Wait for completion (poll up to 120s)
                    for _ in range(60):
                        await asyncio.sleep(2)
                        cached = (
                            await self.db.execute(
                                select(TrackDeepAnalysis).where(
                                    TrackDeepAnalysis.track_id == UUID(tid),
                                    TrackDeepAnalysis.version == DEEP_ANALYSIS_VERSION,
                                )
                            )
                        ).scalar_one_or_none()
                        if cached:
                            break

                if not cached:
                    errors.append(f"Analysis timed out for track {tid}")
                    continue

                # Load track metadata
                track = (
                    await self.db.execute(select(Track).where(Track.id == UUID(tid)))
                ).scalar_one_or_none()

                if track:
                    analyses.append(cached.results)
                    track_metas.append({
                        "artist": track.artist,
                        "title": track.title,
                        "album": track.album,
                        "duration_seconds": track.duration_seconds,
                    })

            except Exception as e:
                errors.append(f"Error analyzing track {tid}: {str(e)}")

        if not analyses:
            return {
                "error": "No analyses completed",
                "errors": errors,
            }

        # Generate report
        if len(analyses) == 1:
            report = generate_report(analyses[0], track_metas[0])
        elif include_comparative:
            report = generate_comparative_report(analyses, track_metas)
        else:
            # Multiple tracks without comparison: just concatenate
            parts = []
            for a, m in zip(analyses, track_metas):
                parts.append(generate_report(a, m))
            report = "\n\n---\n\n".join(parts)

        result: dict[str, Any] = {
            "report": report,
            "tracks_analyzed": len(analyses),
            "total_requested": len(track_ids),
        }
        if errors:
            result["errors"] = errors

        return result

    # --- Spotify playlist tools ---

    async def _list_spotify_playlists(self, limit: int = 20) -> dict[str, Any]:
        """List user's Spotify playlists."""
        try:
            limit = int(float(limit)) if limit else 20
        except (ValueError, TypeError):
            limit = 20

        if not self.profile_id:
            return {
                "playlists": [],
                "count": 0,
                "error": "No profile ID provided. User needs to be logged in.",
            }

        from app.services.spotify import SpotifyPlaylistService

        try:
            service = SpotifyPlaylistService(self.db)
            playlists = await service.list_playlists(self.profile_id, limit=limit)

            return {
                "playlists": playlists,
                "count": len(playlists),
                "note": "Use get_spotify_playlist_tracks to see tracks in a playlist, or import_spotify_playlist to import one.",
            }
        except ValueError as e:
            return {
                "playlists": [],
                "count": 0,
                "error": str(e),
                "note": "User needs to connect Spotify in Settings first.",
            }
        except Exception as e:
            logger.error(f"Error listing Spotify playlists: {e}")
            return {
                "playlists": [],
                "count": 0,
                "error": "Failed to fetch Spotify playlists",
            }

    async def _get_spotify_playlist_tracks(
        self,
        playlist_id: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Get tracks from a Spotify playlist with local match info."""
        try:
            limit = int(float(limit)) if limit else 50
        except (ValueError, TypeError):
            limit = 50

        if not self.profile_id:
            return {
                "tracks": [],
                "error": "No profile ID provided.",
            }

        from app.services.spotify import SpotifyPlaylistService

        try:
            service = SpotifyPlaylistService(self.db)
            result = await service.get_playlist_tracks(
                self.profile_id,
                playlist_id,
                limit=limit,
            )

            return {
                "playlist_name": result.get("playlist_name"),
                "tracks": result.get("tracks", []),
                "total": result.get("total", 0),
                "in_library": result.get("in_library", 0),
                "missing": result.get("missing", 0),
                "match_rate": result.get("match_rate", "0%"),
                "note": "Use import_spotify_playlist to import this playlist to Familiar.",
            }
        except ValueError as e:
            return {
                "tracks": [],
                "error": str(e),
            }
        except Exception as e:
            logger.error(f"Error getting Spotify playlist tracks: {e}")
            return {
                "tracks": [],
                "error": "Failed to fetch playlist tracks",
            }

    async def _import_spotify_playlist(
        self,
        spotify_playlist_id: str,
        name: str | None = None,
        include_missing: bool = True,
    ) -> dict[str, Any]:
        """Import a Spotify playlist to Familiar."""
        if not self.profile_id:
            return {
                "error": "No profile ID provided.",
                "imported": False,
            }

        from app.services.spotify import SpotifyPlaylistService

        try:
            service = SpotifyPlaylistService(self.db)
            playlist = await service.import_playlist(
                profile_id=self.profile_id,
                spotify_playlist_id=spotify_playlist_id,
                name=name,
                include_missing=include_missing,
            )

            # Get track counts
            from sqlalchemy import func, select

            from app.db.models import PlaylistTrack

            total_count = await self.db.scalar(
                select(func.count(PlaylistTrack.id)).where(
                    PlaylistTrack.playlist_id == playlist.id
                )
            ) or 0

            local_count = await self.db.scalar(
                select(func.count(PlaylistTrack.id)).where(
                    PlaylistTrack.playlist_id == playlist.id,
                    PlaylistTrack.track_id.isnot(None),
                )
            ) or 0

            return {
                "imported": True,
                "playlist_id": str(playlist.id),
                "playlist_name": playlist.name,
                "total_tracks": total_count,
                "local_tracks": local_count,
                "missing_tracks": total_count - local_count,
                "message": f"Successfully imported playlist '{playlist.name}' with {total_count} tracks ({local_count} local, {total_count - local_count} missing).",
            }
        except ValueError as e:
            return {
                "error": str(e),
                "imported": False,
            }
        except Exception as e:
            logger.error(f"Error importing Spotify playlist: {e}")
            return {
                "error": "Failed to import playlist",
                "imported": False,
            }

    # --- Web page reading tools ---

    async def _fetch_webpage(self, url: str) -> dict[str, Any]:
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
        self,
        name: str,
        items: list[dict[str, Any]],
        description: str | None = None,
        tracks_per_album: int = 3,
    ) -> dict[str, Any]:
        """Create a playlist from extracted music items.

        Matches items to local library and creates external tracks for missing items.
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

        matcher = ExternalTrackMatcher(self.db)
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
                # Create external track for missing item
                display_title = track_name or album or f"Tracks by {artist}"

                external_track = await matcher.create_external_track(
                    title=display_title,
                    artist=artist,
                    album=album,
                    source=ExternalTrackSource.LLM_RECOMMENDATION,
                    external_data={
                        "year": year,
                        "source_url": description,
                        "original_item": item,
                    },
                    source_playlist_id=playlist.id,
                    try_match=True,  # Try to match to local library
                )

                # Check if matcher found a match
                if external_track.matched_track_id:
                    # Use the matched local track instead
                    playlist_track = PlaylistTrack(
                        playlist_id=playlist.id,
                        track_id=external_track.matched_track_id,
                        position=position,
                    )
                    local_tracks_added += 1
                    found_items.append({
                        "artist": artist,
                        "album": album,
                        "track": track_name,
                        "matched_count": 1,
                        "matched_via": "fuzzy",
                    })
                else:
                    # Add as external/missing track
                    playlist_track = PlaylistTrack(
                        playlist_id=playlist.id,
                        external_track_id=external_track.id,
                        position=position,
                    )
                    missing_tracks_added += 1
                    missing_items.append({
                        "artist": artist,
                        "album": album,
                        "track": track_name,
                        "year": year,
                    })

                self.db.add(playlist_track)
                position += 1

        await self.db.commit()

        total_tracks = local_tracks_added + missing_tracks_added

        return {
            "created": True,
            "playlist_id": str(playlist.id),
            "playlist_name": name,
            "total_tracks": total_tracks,
            "local_tracks": local_tracks_added,
            "missing_tracks": missing_tracks_added,
            "found_items": found_items,
            "missing_items": missing_items,
            "message": f"Created playlist '{name}' with {total_tracks} tracks ({local_tracks_added} local, {missing_tracks_added} missing).",
        }

    async def _search_for_item(
        self,
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
                func.lower(Track.artist).contains(artist.lower()),
                func.lower(Track.title).contains(track.lower()),
            ).limit(1)
            result = await self.db.execute(stmt)
            tracks = list(result.scalars().all())
            if tracks:
                return tracks

            # Try fuzzy match on title
            stmt = select(Track).where(
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
                func.lower(Track.artist).contains(artist.lower()),
                func.lower(Track.album).contains(album.lower()),
            ).order_by(Track.disc_number, Track.track_number).limit(limit)
            result = await self.db.execute(stmt)
            tracks = list(result.scalars().all())
            if tracks:
                return tracks

            # Try album_artist match
            stmt = select(Track).where(
                func.lower(Track.album_artist).contains(artist.lower()),
                func.lower(Track.album).contains(album.lower()),
            ).order_by(Track.disc_number, Track.track_number).limit(limit)
            result = await self.db.execute(stmt)
            tracks = list(result.scalars().all())
            if tracks:
                return tracks

        # Fall back to any tracks by artist
        stmt = select(Track).where(
            func.lower(Track.artist).contains(artist.lower()),
        ).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
