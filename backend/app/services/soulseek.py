"""Soulseek acquisition through a slskd instance Familiar does not own (ADR-0116).

Familiar never speaks the Soulseek protocol. It talks HTTP to **slskd** — a separate client the
operator runs and configures themselves — and only when they have told Familiar where it is. Nothing
in this module is reachable until `soulseek_url` is set; the MCP tools that call it are not even
listed until then (ADR-0116 point 2).

**The API is shaped by how slskd stores a search, which is not obvious from its schema.** A search
reports `responseCount` climbing within a second of being posted, but `GET /searches/{id}/responses`
returns `[]` for the whole time `isComplete` is false — responses are held in memory and written to
slskd's search database only when the search ends, which by default is a ~15 s network timeout
reported as `state: "Completed, TimedOut"`. A caller that reads responses as soon as the count is
positive gets nothing, every time, with no error. `search()` therefore polls the search until it is
complete and only then reads.

**A search result is a file, not an album.** Searching "artist album" returns whichever files in a
sharer's folder matched the words, which for a track-titled query is one file. The folder is the
unit a listener wants, so `search()` groups files by (sharer, parent directory) and `folder()` asks
the sharer for that directory's full listing before anything is enqueued — a search that matched
two tracks must not become a two-track "album".

Soulseek paths are Windows-style with backslashes regardless of the sharer's OS; `_split_path`
handles both separators because a few clients send forward slashes.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

#: Extensions slskd reports as audio. Everything else in a folder (scans, .cue, .log, .nfo) is
#: left where it is; the library scanner would ignore them anyway.
AUDIO_EXTENSIONS = frozenset(
    {"flac", "mp3", "m4a", "aac", "ogg", "opus", "wav", "aiff", "aif", "alac", "wma", "ape"}
)

#: Format preference when ranking folders. Lossless first; within lossy, bitrate breaks the tie.
FORMAT_RANK = {
    "flac": 3,
    "alac": 3,
    "ape": 3,
    "wav": 3,
    "aiff": 3,
    "aif": 3,
    "m4a": 2,
    "ogg": 2,
    "opus": 2,
    "mp3": 1,
    "aac": 1,
    "wma": 0,
}

#: slskd's own network timeout for a search is 15 s. We wait a little past it so that a search
#: which times out normally is read complete, and cap at that so a wedged one cannot hold an MCP
#: call open indefinitely.
SEARCH_WAIT_SECONDS = 25.0
SEARCH_POLL_SECONDS = 1.0


class SoulseekNotConfigured(Exception):
    """No slskd URL is set. The tools are hidden in this state; reaching this means a stale host."""


class SoulseekUnreachable(Exception):
    """slskd is configured but did not answer usefully. The message says which way it failed."""


@dataclass
class SoulseekStatus:
    """What `GET /api/v0/application` says about the slskd this server is pointed at."""

    reachable: bool
    logged_in: bool = False
    username: str | None = None
    version: str | None = None
    shared_files: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reachable": self.reachable,
            "logged_in": self.logged_in,
            "username": self.username,
            "version": self.version,
            "shared_files": self.shared_files,
            "error": self.error,
        }


@dataclass
class SoulseekFile:
    """One shared file, as a search response or a directory listing describes it."""

    filename: str  # full remote path — what enqueue wants
    name: str  # basename
    size: int
    extension: str
    bitrate: int | None = None
    bit_depth: int | None = None
    sample_rate: int | None = None
    length: int | None = None  # seconds

    @property
    def is_audio(self) -> bool:
        return self.extension in AUDIO_EXTENSIONS

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "name": self.name,
            "size": self.size,
            "extension": self.extension,
            "bitrate": self.bitrate,
            "bit_depth": self.bit_depth,
            "sample_rate": self.sample_rate,
            "length": self.length,
        }


@dataclass
class SoulseekFolder:
    """One sharer's folder that matched a search — the unit a listener actually wants."""

    username: str
    directory: str
    files: list[SoulseekFile] = field(default_factory=list)
    has_free_upload_slot: bool = False
    upload_speed: int = 0  # bytes/s, as the sharer reports it
    queue_length: int = 0

    @property
    def audio_files(self) -> list[SoulseekFile]:
        return [f for f in self.files if f.is_audio]

    @property
    def formats(self) -> list[str]:
        return sorted({f.extension for f in self.audio_files})

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.audio_files)

    def rank_key(self) -> tuple[int, int, int, int]:
        """Higher is better. Lossless, then a free slot, then more matched files, then speed.

        A folder with a free slot starts now; one without waits behind the sharer's queue, which
        the listener cannot see the length of in wall-clock terms. That beats raw speed, because a
        fast sharer with a queue of 40 is slower than a modest one with a slot.
        """
        best_format = max((FORMAT_RANK.get(f.extension, 0) for f in self.audio_files), default=0)
        return (
            best_format,
            int(self.has_free_upload_slot),
            len(self.audio_files),
            self.upload_speed,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "directory": self.directory,
            "matched_files": len(self.audio_files),
            "formats": self.formats,
            "total_size_mb": round(self.total_size / 1_000_000, 1),
            "has_free_upload_slot": self.has_free_upload_slot,
            "upload_speed_mbps": round(self.upload_speed * 8 / 1_000_000, 1),
            "queue_length": self.queue_length,
            "files": [f.name for f in self.audio_files],
        }


