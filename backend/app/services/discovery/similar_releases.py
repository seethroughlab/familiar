"""New releases by artists similar to the ones a profile plays (ADR-0180).

Two halves, both background work (ADR-0099 point 1):

- **Matching** reuses the ListenBrainz `fresh-releases` response the library job already fetched
  every three hours: a second pure selector over the same list, against each profile's similar
  artists. No extra request.
- **Warming** fills `Artist.similar_artists` from Last.fm for each profile's most-played artists,
  a few calls at a time, so the similar set exists without anyone opening an artist page.

Releases are stored once for the library in `external_album_cache` (context
`similar_artist_new_release`); which played artist brought each one to which profile is in
`profile_release_reasons`, and a similar artist's release is shown only to those profiles.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.external_albums_helpers import normalize_artist_name

logger = logging.getLogger(__name__)

SIMILAR_CONTEXT = "similar_artist_new_release"
#: How many of a profile's most-played artists seed its similar set (ADR-0180 point 2).
TOP_ARTISTS = 25
#: How many of each seed's similar artists are kept, and how close they must be.
SIMILAR_PER_ARTIST = 10
MIN_MATCH = 0.3
#: A release counts as new music only if it came out this recently (point 7), so the first run
#: does not announce a month of releases at once.
FRESH_DAYS = 14
#: Last.fm calls one warming run may make (point 1).
WARM_BUDGET = 25


@dataclass(frozen=True)
class Candidate:
    """A similar artist a profile might want new music from, and why."""

    mbid: str
    name: str
    seed_artist_id: UUID | None
    seed_name: str
    match: float


def _match(entry: dict[str, Any]) -> float:
    try:
        return float(entry.get("match") or 0)
    except (TypeError, ValueError):
        return 0.0


def candidates_from_similar(
    *,
    seed_artist_id: UUID | None,
    seed_name: str,
    similar: list[dict[str, Any]],
    library_names: set[str],
    library_mbids: set[str],
) -> list[Candidate]:
    """One seed's similar artists that could bring new music: close enough, not already owned.

    Only entries Last.fm gave a MusicBrainz id for: ListenBrainz releases are matched by id, and a
    name alone would match the wrong artist. The name is still checked against the release later.
    """
    picked: list[Candidate] = []
    for entry in sorted(similar, key=_match, reverse=True):
        if len(picked) >= SIMILAR_PER_ARTIST:
            break
        name = (entry.get("name") or "").strip()
        mbid = (entry.get("mbid") or "").strip()
        score = _match(entry)
        if not name or not mbid or score < MIN_MATCH:
            continue
        if mbid in library_mbids or normalize_artist_name(name) in library_names:
            continue
        picked.append(Candidate(mbid, name, seed_artist_id, seed_name, score))
    return picked


def _released(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def select_for_similar(
    releases: list[dict[str, Any]],
    candidates: dict[str, Candidate],
    *,
    now: datetime,
) -> list[tuple[dict[str, Any], Candidate]]:
    """The fresh releases made by a profile's similar artists, normalised for the cache.

    A release must be a wanted type, have a release-group id, not be Various Artists, name one of
    the candidates by MusicBrainz id **and** credit that artist by name (Last.fm's `mbid` is
    sometimes simply wrong), and have come out within `FRESH_DAYS`.
    """
    from app.services.discovery.listenbrainz import VARIOUS_ARTISTS_MBID, WANTED_TYPES

    chosen: list[tuple[dict[str, Any], Candidate]] = []
    for release in releases:
        if release.get("release_group_primary_type") not in WANTED_TYPES:
            continue
        release_group = release.get("release_group_mbid")
        artist_mbids = release.get("artist_mbids") or []
        if not release_group or VARIOUS_ARTISTS_MBID in artist_mbids:
            continue
        candidate = next((candidates[m] for m in artist_mbids if m in candidates), None)
        if candidate is None:
            continue
        credit = normalize_artist_name(release.get("artist_credit_name") or "")
        if normalize_artist_name(candidate.name) not in credit:
            continue
        released = _released(release.get("release_date"))
        if released is None or not (now - timedelta(days=FRESH_DAYS) <= released <= now + timedelta(days=1)):
            continue
        chosen.append(
            (
                {
                    "release_id": release_group,
                    "artist_name": candidate.name,
                    "artist_name_normalized": normalize_artist_name(candidate.name),
                    "musicbrainz_artist_id": candidate.mbid,
                    "release_name": release.get("release_name") or "Unknown",
                    "release_type": (release.get("release_group_primary_type") or "").lower() or None,
                    "release_date": released,
                    "artwork_url": (
                        f"https://coverartarchive.org/release/{release['caa_release_mbid']}/front-250"
                        if release.get("caa_release_mbid")
                        else None
                    ),
                },
                candidate,
            )
        )
    return chosen


async def _seeds(db: AsyncSession, profile_id: UUID) -> list[tuple[UUID, str, list[dict[str, Any]]]]:
    """This profile's most-played artists, with whatever similar artists are cached for them."""
    from app.db.models import Artist, ProfilePlayHistory, Track

    rows = await db.execute(
        select(Artist.id, Artist.name, Artist.similar_artists)
        .join(Track, Track.canonical_artist_id == Artist.id)
        .join(ProfilePlayHistory, ProfilePlayHistory.track_id == Track.id)
        .where(ProfilePlayHistory.profile_id == profile_id)
        .group_by(Artist.id)
        .order_by(func.sum(ProfilePlayHistory.play_count).desc())
        .limit(TOP_ARTISTS)
    )
    return [(artist_id, name, similar or []) for artist_id, name, similar in rows.all()]


