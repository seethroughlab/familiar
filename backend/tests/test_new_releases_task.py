"""Fault isolation in the discovery batch (ADR-0099 point 9).

One artist's failure must cost one artist. Before `_check_one_artist_isolated`
existed, the only `try` in the path wrapped the MusicBrainz call, so a database
error raised while *saving* a release escaped to the run's outer handler and
ended the batch — which is how one duplicated row stopped nineteen consecutive
nights of discovery.
"""

from typing import Any

import pytest

from app.services.tasks.new_releases import (
    _check_artist_against_musicbrainz,
    _check_one_artist_isolated,
)


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


# ---------------------------------------------------------------------------
# The backlog must actually drain (ADR-0101 follow-through)
# ---------------------------------------------------------------------------


class _RecordingService:
    """Captures update_artist_cache calls without touching a database."""

    def __init__(self) -> None:
        self.cached: list[tuple[str, str | None]] = []

    async def save_discovered_release(self, **kwargs: Any):
        return None

    async def update_artist_cache(self, *, artist_normalized: str, musicbrainz_id=None):
        self.cached.append((artist_normalized, musicbrainz_id))


@pytest.mark.asyncio
async def test_an_artist_musicbrainz_cannot_match_is_still_recorded_as_checked(
    monkeypatch,
):
    """Otherwise the never-checked reserve re-picks it forever.

    Found on the live library: with unplayed artists admitted to the rotation, a
    20-artist batch touched six cache rows and inserted none, while 2,937 artists
    had no row at all. Artists MusicBrainz has no entry for were being re-selected
    every batch and displacing artists never looked at even once — so widening the
    pool drained nothing.

    "Asked, nothing matched" is recorded with a NULL musicbrainz id: the artist
    leaves the backlog and rejoins the ordinary staleness rotation.
    """
    monkeypatch.setattr(
        "app.services.metadata.musicbrainz.search_artist", lambda *a, **k: None
    )
    service = _RecordingService()
    stats: dict[str, Any] = {"releases_found": 0, "releases_new": 0, "musicbrainz_queries": 0}

    await _check_artist_against_musicbrainz(
        service=service,
        artist_name="Obscure Local Band",
        normalized="obscure local band",
        mb_artist_id=None,
        days_back=90,
        stats=stats,
    )

    assert service.cached == [("obscure local band", None)]
    assert stats["artists_unmatched"] == 1


@pytest.mark.asyncio
async def test_an_artist_whose_lookup_errored_is_not_recorded(monkeypatch):
    """The other half: a failed call must be retried, not written off.

    Distinguishing these is the whole point. Recording a network blip as "checked"
    would silently drop the artist for a full rotation.
    """
    def _boom(*a: Any, **k: Any):
        raise ConnectionError("musicbrainz unreachable")

    monkeypatch.setattr("app.services.metadata.musicbrainz.search_artist", _boom)
    service = _RecordingService()
    stats: dict[str, Any] = {"releases_found": 0, "releases_new": 0, "musicbrainz_queries": 0}

    await _check_artist_against_musicbrainz(
        service=service,
        artist_name="Unreachable Artist",
        normalized="unreachable artist",
        mb_artist_id=None,
        days_back=90,
        stats=stats,
    )

    assert service.cached == [], "a failed lookup leaves no record, so it retries"
    assert stats.get("artists_unmatched", 0) == 0
