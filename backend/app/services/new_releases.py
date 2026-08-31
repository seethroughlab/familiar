"""New releases discovery service for finding new music from library artists.

Phase 1 (revival): MusicBrainz only. Reads/writes the shared
``external_album_cache`` table filtered to ``discovery_context='artist_new_release'``.
The same table will host playlist-context external recommendations in a later
pass under a different ``discovery_context`` value.
"""

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Float, and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Artist,
    ArtistCheckCache,
    ExternalAlbumCache,
    ProfilePlayHistory,
    Track,
    TrackStatus,
)
from app.services.external_albums_helpers import (
    _INDEX_WHERE_BY_CONTEXT,
    ARTIST_NEW_RELEASE_CONTEXT,
    check_user_has_release,
    normalize_artist_name,
)
from app.services.search_links import generate_release_search_urls
from app.utils.time import utcnow

# Re-export normalize_artist_name for back-compat with existing imports.
__all__ = ["DISCOVERY_CONTEXT", "NewReleasesService", "normalize_artist_name"]

logger = logging.getLogger(__name__)

DISCOVERY_CONTEXT = ARTIST_NEW_RELEASE_CONTEXT



# How far ahead of today a release date can be before it is certainly wrong.
#
# Generous on purpose. MusicBrainz legitimately carries announced future releases — an album due in
# three months is real and should appear. Nothing, though, is released more than a year out, so this
# only catches data that cannot be true.
MAX_RELEASE_DATE_LOOKAHEAD = timedelta(days=366)


def plausible_release_date(
    value: datetime | None, *, now: datetime | None = None
) -> datetime | None:
    """A release date, or `None` when the source gave one that cannot be true.

    **This exists because two of 589 cached releases claimed 2913 and 2209**, both year-only dates
    from MusicBrainz where someone typed a digit wrong. They parse cleanly — `2913-01-01` is valid
    ISO — so nothing rejected them, and because this list is ordered by date descending they sorted
    *above every real release*. The two most prominent cards in Discover were the two worst rows in
    the table.

    Returning `None` rather than dropping the release keeps the album discoverable — these are real
    compilations with a typo attached — while removing the claim that is wrong. The query orders
    `nullslast`, so a release with no trustworthy date stops leading a list called "new releases".

    Only the future bound is checked. An old first-release date is a different question: a reissue
    can legitimately carry one, and deciding what that means for this feature is not this function's
    business.
    """
    if value is None:
        return None

    # Written out rather than folded into a conditional expression: the aware/naive distinction
    # decides whether the subtraction below raises, and `a or b if c else d` binds in a way that
    # reads as the opposite of what it does.
    if now is not None:
        reference = now
    elif value.tzinfo is not None:
        reference = datetime.now(tz=value.tzinfo)
    else:
        reference = datetime.now()

    # The stored column is naive and a caller's `now` may not be. Comparing the two raises, and a
    # crash in a background sync is a worse outcome than trusting one odd date.
    if (value.tzinfo is None) != (reference.tzinfo is None):
        return value

    if value - reference > MAX_RELEASE_DATE_LOOKAHEAD:
        return None
    return value


#: Share of each discovery batch reserved for artists never checked at all.
#:
#: **Without a reserve, admitting unplayed artists to the pool accomplishes nothing.**
#: They score zero on both recency and frequency, so they sort below every artist with
#: any listening history — and measured on 2026-08-31 the played set alone oversubscribes
#: the rotation: 706 played artists eligible at any moment against a capacity of 525 per
#: seven-day cycle. A queue that refills faster than it drains never reaches its tail.
#:
#: One third rather than a half or a tenth, and the tension is real in both directions.
#: Too small and the 2,932 never-checked artists take years; too large and new releases by
#: the artists someone actually listens to go unnoticed while the backlog is walked. Two
#: thirds keeps the listened-to set current, which is the thing a person notices.
#:
#: This is a backlog mechanism, not a permanent policy: once every artist has been checked
#: once, no artist matches the reserve and the whole batch is priority-ordered again.
NEVER_CHECKED_BATCH_SHARE = 1 / 3