async def _library_identity(db: AsyncSession) -> tuple[set[str], set[str]]:
    """Every name and MusicBrainz id the library already has, so owned artists are left out."""
    from app.db.models import Artist, ArtistAlias

    names = set((await db.execute(select(ArtistAlias.alias_normalized))).scalars().all())
    mbids = set(
        (await db.execute(select(Artist.musicbrainz_id).where(Artist.musicbrainz_id.isnot(None))))
        .scalars()
        .all()
    )
    return names, mbids


async def profile_candidates(
    db: AsyncSession, profile_id: UUID, library: tuple[set[str], set[str]] | None = None
) -> dict[str, Candidate]:
    """A profile's similar artists by MusicBrainz id, each keeping its closest seed."""
    names, mbids = library or await _library_identity(db)
    best: dict[str, Candidate] = {}
    for seed_id, seed_name, similar in await _seeds(db, profile_id):
        for candidate in candidates_from_similar(
            seed_artist_id=seed_id,
            seed_name=seed_name,
            similar=similar,
            library_names=names,
            library_mbids=mbids,
        ):
            if candidate.mbid not in best or candidate.match > best[candidate.mbid].match:
                best[candidate.mbid] = candidate
    return best


async def save_for_profile(
    db: AsyncSession, profile_id: UUID, item: dict[str, Any], candidate: Candidate
) -> bool:
    """Store the release once for the library and the reason for this profile.

    Returns whether this profile has just been given a release it did not have.
    """
    from app.db.models import ExternalAlbumCache, ProfileReleaseReason

    inserted = await db.execute(
        pg_insert(ExternalAlbumCache)
        .values(discovery_context=SIMILAR_CONTEXT, **item)
        .on_conflict_do_nothing(
            index_elements=["release_id"],
            index_where=ExternalAlbumCache.discovery_context == SIMILAR_CONTEXT,
        )
        .returning(ExternalAlbumCache.id)
    )
    album_id = inserted.scalar_one_or_none()
    if album_id is None:
        album_id = (
            await db.execute(
                select(ExternalAlbumCache.id).where(
                    ExternalAlbumCache.discovery_context == SIMILAR_CONTEXT,
                    ExternalAlbumCache.release_id == item["release_id"],
                )
            )
        ).scalar_one()

    is_new = await db.get(ProfileReleaseReason, (album_id, profile_id)) is None
    statement = pg_insert(ProfileReleaseReason).values(
        external_album_id=album_id,
        profile_id=profile_id,
        seed_artist_id=candidate.seed_artist_id,
        seed_artist_name=candidate.seed_name,
        match_score=candidate.match,
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=["external_album_id", "profile_id"],
            set_={
                "seed_artist_id": statement.excluded.seed_artist_id,
                "seed_artist_name": statement.excluded.seed_artist_name,
                "match_score": statement.excluded.match_score,
            },
            # Keep the closest reason: a second, weaker path to the same release changes nothing.
            where=ProfileReleaseReason.match_score < statement.excluded.match_score,
        )
    )
    return is_new


