"""Torrent search service for Jackett/Prowlarr integration."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from app.services.app_settings import get_app_settings_service

logger = logging.getLogger(__name__)


@dataclass
class TorrentResult:
    """A single torrent search result."""

    title: str
    indexer: str
    size_bytes: int
    seeders: int
    leechers: int
    magnet_url: str | None
    torrent_url: str | None
    info_url: str | None
    category: str  # "lossless", "mp3", "audio"
    publish_date: str | None

    @property
    def size_display(self) -> str:
        """Human-readable size string."""
        if self.size_bytes <= 0:
            return "? MB"
        gb = self.size_bytes / (1024**3)
        if gb >= 1.0:
            return f"{gb:.1f} GB"
        mb = self.size_bytes / (1024**2)
        return f"{mb:.0f} MB"


@dataclass
class TorrentSearchResponse:
    """Response from a torrent search."""

    results: list[TorrentResult] = field(default_factory=list)
    total: int = 0
    query: str = ""
    error: str | None = None


def _categorize_jackett(categories: list[dict[str, Any]]) -> str:
    """Map Jackett category IDs to simple labels."""
    cat_ids = {c.get("ID", 0) for c in categories}
    # 3040 = Audio/Lossless
    if 3040 in cat_ids:
        return "lossless"
    # 3010 = Audio/MP3
    if 3010 in cat_ids:
        return "mp3"
    return "audio"


def _categorize_prowlarr(categories: list[dict[str, Any]]) -> str:
    """Map Prowlarr categories to simple labels."""
    for cat in categories:
        name = (cat.get("name") or "").lower()
        cat_id = cat.get("id", 0)
        if cat_id == 3040 or "lossless" in name or "flac" in name:
            return "lossless"
        if cat_id == 3010 or "mp3" in name:
            return "mp3"
    return "audio"


class TorrentSearchService:
    """Service for searching torrents via Jackett or Prowlarr."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        provider: str = "jackett",
        prefer_lossless: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.provider = provider
        self.prefer_lossless = prefer_lossless
        self.client = httpx.AsyncClient(timeout=30.0)

    async def search(
        self,
        artist: str,
        title: str | None = None,
        album: str | None = None,
        limit: int = 20,
    ) -> TorrentSearchResponse:
        """Search for torrents matching the given track info."""
        # Build search query
        parts = [artist]
        if album:
            parts.append(album)
        elif title:
            parts.append(title)
        query = " ".join(parts)

        try:
            if self.provider == "prowlarr":
                return await self._search_prowlarr(query, limit)
            else:
                return await self._search_jackett(query, limit)
        except httpx.TimeoutException:
            return TorrentSearchResponse(
                query=query, error="Search timed out (30s)"
            )
        except httpx.ConnectError:
            return TorrentSearchResponse(
                query=query,
                error=f"Cannot connect to {self.provider} at {self.base_url}",
            )
        except Exception as e:
            logger.warning(f"Torrent search error: {e}")
            return TorrentSearchResponse(query=query, error=str(e))

    async def _search_jackett(
        self, query: str, limit: int
    ) -> TorrentSearchResponse:
        """Search via Jackett API."""
        params: dict[str, Any] = {
            "apikey": self.api_key,
            "Query": query,
            "Category[]": [3000],  # Audio
        }

        resp = await self.client.get(
            f"{self.base_url}/api/v2.0/indexers/all/results",
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()

        results: list[TorrentResult] = []
        for item in data.get("Results", []):
            category = _categorize_jackett(item.get("Category", []))

            # Skip non-lossless when prefer_lossless is on and we have enough results
            if self.prefer_lossless and category == "mp3" and len(results) >= limit // 2:
                continue

            results.append(
                TorrentResult(
                    title=item.get("Title", ""),
                    indexer=item.get("Tracker", ""),
                    size_bytes=item.get("Size", 0),
                    seeders=item.get("Seeders", 0),
                    leechers=item.get("Peers", 0),
                    magnet_url=item.get("MagnetUri"),
                    torrent_url=item.get("Link"),
                    info_url=item.get("Details") or item.get("Comments"),
                    category=category,
                    publish_date=item.get("PublishDate"),
                )
            )

        # Sort: lossless first (if preferred), then by seeders descending
        results.sort(
            key=lambda r: (
                0 if self.prefer_lossless and r.category == "lossless" else 1,
                -r.seeders,
            )
        )

        return TorrentSearchResponse(
            results=results[:limit],
            total=len(data.get("Results", [])),
            query=query,
        )

    async def _search_prowlarr(
        self, query: str, limit: int
    ) -> TorrentSearchResponse:
        """Search via Prowlarr API."""
        params: dict[str, Any] = {
            "query": query,
            "categories": [3000],  # Audio
            "type": "search",
        }
        headers = {"X-Api-Key": self.api_key}

        resp = await self.client.get(
            f"{self.base_url}/api/v1/search",
            params=params,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()

        results: list[TorrentResult] = []
        for item in data:
            category = _categorize_prowlarr(item.get("categories", []))

            if self.prefer_lossless and category == "mp3" and len(results) >= limit // 2:
                continue

            # Prowlarr magnet/torrent URLs
            magnet_url = None
            torrent_url = None
            download_url = item.get("downloadUrl", "")
            if download_url and download_url.startswith("magnet:"):
                magnet_url = download_url
            elif download_url:
                torrent_url = download_url

            results.append(
                TorrentResult(
                    title=item.get("title", ""),
                    indexer=item.get("indexer", ""),
                    size_bytes=item.get("size", 0),
                    seeders=item.get("seeders", 0),
                    leechers=item.get("leechers", 0),
                    magnet_url=magnet_url,
                    torrent_url=torrent_url,
                    info_url=item.get("infoUrl") or item.get("guid"),
                    category=category,
                    publish_date=item.get("publishDate"),
                )
            )

        results.sort(
            key=lambda r: (
                0 if self.prefer_lossless and r.category == "lossless" else 1,
                -r.seeders,
            )
        )

        return TorrentSearchResponse(
            results=results[:limit],
            total=len(data),
            query=query,
        )

    async def test_connection(self) -> dict[str, Any]:
        """Test connectivity to the configured search provider."""
        try:
            if self.provider == "prowlarr":
                resp = await self.client.get(
                    f"{self.base_url}/api/v1/health",
                    headers={"X-Api-Key": self.api_key},
                )
            else:
                # Jackett: test with a simple search
                resp = await self.client.get(
                    f"{self.base_url}/api/v2.0/indexers/all/results",
                    params={"apikey": self.api_key, "Query": "test", "Category[]": [3000]},
                )

            if resp.status_code == 401:
                return {"ok": False, "provider": self.provider, "error": "Invalid API key"}
            resp.raise_for_status()
            return {"ok": True, "provider": self.provider, "error": None}

        except httpx.ConnectError:
            return {
                "ok": False,
                "provider": self.provider,
                "error": f"Cannot connect to {self.base_url}",
            }
        except httpx.TimeoutException:
            return {
                "ok": False,
                "provider": self.provider,
                "error": "Connection timed out",
            }
        except Exception as e:
            return {"ok": False, "provider": self.provider, "error": str(e)}


class TransmissionClient:
    """Client for Transmission RPC API."""

    def __init__(
        self,
        base_url: str,
        username: str | None = None,
        password: str | None = None,
    ):
        self.rpc_url = f"{base_url.rstrip('/')}/transmission/rpc"
        auth = (username, password) if username else None
        self.client = httpx.AsyncClient(timeout=15.0, auth=auth)
        self._session_id: str | None = None

    async def _rpc(self, method: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make an RPC call, handling the CSRF session-id handshake."""
        body = {"method": method}
        if arguments:
            body["arguments"] = arguments

        headers = {}
        if self._session_id:
            headers["X-Transmission-Session-Id"] = self._session_id

        resp = await self.client.post(self.rpc_url, json=body, headers=headers)

        # 409 = need session ID, retry once
        if resp.status_code == 409:
            self._session_id = resp.headers.get("X-Transmission-Session-Id", "")
            headers["X-Transmission-Session-Id"] = self._session_id
            resp = await self.client.post(self.rpc_url, json=body, headers=headers)

        resp.raise_for_status()
        return resp.json()

    async def add_torrent(self, url: str) -> dict[str, Any]:
        """Add a torrent by magnet URL or .torrent URL."""
        try:
            result = await self._rpc("torrent-add", {"filename": url})
            added = result.get("arguments", {})
            torrent = added.get("torrent-added") or added.get("torrent-duplicate")
            name = torrent.get("name", "Unknown") if torrent else "Unknown"
            duplicate = "torrent-duplicate" in added
            return {
                "ok": True,
                "name": name,
                "duplicate": duplicate,
                "error": None,
            }
        except httpx.ConnectError:
            return {"ok": False, "name": None, "duplicate": False, "error": "Cannot connect to Transmission"}
        except httpx.TimeoutException:
            return {"ok": False, "name": None, "duplicate": False, "error": "Connection timed out"}
        except Exception as e:
            logger.warning(f"Transmission add error: {e}")
            return {"ok": False, "name": None, "duplicate": False, "error": str(e)}

    async def test_connection(self) -> dict[str, Any]:
        """Test connectivity to Transmission."""
        try:
            result = await self._rpc("session-get", {"fields": ["version"]})
            version = result.get("arguments", {}).get("version", "unknown")
            return {"ok": True, "version": version, "error": None}
        except httpx.ConnectError:
            return {"ok": False, "version": None, "error": "Cannot connect to Transmission"}
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {"ok": False, "version": None, "error": "Invalid username/password"}
            return {"ok": False, "version": None, "error": str(e)}
        except Exception as e:
            return {"ok": False, "version": None, "error": str(e)}


def get_download_client() -> TransmissionClient | None:
    """Factory: returns a TransmissionClient if configured, else None."""
    service = get_app_settings_service()
    settings = service.get()

    if not settings.download_client_url:
        return None

    return TransmissionClient(
        base_url=settings.download_client_url,
        username=settings.download_client_username,
        password=settings.download_client_password,
    )


def get_torrent_search_service() -> TorrentSearchService | None:
    """Factory: returns a TorrentSearchService if configured, else None."""
    service = get_app_settings_service()
    settings = service.get()

    if not (
        settings.torrent_search_enabled
        and settings.torrent_search_url
        and settings.torrent_search_api_key
    ):
        return None

    return TorrentSearchService(
        base_url=settings.torrent_search_url,
        api_key=settings.torrent_search_api_key,
        provider=settings.torrent_search_provider,
        prefer_lossless=settings.torrent_search_prefer_lossless,
    )
