"""What's new for a profile, and how far it has looked (ADR-0179).

Shared by `GET/POST /api/v1/library/discover/whats-new` and the MCP tool (ADR-0173). Reads stored
rows only: discovery itself is the background job's (ADR-0099 point 1).

**"New" is relative to what this profile has seen, not to a time window.** A window cannot clear:
the reminder would stay lit for a week after the listener had looked. So the server keeps
`seen_through` per profile, and a release is new when it was found after it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ArtistAlias,
    ExternalAlbumCache,
    ProfileDiscoveryState,
    ProfilePlayHistory,
    ProfileReleaseReason,
    Track,
)
from app.services.discovery.similar_releases import SIMILAR_CONTEXT
from app.services.external_albums_helpers import normalize_artist_name
from app.services.new_releases import DISCOVERY_CONTEXT
from app.services.search_links import generate_release_search_urls
from app.utils.time import utcnow

State = Literal["ok", "never_run", "disabled"]

#: Releases further back than this are not "new music", whenever they were found: the MusicBrainz
#: check also turns up an artist's old albums. Matches the new-releases read (`days_back=90`).
RELEASE_WINDOW = timedelta(days=90)


@dataclass
class WhatsNew:
    state: State
    as_of: datetime | None
    age_hours: float | None
    seen_through: datetime | None
    new_count: int
    items: list[dict[str, Any]] = field(default_factory=list)


def _naive_utc(value: datetime) -> datetime:
    """Compare as `discovered_at` is stored: naive UTC."""
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _eligible(now: datetime):
    """The releases a what's-new list may show: not dismissed, not already owned, recent.

    A library artist's release is for everyone; a similar artist's only for a profile it was
    found for (ADR-0180 point 5), which the outer join to `ProfileReleaseReason` decides.
    """
    cutoff = now - RELEASE_WINDOW
    return (
        (ExternalAlbumCache.discovery_context == DISCOVERY_CONTEXT)
        | (
            (ExternalAlbumCache.discovery_context == SIMILAR_CONTEXT)
            & ProfileReleaseReason.profile_id.isnot(None)
        ),
        ExternalAlbumCache.dismissed.is_(False),
        ExternalAlbumCache.local_album_match.is_(False),
        (ExternalAlbumCache.release_date.is_(None)) | (ExternalAlbumCache.release_date >= cutoff),
    )


#: What a what's-new list is made of: library artists' releases, and similar artists' (ADR-0180).
CONTEXTS = (DISCOVERY_CONTEXT, SIMILAR_CONTEXT)


async def _freshness(db: AsyncSession) -> tuple[datetime | None, float | None]:
    """When discovery last found anything this list could show, and how many hours ago.

    Both contexts: a library that only has similar artists' releases so far has run, and saying
    `never_run` would be wrong (ADR-0099 point 8).
    """
    as_of = (
        await db.execute(
            select(func.max(ExternalAlbumCache.discovered_at)).where(
                ExternalAlbumCache.discovery_context.in_(CONTEXTS)
            )
        )
    ).scalar()
    if as_of is None:
        return None, None
    age = (utcnow().replace(tzinfo=None) - as_of).total_seconds() / 3600.0
    return as_of, max(0.0, age)


async def _state_row(db: AsyncSession, profile_id: UUID) -> ProfileDiscoveryState:
    """The profile's row, created on first use with the backlog already counted as seen."""
    row = await db.get(ProfileDiscoveryState, profile_id)
    if row is not None:
        return row
    newest = (
        await db.execute(
            select(func.max(ExternalAlbumCache.discovered_at)).where(
                ExternalAlbumCache.discovery_context.in_(CONTEXTS)
            )
        )
    ).scalar()
    await db.execute(
        pg_insert(ProfileDiscoveryState)
        .values(profile_id=profile_id, seen_through=newest or utcnow().replace(tzinfo=None))
        .on_conflict_do_nothing(index_elements=["profile_id"])
    )
    await db.flush()
    row = await db.get(ProfileDiscoveryState, profile_id, populate_existing=True)
    assert row is not None
    return row


async def _plays_by_artist(
    db: AsyncSession, profile_id: UUID, normalized_names: set[str]
) -> dict[str, int]:
    """How often this profile has played each artist, keyed by normalised name."""
    if not normalized_names:
        return {}
    rows = await db.execute(
        select(ArtistAlias.alias_normalized, func.sum(ProfilePlayHistory.play_count))
        .join(Track, Track.canonical_artist_id == ArtistAlias.artist_id)
        .join(ProfilePlayHistory, ProfilePlayHistory.track_id == Track.id)
        .where(
            ArtistAlias.alias_normalized.in_(normalized_names),
            ProfilePlayHistory.profile_id == profile_id,
        )
        .group_by(ArtistAlias.alias_normalized)
    )
    return {name: int(total or 0) for name, total in rows.all()}


