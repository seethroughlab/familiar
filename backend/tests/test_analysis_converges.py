"""ADR-0172: analysis work converges.

Built from the NAS's state on 2026-11-09, where every two-hourly sync spun its features and
embeddings phases until `queue_churn_limit_exceeded:61/60:300s` on a library with nothing to do:

- 30 tracks with no analysis that are not `active` (27 `skipped`, 2 `missing`,
  1 `pending_deletion`): counted as pending features for ever, queued never;
- 1 `pending_deletion` track with current features and no embedding: the same, for embeddings;
- 4 active tracks whose files ffmpeg cannot decode ("could not decode … Unspecified internal
  error"): failed, retried after 24 hours, failed again, indefinitely.

One of each shape is enough, and is what this file seeds.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.config import EMBEDDING_VERSION, FEATURES_VERSION, MELODIC_VERSION
from app.db.models import Track, TrackAnalysis, TrackStatus
from app.services import analysis_lifecycle as lifecycle
from app.services.analysis_lifecycle import FailureReason, classify, is_terminal
from app.utils.time import utcnow

UNDECODABLE = (
    "Embedding extraction failed: could not decode /music/Cranes/Loved/10 Paris & Rome.mp3: "
    "Unspecified internal error."
)


# ── Classification ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "message,reason",
    [
        (UNDECODABLE, FailureReason.UNDECODABLE),
        ("[Errno 2] No such file or directory: '/music/x.mp3'", FailureReason.FILE_MISSING),
        ("File not found: /music/x.mp3", FailureReason.FILE_MISSING),
        ("A process in the process pool was terminated abruptly", FailureReason.WORKER_CRASHED),
        ("Embedding timed out after 600s", FailureReason.TIMEOUT),
        ("CUDA out of memory", FailureReason.ERROR),
        (None, FailureReason.ERROR),
    ],
)
def test_failures_are_classified(message, reason):
    assert classify(message) is reason


def test_a_permanent_reason_is_terminal_at_once_and_a_transient_one_after_three():
    assert is_terminal(FailureReason.UNDECODABLE, 1)
    assert is_terminal(FailureReason.FILE_MISSING, 1)
    assert not is_terminal(FailureReason.ERROR, 2)
    assert is_terminal(FailureReason.ERROR, lifecycle.MAX_ATTEMPTS)


# ── The NAS state ───────────────────────────────────────────────────────────────────────────────


@pytest.fixture
async def global_engine_released():
    """The queue functions use the app's global engine, whose pooled connections belong to
    whichever event loop last used them. Released before, since an earlier test may have left
    connections on its own loop, and after, so this one leaves none on ours."""
    from app.db.session import engine

    await engine.dispose()
    yield
    await engine.dispose()



def _track(status=TrackStatus.ACTIVE, **kw) -> Track:
    return Track(
        id=uuid4(),
        file_path=f"/music/{uuid4()}.mp3",
        file_hash=uuid4().hex,
        title="t",
        artist="a",
        status=status,
        **kw,
    )


def _analysis(track: Track, *, embedded: bool, **kw) -> TrackAnalysis:
    return TrackAnalysis(
        track_id=track.id,
        features_version=FEATURES_VERSION,
        embedding_version=EMBEDDING_VERSION if embedded else 0,
        melodic_version=MELODIC_VERSION,
        analysis_detail={"sections": []},
        **kw,
    )


async def _seed_the_nas(db) -> dict[str, Track]:
    """One track of each shape, plus one finished track."""
    long_ago = utcnow() - timedelta(hours=25)
    tracks = {
        "done": _track(),
        "skipped": _track(TrackStatus.SKIPPED),
        "missing": _track(TrackStatus.MISSING, missing_since=long_ago),
        "pending_deletion": _track(TrackStatus.PENDING_DELETION),
        "pending_deletion_unembedded": _track(TrackStatus.PENDING_DELETION),
        "undecodable": _track(),
        "transient_exhausted": _track(),
    }
    db.add_all(tracks.values())
    await db.flush()
    db.add_all(
        [
            _analysis(tracks["done"], embedded=True),
            _analysis(tracks["pending_deletion_unembedded"], embedded=False),
            # As the migration backfills it: reason from the stored message, one attempt.
            _analysis(
                tracks["undecodable"],
                embedded=False,
                embedding_error=UNDECODABLE,
                embedding_failed_at=long_ago,
                embedding_failure_reason=FailureReason.UNDECODABLE.value,
                embedding_attempts=1,
            ),
            _analysis(
                tracks["transient_exhausted"],
                embedded=False,
                embedding_error="CUDA out of memory",
                embedding_failed_at=long_ago,
                embedding_failure_reason=FailureReason.ERROR.value,
                embedding_attempts=lifecycle.MAX_ATTEMPTS,
            ),
        ]
    )
    await db.commit()
    return tracks


@pytest.mark.asyncio
async def test_nothing_remains_on_the_nas_state(async_db):
    """The counts the sync loop exits on. Before ADR-0172 they were 3 and 3 here, for ever."""
    await _seed_the_nas(async_db)
    assert await lifecycle.features_remaining(async_db) == 0
    assert await lifecycle.embeddings_remaining(async_db) == 0


@pytest.mark.asyncio
async def test_what_remains_is_exactly_what_the_queue_takes(async_db, global_engine_released):
    """Point 6: the count and the queue use one definition, so they cannot disagree."""
    tracks = await _seed_the_nas(async_db)
    long_ago = utcnow() - timedelta(hours=25)
    fresh = _track()
    retry = _track()
    async_db.add_all([fresh, retry])
    await async_db.flush()
    async_db.add(
        _analysis(
            retry,
            embedded=False,
            embedding_failed_at=long_ago,
            embedding_failure_reason=FailureReason.ERROR.value,
            embedding_attempts=1,
        )
    )
    await async_db.commit()

    assert await lifecycle.features_remaining(async_db) == 1
    assert await lifecycle.embeddings_remaining(async_db) == 1

    manager = MagicMock()
    manager.run_analysis = AsyncMock()
    clap = MagicMock()
    clap.is_clap_embeddings_enabled.return_value = (True, "enabled")
    with (
        patch("app.services.background.get_background_manager", return_value=manager),
        patch("app.services.app_settings.get_app_settings_service", return_value=clap),
        patch("app.services.analysis._models_missing", return_value=[]),
    ):
        from app.services.tasks import queue_tracks_for_embeddings, queue_tracks_for_features

        assert await queue_tracks_for_features(limit=100) == 1
        assert await queue_tracks_for_embeddings(limit=100) == 1

    queued = {(call.args[0], call.kwargs.get("phase")) for call in manager.run_analysis.call_args_list}
    assert queued == {(str(fresh.id), "features"), (str(retry.id), "embedding")}
    assert str(tracks["undecodable"].id) not in {q[0] for q in queued}


@pytest.mark.asyncio
async def test_a_changed_file_is_tried_again(async_db):
    """A permanent failure lasts until the file changes: the scanner deletes the analysis row, and
    the failure goes with it."""
    tracks = await _seed_the_nas(async_db)
    from sqlalchemy import delete

    await async_db.execute(
        delete(TrackAnalysis).where(TrackAnalysis.track_id == tracks["undecodable"].id)
    )
    await async_db.commit()
    assert await lifecycle.features_remaining(async_db) == 1


def test_recording_a_failure_counts_and_classifies(monkeypatch):
    """`_record_embedding_failure` is what the worker calls; the reason and count are what stop the
    retries."""
    from app.services.tasks import analysis_pipeline

    row = MagicMock(embedding_attempts=0)
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    session.execute.return_value.scalar_one_or_none.return_value = row
    monkeypatch.setattr("app.db.session.sync_session_maker", lambda: session)

    analysis_pipeline._record_embedding_failure(str(uuid4()), UNDECODABLE)
    assert row.embedding_failure_reason == "undecodable"
    assert row.embedding_attempts == 1
    analysis_pipeline._record_embedding_failure(str(uuid4()), "CUDA out of memory")
    assert row.embedding_failure_reason == "error"
    assert row.embedding_attempts == 2


# ── Point 5: a no-op sync over that state reaches idle without the guard ────────────────────────


@pytest.mark.asyncio
async def test_a_sync_with_nothing_new_finishes_without_the_churn_guard(
    async_db, global_engine_released, tmp_path, monkeypatch, caplog
):
    """The real `run_library_sync`, with only the file scan stubbed. Before ADR-0172 this took two
    minutes per phase and ended in `queue_churn_limit_exceeded`; now it finishes at once."""
    from app.config import settings
    from app.services.tasks import library_sync

    await _seed_the_nas(async_db)
    (tmp_path / "a.mp3").write_bytes(b"")
    monkeypatch.setattr(type(settings), "music_library_paths", property(lambda self: [tmp_path]))
    monkeypatch.setattr(library_sync, "_initial_import_pending", AsyncMock(return_value=False))
    monkeypatch.setattr(library_sync, "_get_scan_executor", lambda: None)
    monkeypatch.setattr(
        library_sync,
        "_run_scan_in_process",
        lambda *a, **k: {"status": "success", "new": 0, "updated": 0, "unchanged": 7},
    )
    caps = {"embeddings_enabled": True, "features_enabled": True}
    manager = MagicMock()
    manager.run_analysis = AsyncMock()
    clap = MagicMock()
    clap.is_clap_embeddings_enabled.return_value = (True, "enabled")

    with (
        patch("app.services.analysis.get_analysis_capabilities", return_value=caps),
        patch("app.services.background.get_background_manager", return_value=manager),
        patch("app.services.app_settings.get_app_settings_service", return_value=clap),
        patch("app.services.analysis._models_missing", return_value=[]),
        caplog.at_level(logging.WARNING, logger="app.services.tasks.library_sync"),
    ):
        result = await asyncio.wait_for(library_sync.run_library_sync(), timeout=60)

    assert result["status"] == "success", result
    assert not [r for r in caplog.records if "forced exit" in r.getMessage()]
    manager.run_analysis.assert_not_called()
