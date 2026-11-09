"""Playlist tool handlers (select_diverse, create_playlist_from_items, search_for_item, save_as_playlist)."""

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

#: Ceiling for `create_playlist_from_items(tracks_per_album=...)`. Kept in step with the schema
#: description in `llm/tools.py`; a test asserts they agree.
MAX_TRACKS_PER_ALBUM = 100


def _playlist_json(playlist: Playlist, track_count: int) -> dict[str, Any]:
    """A playlist as a tool result: the fields the REST response carries, as JSON values."""
    return {
        "id": str(playlist.id),
        "name": playlist.name,
        "description": playlist.description,
        "is_auto_generated": playlist.is_auto_generated,
        "generation_prompt": playlist.generation_prompt,
        "track_count": track_count,
        "auto_download": playlist.auto_download,
        "created_at": playlist.created_at.isoformat() if playlist.created_at else None,
        "updated_at": playlist.updated_at.isoformat() if playlist.updated_at else None,
    }


def clamp_tracks_per_album(value: Any) -> int:
    """Coerce a host's `tracks_per_album` into 1..MAX_TRACKS_PER_ALBUM, defaulting to 3.

    The ceiling was 10, which silently truncated any album longer than that — a host asking
    for whole albums (`tracks_per_album=100`) got 10 of Mezzanine's 19 with nothing in the
    result saying so. 100 covers any single release short of a box set.
    """
    try:
        n = int(float(value)) if value else 3
    except (ValueError, TypeError):
        return 3
    return max(1, min(n, MAX_TRACKS_PER_ALBUM))


