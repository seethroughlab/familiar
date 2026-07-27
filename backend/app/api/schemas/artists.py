"""Artist-related Pydantic schemas shared across route modules."""

from pydantic import BaseModel


class SimilarArtistInfo(BaseModel):
    """A similar artist, with library status and external links.

    Shared by the artist-detail and track-discovery endpoints, which previously
    declared identical copies. Two same-named models made FastAPI emit one of them
    fully qualified — `app__api__routes__tracks__discovery__SimilarArtistInfo` — which
    a generated client would use verbatim as a type name (ADR-0007).
    """

    name: str
    match_score: float  # 0-1 similarity from Last.fm
    in_library: bool
    track_count: int | None = None  # If in library
    image_url: str | None = None
    lastfm_url: str | None = None
    bandcamp_url: str | None = None  # Search link for discovery