def _split_path(path: str) -> tuple[str, str]:
    """(directory, basename) of a Soulseek path, whichever separator the sharer used."""
    normalized = path.replace("/", "\\")
    if "\\" not in normalized:
        return "", normalized
    directory, _, name = normalized.rpartition("\\")
    return directory, name


def _extension(name: str, reported: str | None) -> str:
    """slskd's `extension` field is empty for most files; the filename is the reliable source."""
    if reported:
        return reported.lower().lstrip(".")
    _, _, ext = name.rpartition(".")
    return ext.lower() if ext and ext != name else ""


def _file_from_search(raw: dict[str, Any]) -> SoulseekFile:
    directory, name = _split_path(raw.get("filename", ""))
    return SoulseekFile(
        filename=raw.get("filename", ""),
        name=name,
        size=int(raw.get("size") or 0),
        extension=_extension(name, raw.get("extension")),
        bitrate=raw.get("bitRate"),
        bit_depth=raw.get("bitDepth"),
        sample_rate=raw.get("sampleRate"),
        length=raw.get("length"),
    )


def _file_from_listing(directory: str, raw: dict[str, Any]) -> SoulseekFile:
    """A directory listing gives basenames; the full path is ours to rebuild for enqueue."""
    name = raw.get("filename", "")
    return SoulseekFile(
        filename=f"{directory}\\{name}",
        name=name,
        size=int(raw.get("size") or 0),
        extension=_extension(name, raw.get("extension")),
        bitrate=raw.get("bitRate"),
        bit_depth=raw.get("bitDepth"),
        sample_rate=raw.get("sampleRate"),
        length=raw.get("length"),
    )


def group_responses(responses: list[dict[str, Any]]) -> list[SoulseekFolder]:
    """Fold slskd's per-user responses into per-folder candidates, best first."""
    folders: dict[tuple[str, str], SoulseekFolder] = {}
    for response in responses:
        username = response.get("username", "")
        for raw in response.get("files", []):
            f = _file_from_search(raw)
            if not f.is_audio:
                continue
            directory, _ = _split_path(f.filename)
            key = (username, directory)
            folder = folders.get(key)
            if folder is None:
                folder = SoulseekFolder(
                    username=username,
                    directory=directory,
                    has_free_upload_slot=bool(response.get("hasFreeUploadSlot")),
                    upload_speed=int(response.get("uploadSpeed") or 0),
                    queue_length=int(response.get("queueLength") or 0),
                )
                folders[key] = folder
            folder.files.append(f)
    return sorted(folders.values(), key=SoulseekFolder.rank_key, reverse=True)


