"""The two backend prerequisites for the offline library cache (ADR-0011 points 5, 6 and 7).

A delta cursor is the kind of feature that looks like it works while being wrong, because the
failure is *absence* — rows that should have come back and didn't. Nothing on the client can tell
"nothing changed" from "the query missed it", which is the same shape as the defect ADR-0011's
Context records: a cache holding 50 tracks of 26,396 looked exactly like a working one.

So these tests pin the three behaviours a client cannot verify for itself:

- a removal is visible through the cursor (it is a status change, not a delete);
- an ordinary listing still hides removals, so widening the delta did not widen everything;
- the boundary row is returned again rather than skipped.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.api.routes.library import get_library_fingerprint
from app.api.routes.tracks.listing import list_tracks
from app.db.models import TrackStatus
from tests.factories import insert_test_profile, insert_test_track

# Fixed, naive, and far in the past. Naive because the column is TIMESTAMP WITHOUT TIME ZONE —
# an aware datetime raises "can't subtract offset-naive and offset-aware datetimes" at the driver.
OLD = datetime(2020, 1, 1, 12, 0, 0)
MID = datetime(2024, 6, 1, 12, 0, 0)
NEW = datetime(2025, 1, 1, 12, 0, 0)


async def _track_at(db, updated_at: datetime, *, title: str, status=TrackStatus.ACTIVE):
    """A track whose `updated_at` is set explicitly.

    Assigning the attribute wins over the column's `onupdate=func.now()`, which only fires when the
    column is absent from the UPDATE's SET clause.
    """
    track = await insert_test_track(db, title=title)
    track.updated_at = updated_at
    track.status = status
    await db.commit()
    return track


@pytest.mark.asyncio
async def test_the_cursor_is_reachable_by_a_client(async_db):
    """`updated_at` is on the response, not only in the query.

    Without the field a client has nothing to send back as `updated_since`, so the parameter would
    exist and be unusable — an affordance whose destination is not mounted.
    """
    profile = await insert_test_profile(async_db)
    await _track_at(async_db, MID, title="Reachable")

    result = await list_tracks(db=async_db, profile=profile)

    assert result.items[0].updated_at == MID


@pytest.mark.asyncio
async def test_the_cursor_returns_only_what_changed(async_db):
    profile = await insert_test_profile(async_db)
    await _track_at(async_db, OLD, title="Untouched")
    await _track_at(async_db, NEW, title="Edited")

    result = await list_tracks(db=async_db, profile=profile, updated_since=MID)

    assert [t.title for t in result.items] == ["Edited"]
    assert result.total == 1


@pytest.mark.asyncio
async def test_the_cursor_carries_removals(async_db):
    """ADR-0011 point 7 — the reason the delta needs no separate reconcile pass.

    Familiar does not delete tracks, it moves `status` away from active, which is an ORM update and
    moves `updated_at`. If the delta filtered to active, the row would simply stop appearing and the
    client would keep it forever: a track that no longer exists, playable from a cache, failing at
    the stream. The removal has to arrive *as a row*.
    """
    profile = await insert_test_profile(async_db)
    await _track_at(async_db, NEW, title="Gone", status=TrackStatus.MISSING)

    result = await list_tracks(db=async_db, profile=profile, updated_since=MID)

    assert [t.title for t in result.items] == ["Gone"]
    assert result.items[0].status != "active", "the client drops it by reading the status back"


@pytest.mark.asyncio
async def test_a_listing_without_the_cursor_still_hides_removals(async_db):
    """The delta widens itself to every status. It must not widen the ordinary listing too."""
    profile = await insert_test_profile(async_db)
    await _track_at(async_db, NEW, title="Present")
    await _track_at(async_db, NEW, title="Gone", status=TrackStatus.MISSING)

    result = await list_tracks(db=async_db, profile=profile)

    assert [t.title for t in result.items] == ["Present"]


@pytest.mark.asyncio
async def test_the_boundary_row_is_returned_again_not_skipped(async_db):
    """`>=`, not `>`.

    A client sends back the `max(updated_at)` it last saw. With `>` every row carrying exactly that
    timestamp is skipped — invisibly, and permanently, since the cursor has already passed them.
    Returning them again costs an idempotent re-write on the client.
    """
    profile = await insert_test_profile(async_db)
    await _track_at(async_db, MID, title="On the boundary")

    result = await list_tracks(db=async_db, profile=profile, updated_since=MID)

    assert [t.title for t in result.items] == ["On the boundary"]


@pytest.mark.asyncio
async def test_the_fingerprint_measures_the_set_it_guards(async_db):
    """Active rows only — the same set `list_tracks` pages when no cursor is given."""
    await _track_at(async_db, OLD, title="One")
    await _track_at(async_db, NEW, title="Two")
    await _track_at(async_db, NEW, title="Gone", status=TrackStatus.MISSING)

    fingerprint = await get_library_fingerprint(async_db)

    assert fingerprint.track_count == 2
    assert fingerprint.max_updated_at == NEW


@pytest.mark.asyncio
async def test_a_removal_moves_the_fingerprint_through_the_count(async_db):
    """The count is the backstop, and this is the case that proves it is needed.

    A removed track's `updated_at` leaves the active set with it, so `max_updated_at` can sit
    perfectly still while the library shrinks. Only the count notices.
    """
    await _track_at(async_db, NEW, title="Newest")
    doomed = await _track_at(async_db, OLD, title="Doomed")

    before = await get_library_fingerprint(async_db)

    doomed.status = TrackStatus.MISSING
    await async_db.commit()
    after = await get_library_fingerprint(async_db)

    assert after.max_updated_at == before.max_updated_at, "the maximum cannot see this change"
    assert after.track_count == before.track_count - 1, "so the count has to"
