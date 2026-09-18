"""Soulseek acquisition handlers (ADR-0116).

Four tools over `app.services.soulseek`. They are dispatched by `ToolExecutor` like every other
tool, but `app.mcp.server.exposed_tools` withholds them until a slskd URL is configured, so a
`SoulseekNotConfigured` here means a host is holding a stale tool list — answered with the same
sentence the settings panel shows, rather than a stack trace.

`find_missing_on_soulseek` is the one that earns the set its place: it is the difference between
"I recommend Lamb, which you don't have" and "I recommend Lamb, which you don't have — here are
three lossless copies." It checks the library first so a model cannot search the network for an
album that is already on disk.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.db.models import Track
from app.services.soulseek import (
    SoulseekNotConfigured,
    SoulseekUnreachable,
)

if TYPE_CHECKING:
    from ..executor import ToolExecutor

logger = logging.getLogger(__name__)


#: Where an inbox mount lands if the operator configured one (ADR-0117 point 2).
INBOX_PATH = "Inbox"


def _handoff(download_root: str | None, directory: str | None) -> dict[str, Any]:
    """What whoever has hands needs, to get a finished folder into the library (ADR-0117 point 7).

    Familiar never moves files. Two arrangements make a download appear, and the handoff says
    which applies here:

    - An **inbox** is mounted inside the library: the folder is already visible to the scanner,
      the poll triggers a sync when it settles, and the tracks show up in Pending Review. Nothing
      to move.
    - **No inbox**: the folder sits in slskd's completed directory until someone moves it — the
      listener, or an MCP host with its own shell — into the library. Then `start_library_sync`.

    `slskd_path` is the folder as slskd sees it (its container or host), because that is the
    only path Familiar can know; the operator maps it to their own filesystem.
    """
    from app.config import MUSIC_LIBRARY_PATH

    inbox = MUSIC_LIBRARY_PATH / INBOX_PATH
    inbox_mounted = inbox.is_dir()
    folder_name = (directory or "").replace("/", "\\").rpartition("\\")[2] or directory
    slskd_path = (
        f"{download_root.rstrip('/')}/{folder_name}" if download_root and folder_name else None
    )
    if inbox_mounted:
        how = (
            f"An inbox is mounted at {inbox}, so nothing needs moving: once the folder settles, a "
            "library sync runs within a couple of minutes and the tracks appear in Pending Review "
            "for the listener to accept or skip."
        )
    else:
        how = (
            "No inbox is mounted, and Familiar never moves files. When the folder has settled, "
            f"move it from slskd's completed directory{' (' + slskd_path + ' as slskd sees it)' if slskd_path else ''} "
            f"into the music library — {MUSIC_LIBRARY_PATH}/<Artist>/<Album>/ is the convention — "
            "either by asking the listener to, or with your own shell access if you have it. Then "
            "call start_library_sync so Familiar reads the new files; they arrive in Pending Review."
        )
    return {
        "folder": folder_name,
        "slskd_path": slskd_path,
        "inbox_mounted": inbox_mounted,
        "library_path": str(MUSIC_LIBRARY_PATH),
        "how_to_file": how,
    }


class SoulseekHandlersMixin:
    """Search, download, transfers, and the library-checked find."""

    async def _search_soulseek(self: ToolExecutor, query: str, limit: int = 8) -> dict[str, Any]:
        try:
            limit = max(1, min(int(float(limit)), 25)) if limit else 8
        except (ValueError, TypeError):
            limit = 8
        try:
            async with self.services.soulseek.client() as slsk:
                folders = await slsk.search(query, limit=limit)
        except SoulseekNotConfigured as e:
            return {"error": str(e)}
        except SoulseekUnreachable as e:
            return {"error": str(e), "query": query}
        return {
            "query": query,
            "folders": [f.to_dict() for f in folders],
            "count": len(folders),
            "note": (
                "Folders are ranked best-first: lossless, then a free upload slot, then how many "
                "files matched. `files` lists only the files that matched the query — "
                "download_from_soulseek fetches the whole folder."
                if folders
                else "No sharer answered with audio matching that query. Try fewer words, or "
                "check get_soulseek_transfers to confirm slskd is logged in."
            ),
        }

    async def _download_from_soulseek(
        self: ToolExecutor, username: str, directory: str
    ) -> dict[str, Any]:
        try:
            async with self.services.soulseek.client() as slsk:
                folder = await slsk.folder(username, directory)
                files = folder.audio_files
                if not files:
                    return {
                        "error": f"{username} shares no audio files in that folder (or it is no longer shared).",
                        "username": username,
                        "directory": directory,
                    }
                queued = await slsk.enqueue(username, files)
                download_root = await slsk.download_root()
        except SoulseekNotConfigured as e:
            return {"error": str(e)}
        except SoulseekUnreachable as e:
            return {"error": str(e), "username": username, "directory": directory}
        handoff = _handoff(download_root, directory)
        return {
            "username": username,
            "directory": directory,
            "queued": queued,
            "formats": folder.formats,
            "total_size_mb": round(folder.total_size / 1_000_000, 1),
            "files": [f.name for f in files],
            "handoff": handoff,
            "note": (
                "Queued with the sharer. Transfers start when they have a free slot; watch "
                "get_soulseek_transfers. " + handoff["how_to_file"]
            ),
        }

    async def _get_soulseek_transfers(self: ToolExecutor) -> dict[str, Any]:
        try:
            async with self.services.soulseek.client() as slsk:
                status = await slsk.status()
                if not status.reachable:
                    return {"status": status.to_dict(), "transfers": [], "count": 0}
                transfers = await slsk.downloads()
                download_root = await slsk.download_root()
        except SoulseekNotConfigured as e:
            return {"error": str(e)}
        except SoulseekUnreachable as e:
            return {"error": str(e)}
        # ADR-0117 point 6: "is it in yet?" is answerable. A settled folder whose sync has been
        # triggered is in Pending Review (or will be within the sync); one not yet triggered is
        # waiting for the next two-minute poll.
        from app.services.background import get_background_manager

        bg = get_background_manager()
        for folder in transfers:
            folder["sync_triggered"] = bool(folder.get("settled")) and bg.soulseek_sync_triggered(
                folder.get("username") or "", folder.get("directory") or ""
            )
            folder["slskd_path"] = _handoff(download_root, folder.get("directory"))["slskd_path"]
        handoff = _handoff(download_root, None)
        return {
            "status": status.to_dict(),
            "transfers": transfers,
            "count": len(transfers),
            "inbox_mounted": handoff["inbox_mounted"],
            "library_path": handoff["library_path"],
            "note": (
                "A folder is `settled` when nothing in it is still moving and at least one file "
                "arrived. " + handoff["how_to_file"]
            ),
        }

    async def _start_library_sync(self: ToolExecutor) -> dict[str, Any]:
        """Ask Familiar to look for new files now rather than at the next two-hourly cron.

        DB-only: the sync reads the library and writes rows. It is the step after someone has
        moved a finished download into the library by hand (ADR-0117 point 7). Runs in the
        background; the result says whether it started or was already running.
        """
        from app.services.background import get_background_manager

        bg = get_background_manager()
        if bg.is_sync_running():
            return {
                "status": "already_running",
                "note": "A library sync is already in progress; new files will be picked up by it "
                "or by the next one.",
            }
        result = await bg.run_sync()
        return {
            "status": result.get("status", "started"),
            "note": (
                "Library sync started in the background. New files enter Pending Review, where "
                "the listener accepts or skips them; analysis of new tracks follows."
            ),
        }

    async def _find_missing_on_soulseek(
        self: ToolExecutor, artist: str, album: str | None = None
    ) -> dict[str, Any]:
        """Library first, network second — never the other way round."""
        artist = (artist or "").strip()
        album = (album or "").strip() or None
        if not artist:
            return {"error": "artist is required"}

        owned = await self._library_holdings(artist, album)
        if owned["in_library"]:
            return {
                "artist": artist,
                "album": album,
                "in_library": True,
                "library_tracks": owned["tracks"],
                "library_albums": owned["albums"],
                "note": (
                    "Already in the library — nothing was searched. Use search_library or "
                    "get_album_tracks to play it."
                ),
            }

        query = f"{artist} {album}" if album else artist
        result = await self._search_soulseek(query, limit=5)
        result.update(
            {
                "artist": artist,
                "album": album,
                "in_library": False,
                "library_albums": owned["albums"],
            }
        )
        if owned["albums"] and album:
            result["note"] = (
                f"The library has other {artist} albums ({', '.join(owned['albums'][:5])}) but not "
                f"'{album}'. " + str(result.get("note", ""))
            )
        return result

    async def _library_holdings(
        self: ToolExecutor, artist: str, album: str | None
    ) -> dict[str, Any]:
        """What the library holds for this artist (and album), by case-insensitive tag match.

        Matches either the track artist or the album artist, so a compilation credited to the
        artist counts and a guest credit on someone else's album does not hide it.
        """
        artist_match = (func.lower(func.trim(Track.artist)) == artist.lower()) | (
            func.lower(func.trim(Track.album_artist)) == artist.lower()
        )
        albums_stmt = (
            select(Track.album, func.count(Track.id))
            .where(Track.active_filter(), artist_match, Track.album.isnot(None))
            .group_by(Track.album)
            .order_by(func.count(Track.id).desc())
        )
        rows = (await self.db.execute(albums_stmt)).all()
        albums = [name for name, _ in rows if name]
        total = sum(count for _, count in rows)

        if album is None:
            return {"in_library": total > 0, "tracks": total, "albums": albums}

        album_stmt = select(func.count(Track.id)).where(
            Track.active_filter(),
            artist_match,
            func.lower(func.trim(Track.album)) == album.lower(),
        )
        album_tracks = await self.db.scalar(album_stmt) or 0
        return {"in_library": album_tracks > 0, "tracks": album_tracks, "albums": albums}
