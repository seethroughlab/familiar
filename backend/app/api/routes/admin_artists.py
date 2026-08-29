"""Admin endpoints for managing canonical artist rows.

Pass 2 of the canonical-artists migration. Lets the user merge
artist rows that auto-resolution couldn't safely close (e.g. "Beatles"
and "The Beatles" — both real artists, but only one carries the
canonical MBID; the strict-match resolver leaves them as two rows).

Auth is ``RequiredProfile`` — Familiar is a single-user-on-personal-server
app and there's no admin role. The frontend's MBID guard (the Merge button
disables when ≥2 candidates have different non-NULL MBIDs) is the
operational safety net.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text, update

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import NotFoundError
from app.db.models import Artist, Track
from app.services.artist_resolver import _canonicalize_for_match

logger = logging.getLogger(__name__)

# `/artists`, not `/admin/artists` (ADR-0076 point 5, deferred there and taken here). The `/admin/`
# prefix promised a namespace two-thirds of this API would qualify for and only these three used —
# under ADR-0058 most of Familiar's API *is* administration, so a prefix claiming the word is worse
# than no prefix. Distinct from `/library/artists`, which browses; this merges.
router = APIRouter(prefix="/artists", tags=["artists"])

MAX_MERGE_BATCH = 20


# ── Schemas ────────────────────────────────────────────────────────


class MergeArtistsRequest(BaseModel):
    keep_id: UUID
    merge_ids: list[UUID] = Field(..., min_length=1, max_length=MAX_MERGE_BATCH)


class MergeArtistsResponse(BaseModel):
    kept_artist_id: str
    aliases_moved: int
    aliases_dropped_as_duplicates: int
    tracks_repointed: int
    tracks_album_artist_repointed: int
    artists_deleted: int


class MergeCandidate(BaseModel):
    id: str
    name: str
    sort_name: str
    track_count: int
    musicbrainz_id: str | None


class MergeSuggestion(BaseModel):
    canonical_form: str
    suggested_keep_id: str
    candidates: list[MergeCandidate]


class MergeSuggestionsResponse(BaseModel):
    suggestions: list[MergeSuggestion]


class ArtistSearchResult(BaseModel):
    id: str
    name: str
    sort_name: str
    track_count: int
    musicbrainz_id: str | None


class ArtistSearchResponse(BaseModel):
    results: list[ArtistSearchResult]


# ── Routes ─────────────────────────────────────────────────────────


@router.post("/merge", response_model=MergeArtistsResponse)
async def merge_artists(
    db: DbSession,
    profile: RequiredProfile,  # noqa: ARG001 — single-user gate
    request: MergeArtistsRequest,
) -> MergeArtistsResponse:
    """Merge several ``Artist`` rows into one canonical row.

    Atomic. Locks the source rows so the scanner's resolver can't
    insert a new alias pointing at any merge_id mid-merge. Aliases
    that would collide with one already on the keep artist are
    dropped (keep-side wins). ``tracks.canonical_artist_id`` is
    repointed BEFORE the artist DELETE — the FK is ON DELETE SET
    NULL, which would silently null tracks if the order were
    reversed.

    Idempotency: re-running with the same payload finds the
    merge_ids gone and returns 404 — honest signal, not 200.
    """
    if request.keep_id in request.merge_ids:
        raise HTTPException(
            status_code=400,
            detail="keep_id must not appear in merge_ids",
        )
    if len(set(request.merge_ids)) != len(request.merge_ids):
        raise HTTPException(
            status_code=400,
            detail="merge_ids must not contain duplicates",
        )

    keep = await db.get(Artist, request.keep_id)
    if keep is None:
        raise NotFoundError(f"keep_id {request.keep_id} not found")

    merge_ids_str = [str(mid) for mid in request.merge_ids]

    # Lock source rows. If any are missing, surface a 404 — the merge
    # already ran (or one of the ids is bogus).
    locked = (
        await db.execute(
            select(Artist.id)
            .where(Artist.id.in_(request.merge_ids))
            .with_for_update()
        )
    ).all()
    locked_set = {str(row.id) for row in locked}
    missing = [mid for mid in merge_ids_str if mid not in locked_set]
    if missing:
        raise NotFoundError(
            f"merge_ids not found (already merged or invalid): {missing}"
        )

    # 1. Move aliases. Aliases whose ``alias_normalized`` already
    #    exists on the keep artist are skipped here and dropped in
    #    step 2 — keep-side wins, source duplicate is forgotten.
    moved_result = await db.execute(
        text(
            """
            UPDATE artist_aliases
            SET artist_id = :keep_id
            WHERE artist_id = ANY(:merge_ids)
              AND alias_normalized NOT IN (
                SELECT alias_normalized FROM artist_aliases WHERE artist_id = :keep_id
              )
            """
        ),
        {"keep_id": str(request.keep_id), "merge_ids": merge_ids_str},
    )
    aliases_moved = moved_result.rowcount or 0  # type: ignore[attr-defined]

    # 2. Drop the colliding aliases that didn't move.
    dropped_result = await db.execute(
        text(
            "DELETE FROM artist_aliases WHERE artist_id = ANY(:merge_ids)"
        ),
        {"merge_ids": merge_ids_str},
    )
    aliases_dropped = dropped_result.rowcount or 0  # type: ignore[attr-defined]

    # 3a. Repoint tracks via canonical_artist_id. MUST happen before the
    #     artist DELETE — the FK is ON DELETE SET NULL, which would
    #     silently null tracks rather than repointing them.
    tracks_result = await db.execute(
        update(Track)
        .where(Track.canonical_artist_id.in_(request.merge_ids))
        .values(canonical_artist_id=request.keep_id)
    )
    tracks_repointed = tracks_result.rowcount or 0  # type: ignore[attr-defined]

    # 3b. Same for canonical_album_artist_id (Pass 3 column). Same FK
    #     semantics, same ordering requirement.
    album_artist_result = await db.execute(
        update(Track)
        .where(Track.canonical_album_artist_id.in_(request.merge_ids))
        .values(canonical_album_artist_id=request.keep_id)
    )
    tracks_album_artist_repointed = (
        album_artist_result.rowcount or 0  # type: ignore[attr-defined]
    )

    # 4. Delete the now-orphaned artist rows.
    delete_result = await db.execute(
        delete(Artist).where(Artist.id.in_(request.merge_ids))
    )
    artists_deleted = delete_result.rowcount or 0  # type: ignore[attr-defined]

    await db.commit()

    return MergeArtistsResponse(
        kept_artist_id=str(request.keep_id),
        aliases_moved=aliases_moved,
        aliases_dropped_as_duplicates=aliases_dropped,
        tracks_repointed=tracks_repointed,
        tracks_album_artist_repointed=tracks_album_artist_repointed,
        artists_deleted=artists_deleted,
    )


@router.get("/merge-suggestions", response_model=MergeSuggestionsResponse)
async def get_merge_suggestions(
    db: DbSession,
    profile: RequiredProfile,  # noqa: ARG001 — single-user gate
    limit: int = 100,
) -> MergeSuggestionsResponse:
    """Return groups of artists whose canonicalized names collide.

    The obvious "Beatles" + "The Beatles" + "Beatles, The" cluster.
    Pure-Python pass over a fetched-once list — ~3.5k artists fits in
    <5MB Python overhead, sub-50ms group. Each suggestion ranks
    MBID-bearing candidates first (likely canonical winner); UI
    guards against merging two non-matching MBIDs.

    Long-tail rename cases ("Antony" → "ANOHNI", "Ceephax" → "Ceephax
    Acid Crew") aren't surfaced here — different canonical forms. The
    user picks those manually via the merge UI's search panel.
    """
    rows = (
        await db.execute(
            select(
                Artist.id,
                Artist.name,
                Artist.sort_name,
                Artist.musicbrainz_id,
                func.count(Track.id).label("track_count"),
            )
            .outerjoin(Track, Track.canonical_artist_id == Artist.id)
            .group_by(
                Artist.id,
                Artist.name,
                Artist.sort_name,
                Artist.musicbrainz_id,
            )
        )
    ).all()

    groups: dict[str, list[Any]] = {}
    for r in rows:
        key = _canonicalize_for_match(r.name)
        if not key:
            continue
        groups.setdefault(key, []).append(r)

    suggestions: list[MergeSuggestion] = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        # MBID-bearing first (likely canonical); ties broken by track
        # count desc so the most-impactful winner floats up.
        members.sort(
            key=lambda m: (
                0 if m.musicbrainz_id else 1,
                -(m.track_count or 0),
            )
        )
        suggestions.append(
            MergeSuggestion(
                canonical_form=key,
                suggested_keep_id=str(members[0].id),
                candidates=[
                    MergeCandidate(
                        id=str(m.id),
                        name=m.name,
                        sort_name=m.sort_name,
                        track_count=m.track_count or 0,
                        musicbrainz_id=m.musicbrainz_id,
                    )
                    for m in members
                ],
            )
        )

    # Most-impactful merges first.
    suggestions.sort(
        key=lambda s: -sum(c.track_count for c in s.candidates)
    )

    return MergeSuggestionsResponse(suggestions=suggestions[:limit])


@router.get("/search", response_model=ArtistSearchResponse)
async def search_artists(
    db: DbSession,
    profile: RequiredProfile,  # noqa: ARG001 — single-user gate
    q: str,
    limit: int = 20,
) -> ArtistSearchResponse:
    """Substring search across canonical artist names + sort_names.

    Powers the merge UI's manual-search panel — finds long-tail rename
    or abbreviation cases that the canonical-form-collision suggestions
    can't see (e.g. "Various" vs "Various Artists", "Señor Coconut"
    vs "Señor Coconut and His Orchestra"). Trim/lower the query, ILIKE
    against name + sort_name, order by track count desc.
    """
    if not q.strip():
        return ArtistSearchResponse(results=[])
    pattern = f"%{q.strip().lower()}%"
    rows = (
        await db.execute(
            select(
                Artist.id,
                Artist.name,
                Artist.sort_name,
                Artist.musicbrainz_id,
                func.count(Track.id).label("track_count"),
            )
            .outerjoin(Track, Track.canonical_artist_id == Artist.id)
            .where(
                func.lower(Artist.name).like(pattern)
                | func.lower(Artist.sort_name).like(pattern)
            )
            .group_by(
                Artist.id, Artist.name, Artist.sort_name, Artist.musicbrainz_id
            )
            .order_by(func.count(Track.id).desc())
            .limit(limit)
        )
    ).all()
    return ArtistSearchResponse(
        results=[
            ArtistSearchResult(
                id=str(r.id),
                name=r.name,
                sort_name=r.sort_name,
                track_count=r.track_count or 0,
                musicbrainz_id=r.musicbrainz_id,
            )
            for r in rows
        ]
    )
