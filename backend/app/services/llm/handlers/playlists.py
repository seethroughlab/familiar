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
    """Mixin providing playlist-related tool handlers.

    The read and append handlers below **call the route functions directly** rather than repeating
    their queries. That is already how this codebase composes them — `crud.py` and `tracks.py` call
    each other the same way — and it keeps one implementation of dedupe, ordering and the ownership
    check. The only adaptation needed is loading the `Profile`: routes take the ORM object, and a
    tool handler holds only `self.profile_id`.
    """

    async def _profile(self: "ToolExecutor") -> Any:
        """The `Profile` row the route functions expect."""
        from app.db.models import Profile

        return await self.db.get(Profile, self.profile_id)

    async def _list_playlists(
        self: "ToolExecutor",
        include_auto: bool = True,
        limit: int = 50,
    ) -> dict[str, Any]:
        """The listener's playlists, most recently updated first."""
        from app.api.routes.playlists.crud import list_playlists

        profile = await self._profile()
        if profile is None:
            return {"error": "No profile is bound to this session."}

        # `include_auto` is passed explicitly: the route defaults it with `Query(...)`, which
        # arrives as a FastAPI object rather than a bool when the function is called directly.
        playlists = await list_playlists(self.db, profile, include_auto=include_auto)

        # Bounded here because the route is not. It paginates in a UI; a tool result cannot, and a
        # library with hundreds of auto-generated playlists would bury the answer.
        shown = [p.model_dump(mode="json") for p in playlists[:limit]]
        result: dict[str, Any] = {"playlists": shown, "count": len(shown)}
        if len(playlists) > limit:
            result["note"] = (
                f"Showing {limit} of {len(playlists)} playlists, most recently updated first."
            )
        return result

    async def _get_playlist(self: "ToolExecutor", playlist_id: str) -> dict[str, Any]:
        """One playlist and the tracks on it, in order."""
        from app.api.exceptions import PlaylistNotFoundError
        from app.api.routes.playlists.crud import get_playlist

        profile = await self._profile()
        if profile is None:
            return {"error": "No profile is bound to this session."}
        ids = self._safe_parse_uuids([playlist_id])
        if not ids:
            return {"error": f"{playlist_id!r} is not a valid playlist id."}

        try:
            detail = await get_playlist(ids[0], self.db, profile)
        except PlaylistNotFoundError:
            # Caught rather than raised: the executor's catch-all would render an HTTP exception,
            # which tells the model nothing it can act on. "No such playlist" is actionable.
            return {"error": f"No playlist {playlist_id} belongs to this listener."}
        return detail.model_dump(mode="json")

    async def _add_tracks_to_playlist(
        self: "ToolExecutor",
        playlist_id: str,
        track_ids: list[str],
    ) -> dict[str, Any]:
        """Append tracks to a playlist that already exists."""
        from app.api.exceptions import PlaylistNotFoundError
        from app.api.routes.playlists.tracks import add_tracks_to_playlist

        profile = await self._profile()
        if profile is None:
            return {"error": "No profile is bound to this session."}
        ids = self._safe_parse_uuids([playlist_id])
        if not ids:
            return {"error": f"{playlist_id!r} is not a valid playlist id."}
        if not track_ids:
            return {"error": "No track ids were given."}

        before = len(await self._playlist_track_ids(ids[0]))
        try:
            detail = await add_tracks_to_playlist(
                ids[0], self.db, profile, track_ids=track_ids
            )
        except PlaylistNotFoundError:
            return {"error": f"No playlist {playlist_id} belongs to this listener."}

        # Summarised rather than returned whole: the route re-reads the entire playlist, which for
        # a long one is far more than the model asked for or needs.
        added = len(detail.tracks) - before
        return {
            "playlist_id": str(detail.id),
            "name": detail.name,
            "added": added,
            "track_count": len(detail.tracks),
            "note": (
                f"Added {added} of {len(track_ids)} requested; the rest were already on the "
                f"playlist or matched no track."
                if added < len(track_ids)
                else f"Added {added} tracks."
            ),
        }

    async def _playlist_track_ids(self: "ToolExecutor", playlist_id: UUID) -> list[UUID]:
        """Current members, for reporting how many an append actually added."""
        rows = await self.db.execute(
            select(PlaylistTrack.track_id).where(PlaylistTrack.playlist_id == playlist_id)
        )
        return list(rows.scalars().all())

    async def _set_favorite(
        self: "ToolExecutor",
        track_id: str,
        favorite: bool = True,
    ) -> dict[str, Any]:
        """Mark or unmark a track as a favourite.

        **Set semantics, deliberately not a toggle.** `_toggle_local_favorite` is the obvious thing
        to reuse — it is the only function in that module taking a raw `profile_id` — and it is the
        wrong primitive here: a tool call that is retried, which happens routinely, would flip the
        state back, so asking twice to favourite something would un-favourite it. `add_favorite` and
        `remove_favorite` are already idempotent, which is what a retryable tool needs.
        """
        from app.api.exceptions import TrackNotFoundError
        from app.api.routes.favorites import add_favorite, remove_favorite

        profile = await self._profile()
        if profile is None:
            return {"error": "No profile is bound to this session."}
        ids = self._safe_parse_uuids([track_id])
        if not ids:
            return {"error": f"{track_id!r} is not a valid track id."}

        try:
            if favorite:
                await add_favorite(ids[0], self.db, profile)
            else:
                await remove_favorite(ids[0], self.db, profile)
        except TrackNotFoundError:
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
