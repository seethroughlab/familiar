"""The listener's year, summarised (ADR-0156).

Tagged `plays`: it summarises the event stream that tag owns. The path is its own because a recap
is a resource in its own right, not a property of a track (ADR-0072 point 1).
"""

from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Path, Query
from pydantic import BaseModel, ConfigDict

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import ValidationError
from app.api.schemas.common import UTCDateTime
from app.services.recap import compute_recap

router = APIRouter(prefix="/recap", tags=["plays"])


class _FromService(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RecapTrackStat(_FromService):
    id: UUID
    title: str | None
    artist: str | None
    plays: int
    minutes: float


class RecapArtistStat(_FromService):
    id: UUID | None
    name: str
    plays: int
    minutes: float
    track_id: UUID


class RecapAlbumStat(_FromService):
    id: UUID | None
    name: str
    artist: str | None
    plays: int
    minutes: float
    track_id: UUID


class RecapSoundPercentilesStat(_FromService):
    """Each median's percentile rank in the whole library, 0-100; 50 is the library's middle.

    Present these rather than the raw medians: the analysis scores most of a library alike, so
    an absolute value says little about one listener's year (ADR-0156 Implementation).
    """

    bpm: int | None
    energy: int | None
    valence: int | None
    danceability: int | None


class RecapSoundStat(_FromService):
    bpm: float | None
    energy: float | None
    valence: float | None
    danceability: float | None
    key: str | None
    mood_tags: list[str]
    library_percentile: RecapSoundPercentilesStat


class RecapResponse(_FromService):
    """A summary of one window of play events.

    `window_start`/`window_end` are what was actually summarised: the year, clipped to the first
    trustworthy day and to now. A client labels the recap from these, never from the year alone.
    """

    year: int
    timezone: str
    window_start: UTCDateTime
    window_end: UTCDateTime
    # Fewer completed plays than the threshold: clients show no recap at all (ADR-0156 point 5).
    insufficient: bool
    plays: int
    minutes_listened: float
    unique_tracks: int
    unique_artists: int
    top_tracks: list[RecapTrackStat]
    top_artists: list[RecapArtistStat]
    top_album: RecapAlbumStat | None
    sound: RecapSoundStat
    listening_clock: list[int]
    peak_hour: int | None
    top_month: int | None
    first_listens: int
    favorites_added: int


@router.get("/{year}", response_model=RecapResponse)
async def get_recap(
    db: DbSession,
    profile: RequiredProfile,
    year: int = Path(ge=2000, le=2100),
    tz: str = Query("UTC", description="IANA time zone the year and the clock are read in"),
) -> RecapResponse:
    """The current profile's recap for `year`."""
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError(f"Unknown time zone: {tz}") from exc
    recap = await compute_recap(db, profile.id, year, zone)
    return RecapResponse.model_validate(recap)
