"""Integration tests for ProposedChangesService against real PostgreSQL.

Tests the full lifecycle: create, preview, apply, undo, reject, delete.
Mocks write_metadata to avoid file I/O.
"""

from uuid import uuid4

import pytest

from app.db.models import ChangeSource, ChangeStatus
from app.services.proposed_changes import ProposedChangesService
from tests.factories import insert_test_profile, insert_test_track


@pytest.fixture
async def profile(async_db):
    p = await insert_test_profile(async_db)
    await async_db.commit()
    return p


@pytest.fixture
def svc(async_db):
    return ProposedChangesService(db=async_db)


class TestCreateAndGet:
    @pytest.mark.asyncio
    async def test_create_change(self, async_db, svc):
        t = await insert_test_track(async_db, title="Original", genre="Pop")
        await async_db.commit()

        change = await svc.create_change(
            change_type="metadata",
            target_type="track",
            target_ids=[str(t.id)],
            source=ChangeSource.USER_REQUEST,
            field="genre",
            old_value="Pop",
            new_value="Rock",
        )
        assert change.id is not None
        assert change.status == ChangeStatus.PENDING

        fetched = await svc.get_by_id(change.id)
        assert fetched is not None
        assert fetched.new_value == "Rock"

    @pytest.mark.asyncio
    async def test_get_by_track(self, async_db, svc):
        t = await insert_test_track(async_db, title="TrackLookup")
        await async_db.commit()

        await svc.create_change(
            change_type="metadata",
            target_type="track",
            target_ids=[str(t.id)],
            source=ChangeSource.USER_REQUEST,
            field="genre",
            new_value="Jazz",
        )

        changes = await svc.get_by_track(t.id)
        assert len(changes) >= 1


class TestListPendingFiltered:
    @pytest.mark.asyncio
    async def test_get_pending(self, async_db, svc):
        t = await insert_test_track(async_db, title="Pending")
        await async_db.commit()

        await svc.create_change(
            change_type="metadata", target_type="track",
            target_ids=[str(t.id)], source=ChangeSource.USER_REQUEST,
            field="title", new_value="New",
        )
        pending = await svc.get_pending()
        assert len(pending) >= 1
        assert all(c.status == ChangeStatus.PENDING for c in pending)

    @pytest.mark.asyncio
    async def test_get_by_status(self, async_db, svc):
        t = await insert_test_track(async_db, title="Status")
        await async_db.commit()

        c = await svc.create_change(
            change_type="metadata", target_type="track",
            target_ids=[str(t.id)], source=ChangeSource.USER_REQUEST,
            field="title", new_value="New",
        )
        await svc.reject(c.id)

        rejected = await svc.get_by_status(ChangeStatus.REJECTED)
        assert len(rejected) >= 1


class TestGetStats:
    @pytest.mark.asyncio
    async def test_stats(self, async_db, svc):
        t = await insert_test_track(async_db, title="Stats")
        await async_db.commit()

        await svc.create_change(
            change_type="metadata", target_type="track",
            target_ids=[str(t.id)], source=ChangeSource.USER_REQUEST,
            field="title", new_value="A",
        )
        c2 = await svc.create_change(
            change_type="metadata", target_type="track",
            target_ids=[str(t.id)], source=ChangeSource.USER_REQUEST,
            field="genre", new_value="B",
        )
        await svc.reject(c2.id)

        stats = await svc.get_stats()
        assert stats.pending >= 1
        assert stats.rejected >= 1


class TestRejectChange:
    @pytest.mark.asyncio
    async def test_reject(self, async_db, svc):
        t = await insert_test_track(async_db, title="Reject")
        await async_db.commit()

        c = await svc.create_change(
            change_type="metadata", target_type="track",
            target_ids=[str(t.id)], source=ChangeSource.USER_REQUEST,
            field="genre", new_value="X",
        )
        result = await svc.reject(c.id)
        assert result is not None
        assert result.status == ChangeStatus.REJECTED

    @pytest.mark.asyncio
    async def test_reject_already_rejected(self, async_db, svc):
        t = await insert_test_track(async_db, title="ReReject")
        await async_db.commit()

        c = await svc.create_change(
            change_type="metadata", target_type="track",
            target_ids=[str(t.id)], source=ChangeSource.USER_REQUEST,
            field="genre", new_value="X",
        )
        await svc.reject(c.id)
        result = await svc.reject(c.id)
        assert result.status == ChangeStatus.REJECTED  # No state transition


