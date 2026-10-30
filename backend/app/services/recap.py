"""A listener's year, summarised from their play events (ADR-0156).

Computed on request from `play_events` alone. `ProfilePlayHistory` is never read: it has no
dates, so anything taken from it would put all-time plays on a card that says "this year".
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from statistics import median
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Album,
    Artist,
    PlayEvent,
    ProfileFavorite,
    Track,
    TrackAnalysis,
)
from app.services.listening_feedback import FEEDBACK_TRUSTWORTHY_SINCE
from app.utils.time import utcnow

# Below this many completed plays, a recap would be a thin one that looks complete (point 5).
RECAP_MIN_PLAYS = 50

TOP_N = 5
TOP_MOOD_TAGS = 3

_COMPLETED = "completed"
_ERRORED = "errored"

# Medians over completed plays, weighted by play (point 6).
_SOUND_FEATURES = ("bpm", "energy", "valence", "danceability")


@dataclass
class RecapTrack:
    id: UUID
    title: str | None
    artist: str | None
    plays: int
    minutes: float


@dataclass
class RecapArtist:
    # None when the track's artist tag never resolved to a canonical Artist.
    id: UUID | None
    name: str
    plays: int
    minutes: float
    # A track by this artist, for the client to fetch artwork from when there is no photo.
    track_id: UUID


@dataclass
class RecapAlbum:
    id: UUID | None
    name: str
    artist: str | None
    plays: int
    minutes: float
    # Album artwork is served per track (`GET /tracks/{id}/artwork`).
    track_id: UUID


@dataclass
class RecapSound:
    bpm: float | None = None
    energy: float | None = None
    valence: float | None = None
    danceability: float | None = None
    key: str | None = None
    mood_tags: list[str] = field(default_factory=list)


@dataclass
class Recap:
    year: int
    timezone: str
    window_start: datetime
    window_end: datetime
    insufficient: bool
    plays: int = 0
    minutes_listened: float = 0.0
    unique_tracks: int = 0
    unique_artists: int = 0
    top_tracks: list[RecapTrack] = field(default_factory=list)
    top_artists: list[RecapArtist] = field(default_factory=list)
    top_album: RecapAlbum | None = None
    sound: RecapSound = field(default_factory=RecapSound)
    # Completed plays by local hour, always 24 entries.
    listening_clock: list[int] = field(default_factory=lambda: [0] * 24)
    peak_hour: int | None = None
    # 1-12, in the listener's time zone.
    top_month: int | None = None
    first_listens: int = 0
    favorites_added: int = 0


def recap_window(year: int, tz: ZoneInfo, now: datetime | None = None) -> tuple[datetime, datetime]:
    """The year in the listener's zone, clipped to trustworthy data and to now (point 3).

    Returned as naive UTC to match `PlayEvent.started_at`. An empty window (a year before the
    cutoff, or one that has not begun) comes back with start == end rather than inverted.
    """
    def naive_utc(local: datetime) -> datetime:
        return local.replace(tzinfo=tz).astimezone(UTC).replace(tzinfo=None)

    start = max(naive_utc(datetime(year, 1, 1)), FEEDBACK_TRUSTWORTHY_SINCE)
    end = min(naive_utc(datetime(year + 1, 1, 1)), now or utcnow())
    return start, max(start, end)


def _rank_key(name: str | None):
    """Plays, then minutes, then name: a stable order for ties."""
    def key(item):
        return (-item.plays, -item.minutes, (getattr(item, name) or "").casefold())
    return key


async def compute_recap(
    db: AsyncSession,
    profile_id: UUID,
    year: int,
    tz: ZoneInfo,
    *,
    now: datetime | None = None,
) -> Recap:
    start, end = recap_window(year, tz, now)
    recap = Recap(
        year=year, timezone=tz.key, window_start=start, window_end=end, insufficient=True
    )
    if start == end:
        return recap

    rows = (
        await db.execute(
            select(
                PlayEvent.track_id,
                PlayEvent.started_at,
                PlayEvent.played_seconds,
                PlayEvent.outcome,
                Track.title,
                Track.artist,
                Track.album,
                Track.album_artist,
                Track.canonical_artist_id,
                Track.canonical_album_id,
            )
            .join(Track, Track.id == PlayEvent.track_id)
            .where(
                PlayEvent.profile_id == profile_id,
                PlayEvent.started_at >= start,
                PlayEvent.started_at < end,
                PlayEvent.outcome != _ERRORED,
            )
        )
    ).all()

    completed = [r for r in rows if r.outcome == _COMPLETED]
    recap.plays = len(completed)
    recap.minutes_listened = round(sum(r.played_seconds for r in rows) / 60, 1)
    recap.insufficient = recap.plays < RECAP_MIN_PLAYS
    recap.unique_tracks = len({r.track_id for r in completed})

    tracks: dict[UUID, RecapTrack] = {}
    artists: dict[UUID | str, RecapArtist] = {}
    albums: dict[UUID | tuple, RecapAlbum] = {}
    months: Counter[int] = Counter()

    for r in completed:
        minutes = r.played_seconds / 60

        track = tracks.setdefault(
            r.track_id, RecapTrack(id=r.track_id, title=r.title, artist=r.artist, plays=0, minutes=0)
        )
        track.plays += 1
        track.minutes += minutes

        # Grouped by canonical artist, as everything else that counts artists is; an unresolved
        # tag stands on its own name rather than vanishing.
        artist_key = r.canonical_artist_id or (r.artist or "").casefold()
        artist = artists.setdefault(
            artist_key,
            RecapArtist(
                id=r.canonical_artist_id, name=r.artist or "Unknown artist",
                plays=0, minutes=0, track_id=r.track_id,
            ),
        )
        artist.plays += 1
        artist.minutes += minutes

        if r.album:
            album_key = r.canonical_album_id or ((r.album_artist or r.artist or "").casefold(),
                                                 r.album.casefold())
            album = albums.setdefault(
                album_key,
                RecapAlbum(
                    id=r.canonical_album_id, name=r.album, artist=r.album_artist or r.artist,
                    plays=0, minutes=0, track_id=r.track_id,
                ),
            )
            album.plays += 1
            album.minutes += minutes

        local = r.started_at.replace(tzinfo=UTC).astimezone(tz)
        recap.listening_clock[local.hour] += 1
        months[local.month] += 1

    recap.unique_artists = len(artists)
    recap.top_tracks = sorted(tracks.values(), key=_rank_key("title"))[:TOP_N]
    recap.top_artists = sorted(artists.values(), key=_rank_key("name"))[:TOP_N]
    ranked_albums = sorted(albums.values(), key=_rank_key("name"))
    recap.top_album = ranked_albums[0] if ranked_albums else None
    if completed:
        # max() keeps the first of equal values, so a tie goes to the earlier hour / month.
        recap.peak_hour = max(range(24), key=lambda h: recap.listening_clock[h])
        recap.top_month = max(sorted(months), key=lambda m: months[m])

    await _canonical_names(db, recap)
    ranked: list[RecapTrack | RecapArtist | RecapAlbum] = [*recap.top_tracks, *recap.top_artists]
    if recap.top_album is not None:
        ranked.append(recap.top_album)
    for item in ranked:
        item.minutes = round(item.minutes, 1)

    play_counts = Counter(r.track_id for r in completed)
    recap.sound = await _sound(db, play_counts)
    recap.first_listens = await _first_listens(db, profile_id, start, {r.track_id for r in rows})
    recap.favorites_added = await db.scalar(
        select(func.count()).where(
            ProfileFavorite.profile_id == profile_id,
            ProfileFavorite.favorited_at >= start,
            ProfileFavorite.favorited_at < end,
        )
    ) or 0
    return recap


async def _canonical_names(db: AsyncSession, recap: Recap) -> None:
    """Show the canonical spelling, not whichever tag happened to be played first."""
    artist_ids = [a.id for a in recap.top_artists if a.id is not None]
    if artist_ids:
        rows = await db.execute(select(Artist.id, Artist.name).where(Artist.id.in_(artist_ids)))
        names: dict[UUID, str] = {row.id: row.name for row in rows}
        for artist in recap.top_artists:
            artist.name = names.get(artist.id, artist.name)
    if recap.top_album is not None and recap.top_album.id is not None:
        name = await db.scalar(select(Album.name).where(Album.id == recap.top_album.id))
        recap.top_album.name = name or recap.top_album.name


async def _sound(db: AsyncSession, play_counts: Counter[UUID]) -> RecapSound:
    """What the year sounded like, weighted by how often each track was played."""
    sound = RecapSound()
    if not play_counts:
        return sound
    analyses = (
        await db.execute(
            select(TrackAnalysis).where(TrackAnalysis.track_id.in_(list(play_counts)))
        )
    ).scalars().all()

    for name in _SOUND_FEATURES:
        values = [
            value
            for a in analyses
            if (value := getattr(a, name)) is not None
            for _ in range(play_counts[a.track_id])
        ]
        if values:
            setattr(sound, name, round(median(values), 3))

    keys: Counter[str] = Counter()
    tags: Counter[str] = Counter()
    for a in analyses:
        weight = play_counts[a.track_id]
        if a.key:
            keys[a.key] += weight
        for tag in a.mood_tags or []:
            if tag.get("tag"):
                tags[tag["tag"]] += weight
    if keys:
        sound.key = keys.most_common(1)[0][0]
    sound.mood_tags = [tag for tag, _ in tags.most_common(TOP_MOOD_TAGS)]
    return sound


async def _first_listens(
    db: AsyncSession, profile_id: UUID, start: datetime, heard: set[UUID]
) -> int:
    """Tracks heard in the window that had never been heard before it.

    "Before" reaches back past the trustworthy cutoff on purpose: a play in July is unreliable
    about how much was heard, not about whether the track was heard at all.
    """
    if not heard:
        return 0
    heard_before = set(
        (
            await db.execute(
                select(PlayEvent.track_id)
                .where(
                    PlayEvent.profile_id == profile_id,
                    PlayEvent.started_at < start,
                    PlayEvent.outcome != _ERRORED,
                    PlayEvent.track_id.in_(list(heard)),
                )
                .distinct()
            )
        ).scalars()
    )
    return len(heard - heard_before)
