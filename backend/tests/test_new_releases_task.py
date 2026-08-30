"""Fault isolation in the discovery batch (ADR-0099 point 9).

One artist's failure must cost one artist. Before `_check_one_artist_isolated`
existed, the only `try` in the path wrapped the MusicBrainz call, so a database
error raised while *saving* a release escaped to the run's outer handler and
ended the batch — which is how one duplicated row stopped nineteen consecutive
nights of discovery.
"""

from typing import Any

import pytest

from app.services.tasks.new_releases import _check_one_artist_isolated


class _RecordingSession:
    """Minimal stand-in that records commit/rollback ordering."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def commit(self) -> None:
        self.calls.append("commit")

    async def rollback(self) -> None:
        self.calls.append("rollback")


def _stats() -> dict[str, Any]:
    return {
        "artists_checked": 0,
        "releases_found": 0,
        "releases_new": 0,
        "musicbrainz_queries": 0,
        "artists_failed": 0,
    }


@pytest.mark.asyncio
async def test_a_failing_artist_is_contained_and_rolled_back(monkeypatch):
    """A raise is caught, counted, and the session is rolled back.

    The rollback is the load-bearing half: catching without it leaves the
    AsyncSession in a failed transaction, so every later artist raises
    PendingRollbackError and the batch is just as dead.
    """
    async def _boom(**kwargs: Any) -> None:
        raise RuntimeError("Multiple rows were found when one or none was required")

    monkeypatch.setattr(
        "app.services.tasks.new_releases._check_artist_against_musicbrainz", _boom
    )
    monkeypatch.setattr(
        "app.services.tasks.common._record_task_failure", lambda *a, **k: None
    )

    db = _RecordingSession()
    stats = _stats()

    ok = await _check_one_artist_isolated(
        db=db,
        service=object(),
        artist_name="Bruised Sky",
        normalized="bruised sky",
        mb_artist_id=None,
        days_back=90,
        stats=stats,
    )

    assert ok is False
    assert stats["artists_failed"] == 1
    assert db.calls == ["rollback"], "must roll back, and must not commit"


@pytest.mark.asyncio
async def test_a_successful_artist_commits_on_its_own(monkeypatch):
    """Commit is per artist, so a later rollback cannot discard earlier work."""
    async def _ok(**kwargs: Any) -> None:
        kwargs["stats"]["releases_new"] += 1

    monkeypatch.setattr(
        "app.services.tasks.new_releases._check_artist_against_musicbrainz", _ok
    )

    db = _RecordingSession()
    stats = _stats()

    ok = await _check_one_artist_isolated(
        db=db,
        service=object(),
        artist_name="Boards of Canada",
        normalized="boards of canada",
        mb_artist_id=None,
        days_back=90,
        stats=stats,
    )

    assert ok is True
    assert stats["artists_failed"] == 0
    assert stats["releases_new"] == 1
    assert db.calls == ["commit"]


@pytest.mark.asyncio
async def test_one_failing_artist_does_not_abort_the_batch(monkeypatch):
    """The whole point: artist 2 fails, artists 1 and 3 still get checked.

    Against the pre-ADR-0099 code the raise on artist 2 propagated out of the
    loop and artist 3 was never reached.
    """
    seen: list[str] = []

    async def _fail_on_second(**kwargs: Any) -> None:
        name = kwargs["artist_name"]
        seen.append(name)
        if name == "artist-2":
            raise RuntimeError("boom")
        kwargs["stats"]["releases_new"] += 1

    monkeypatch.setattr(
        "app.services.tasks.new_releases._check_artist_against_musicbrainz",
        _fail_on_second,
    )
    monkeypatch.setattr(
        "app.services.tasks.common._record_task_failure", lambda *a, **k: None
    )

    db = _RecordingSession()
    stats = _stats()

    for name in ("artist-1", "artist-2", "artist-3"):
        stats["artists_checked"] += 1
        await _check_one_artist_isolated(
            db=db,
            service=object(),
            artist_name=name,
            normalized=name,
            mb_artist_id=None,
            days_back=90,
            stats=stats,
        )

    assert seen == ["artist-1", "artist-2", "artist-3"]
    assert stats["artists_checked"] == 3
    assert stats["artists_failed"] == 1
    assert stats["releases_new"] == 2
    assert db.calls == ["commit", "rollback", "commit"]
