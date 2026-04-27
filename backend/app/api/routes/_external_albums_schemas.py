"""Shared Pydantic schemas for external-album endpoints.

Used by:
- ``playlists/recommendations.py`` for per-playlist recommendations (#2)
- ``library_discover.py`` for listening-profile recommendations (#2 in Discover)
"""

from typing import Any

from pydantic import BaseModel


class ExternalAlbumResponse(BaseModel):
    """An external (not-in-library) album recommendation."""

    id: str
    artist_name: str
    release_name: str
    release_type: str | None
    release_date: str | None
    artwork_url: str
    external_url: str | None
    track_count: int | None
    match_score: float
    seed_artist: str | None
    local_album_match: bool
    dismissed: bool
    discovered_at: str
    purchase_links: dict[str, Any]


class ExternalAlbumsResponse(BaseModel):
    """List of external album recommendations."""

    albums: list[ExternalAlbumResponse]