class SoulseekService:
    """An HTTP client for one slskd instance. Construct per call; `close()` in a `finally`."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        *,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        headers = {"X-API-Key": api_key} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=f"{self.base_url}/api/v0",
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ── transport ──────────────────────────────────────────────────────────────────────────

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """One call, with every way slskd can fail turned into a sentence.

        The distinctions matter to an operator: "nothing is listening" (wrong URL, container
        down), "the key is wrong" (401), and "that is not slskd" (a 200 that is some other
        service's HTML) each have a different fix, and a bare exception name says none of them.
        """
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.ConnectError as e:
            raise SoulseekUnreachable(
                f"Nothing answered at {self.base_url} — is slskd running, and is that URL "
                f"reachable from the Familiar server? ({e})"
            ) from e
        except httpx.TimeoutException as e:
            raise SoulseekUnreachable(
                f"slskd at {self.base_url} did not answer in time ({e})"
            ) from e
        if response.status_code == 401:
            raise SoulseekUnreachable("slskd rejected the API key (401). Check soulseek_api_key.")
        if response.status_code == 404 and path == "/application":
            raise SoulseekUnreachable(
                f"{self.base_url} answered, but not as slskd (no /api/v0/application)."
            )
        if response.status_code >= 400:
            detail = response.text[:200]
            raise SoulseekUnreachable(
                f"slskd returned {response.status_code} for {method} {path}: {detail}"
            )
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as e:
            raise SoulseekUnreachable(
                f"{self.base_url} answered {method} {path} with something that is not JSON — "
                "probably not slskd."
            ) from e

    # ── operations ─────────────────────────────────────────────────────────────────────────

    async def status(self) -> SoulseekStatus:
        """Is there a slskd there, and is it logged in to the network?

        Never raises: the settings panel's "test connection" and the MCP host both want the
        answer as data, not as an exception to catch.
        """
        try:
            app = await self._request("GET", "/application")
        except SoulseekUnreachable as e:
            return SoulseekStatus(reachable=False, error=str(e))
        server = app.get("server") or {}
        user = app.get("user") or {}
        state = str(server.get("state") or "")
        logged_in = bool(server.get("isLoggedIn")) or "LoggedIn" in state
        version = app.get("version") or {}
        shares = app.get("shares") or {}
        return SoulseekStatus(
            reachable=True,
            logged_in=logged_in,
            username=user.get("username") or None,
            version=version.get("current") if isinstance(version, dict) else str(version),
            shared_files=shares.get("files"),
            error=None
            if logged_in
            else f"slskd is up but not logged in (state: {state or 'unknown'})",
        )

    async def search(
        self, query: str, *, wait_seconds: float = SEARCH_WAIT_SECONDS, limit: int = 10
    ) -> list[SoulseekFolder]:
        """Post a search, wait for it to finish, group the responses, delete the search.

        Deleted because slskd keeps every search in its database until told otherwise, and an MCP
        host that searches on a listener's behalf would otherwise fill it with one-off queries
        the listener never sees.
        """
        created = await self._request("POST", "/searches", json={"searchText": query})
        search_id = created["id"]
        try:
            deadline = asyncio.get_running_loop().time() + wait_seconds
            while True:
                current = await self._request("GET", f"/searches/{search_id}")
                if current.get("isComplete"):
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    # Ask slskd to stop; responses are only persisted once it does.
                    await self._request("PUT", f"/searches/{search_id}")
                    await asyncio.sleep(SEARCH_POLL_SECONDS)
                    break
                await asyncio.sleep(SEARCH_POLL_SECONDS)
            responses = await self._request("GET", f"/searches/{search_id}/responses") or []
        finally:
            try:
                await self._request("DELETE", f"/searches/{search_id}")
            except SoulseekUnreachable:
                logger.debug("Could not delete slskd search %s", search_id)
        return group_responses(responses)[:limit]

    async def folder(self, username: str, directory: str) -> SoulseekFolder:
        """The full listing of one sharer's directory — every file, not only the ones that matched."""
        listing = await self._request(
            "POST", f"/users/{username}/directory", json={"directory": directory}
        )
        entries = listing if isinstance(listing, list) else [listing]
        files: list[SoulseekFile] = []
        for entry in entries:
            name = entry.get("name") or directory
            for raw in entry.get("files", []):
                files.append(_file_from_listing(name, raw))
        return SoulseekFolder(username=username, directory=directory, files=files)

    async def enqueue(self, username: str, files: list[SoulseekFile]) -> int:
        """Queue downloads with the sharer. Returns how many were accepted."""
        if not files:
            return 0
        body = [{"filename": f.filename, "size": f.size} for f in files]
        await self._request("POST", f"/transfers/downloads/{username}", json=body)
        return len(files)

    async def download_root(self) -> str | None:
        """Where slskd puts completed files, *as slskd sees it* (e.g. `/downloads/complete`).

        This is a path inside slskd's own container or host, not Familiar's — the operator is
        the only party who knows how the two map. It is reported so the handoff can say
        "the folder is at <root>/<name>" in terms the operator recognises.
        """
        try:
            options = await self._request("GET", "/options")
        except SoulseekUnreachable:
            return None
        directories = (options or {}).get("directories") or {}
        return directories.get("downloads") or None

    async def downloads(self) -> list[dict[str, Any]]:
        """Every download slskd knows about, folded to one line per folder."""
        raw = await self._request("GET", "/transfers/downloads") or []
        summary: list[dict[str, Any]] = []
        for user in raw:
            for d in user.get("directories", []):
                files = d.get("files", [])
                states = [str(f.get("state", "")) for f in files]
                done = sum(1 for s in states if s.startswith("Completed, Succeeded"))
                failed = sum(
                    1 for s in states if s.startswith("Completed") and "Succeeded" not in s
                )
                active = sum(1 for s in states if s.startswith("InProgress"))
                queued = len(files) - done - failed - active
                total = sum(int(f.get("size") or 0) for f in files)
                transferred = sum(int(f.get("bytesTransferred") or 0) for f in files)
                summary.append(
                    {
                        "username": user.get("username"),
                        "directory": d.get("directory"),
                        "files": len(files),
                        "completed": done,
                        "failed": failed,
                        "in_progress": active,
                        "queued": max(queued, 0),
                        "percent": round(100 * transferred / total) if total else 0,
                        # ADR-0117 point 3: nothing left to wait for, and something arrived.
                        # slskd moves each file to `complete` as it finishes, so "any file done"
                        # is too early — a sync then would import one track of eleven.
                        "settled": active == 0 and queued <= 0 and done >= 1,
                    }
                )
        return summary


# ── the boundary the application holds (ADR-0130 point 5) ─────────────────────────────────────


class SoulseekConfiguration(Protocol):
    """Where slskd is, as the operator configured it — read at call time, never cached.

    The URL can be set or cleared in the settings panel while the server runs, and the tools that
    depend on it must appear and disappear accordingly (ADR-0116 point 2), so this is a question
    asked on every use rather than a value captured at startup. The application's settings
    service answers it in production; a test answers it with two strings.
    """

    def soulseek_url(self) -> str | None: ...

    def soulseek_api_key(self) -> str | None: ...


NOT_CONFIGURED_MESSAGE = (
    "No Soulseek client is configured. Set the slskd URL and API key under "
    "Server → Integrations → Soulseek."
)


class SoulseekGateway:
    """The application's one handle on slskd: whether it is configured, and a client when it is.

    Held by the application container (ADR-0130 point 2) and handed to the route, the MCP
    executor and the background poll by injection, in place of the `SoulseekService.from_settings`
    classmethod every one of them used to reach for — which is what made "is slskd configured"
    something tests could only answer by monkeypatching the settings singleton.

    `transport` is for tests: an `httpx.MockTransport` stands in for slskd without a socket.
    """

    def __init__(
        self,
        configuration: SoulseekConfiguration,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._configuration = configuration
        self._transport = transport

    @property
    def url(self) -> str | None:
        return self._configuration.soulseek_url() or None

    @property
    def configured(self) -> bool:
        """A URL is enough; slskd can run without an API key (ADR-0116)."""
        return self.url is not None

    @asynccontextmanager
    async def client(self, *, timeout: float = 10.0) -> AsyncIterator[SoulseekService]:
        """A client for the configured slskd, closed on exit; `SoulseekNotConfigured` if none."""
        url = self.url
        if url is None:
            raise SoulseekNotConfigured(NOT_CONFIGURED_MESSAGE)
        service = SoulseekService(
            url,
            self._configuration.soulseek_api_key(),
            timeout=timeout,
            transport=self._transport,
        )
        try:
            yield service
        finally:
            await service.close()

    async def aclose(self) -> None:
        """Nothing is held between calls; here so the container can close every gateway alike."""

