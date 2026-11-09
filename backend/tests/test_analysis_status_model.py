"""ADR-0172 point 6: one status model, and every endpoint reports it.

Before it, four places defined "pending" four ways: `/health/system` and `/health/workers` as every
track minus current analyses, `/library/stats` as active tracks minus active analyses (clamped, after
it went to -41), and `/library/analysis/status` as no current analysis and not failed in 24 hours.
On the NAS on 2026-09-17 two of them said 52 and 0. These tests seed one library and require every
endpoint to report the same numbers, and the states to add up.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from app.config import EMBEDDING_VERSION, FEATURES_VERSION, MELODIC_VERSION, MOOD_TAGS_VERSION
from app.db.models import Track, TrackAnalysis, TrackStatus
from app.services.analysis_lifecycle import MAX_ATTEMPTS, FailureReason, phase_counts
from app.utils.time import utcnow

UNDECODABLE = "Embedding extraction failed: could not decode /music/x.mp3: Unspecified internal error."


@pytest.fixture
async def global_engine_released():
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


def _analysis(track, *, embedded=True, detail=True, melodic=True, mood=True, **kw):
    # `analysis_detail` is left unset rather than None: None on a JSONB column is stored as JSON
    # `null`, which `IS NULL` does not match, while a real row without detail holds SQL NULL.
    if detail:
        kw["analysis_detail"] = {"sections": []}
    return TrackAnalysis(
        track_id=track.id,
        features_version=FEATURES_VERSION,
        embedding_version=EMBEDDING_VERSION if embedded else 0,
        embedding=[0.0] * 512 if embedded else None,
        melodic_version=MELODIC_VERSION if melodic else 0,
        mood_tags_version=MOOD_TAGS_VERSION if mood else 0,
        **kw,
    )


async def _seed(db) -> dict[str, Track]:
    """Every state of every phase that records one, plus tracks outside the library."""
    now = utcnow()
    t = {
        "done": _track(),
        "new": _track(),  # features queued; every later phase waiting
        "feature_failed": _track(analysis_failed_at=now, analysis_error="Feature extraction failed"),
        "embed_queued": _track(),
        "embed_retrying": _track(),
        "embed_retry_due": _track(),
        "embed_undecodable": _track(),
        "embed_exhausted": _track(),
        "embed_legacy_failure": _track(),
        "melodic_queued": _track(),
        "mood_queued": _track(),
        "skipped": _track(TrackStatus.SKIPPED),
        "pending_deletion": _track(TrackStatus.PENDING_DELETION),
    }
    db.add_all(t.values())
    await db.flush()
    db.add_all(
        [
            _analysis(t["done"]),
            _analysis(t["feature_failed"], embedded=False, detail=False, melodic=False, mood=False),
            _analysis(t["embed_queued"], embedded=False, mood=False),
            _analysis(
                t["embed_retrying"], embedded=False, mood=False,
                embedding_failed_at=now - timedelta(hours=1),
                embedding_failure_reason=FailureReason.ERROR.value, embedding_attempts=1,
            ),
            _analysis(
                t["embed_retry_due"], embedded=False, mood=False,
                embedding_failed_at=now - timedelta(hours=25),
                embedding_failure_reason=FailureReason.TIMEOUT.value, embedding_attempts=2,
            ),
            _analysis(
                t["embed_undecodable"], embedded=False, mood=False, embedding_error=UNDECODABLE,
                embedding_failed_at=now - timedelta(hours=25),
                embedding_failure_reason=FailureReason.UNDECODABLE.value, embedding_attempts=1,
            ),
            _analysis(
                t["embed_exhausted"], embedded=False, mood=False,
                embedding_failed_at=now - timedelta(hours=25),
                embedding_failure_reason=FailureReason.ERROR.value, embedding_attempts=MAX_ATTEMPTS,
            ),
            # Recorded before reason codes: NULL reason, recent. Must be retrying, not lost.
            _analysis(
                t["embed_legacy_failure"], embedded=False, mood=False,
                embedding_failed_at=now - timedelta(hours=2), embedding_attempts=0,
            ),
            _analysis(t["melodic_queued"], melodic=False),
            _analysis(t["mood_queued"], mood=False),
            # Outside the library: counted by nothing.
            _analysis(t["pending_deletion"], embedded=False, detail=False, melodic=False, mood=False),
        ]
    )
    await db.commit()
    return t


@pytest.mark.asyncio
async def test_the_states_partition_the_library(async_db):
    await _seed(async_db)
    counts = await phase_counts(async_db)
    for c in counts.values():
        assert c.complete + c.queued + c.retrying + c.failed + c.waiting == c.total, c
        assert c.total == 11, "skipped and pending_deletion tracks are not in the library"


@pytest.mark.asyncio
async def test_each_state_counts_what_it_says(async_db):
    await _seed(async_db)
    counts = await phase_counts(async_db)
    f, e = counts["features"], counts["embeddings"]
    assert (f.complete, f.queued, f.retrying, f.failed, f.waiting) == (9, 1, 0, 1, 0)
    # complete: done, melodic_queued, mood_queued. queued: embed_queued, embed_retry_due, and
    # feature_failed, since a feature failure marks the features version current and the embedding
    # queue takes it as before. retrying: embed_retrying, embed_legacy_failure. failed:
    # undecodable, exhausted. waiting: new.
    assert (e.complete, e.queued, e.retrying, e.failed, e.waiting) == (3, 3, 2, 2, 1)
    assert counts["melodic"].queued == 1
    assert counts["mood_tags"].queued == 1


@pytest.mark.asyncio
async def test_every_endpoint_reports_the_same_numbers(async_db, global_engine_released):
    from app.api.routes.health import get_worker_status, system_health_check
    from app.api.routes.library import get_library_stats
    from app.api.routes.library_analysis import get_analysis_status

    await _seed(async_db)
    counts = await phase_counts(async_db)
    features = counts["features"]

    workers = await get_worker_status(async_db)
    stats = await get_library_stats(async_db)
    status = await get_analysis_status(async_db)
    system = await system_health_check(async_db)
    analysis_service = next(s for s in system.services if s.name == "analysis")

    assert workers.analysis_progress.pending == features.pending
    assert stats.pending_analysis == features.pending
    assert status.pending == features.pending
    assert analysis_service.details["pending"] == features.pending
    assert workers.analysis_progress.analyzed == stats.analyzed_tracks == status.analyzed
    assert status.failed == features.failed

    by_phase = {q.phase: q for q in workers.phase_queues}
    for phase, q in by_phase.items():
        c = counts[phase]
        assert (q.completed, q.queued, q.retrying, q.failed, q.waiting, q.pending) == (
            c.complete, c.queued, c.retrying, c.failed, c.waiting, c.pending,
        ), phase
    assert stats.pending_melodic == counts["melodic"].pending
    assert stats.pending_mood_tags == counts["mood_tags"].pending
    assert stats.pending_backfill == counts["deep_backfill"].pending


@pytest.mark.asyncio
async def test_the_failures_list_names_each_failure_and_whether_it_is_final(async_db):
    from app.api.routes.library_analysis import get_analysis_failures

    t = await _seed(async_db)
    result = await get_analysis_failures(async_db, limit=100)
    by_track = {(f.track_id, f.phase): f for f in result.failures}

    assert result.total == 6
    assert by_track[(t["embed_undecodable"].id, "embeddings")].reason == "undecodable"
    assert by_track[(t["embed_undecodable"].id, "embeddings")].final
    assert by_track[(t["embed_exhausted"].id, "embeddings")].final
    assert not by_track[(t["embed_retrying"].id, "embeddings")].final
    assert by_track[(t["feature_failed"].id, "features")].final
    # Recorded before reason codes: classified from its message (none here, so "error").
    assert by_track[(t["embed_legacy_failure"].id, "embeddings")].reason == "error"
    assert not any(f.track_id == t["pending_deletion"].id for f in result.failures)