# Beyond this, the precompute is old enough that a caller should say so out loud.
# Three days rather than one: discovery rotates through the library over roughly a
# day, so a result from yesterday is normal operation, not a problem.
STALE_AFTER_HOURS = 72.0


def new_release_note(
    *,
    found: int,
    new_count: int,
    days_back: int,
    as_of: datetime | None,
    age_hours: float | None,
) -> str:
    """What to tell a person about results whose age they cannot see.

    The interesting case is the unhappy one, and it keeps being unrepresentable. The
    first version could only say "found N" or "found none", so a scan cut short by a
    rate-limited upstream reported "No recent releases found" — a confident wrong
    answer. This is the same rule applied to *time*: an empty list means one of three
    quite different things, and the note is where they are told apart.

    **"Never run" is its own case on purpose** (ADR-0099 point 8). It was the true
    state for nineteen nights while the nightly job crashed, and nothing said so.
    """
    if as_of is None:
        return (
            "Discovery has not recorded any releases yet, so this is not the same as "
            "'nothing new' — the background job may not have run successfully. Check "
            "the Server page."
        )

    if age_hours is not None and age_hours >= STALE_AFTER_HOURS:
        days = int(age_hours // 24)
        stamp = f"{days} day(s) ago" if days else f"{int(age_hours)} hour(s) ago"
        return (
            f"{found} release(s) ({new_count} not in library), but discovery last found "
            f"anything {stamp} — these results are stale and something new may be missing."
        )

    if found:
        return (
            f"Found {found} recent releases ({new_count} not in library) from the last "
            f"{days_back} days."
        )
    return f"No new releases in the last {days_back} days."


class NewReleasesService:
    """Service for discovering new releases from artists in the user's library."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_library_artists(self) -> list[dict[str, Any]]:
        """Return one entry per canonical library artist with name + MB id.

        Reads from the canonical ``artists`` table (joined to active
        tracks) so spelling variants of the same artist collapse into
        one entry. ``ArtistCheckCache`` is keyed by the normalized
        canonical name (Python-side ``normalize_artist_name``), not by
        ``Artist.id`` — the cache table is legacy string-keyed and
        stays that way until a Pass-3 cleanup.
        """
        result = await self.db.execute(
            select(
                Artist.id,
                Artist.name,
                Artist.musicbrainz_id,
            )
            .join(Track, Track.canonical_artist_id == Artist.id)
            .where(Track.status == TrackStatus.ACTIVE)
            .group_by(Artist.id, Artist.name, Artist.musicbrainz_id)
        )
        rows = result.fetchall()

        return [
            {
                "name": row.name,
                "normalized_name": normalize_artist_name(row.name),
                "musicbrainz_artist_id": row.musicbrainz_id,
            }
            for row in rows
        ]

    async def get_artist_check_cache(self, artist_normalized: str) -> ArtistCheckCache | None:
        result = await self.db.execute(
            select(ArtistCheckCache).where(
                ArtistCheckCache.artist_name_normalized == artist_normalized
            )
        )
        return result.scalar_one_or_none()

    async def should_check_artist(
        self,
        artist_normalized: str,
        cache_hours: int = 24,
    ) -> bool:
        cache = await self.get_artist_check_cache(artist_normalized)
        if not cache:
            return True
        cutoff = utcnow() - timedelta(hours=cache_hours)
        return cache.last_checked_at < cutoff

    async def update_artist_cache(
        self,
        artist_normalized: str,
        musicbrainz_id: str | None = None,
    ) -> None:
        cache = await self.get_artist_check_cache(artist_normalized)
        if cache:
            cache.last_checked_at = utcnow()
            if musicbrainz_id:
                cache.musicbrainz_artist_id = musicbrainz_id
        else:
            cache = ArtistCheckCache(
                artist_name_normalized=artist_normalized,
                musicbrainz_artist_id=musicbrainz_id,
                last_checked_at=utcnow(),
            )
            self.db.add(cache)
        await self.db.flush()

    async def check_if_user_has_release(
        self,
        artist_name: str,
        album_name: str,
        musicbrainz_album_id: str | None = None,
    ) -> bool:
        """Thin wrapper around ``check_user_has_release`` for back-compat."""
        return await check_user_has_release(
            self.db, artist_name, album_name, musicbrainz_album_id
        )

    async def save_discovered_release(
        self,
        artist_name: str,
        release_id: str,
        release_name: str,
        release_type: str | None = None,
        release_date: datetime | None = None,
        artwork_url: str | None = None,
        external_url: str | None = None,
        track_count: int | None = None,
        extra_data: dict[str, Any] | None = None,
        musicbrainz_artist_id: str | None = None,
    ) -> ExternalAlbumCache | None:
        """Save a discovered release if not already cached. Returns the row or None.

        **The existence check is scoped to this discovery context, and that scoping is
        load-bearing.** ``external_album_cache`` does not enforce uniqueness on
        ``release_id`` globally — it carries three *partial* unique indexes, one per
        ``discovery_context``, so the same release legitimately exists once per context.
        This method used to select on ``release_id`` alone and call
        ``scalar_one_or_none()``, which raises ``MultipleResultsFound`` the moment any
        release appears in two contexts. Exactly one did, and it killed the nightly
        discovery job every night for nineteen nights. See ADR-0099.

        The insert is an upsert rather than check-then-write for a second reason: the
        scheduled job and ``POST /new-releases/check/batch`` both start runs with no
        lock between them, so two runs could pass the check and the loser would raise
        ``IntegrityError`` — poisoning the session the same way.
        """
        local_match = await self.check_if_user_has_release(artist_name, release_name)

        result = await self.db.execute(
            pg_insert(ExternalAlbumCache)
            .values(
                discovery_context=DISCOVERY_CONTEXT,
                # Stamped from the application clock, not `server_default=func.now()`:
                # in PostgreSQL `now()` is the *transaction* timestamp. The neighbouring
                # writer in `recommendations.py` records what that cost when it was got
                # wrong.
                discovered_at=utcnow(),
                artist_name=artist_name,
                artist_name_normalized=normalize_artist_name(artist_name),
                musicbrainz_artist_id=musicbrainz_artist_id,
                release_id=release_id,
                release_name=release_name,
                release_type=release_type,
                release_date=release_date,
                artwork_url=artwork_url,
                external_url=external_url,
                track_count=track_count,
                extra_data=extra_data or {},
                local_album_match=local_match,
            )
            .on_conflict_do_nothing(
                index_elements=["release_id"],
                index_where=_INDEX_WHERE_BY_CONTEXT[DISCOVERY_CONTEXT],
            )
            .returning(ExternalAlbumCache)
        )
        # `RETURNING` yields no row when the conflict clause suppressed the insert, so
        # `None` still means "already had this one" and callers counting new releases
        # keep counting the same thing.
        return result.scalar_one_or_none()

    async def get_discovery_freshness(self) -> tuple[datetime | None, float | None]:
        """When discovery last wrote, and how many hours ago that was.

        ``None`` means it has never written anything — which is a different
        statement from "there is nothing new", and the two must not be collapsed.
        """
        result = await self.db.execute(
            select(func.max(ExternalAlbumCache.discovered_at)).where(
                ExternalAlbumCache.discovery_context == DISCOVERY_CONTEXT
            )
        )
        as_of: datetime | None = result.scalar()
        if as_of is None:
            return None, None
        age_hours = (utcnow().replace(tzinfo=None) - as_of).total_seconds() / 3600.0
        return as_of, max(0.0, age_hours)

    async def get_new_releases_view(
        self,
        days_back: int = 90,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Recent releases for a listener, read from the precompute. Never calls out.

        **This is the read path, and it is a database query by decision** (ADR-0099
        point 1). It used to be a live MusicBrainz scan of the top fifteen artists on
        the request path, which is what hung an MCP host for 240 seconds while a
        populated cache sat beside it.

        The response carries the *age* of what it returns (point 7). A caller has to be
        able to tell "nothing new" from "discovery last succeeded five days ago" from
        "discovery has never run" — an empty list looks identical in all three and leads
        to opposite conclusions.
        """
        as_of, age_hours = await self.get_discovery_freshness()

        cutoff = utcnow().replace(tzinfo=None) - timedelta(days=days_back)
        query = (
            select(ExternalAlbumCache)
            .where(
                ExternalAlbumCache.discovery_context == DISCOVERY_CONTEXT,
                ExternalAlbumCache.dismissed.is_(False),
                or_(
                    ExternalAlbumCache.release_date.is_(None),
                    ExternalAlbumCache.release_date >= cutoff,
                ),
            )
            .order_by(
                ExternalAlbumCache.release_date.desc().nullslast(),
                ExternalAlbumCache.discovered_at.desc(),
            )
            .limit(limit)
        )
        result = await self.db.execute(query)
        rows = result.scalars().all()

        releases = [
            {
                "artist": r.artist_name,
                "title": r.release_name,
                "type": r.release_type,
                "date": r.release_date.isoformat() if r.release_date else None,
                # Computed by the background job at write time via
                # `check_user_has_release`, so the read path does no matching work.
                "in_library": r.local_album_match,
            }
            for r in rows
        ]
        new_count = sum(1 for r in releases if not r["in_library"])

        return {
            "releases": releases,
            "count": len(releases),
            "new_releases_not_in_library": new_count,
            "as_of": as_of.isoformat() if as_of else None,
            "age_hours": round(age_hours, 1) if age_hours is not None else None,
            "note": new_release_note(
                found=len(releases),
                new_count=new_count,
                days_back=days_back,
                as_of=as_of,
                age_hours=age_hours,
            ),
        }

    async def get_cached_releases(
        self,
        limit: int = 50,
        offset: int = 0,
        include_dismissed: bool = False,
        include_owned: bool = False,
    ) -> list[dict[str, Any]]:
        query = select(ExternalAlbumCache).where(
            ExternalAlbumCache.discovery_context == DISCOVERY_CONTEXT
        )
        if not include_dismissed:
            query = query.where(ExternalAlbumCache.dismissed.is_(False))
        if not include_owned:
            query = query.where(ExternalAlbumCache.local_album_match.is_(False))

        query = (
            query.order_by(
                ExternalAlbumCache.release_date.desc().nullslast(),
                ExternalAlbumCache.discovered_at.desc(),
            )
            .offset(offset)
            .limit(limit)
        )

        result = await self.db.execute(query)
        releases = result.scalars().all()

        return [
            {
                "id": str(r.id),
                "artist_name": r.artist_name,
                "release_name": r.release_name,
                "release_type": r.release_type,
                "release_date": r.release_date.isoformat() if r.release_date else None,
                "artwork_url": r.artwork_url
                or f"https://coverartarchive.org/release-group/{r.release_id}/front-250",
                "external_url": r.external_url,
                "track_count": r.track_count,
                "local_album_match": r.local_album_match,
                "dismissed": r.dismissed,
                "discovered_at": r.discovered_at.isoformat(),
                "purchase_links": generate_release_search_urls(r.artist_name, r.release_name),
            }
            for r in releases
        ]

    async def get_releases_count(
        self,
        include_dismissed: bool = False,
        include_owned: bool = False,
    ) -> int:
        query = select(func.count(ExternalAlbumCache.id)).where(
            ExternalAlbumCache.discovery_context == DISCOVERY_CONTEXT
        )
        if not include_dismissed:
            query = query.where(ExternalAlbumCache.dismissed.is_(False))
        if not include_owned:
            query = query.where(ExternalAlbumCache.local_album_match.is_(False))
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def dismiss_release(
        self,
        release_id: UUID,
        profile_id: UUID,
    ) -> bool:
        result = await self.db.execute(
            select(ExternalAlbumCache).where(
                ExternalAlbumCache.id == release_id,
                ExternalAlbumCache.discovery_context == DISCOVERY_CONTEXT,
            )
        )
        release = result.scalar_one_or_none()
        if not release:
            return False
        release.dismissed = True
        release.dismissed_by_profile_id = profile_id
        await self.db.flush()
        return True

    async def get_prioritized_artists_batch(
        self,
        profile_id: UUID,
        batch_size: int = 75,
        min_days_since_check: int = 7,
    ) -> list[dict[str, Any]]:
        """Return library artists prioritized by listening recency (60%) + frequency (40%).

        **Every artist in the library is a candidate, whether or not you have played
        them.** This used to select *from* ``ProfilePlayHistory``, which made play
        history a gate rather than a priority: 2,614 of 3,453 owned artists had no row
        there and were structurally invisible to new-release discovery. Nothing in
        ADR-0099 asked for that — it was an implementation accident, recorded as a bug
        in ADR-0101.

        Play history is now an outer join and decides *order*, not membership. An
        artist you have never played scores zero and sorts last, which is correct and,
        on its own, still useless — see ``NEVER_CHECKED_BATCH_SHARE``.

        Groups by canonical ``Artist.id`` so spelling variants share one priority
        score. ``ArtistCheckCache`` is joined on a Python-side normalized form of
        ``Artist.name`` — the cache table is legacy string-keyed and stays that way;
        the join condition uses the same ``lower(trim(Artist.name))`` normalization the
        resolver wrote with.
        """
        artist_stats = (
            select(
                Artist.id.label("artist_id"),
                Artist.name.label("artist_name"),
                Artist.musicbrainz_id.label("musicbrainz_artist_id"),
                func.lower(func.trim(Artist.name)).label("artist_normalized"),
                func.max(ProfilePlayHistory.last_played_at).label("last_played"),
                # `coalesce` matters: an artist with no play history has a NULL sum,
                # and NULL propagates through `ln()` to a NULL priority score, which
                # sorts unpredictably rather than last.
                func.coalesce(func.sum(ProfilePlayHistory.play_count), 0).label("total_plays"),
            )
            .select_from(Artist)
            .join(Track, Track.canonical_artist_id == Artist.id)
            .outerjoin(
                ProfilePlayHistory,
                and_(
                    ProfilePlayHistory.track_id == Track.id,
                    ProfilePlayHistory.profile_id == profile_id,
                ),
            )
            .where(Track.status == TrackStatus.ACTIVE)
            .group_by(
                Artist.id,
                Artist.name,
                Artist.musicbrainz_id,
            )
        ).subquery("artist_stats")

        max_plays_result = await self.db.execute(select(func.max(artist_stats.c.total_plays)))
        max_plays = max_plays_result.scalar() or 1

        cache_cutoff = utcnow() - timedelta(days=min_days_since_check)

        days_since_played = (
            func.extract("epoch", func.now() - artist_stats.c.last_played) / 86400.0
        )

        recency_score = 60.0 * func.greatest(
            0.0, 1.0 - func.least(days_since_played, 365.0) / 365.0
        )

        frequency_score = 40.0 * (
            func.ln(artist_stats.c.total_plays.cast(Float) + 1.0)
            / func.ln(float(max_plays) + 1.0)
        )

        priority_score = (recency_score + frequency_score).label("priority_score")

        def eligible(*, never_checked_only: bool, limit: int, exclude: set[str]):
            """Eligible artists in priority order, optionally only the unchecked ones."""
            stale = or_(
                ArtistCheckCache.last_checked_at.is_(None),
                ArtistCheckCache.last_checked_at < cache_cutoff,
            )
            conditions = [ArtistCheckCache.last_checked_at.is_(None)] if never_checked_only else [stale]
            if exclude:
                conditions.append(artist_stats.c.artist_normalized.notin_(exclude))
            return (
                select(
                    artist_stats.c.artist_normalized,
                    artist_stats.c.artist_name,
                    artist_stats.c.musicbrainz_artist_id,
                    artist_stats.c.last_played,
                    artist_stats.c.total_plays,
                    priority_score,
                    ArtistCheckCache.last_checked_at.label("last_checked_at"),
                )
                .select_from(artist_stats)
                .outerjoin(
                    ArtistCheckCache,
                    artist_stats.c.artist_normalized == ArtistCheckCache.artist_name_normalized,
                )
                .where(*conditions)
                .order_by(priority_score.desc())
                .limit(limit)
            )

        # **The reserved slots are the half of this fix that does the work.** Widening the
        # pool alone changes nothing: measured 2026-08-31, 706 played artists are eligible
        # at any moment against a capacity of 525 per seven-day cycle, so the played set
        # oversubscribes on its own and anything scoring zero waits behind a queue that
        # refills faster than it drains. A fix that is correct in the query and inert in
        # effect is not a fix.
        reserved = max(1, round(batch_size * NEVER_CHECKED_BATCH_SHARE))
        first_pass = (await self.db.execute(
            eligible(never_checked_only=True, limit=reserved, exclude=set())
        )).fetchall()

        seen = {row.artist_normalized for row in first_pass}
        remainder = (await self.db.execute(
            eligible(
                never_checked_only=False,
                limit=max(0, batch_size - len(first_pass)),
                exclude=seen,
            )
        )).fetchall()

        return [
            {
                "name": row.artist_name,
                "normalized_name": row.artist_normalized,
                "musicbrainz_artist_id": row.musicbrainz_artist_id,
                "last_played": row.last_played.isoformat() if row.last_played else None,
                "total_plays": row.total_plays,
                "priority_score": float(row.priority_score) if row.priority_score else 0.0,
                # Read off the row rather than from membership of the reserved slice:
                # the remainder is filtered on "stale *or* never checked", so it can
                # legitimately contain never-checked artists too once the reserve is
                # smaller than the backlog.
                "never_checked": row.last_checked_at is None,
            }
            for row in [*first_pass, *remainder]
        ]

    async def get_rotation_status(self, profile_id: UUID) -> dict[str, Any]:
        total_in_rotation_result = await self.db.execute(
            select(func.count(func.distinct(Track.canonical_artist_id)))
            .select_from(ProfilePlayHistory)
            .join(Track, ProfilePlayHistory.track_id == Track.id)
            .where(
                ProfilePlayHistory.profile_id == profile_id,
                Track.canonical_artist_id.isnot(None),
            )
        )
        total_in_rotation = total_in_rotation_result.scalar() or 0

        week_ago = utcnow() - timedelta(days=7)
        checked_this_week_result = await self.db.execute(
            select(func.count(ArtistCheckCache.artist_name_normalized)).where(
                ArtistCheckCache.last_checked_at >= week_ago
            )
        )
        checked_this_week = checked_this_week_result.scalar() or 0

        remaining = max(0, total_in_rotation - checked_this_week)
        days_to_complete = (remaining // 75) + (1 if remaining % 75 > 0 else 0)

        return {
            "total_artists_in_rotation": total_in_rotation,
            "checked_this_week": checked_this_week,
            "remaining_this_week": remaining,
            "estimated_days_to_complete": days_to_complete,
        }

    async def get_check_status(self) -> dict[str, Any]:
        total_releases = await self.get_releases_count(
            include_dismissed=True, include_owned=True
        )
        new_releases = await self.get_releases_count()

        result = await self.db.execute(select(func.max(ArtistCheckCache.last_checked_at)))
        last_check = result.scalar()

        result = await self.db.execute(
            select(func.count(ArtistCheckCache.artist_name_normalized))
        )
        artists_checked = result.scalar() or 0

        artists = await self.get_library_artists()

        return {
            "total_releases_found": total_releases,
            "new_releases_available": new_releases,
            "artists_in_library": len(artists),
            "artists_checked": artists_checked,
            "last_check_at": last_check.isoformat() if last_check else None,
        }