def _reason(artist: str, plays: int) -> dict[str, Any]:
    """Why a library artist's release is listed (ADR-0101 point 3, as ADR-0179 narrows it)."""
    text = (
        f"You've played {artist} {plays} time{'s' if plays != 1 else ''}"
        if plays
        else f"{artist} is in your library"
    )
    return {"kind": "library_artist", "text": text, "seed_artist_name": artist, "play_count": plays}


def _similar_reason(seed: str, plays: int) -> dict[str, Any]:
    """Why a similar artist's release is listed: the artist the listener plays (ADR-0180 point 6)."""
    return {
        "kind": "similar_artist",
        "text": f"Similar to {seed}, which you play",
        "seed_artist_name": seed,
        "play_count": plays,
    }


async def get(db: AsyncSession, profile_id: UUID, *, limit: int = 20) -> WhatsNew:
    """This profile's what's-new list: newest found first, each marked new or not, with a reason."""
    from app.services.app_settings import get_app_settings_service

    if not getattr(get_app_settings_service().get(), "discovery_enabled", True):
        return WhatsNew("disabled", None, None, None, 0)

    # Before the never-run check: a profile that first asks before discovery has found anything
    # starts from now, so what is found afterwards is new to it rather than silently the baseline.
    state = await _state_row(db, profile_id)
    as_of, age_hours = await _freshness(db)
    if as_of is None:
        return WhatsNew("never_run", None, None, state.seen_through, 0)

    seen = state.seen_through
    now = utcnow().replace(tzinfo=None)
    eligible = _eligible(now)

    reasons = and_(
        ProfileReleaseReason.external_album_id == ExternalAlbumCache.id,
        ProfileReleaseReason.profile_id == profile_id,
    )
    new_count = (
        await db.execute(
            select(func.count())
            .select_from(ExternalAlbumCache)
            .outerjoin(ProfileReleaseReason, reasons)
            .where(*eligible, ExternalAlbumCache.discovered_at > seen)
        )
    ).scalar_one()
    rows = (
        await db.execute(
            select(ExternalAlbumCache, ProfileReleaseReason)
            .outerjoin(ProfileReleaseReason, reasons)
            .where(*eligible)
            .order_by(
                ExternalAlbumCache.discovered_at.desc(),
                ExternalAlbumCache.release_date.desc().nullslast(),
            )
            .limit(limit)
        )
    ).all()
    played_names = {r.artist_name_normalized for r, why in rows if why is None}
    played_names |= {normalize_artist_name(why.seed_artist_name) for _, why in rows if why is not None}
    plays = await _plays_by_artist(db, profile_id, played_names)
    items = [
        {
            "id": str(r.id),
            "artist_name": r.artist_name,
            "release_name": r.release_name,
            "release_type": r.release_type,
            "release_date": r.release_date,
            "artwork_url": r.artwork_url
            or f"https://coverartarchive.org/release-group/{r.release_id}/front-250",
            "discovered_at": r.discovered_at,
            "is_new": seen is None or r.discovered_at > seen,
            "bandcamp_url": generate_release_search_urls(r.artist_name, r.release_name)
            .get("bandcamp", {})
            .get("url"),
            "external_url": r.external_url,
            "reason": _reason(r.artist_name, plays.get(r.artist_name_normalized, 0))
            if why is None
            else _similar_reason(
                why.seed_artist_name, plays.get(normalize_artist_name(why.seed_artist_name), 0)
            ),
        }
        for r, why in rows
    ]
    return WhatsNew("ok", as_of, age_hours, seen, int(new_count), items)


async def mark_seen(db: AsyncSession, profile_id: UUID, through: datetime) -> tuple[datetime, bool]:
    """Record that this profile has seen everything found up to `through`. Only moves forward.

    `through` is the newest `discovered_at` the client actually showed, never the time of the
    request, so a release found between the read and this write is not marked seen unread.
    Returns the profile's `seen_through` afterwards, and whether it changed.
    """
    through = _naive_utc(through)
    state = await _state_row(db, profile_id)
    before = state.seen_through
    await db.execute(
        update(ProfileDiscoveryState)
        .where(ProfileDiscoveryState.profile_id == profile_id)
        .values(seen_through=func.greatest(ProfileDiscoveryState.seen_through, through))
    )
    await db.flush()
    after = (
        await db.execute(
            select(ProfileDiscoveryState.seen_through).where(
                ProfileDiscoveryState.profile_id == profile_id
            )
        )
    ).scalar_one()
    return after, after != before