async def match_similar_releases(
    db: AsyncSession, releases: list[dict[str, Any]], *, now: datetime
) -> dict[str, Any]:
    """Every profile's similar-artist releases from one ListenBrainz response. Commits per release.

    Returns counts, and the profiles that were given something new so they can be told.
    """
    from app.db.models import Profile

    stats: dict[str, Any] = {"similar_candidates": 0, "similar_matched": 0, "similar_new": 0}
    told: set[UUID] = set()
    library = await _library_identity(db)
    for profile_id in (await db.execute(select(Profile.id))).scalars().all():
        candidates = await profile_candidates(db, profile_id, library)
        stats["similar_candidates"] += len(candidates)
        for item, candidate in select_for_similar(releases, candidates, now=now):
            stats["similar_matched"] += 1
            try:
                if await save_for_profile(db, profile_id, item, candidate):
                    stats["similar_new"] += 1
                    told.add(profile_id)
                await db.commit()
            except Exception:
                await db.rollback()
                logger.warning(
                    "similar_release_failed",
                    extra={"release": item.get("release_name")},
                    exc_info=True,
                )
    stats["profiles_told"] = sorted(str(p) for p in told)
    return stats


async def run_similar_artists_warm(budget: int = WARM_BUDGET) -> dict[str, Any]:
    """Fill `Artist.similar_artists` for the artists profiles play most (ADR-0180 point 1).

    At most `budget` Last.fm calls, for played artists with no similar artists cached. Gated like
    every discovery source (ADR-0099 point 12).

    **Writes `similar_artists` only, never `fetched_at`.** The artist page reads a recent
    `fetched_at` as "bio, tags and images are cached" and stops fetching them; setting it here
    would leave those empty for a month.
    """
    from app.db.models import Artist, ProfilePlayHistory, Track
    from app.db.session import create_task_engine_session
    from app.services.discovery import get_recorder, source_enabled
    from app.services.lastfm import get_lastfm_service

    if not source_enabled("lastfm"):
        return {"status": "disabled", "warmed": 0}
    lastfm = get_lastfm_service()
    if not lastfm.is_configured():
        return {"status": "not_configured", "warmed": 0}

    health = get_recorder()
    warmed = failed = 0
    engine, session_maker = create_task_engine_session()
    try:
        async with session_maker() as db:
            wanted = (
                await db.execute(
                    select(Artist)
                    .join(Track, Track.canonical_artist_id == Artist.id)
                    .join(ProfilePlayHistory, ProfilePlayHistory.track_id == Track.id)
                    .where(func.coalesce(func.jsonb_array_length(Artist.similar_artists), 0) == 0)
                    .group_by(Artist.id)
                    .order_by(func.sum(ProfilePlayHistory.play_count).desc())
                    .limit(budget)
                )
            ).scalars().all()
            for artist in wanted:
                try:
                    similar = await lastfm.get_similar_artists(artist.name, limit=20)
                except Exception:
                    failed += 1
                    logger.warning("similar_warm_failed", extra={"artist": artist.name}, exc_info=True)
                    continue
                artist.similar_artists = similar or []
                await db.commit()
                warmed += 1
    finally:
        await engine.dispose()

    if wanted and failed == len(wanted):
        await health.record_failure("lastfm", kind="http_error", detail="every similar-artists call failed")
        return {"status": "error", "warmed": 0, "failed": failed}
    await health.record_success("lastfm", items=warmed)
    return {"status": "success", "warmed": warmed, "failed": failed}
