"""Torrent search API endpoints (Jackett/Prowlarr)."""

import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import RequiredProfile
from app.services.torrent_search import get_download_client, get_torrent_search_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/torrent-search", tags=["torrent-search"])


# ── Response Models ──────────────────────────────────────────────────


class TorrentResultResponse(BaseModel):
    title: str
    indexer: str
    size_bytes: int
    size_display: str
    seeders: int
    leechers: int
    magnet_url: str | None
    torrent_url: str | None
    info_url: str | None
    category: str
    publish_date: str | None


class TorrentSearchResultsResponse(BaseModel):
    results: list[TorrentResultResponse]
    total: int
    query: str
    error: str | None = None


class TorrentConnectionTestResponse(BaseModel):
    ok: bool
    provider: str
    error: str | None = None


class DownloadRequest(BaseModel):
    url: str  # magnet or .torrent URL


class DownloadResponse(BaseModel):
    ok: bool
    name: str | None = None
    duplicate: bool = False
    error: str | None = None


# ── Endpoints ────────────────────────────────────────────────────────


@router.get("/search", response_model=TorrentSearchResultsResponse)
async def search_torrents(
    _profile: RequiredProfile,
    artist: str = Query(..., description="Artist name"),
    title: str | None = Query(None, description="Track title"),
    album: str | None = Query(None, description="Album name"),
    limit: int = Query(20, ge=1, le=100),
) -> TorrentSearchResultsResponse:
    """Search for torrents matching the given artist/title/album."""
    service = get_torrent_search_service()
    if service is None:
        return TorrentSearchResultsResponse(
            results=[], total=0, query=artist,
            error="Torrent search is not configured. Enable it in Admin Settings.",
        )

    response = await service.search(artist, title, album, limit)
    return TorrentSearchResultsResponse(
        results=[
            TorrentResultResponse(
                title=r.title,
                indexer=r.indexer,
                size_bytes=r.size_bytes,
                size_display=r.size_display,
                seeders=r.seeders,
                leechers=r.leechers,
                magnet_url=r.magnet_url,
                torrent_url=r.torrent_url,
                info_url=r.info_url,
                category=r.category,
                publish_date=r.publish_date,
            )
            for r in response.results
        ],
        total=response.total,
        query=response.query,
        error=response.error,
    )


@router.get("/status", response_model=TorrentConnectionTestResponse)
async def get_status(
    _profile: RequiredProfile,
) -> TorrentConnectionTestResponse:
    """Check if torrent search is configured. Always returns (never 404)."""
    service = get_torrent_search_service()
    if service is None:
        return TorrentConnectionTestResponse(
            ok=False, provider="none", error="Not configured"
        )
    return TorrentConnectionTestResponse(
        ok=True, provider=service.provider, error=None
    )


@router.post("/test", response_model=TorrentConnectionTestResponse)
async def test_connection(
    _profile: RequiredProfile,
) -> TorrentConnectionTestResponse:
    """Actively test the connection to Jackett/Prowlarr."""
    service = get_torrent_search_service()
    if service is None:
        return TorrentConnectionTestResponse(
            ok=False, provider="none", error="Not configured"
        )

    result = await service.test_connection()
    return TorrentConnectionTestResponse(**result)


@router.post("/download", response_model=DownloadResponse)
async def download_torrent(
    request: DownloadRequest,
    _profile: RequiredProfile,
) -> DownloadResponse:
    """Send a magnet/torrent URL to the download client (Transmission)."""
    client = get_download_client()
    if client is None:
        return DownloadResponse(
            ok=False,
            error="No download client configured. Add a Transmission URL in Admin Settings.",
        )

    result = await client.add_torrent(request.url)
    return DownloadResponse(**result)
