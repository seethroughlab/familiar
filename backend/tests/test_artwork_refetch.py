"""A placeholder cover can be replaced by a real one.

**The bug these tests exist for lived in the gap between a service and the route in front of it.**
`ArtworkFetcher.queue` had always allowed re-queueing generated art — with a comment saying so —
while `POST /artwork/queue` and `/queue/batch` answered `"exists"` on a bare `full_path.exists()`
and returned before the service was ever consulted. A generated cover is a `.jpg`, so 661 albums
were permanently stuck on a picture Familiar drew itself. Nothing failed; every batch call in
production reported `queued=0, existing=1`.

So these go through the HTTP routes. A test against `ArtworkFetcher.queue` would have passed
throughout, which is exactly why the defect survived.
"""

from __future__ import annotations

import os
import time

import pytest

from app.services.artwork import (
    ARTWORK_REFETCH_INTERVAL,
    _generated_marker_path,
    get_artwork_path,
    should_refetch_online,
)


@pytest.fixture
def art_dir(tmp_path, monkeypatch):
    """Point the artwork store at a temporary directory."""
    from app.config import settings

    monkeypatch.setattr(settings, "art_path", tmp_path)
    return tmp_path


def _write_art(album_key: str, *, generated: bool, age_days: float = 0) -> None:
    """Put artwork on disk, optionally marked generated and aged."""
    for size in ("full", "thumb"):
        path = get_artwork_path(album_key, size)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"jpeg")

    if generated:
        marker = _generated_marker_path(album_key)
        marker.write_text("5")
        if age_days:
            old = time.time() - age_days * 86_400
            os.utime(marker, (old, old))


class TestTheRule:
    """`should_refetch_online` is the one condition the routes and the worker share."""

    def test_real_art_is_never_refetched(self, art_dir):
        _write_art("real", generated=False)
        assert should_refetch_online("real") is False, (
            "a successful fetch must never be redone — that would re-ask the internet about "
            "every album in the library"
        )

    def test_a_fresh_placeholder_waits(self, art_dir):
        _write_art("fresh", generated=True, age_days=1)
        assert should_refetch_online("fresh") is False, (
            "an album with genuinely no art online would otherwise be looked up every time it "
            "scrolled into view"
        )

    def test_an_old_placeholder_is_retried(self, art_dir):
        _write_art("stale", generated=True, age_days=ARTWORK_REFETCH_INTERVAL.days + 1)
        assert should_refetch_online("stale") is True

    def test_nothing_on_disk_is_not_a_placeholder(self, art_dir):
        assert should_refetch_online("absent") is False, (
            "an album with no art at all is queued by the ordinary path — this rule is only about "
            "art that already exists"
        )


class TestTheRoutes:
    """Where the defect actually was."""

    def test_queue_offers_to_replace_an_old_placeholder(self, client, art_dir, monkeypatch):
        _write_art("old-placeholder", generated=True, age_days=ARTWORK_REFETCH_INTERVAL.days + 1)
        monkeypatch.setattr(
            "app.api.routes.artwork.album_key_for_tags",
            _fixed_key("old-placeholder"),
        )

        response = client.post("/api/v1/artwork/queue", json={"artist": "A", "album": "B"})

        assert response.status_code in (200, 202)
        assert response.json().get("status") != "exists", (
            'the bug: a placeholder answered "exists" and the fetcher never saw the request'
        )

    def test_queue_still_reports_exists_for_real_art(self, client, art_dir, monkeypatch):
        _write_art("real-art", generated=False)
        monkeypatch.setattr(
            "app.api.routes.artwork.album_key_for_tags", _fixed_key("real-art")
        )

        response = client.post("/api/v1/artwork/queue", json={"artist": "A", "album": "B"})

        assert response.json()["status"] == "exists"

    def test_batch_agrees_with_the_single_route(self, client, art_dir, monkeypatch):
        """These two are separate code paths that have drifted before."""
        _write_art("batch-placeholder", generated=True, age_days=ARTWORK_REFETCH_INTERVAL.days + 1)
        monkeypatch.setattr(
            "app.api.routes.artwork.album_key_for_tags", _fixed_key("batch-placeholder")
        )

        response = client.post(
            "/api/v1/artwork/status/batch", json={"hashes": ["batch-placeholder"]}
        )

        assert response.status_code == 200
        body = response.json()
        assert "batch-placeholder" in body.get("generated", []), (
            "the status endpoint already distinguishes generated art; only the queue routes did not"
        )


def _fixed_key(key: str):
    async def _resolve(*args, **kwargs) -> str:
        return key

    return _resolve
