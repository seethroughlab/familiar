"""The two backend prerequisites for the offline library cache (ADR-0011 points 5, 6 and 7).

A delta cursor is the kind of feature that looks like it works while being wrong, because the
failure is *absence* — rows that should have come back and didn't. Nothing on the client can tell
"nothing changed" from "the query missed it", which is the same shape as the defect ADR-0011's
Context records: a cache holding 50 tracks of 26,396 looked exactly like a working one.

So these pin the three behaviours a client cannot verify for itself:

- a removal is visible through the cursor (it is a status change, not a delete);
- an ordinary listing still hides removals, so widening the delta did not widen everything;
- the boundary row is returned again rather than skipped.

**These go over HTTP rather than calling the route function.** The first draft called `list_tracks`
directly, which skips FastAPI's parameter resolution — every `Query(...)` default arrives as a
`Query` *object* rather than its value, so `updated_since is not None` was true on a request that
supplied no cursor, and the sentinel went to the driver as a bind parameter. The bug lived in the
layer a direct call omits.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.db.models import TrackStatus
from tests.conftest import make_profile_headers
from tests.factories import insert_test_track

# Fixed, naive, and far apart. Naive because the column is TIMESTAMP WITHOUT TIME ZONE — an aware
# datetime raises "can't subtract offset-naive and offset-aware datetimes" at the driver.
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


def _titles(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [t["title"] for t in response.json()["items"]]


@pytest.mark.asyncio
async def test_the_cursor_is_reachable_by_a_client(async_db, client: TestClient, test_profile):
    """`updated_at` is on the response, not only in the query.

    Without the field a client has nothing to send back as `updated_since`, so the parameter would
    exist and be unusable — an affordance whose destination is not mounted.
    """
    await _track_at(async_db, MID, title="Reachable")

    resp = client.get("/api/v1/tracks", headers=make_profile_headers(test_profile))

    assert resp.status_code == 200, resp.text
    assert resp.json()["items"][0]["updated_at"].startswith("2024-06-01T12:00:00")


@pytest.mark.asyncio
async def test_the_cursor_returns_only_what_changed(async_db, client: TestClient, test_profile):
    await _track_at(async_db, OLD, title="Untouched")
    await _track_at(async_db, NEW, title="Edited")

    resp = client.get(
        "/api/v1/tracks",
        params={"updated_since": MID.isoformat()},
        headers=make_profile_headers(test_profile),
    )

    assert _titles(resp) == ["Edited"]
    assert resp.json()["total"] == 1


@pytest.mark.asyncio
async def test_the_cursor_carries_removals(async_db, client: TestClient, test_profile):
    """ADR-0011 point 7 — the reason the delta needs no separate reconcile pass.

    Familiar does not delete tracks, it moves `status` away from active, which is an ORM update and
    moves `updated_at`. If the delta filtered to active the row would simply stop appearing, and the
    client would keep it forever: a track that no longer exists, offered from a cache, failing at the
    stream. The removal has to arrive *as a row*.
    """
    await _track_at(async_db, NEW, title="Gone", status=TrackStatus.MISSING)

    resp = client.get(
        "/api/v1/tracks",
        params={"updated_since": MID.isoformat()},
        headers=make_profile_headers(test_profile),
    )

    assert _titles(resp) == ["Gone"]
    assert resp.json()["items"][0]["status"] != "active", "the client drops it by reading status"


@pytest.mark.asyncio
async def test_a_listing_without_the_cursor_still_hides_removals(
    async_db, client: TestClient, test_profile
):
    """The delta widens itself to every status. It must not widen the ordinary listing too."""
    await _track_at(async_db, NEW, title="Present")
    await _track_at(async_db, NEW, title="Gone", status=TrackStatus.MISSING)

    resp = client.get("/api/v1/tracks", headers=make_profile_headers(test_profile))

    assert _titles(resp) == ["Present"]


@pytest.mark.asyncio
async def test_the_boundary_row_is_returned_again_not_skipped(
    async_db, client: TestClient, test_profile
):
    """`>=`, not `>`.

    A client sends back the `max(updated_at)` it last saw. With `>` every row carrying exactly that
    timestamp is skipped — invisibly, and permanently, since the cursor has already passed them.
    Returning them again costs an idempotent re-write on the client.
    """
    await _track_at(async_db, MID, title="On the boundary")

    resp = client.get(
        "/api/v1/tracks",
        params={"updated_since": MID.isoformat()},
        headers=make_profile_headers(test_profile),
    )

    assert _titles(resp) == ["On the boundary"]


@pytest.mark.asyncio
async def test_the_cursor_accepts_an_aware_timestamp(async_db, client: TestClient, test_profile):
    """The form every generated client actually sends.

    `Track.updated_at` is TIMESTAMP WITHOUT TIME ZONE, and asyncpg refuses to compare that against
    an aware datetime — it raises, and FastAPI turns it into a 500. The Swift client sends RFC 3339
    with a `Z`, so this was broken for every real caller while passing all of the tests above and
    every curl by hand, because those all send the naive form.

    Found by a live slice test against the real server, which is the only thing that spoke the same
    dialect as the app.
    """
    await _track_at(async_db, NEW, title="Edited")

    resp = client.get(
        "/api/v1/tracks",
        params={"updated_since": "2024-06-01T12:00:00Z"},
        headers=make_profile_headers(test_profile),
    )

    assert resp.status_code == 200, resp.text
    assert _titles(resp) == ["Edited"]


@pytest.mark.asyncio
async def test_an_offset_cursor_is_converted_rather_than_truncated(
    async_db, client: TestClient, test_profile
):
    """An offset cursor names an instant, and the conversion has to preserve it.

    14:00+02:00 is 12:00 UTC. Dropping the tzinfo instead of converting would read it as 14:00 and
    silently skip two hours of changes — a delta that loses rows rather than failing.
    """
    await _track_at(async_db, datetime(2024, 6, 1, 13, 0, 0), title="After noon UTC")

    resp = client.get(
        "/api/v1/tracks",
        params={"updated_since": "2024-06-01T14:00:00+02:00"},
        headers=make_profile_headers(test_profile),
    )

    assert resp.status_code == 200, resp.text
    assert _titles(resp) == ["After noon UTC"], "the cursor is 12:00 UTC, not 14:00"


@pytest.mark.asyncio
async def test_the_fingerprint_measures_the_set_it_guards(async_db, client: TestClient):
    """Active rows only — the same set `/tracks` pages when no cursor is given."""
    await _track_at(async_db, OLD, title="One")
    await _track_at(async_db, NEW, title="Two")
    await _track_at(async_db, NEW, title="Gone", status=TrackStatus.MISSING)

    resp = client.get("/api/v1/library/fingerprint")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["track_count"] == 2
    assert body["max_updated_at"].startswith("2025-01-01T12:00:00")


@pytest.mark.asyncio
async def test_renaming_an_album_moves_the_library_fingerprint(async_db, client: TestClient):
    """ADR-0011 point 3's open follow-up, asserted rather than assumed.

    The Apple client caches albums and artists and lets their staleness *ride* the track
    fingerprint, on the grounds that both are groupings of track tags. The ADR flagged the risk:
    "an album renamed with no track edit would slip through".

    There is no such operation — an album is renamed *by* editing its tracks' tags, which is an
    ORM update, so `onupdate` moves `updated_at` and the fingerprint with it. This is the test that
    makes that a fact rather than an argument. If a future endpoint ever renames an album without
    touching its tracks, this fails and the client needs its own signal for albums.
    """
    track = await _track_at(async_db, OLD, title="Song")

    before = client.get("/api/v1/library/fingerprint").json()

    # No explicit updated_at: the point is that the column moves by itself.
    track.album = "Renamed After The Fact"
    await async_db.commit()

    after = client.get("/api/v1/library/fingerprint").json()

    assert after["max_updated_at"] != before["max_updated_at"], (
        "a tag edit must be visible to the fingerprint that guards the album cache"
    )


@pytest.mark.asyncio
async def test_a_removal_moves_the_fingerprint_through_the_count(async_db, client: TestClient):
    """The count is the backstop, and this is the case that proves it is needed.

    A removed track's `updated_at` leaves the active set with it, so `max_updated_at` can sit
    perfectly still while the library shrinks. Only the count notices.
    """
    await _track_at(async_db, NEW, title="Newest")
    doomed = await _track_at(async_db, OLD, title="Doomed")

    before = client.get("/api/v1/library/fingerprint").json()

    doomed.status = TrackStatus.MISSING
    await async_db.commit()
    after = client.get("/api/v1/library/fingerprint").json()

    assert after["max_updated_at"] == before["max_updated_at"], "the maximum cannot see this"
    assert after["track_count"] == before["track_count"] - 1, "so the count has to"
