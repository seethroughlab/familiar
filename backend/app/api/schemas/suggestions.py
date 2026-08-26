"""Response shape for in-library suggestions (ADR-0093).

Shared by the playlist and favorites routes because ADR-0093 point 2 makes them one service: the two
differ only in where the seed ids come from, and a second schema would be the first place that stops
being true.
"""

from uuid import UUID

from pydantic import BaseModel

from app.api.schemas.tracks import TrackResponse


class SuggestionReasonResponse(BaseModel):
    """The track of the listener's own that reached this suggestion.

    Deliberately not a full `TrackResponse`: this is a caption, and returning a whole track for every
    suggestion would double the payload to say "because you like X".
    """

    track_id: UUID
    title: str | None = None
    artist: str | None = None


class SuggestedTrackResponse(BaseModel):
    """One addable track, and why it is being offered."""

    track: TrackResponse
    #: **The reason is a real pair of tracks, not a generated label** (ADR-0093 point 7). Three
    #: attempts at naming a cluster failed before this; a seed and a similarity cannot be wrong
    #: about themselves.
    because_of: SuggestionReasonResponse
    similarity: float
    #: How many of the collection's tracks independently reached this one. Agreement is what the
    #: ranking is built on, so it is worth showing rather than hiding.
    votes: int


class SuggestedTracksResponse(BaseModel):
    """Suggestions for one collection, best first."""

    suggestions: list[SuggestedTrackResponse]
    seed_track_count: int