class PlaylistHandlersMixin:
    """Mixin providing playlist-related tool handlers.

    The read, append and favourite handlers are adapters over `app/operations/playlists.py` and
    `favorites.py`, which the REST routes use too (ADR-0173). They used to call the route
    functions themselves, which made a tool depend on HTTP signatures; the operations keep one
    implementation of dedupe, ordering and the ownership check, and what is left here is what a
    tool says: bounded lists, summaries, and errors the model can act on.
    """

    async def _profile(self: "ToolExecutor") -> Any:
        """The `Profile` this session acts as, or None if it no longer exists."""
        from app.db.models import Profile

        return await self.db.get(Profile, self.profile_id)

    async def _list_playlists(
        self: "ToolExecutor",
        include_auto: bool = True,
        limit: int = 50,
    ) -> dict[str, Any]:
        """The listener's playlists, most recently updated first."""
        from app.operations import playlists

        if await self._profile() is None:
            return {"error": "No profile is bound to this session."}

        summaries = await playlists.list_playlists(
            self.db, self.profile_id, include_auto=bool(include_auto)
        )
        # Bounded here because the operation is not. A UI pages; a tool result cannot, and a
        # library with hundreds of auto-generated playlists would bury the answer.
        shown = [_playlist_json(s.playlist, s.track_count) for s in summaries[:limit]]
        result: dict[str, Any] = {"playlists": shown, "count": len(shown)}
        if len(summaries) > limit:
            result["note"] = (
                f"Showing {limit} of {len(summaries)} playlists, most recently updated first."
            )
        return result

    async def _get_playlist(self: "ToolExecutor", playlist_id: str) -> dict[str, Any]:
        """One playlist and the tracks on it, in order."""
        from app.operations import playlists
        from app.operations.errors import PlaylistNotFound

        if await self._profile() is None:
            return {"error": "No profile is bound to this session."}
        ids = self._safe_parse_uuids([playlist_id])
        if not ids:
            return {"error": f"{playlist_id!r} is not a valid playlist id."}

        try:
            detail = await playlists.get_playlist(self.db, self.profile_id, ids[0])
        except PlaylistNotFound:
            # "No such playlist" is actionable; an HTTP error rendered by the executor is not.
            return {"error": f"No playlist {playlist_id} belongs to this listener."}
        return {
            **_playlist_json(detail.playlist, len(detail.entries)),
            "tracks": [
                # The fields the REST `TrackInPlaylist` carries, so a host sees what it always did.
                {
                    "id": str(e.track.id),
                    "playlist_track_id": str(e.item.id),
                    "type": "local",
                    "position": e.item.position,
                    "title": e.track.title,
                    "artist": e.track.artist,
                    "album": e.track.album,
                    "duration_seconds": e.track.duration_seconds,
                    "format": e.track.format,
                    "year": e.track.year,
                    "genre": e.track.genre,
                    "track_number": e.track.track_number,
                    "disc_number": e.track.disc_number,
                    "album_artist": e.track.album_artist,
                    "album_type": e.track.album_type.value if e.track.album_type else None,
                    "analysis_version": e.track.analysis_version,
                    "play_count": e.history.play_count if e.history else None,
                    "last_played_at": (
                        e.history.last_played_at.isoformat()
                        if e.history and e.history.last_played_at
                        else None
                    ),
                }
                for e in detail.entries
            ],
        }

    async def _add_tracks_to_playlist(
        self: "ToolExecutor",
        playlist_id: str,
        track_ids: list[str],
    ) -> dict[str, Any]:
        """Append tracks to a playlist that already exists."""
        from app.operations import playlists
        from app.operations.errors import PlaylistNotFound

        if await self._profile() is None:
            return {"error": "No profile is bound to this session."}
        ids = self._safe_parse_uuids([playlist_id])
        if not ids:
            return {"error": f"{playlist_id!r} is not a valid playlist id."}
        if not track_ids:
            return {"error": "No track ids were given."}

        try:
            result = await playlists.add_tracks(self.db, self.profile_id, ids[0], track_ids)
        except PlaylistNotFound:
            return {"error": f"No playlist {playlist_id} belongs to this listener."}

        track_count = await self.db.scalar(
            select(func.count(PlaylistTrack.id)).where(PlaylistTrack.playlist_id == ids[0])
        )
        added = result.added
        return {
            "playlist_id": str(result.playlist.id),
            "name": result.playlist.name,
            "added": added,
            "track_count": track_count or 0,
            "note": (
                f"Added {added} of {len(track_ids)} requested; the rest were already on the "
                f"playlist or matched no track."
                if added < len(track_ids)
                else f"Added {added} tracks."
            ),
        }

    async def _set_favorite(
        self: "ToolExecutor",
        track_id: str,
        favorite: bool = True,
    ) -> dict[str, Any]:
        """Mark or unmark a track as a favourite.

        **Set semantics, deliberately not a toggle.** A tool call that is retried, which happens
        routinely, would flip a toggle back, so asking twice to favourite something would
        un-favourite it. The operations' `add` and `remove` are idempotent, which is what a
        retryable tool needs.
        """
        from app.operations import favorites
        from app.operations.errors import TrackNotFound

        if await self._profile() is None:
            return {"error": "No profile is bound to this session."}
        ids = self._safe_parse_uuids([track_id])
        if not ids:
            return {"error": f"{track_id!r} is not a valid track id."}

        try:
            if favorite:
                await favorites.add(self.db, self.profile_id, ids[0])
            else:
                await favorites.remove(self.db, self.profile_id, ids[0])
        except TrackNotFound:
            return {"error": f"No track {track_id} is in the library."}
        return {"track_id": track_id, "is_favorite": favorite}

    async def _generate_playlist(
        self: "ToolExecutor",
        track_id: str | None = None,
        album: str | None = None,
        artist: str | None = None,
        track_ids: list[str] | None = None,
        limit: Any = 25,
        max_per_artist: Any = 2,
        include_seed: Any = False,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Seeded playlist generation, ADR-0048 — the same code path the endpoint uses.

        **This deliberately does not re-implement any of the pipeline.** Point 8 puts this on MCP so
        a host can do what the button does; if the tool scored tracks itself the two would drift,
        and the drift would be invisible because both would still return plausible playlists.
        """
        from app.services.playlist_generation import (
            generate_seeded_playlist,
            resolve_seed,
        )

        def safe_int(v: Any, default: int) -> int:
            try:
                return int(float(v)) if v is not None and v != "" else default
            except (ValueError, TypeError):
                return default

        seed_uuid = None
        if track_id:
            parsed = self._safe_parse_uuids([track_id])
            seed_uuid = parsed[0] if parsed else None
            if seed_uuid is None:
                return {"error": f"'{track_id}' is not a valid track id"}

        seed_uuids = self._safe_parse_uuids(track_ids) if track_ids else None

        provided = [seed_uuid is not None, bool(seed_uuids), bool(album), bool(artist and not album)]
        if sum(provided) != 1:
            return {
                "error": "Provide exactly one seed: track_id, album (optionally with artist), "
                         "artist, or track_ids."
            }

        seed = await resolve_seed(
            self.db,
            track_id=seed_uuid,
            artist=artist,
            album=album,
            track_ids=seed_uuids,
        )
        if seed is None:
            return {"error": "No tracks in the library matched that seed", "tracks": [], "count": 0}

        result = await generate_seeded_playlist(
            self.db,
            seed,
            limit=safe_int(limit, 25),
            max_per_artist=safe_int(max_per_artist, 2),
            include_seed=bool(include_seed),
            profile_id=self.profile_id,
        )

        if not result.track_ids:
            return {
                "error": "Nothing in the library was close enough to that seed.",
                "tracks": [],
                "count": 0,
                "pool_size": result.pool_size,
            }

        playlist = Playlist(
            profile_id=self.profile_id,
            name=name or result.name,
            description=None,
            is_auto_generated=True,
            # The seed, not a sentence — there is no sentence. See the endpoint.
            generation_prompt=f"seed:{seed.kind}:{seed.label}",
        )
        self.db.add(playlist)
        await self.db.flush()

        for position, tid in enumerate(result.track_ids):
            self.db.add(PlaylistTrack(playlist_id=playlist.id, track_id=tid, position=position))

        await self.db.commit()

        tracks = (
            await self.db.execute(select(Track).where(Track.id.in_(result.track_ids)))
        ).scalars().all()
        by_id = {t.id: t for t in tracks}

        return {
            "playlist_id": str(playlist.id),
            "name": playlist.name,
            "count": len(result.track_ids),
            "pool_size": result.pool_size,
            "tracks": [
                self._track_to_dict(by_id[tid]) for tid in result.track_ids if tid in by_id
            ],
        }

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

        tracks_per_album = clamp_tracks_per_album(tracks_per_album)

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
