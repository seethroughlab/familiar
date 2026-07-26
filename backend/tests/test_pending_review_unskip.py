"""Tests for un-skipping previously-skipped import tracks.

Inserts tracks via async_db, then drives the un-skip endpoints through the sync TestClient
(both share the same DATABASE_URL). Un-skip returns SKIPPED tracks to PENDING_REVIEW.
"""

import pytest

from app.db.models import TrackStatus
from tests.conftest import make_profile_headers
from tests.factories import insert_test_track


def _ids(groups_response: dict) -> set[str]:
    """Collect every track id across all groups in a /groups response."""
    return {t["id"] for g in groups_response["groups"] for t in g["tracks"]}


class TestUnskip:
    @pytest.mark.asyncio
    async def test_unskip_single_returns_to_pending(self, async_db, client, test_profile):
        track = await insert_test_track(async_db, title="Skipped One")
        track.status = TrackStatus.SKIPPED
        await async_db.commit()
        tid = str(track.id)
        headers = make_profile_headers(test_profile)

        # Starts in skipped, not in pending.
        assert tid in _ids(client.get("/api/v1/pending-tracks/groups?status=skipped").json())
        assert tid not in _ids(client.get("/api/v1/pending-tracks/groups").json())

        resp = client.post(f"/api/v1/pending-tracks/{tid}/unskip", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending_review"

        # Now in pending, gone from skipped.
        assert tid in _ids(client.get("/api/v1/pending-tracks/groups").json())
        assert tid not in _ids(client.get("/api/v1/pending-tracks/groups?status=skipped").json())

    @pytest.mark.asyncio
    async def test_bulk_unskip_all(self, async_db, client, test_profile):
        t1 = await insert_test_track(async_db, title="S1")
        t2 = await insert_test_track(async_db, title="S2")
        t1.status = TrackStatus.SKIPPED
        t2.status = TrackStatus.SKIPPED
        await async_db.commit()
        headers = make_profile_headers(test_profile)

        resp = client.post("/api/v1/pending-tracks/bulk/unskip-all", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["count"] == 2

        pending = _ids(client.get("/api/v1/pending-tracks/groups").json())
        assert {str(t1.id), str(t2.id)} <= pending

    @pytest.mark.asyncio
    async def test_list_status_skipped_excludes_pending(self, async_db, client):
        skipped = await insert_test_track(async_db, title="Sk")
        pending = await insert_test_track(async_db, title="Pe")
        skipped.status = TrackStatus.SKIPPED
        pending.status = TrackStatus.PENDING_REVIEW
        await async_db.commit()

        skipped_ids = _ids(client.get("/api/v1/pending-tracks/groups?status=skipped").json())
        assert str(skipped.id) in skipped_ids
        assert str(pending.id) not in skipped_ids

    @pytest.mark.asyncio
    async def test_unskip_non_skipped_track_404s(self, async_db, client, test_profile):
        track = await insert_test_track(async_db, title="Still Pending")
        track.status = TrackStatus.PENDING_REVIEW
        await async_db.commit()
        headers = make_profile_headers(test_profile)

        resp = client.post(f"/api/v1/pending-tracks/{track.id}/unskip", headers=headers)
        assert resp.status_code == 404