class TestPreview:
    @pytest.mark.asyncio
    async def test_preview_shows_affected_tracks(self, async_db, svc):
        t1 = await insert_test_track(async_db, title="Preview1", artist="A")
        t2 = await insert_test_track(async_db, title="Preview2", artist="A")
        await async_db.commit()

        c = await svc.create_change(
            change_type="metadata", target_type="track",
            target_ids=[str(t1.id), str(t2.id)],
            source=ChangeSource.USER_REQUEST,
            field="artist", old_value="A", new_value="B",
        )
        preview = await svc.preview(c.id)
        assert preview is not None
        assert preview.tracks_affected == 2
        assert len(preview.files_affected) == 2
        assert preview.field == "artist"
        assert preview.new_value == "B"

    @pytest.mark.asyncio
    async def test_preview_not_found(self, async_db, svc):
        result = await svc.preview(uuid4())
        assert result is None


class TestApplyDbOnly:
    @pytest.mark.asyncio
    async def test_apply_updates_db(self, async_db, svc):
        t = await insert_test_track(async_db, title="ApplyMe", genre="Old")
        await async_db.commit()

        c = await svc.create_change(
            change_type="metadata", target_type="track",
            target_ids=[str(t.id)], source=ChangeSource.USER_REQUEST,
            field="genre", old_value="Old", new_value="New",
        )

        result = await svc.apply(c.id)
        assert result.success is True
        assert result.db_updated is True

        # Verify the track was actually updated
        await async_db.refresh(t)
        assert t.genre == "New"

        # Change is now APPLIED
        change = await svc.get_by_id(c.id)
        assert change.status == ChangeStatus.APPLIED


class TestApplyAlreadyApplied:
    @pytest.mark.asyncio
    async def test_cannot_apply_twice(self, async_db, svc):
        t = await insert_test_track(async_db, title="Idempotent", genre="Old")
        await async_db.commit()

        c = await svc.create_change(
            change_type="metadata", target_type="track",
            target_ids=[str(t.id)], source=ChangeSource.USER_REQUEST,
            field="genre", old_value="Old", new_value="New",
        )
        await svc.apply(c.id)

        result = await svc.apply(c.id)
        assert result.success is False
        assert "applied" in result.error.lower()


class TestUndoRestoresOriginal:
    @pytest.mark.asyncio
    async def test_undo(self, async_db, svc):
        t = await insert_test_track(async_db, title="UndoMe", genre="Original")
        await async_db.commit()

        c = await svc.create_change(
            change_type="metadata", target_type="track",
            target_ids=[str(t.id)], source=ChangeSource.USER_REQUEST,
            field="genre", old_value="Original", new_value="Changed",
        )
        await svc.apply(c.id)

        # Verify changed
        await async_db.refresh(t)
        assert t.genre == "Changed"

        # Undo
        result = await svc.undo(c.id)
        assert result.success is True
        assert result.db_updated is True

        # Verify reverted
        await async_db.refresh(t)
        assert t.genre == "Original"

        # Status back to PENDING
        change = await svc.get_by_id(c.id)
        assert change.status == ChangeStatus.PENDING

    @pytest.mark.asyncio
    async def test_undo_no_old_value(self, async_db, svc):
        t = await insert_test_track(async_db, title="NoOld", genre="X")
        await async_db.commit()

        c = await svc.create_change(
            change_type="metadata", target_type="track",
            target_ids=[str(t.id)], source=ChangeSource.USER_REQUEST,
            field="genre", old_value=None, new_value="Y",
        )
        await svc.apply(c.id)

        result = await svc.undo(c.id)
        assert result.success is False
        assert "old value" in result.error.lower()


class TestBatchApply:
    @pytest.mark.asyncio
    async def test_batch(self, async_db, svc):
        t1 = await insert_test_track(async_db, title="Batch1", genre="A")
        t2 = await insert_test_track(async_db, title="Batch2", genre="B")
        await async_db.commit()

        c1 = await svc.create_change(
            change_type="metadata", target_type="track",
            target_ids=[str(t1.id)], source=ChangeSource.USER_REQUEST,
            field="genre", old_value="A", new_value="X",
        )
        c2 = await svc.create_change(
            change_type="metadata", target_type="track",
            target_ids=[str(t2.id)], source=ChangeSource.USER_REQUEST,
            field="genre", old_value="B", new_value="Y",
        )

        results = await svc.apply_batch([c1.id, c2.id])
        assert len(results) == 2
        assert all(r.success for r in results)

        await async_db.refresh(t1)
        await async_db.refresh(t2)
        assert t1.genre == "X"
        assert t2.genre == "Y"


class TestDeleteChange:
    @pytest.mark.asyncio
    async def test_delete(self, async_db, svc):
        t = await insert_test_track(async_db, title="Delete")
        await async_db.commit()

        c = await svc.create_change(
            change_type="metadata", target_type="track",
            target_ids=[str(t.id)], source=ChangeSource.USER_REQUEST,
            field="genre", new_value="Z",
        )
        deleted = await svc.delete(c.id)
        assert deleted is True

        fetched = await svc.get_by_id(c.id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_delete_not_found(self, async_db, svc):
        deleted = await svc.delete(uuid4())
        assert deleted is False
