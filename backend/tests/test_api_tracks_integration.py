"""Integration tests for tracks API endpoints with real DB data.

These tests insert tracks via the async_db fixture, then use the sync TestClient
to hit API endpoints. Both share the same DATABASE_URL so committed data is visible.
"""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models import PlayEvent, ProfilePlayHistory
from tests.factories import (
    insert_test_profile,
    insert_test_track,
)


@pytest.fixture
def headers():
    """Default headers (no profile)."""
    return {}


def _patch_lyrics_service(monkeypatch, *, result):
    """Patch the lyrics service so the endpoint never hits the network.

    Returns a list that records each ``search()`` call so tests can assert
    whether LRCLIB was consulted (vs. served from the DB cache).
    """
    calls: list[dict] = []

    class _FakeLyricsService:
        async def search(self, **kwargs):
            calls.append(kwargs)
            return result

    monkeypatch.setattr(
        "app.services.lyrics.get_lyrics_service", lambda: _FakeLyricsService()
    )
    return calls


# ---------------------------------------------------------------------------
# Track IDs & batch
# ---------------------------------------------------------------------------


class TestListTrackIds:
    @pytest.mark.asyncio
    async def test_returns_ids(self, async_db, client):
        t1 = await insert_test_track(async_db, title="Alpha")
        t2 = await insert_test_track(async_db, title="Beta")
        await async_db.commit()

        resp = client.get("/api/v1/tracks/ids")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2
        returned_ids = data["ids"]
        assert str(t1.id) in returned_ids
        assert str(t2.id) in returned_ids

    @pytest.mark.asyncio
    async def test_filter_by_artist(self, async_db, client):
        await insert_test_track(async_db, artist="Radiohead", title="A")
        await insert_test_track(async_db, artist="Bjork", title="B")
        await async_db.commit()

        resp = client.get("/api/v1/tracks/ids", params={"artist": "Radiohead"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_filter_by_genre(self, async_db, client):
        await insert_test_track(async_db, genre="Jazz", title="C")
        await insert_test_track(async_db, genre="Metal", title="D")
        await async_db.commit()

        resp = client.get("/api/v1/tracks/ids", params={"genre": "Jazz"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_filter_by_year_range(self, async_db, client):
        await insert_test_track(async_db, year=1990, title="E")
        await insert_test_track(async_db, year=2020, title="F")
        await async_db.commit()

        resp = client.get("/api/v1/tracks/ids", params={"year_from": 2000, "year_to": 2025})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1


class TestBatchTracks:
    @pytest.mark.asyncio
    async def test_batch_returns_tracks(self, async_db, client):
        t1 = await insert_test_track(async_db, title="Track1")
        t2 = await insert_test_track(async_db, title="Track2")
        await async_db.commit()

        resp = client.post(
            "/api/v1/tracks/batch",
            json={"ids": [str(t1.id), str(t2.id)]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        titles = {t["title"] for t in data}
        assert "Track1" in titles
        assert "Track2" in titles

    @pytest.mark.asyncio
    async def test_batch_max_50(self, async_db, client):
        ids = [str(uuid4()) for _ in range(51)]
        resp = client.post("/api/v1/tracks/batch", json={"ids": ids})
        assert resp.status_code == 400  # Over limit

    @pytest.mark.asyncio
    async def test_batch_nonexistent_ids(self, async_db, client):
        resp = client.post(
            "/api/v1/tracks/batch",
            json={"ids": [str(uuid4())]},
        )
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# Metadata CRUD
# ---------------------------------------------------------------------------


class TestMetadata:
    @pytest.mark.asyncio
    async def test_get_metadata(self, async_db, client):
        t = await insert_test_track(async_db, title="GetMeta", artist="TestArtist", genre="Rock")
        await async_db.commit()

        resp = client.get(f"/api/v1/tracks/{t.id}/metadata")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "GetMeta"
        assert data["artist"] == "TestArtist"

    @pytest.mark.asyncio
    async def test_patch_metadata(self, async_db, client):
        t = await insert_test_track(async_db, title="OldTitle", genre="Pop")
        await async_db.commit()

        resp = client.patch(
            f"/api/v1/tracks/{t.id}/metadata",
            json={"title": "NewTitle"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "NewTitle"

    @pytest.mark.asyncio
    async def test_patch_metadata_not_found(self, async_db, client):
        resp = client.patch(
            f"/api/v1/tracks/{uuid4()}/metadata",
            json={"title": "NewTitle"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_bulk_common_values(self, async_db, client):
        t1 = await insert_test_track(async_db, artist="SharedArtist", album="AlbumA")
        t2 = await insert_test_track(async_db, artist="SharedArtist", album="AlbumB")
        await async_db.commit()

        resp = client.post(
            "/api/v1/tracks/bulk/common-values",
            json={"track_ids": [str(t1.id), str(t2.id)]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["artist"] == "SharedArtist"
        # Albums differ so common_values should be None for album
        assert data["album"] is None


# ---------------------------------------------------------------------------
# Play recording
# ---------------------------------------------------------------------------


class TestPlayRecording:
    @pytest.mark.asyncio
    async def test_record_play(self, async_db, client):
        t = await insert_test_track(async_db, title="Played")
        profile = await insert_test_profile(async_db)
        await async_db.commit()

        headers = {"X-Profile-ID": str(profile.id)}
        resp = client.post(
            f"/api/v1/tracks/{t.id}/played",
            json={"duration_seconds": 120},
            headers=headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_play_increments_count(self, async_db, client):
        t = await insert_test_track(async_db, title="Incremental")
        profile = await insert_test_profile(async_db)
        await async_db.commit()

        headers = {"X-Profile-ID": str(profile.id)}
        client.post(f"/api/v1/tracks/{t.id}/played", json={"duration_seconds": 60}, headers=headers)
        client.post(f"/api/v1/tracks/{t.id}/played", json={"duration_seconds": 60}, headers=headers)

        # Use batch endpoint which includes play_count when profile header is present
        resp = client.post(
            "/api/v1/tracks/batch",
            json={"ids": [str(t.id)]},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        play_count = data[0].get("play_count")
        assert play_count is not None and play_count >= 2

    @pytest.mark.asyncio
    async def test_play_stats(self, async_db, client):
        t = await insert_test_track(async_db, title="PlayStatsTrack")
        profile = await insert_test_profile(async_db)
        await async_db.commit()

        headers = {"X-Profile-ID": str(profile.id)}
        client.post(f"/api/v1/tracks/{t.id}/played", json={"duration_seconds": 60}, headers=headers)

        resp = client.get("/api/v1/tracks/stats/plays", headers=headers)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Listening events (ADR-0004)
# ---------------------------------------------------------------------------


async def _play_events_for(db, profile_id, track_id) -> list[PlayEvent]:
    """Read back the PlayEvent rows the API wrote, oldest first."""
    result = await db.execute(
        select(PlayEvent)
        .where(PlayEvent.profile_id == profile_id, PlayEvent.track_id == track_id)
        .order_by(PlayEvent.started_at)
    )
    return list(result.scalars().all())


async def _play_count_for(db, profile_id, track_id) -> int | None:
    result = await db.execute(
        select(ProfilePlayHistory.play_count).where(
            ProfilePlayHistory.profile_id == profile_id,
            ProfilePlayHistory.track_id == track_id,
        )
    )
    return result.scalar_one_or_none()


class TestListeningEvents:
    @pytest.mark.asyncio
    async def test_played_writes_both_aggregate_and_event(self, async_db, client):
        t = await insert_test_track(async_db, title="EventPlayed")
        profile = await insert_test_profile(async_db)
        await async_db.commit()

        headers = {"X-Profile-ID": str(profile.id)}
        resp = client.post(
            f"/api/v1/tracks/{t.id}/played",
            json={"duration_seconds": 190, "track_duration": 200, "context": "playlist"},
            headers=headers,
        )
        assert resp.status_code == 200

        assert await _play_count_for(async_db, profile.id, t.id) == 1

        events = await _play_events_for(async_db, profile.id, t.id)
        assert len(events) == 1
        assert events[0].outcome == "completed"
        assert events[0].context == "playlist"
        assert events[0].played_seconds == 190

    @pytest.mark.asyncio
    async def test_played_contract_unchanged_for_legacy_client(self, async_db, client):
        """A client sending only duration_seconds must keep working exactly as before."""
        t = await insert_test_track(async_db, title="EventLegacy")
        profile = await insert_test_profile(async_db)
        await async_db.commit()

        headers = {"X-Profile-ID": str(profile.id)}
        resp = client.post(
            f"/api/v1/tracks/{t.id}/played",
            json={"duration_seconds": 60},
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == {"track_id", "play_count", "total_play_seconds"}
        assert body["play_count"] == 1
        assert body["total_play_seconds"] == 60

    @pytest.mark.asyncio
    async def test_skip_records_event_without_touching_aggregate(self, async_db, client):
        """The core ADR-0004 promise: skips must not inflate ProfilePlayHistory."""
        t = await insert_test_track(async_db, title="EventSkipped")
        profile = await insert_test_profile(async_db)
        await async_db.commit()

        headers = {"X-Profile-ID": str(profile.id)}
        resp = client.post(
            f"/api/v1/tracks/{t.id}/skipped",
            json={"played_seconds": 5, "track_duration": 200},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "skipped"

        # No aggregate row at all — a skip is not a play
        assert await _play_count_for(async_db, profile.id, t.id) is None

        events = await _play_events_for(async_db, profile.id, t.id)
        assert len(events) == 1
        assert events[0].outcome == "skipped"
        assert events[0].completion_ratio == pytest.approx(0.025)

    @pytest.mark.asyncio
    async def test_skip_near_end_counts_as_completed(self, async_db, client):
        """Pressing next at 95% is a completion, not a rejection of the track."""
        t = await insert_test_track(async_db, title="EventNearEnd")
        profile = await insert_test_profile(async_db)
        await async_db.commit()

        headers = {"X-Profile-ID": str(profile.id)}
        resp = client.post(
            f"/api/v1/tracks/{t.id}/skipped",
            json={"played_seconds": 190, "track_duration": 200},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "completed"

    @pytest.mark.asyncio
    async def test_short_track_played_fully_is_not_a_skip(self, async_db, client):
        """A 20s interlude played end to end must not look like a skip."""
        t = await insert_test_track(async_db, title="EventShort")
        profile = await insert_test_profile(async_db)
        await async_db.commit()

        headers = {"X-Profile-ID": str(profile.id)}
        resp = client.post(
            f"/api/v1/tracks/{t.id}/skipped",
            json={"played_seconds": 20, "track_duration": 20},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "completed"

    @pytest.mark.asyncio
    async def test_natural_stop_is_completed_despite_crossfade_shortfall(
        self, async_db, client
    ):
        """Crossfade advances early, so ratio alone would misread a full play."""
        t = await insert_test_track(async_db, title="EventCrossfade")
        profile = await insert_test_profile(async_db)
        await async_db.commit()

        headers = {"X-Profile-ID": str(profile.id)}
        resp = client.post(
            f"/api/v1/tracks/{t.id}/skipped",
            json={"played_seconds": 180, "track_duration": 200, "reason": "natural"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "completed"

    @pytest.mark.asyncio
    async def test_playback_error_is_errored_not_skipped(self, async_db, client):
        """A broken file must never become a negative taste signal (ADR-0004 point 6)."""
        t = await insert_test_track(async_db, title="EventErrored")
        profile = await insert_test_profile(async_db)
        await async_db.commit()

        headers = {"X-Profile-ID": str(profile.id)}
        resp = client.post(
            f"/api/v1/tracks/{t.id}/skipped",
            json={"played_seconds": 0, "track_duration": 200, "reason": "error"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "errored"

        events = await _play_events_for(async_db, profile.id, t.id)
        assert [e.outcome for e in events] == ["errored"]

    @pytest.mark.asyncio
    async def test_rejection_is_distinguishable_from_a_skip(self, async_db, client):
        t = await insert_test_track(async_db, title="EventRejected")
        seed = await insert_test_track(async_db, title="EventRejectedSeed")
        profile = await insert_test_profile(async_db)
        await async_db.commit()

        headers = {"X-Profile-ID": str(profile.id)}
        resp = client.post(
            f"/api/v1/tracks/{t.id}/rejected",
            json={
                "played_seconds": 12,
                "track_duration": 200,
                "context": "radio",
                "source_track_id": str(seed.id),
            },
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "rejected"

        assert await _play_count_for(async_db, profile.id, t.id) is None

        events = await _play_events_for(async_db, profile.id, t.id)
        assert len(events) == 1
        assert events[0].outcome == "rejected"
        assert events[0].context == "radio"
        assert events[0].source_track_id == seed.id

    @pytest.mark.asyncio
    async def test_rejection_stays_rejected_even_when_nearly_complete(
        self, async_db, client
    ):
        """An explicit thumbs-down is never downgraded by the completion heuristic."""
        t = await insert_test_track(async_db, title="EventRejectedLate")
        profile = await insert_test_profile(async_db)
        await async_db.commit()

        headers = {"X-Profile-ID": str(profile.id)}
        resp = client.post(
            f"/api/v1/tracks/{t.id}/rejected",
            json={"played_seconds": 199, "track_duration": 200},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "rejected"

    @pytest.mark.asyncio
    async def test_unknown_duration_does_not_look_like_completion(self, async_db, client):
        t = await insert_test_track(async_db, title="EventNoDuration")
        profile = await insert_test_profile(async_db)
        await async_db.commit()

        headers = {"X-Profile-ID": str(profile.id)}
        resp = client.post(
            f"/api/v1/tracks/{t.id}/skipped",
            json={"played_seconds": 30},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "skipped"
        assert resp.json()["completion_ratio"] == 0.0

    @pytest.mark.asyncio
    async def test_event_endpoints_reject_unknown_track(self, async_db, client):
        profile = await insert_test_profile(async_db)
        await async_db.commit()

        headers = {"X-Profile-ID": str(profile.id)}
        missing = uuid4()
        for path in ("skipped", "rejected"):
            resp = client.post(f"/api/v1/tracks/{missing}/{path}", json={}, headers=headers)
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_event_endpoints_accept_empty_body(self, async_db, client):
        t = await insert_test_track(async_db, title="EventEmptyBody")
        profile = await insert_test_profile(async_db)
        await async_db.commit()

        headers = {"X-Profile-ID": str(profile.id)}
        resp = client.post(f"/api/v1/tracks/{t.id}/skipped", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "skipped"

    @pytest.mark.asyncio
    async def test_invalid_context_is_rejected(self, async_db, client):
        t = await insert_test_track(async_db, title="EventBadContext")
        profile = await insert_test_profile(async_db)
        await async_db.commit()

        headers = {"X-Profile-ID": str(profile.id)}
        resp = client.post(
            f"/api/v1/tracks/{t.id}/skipped",
            json={"context": "not-a-real-context"},
            headers=headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Stream & artwork
# ---------------------------------------------------------------------------


class TestStreamAndArtwork:
    @pytest.mark.asyncio
    async def test_stream_file_missing(self, async_db, client):
        t = await insert_test_track(async_db, title="NoFile", file_path="/nonexistent/file.mp3")
        await async_db.commit()

        resp = client.get(f"/api/v1/tracks/{t.id}/stream")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_artwork_fallback(self, async_db, client):
        t = await insert_test_track(async_db, title="NoArt", album="Unknown")
        await async_db.commit()

        resp = client.get(f"/api/v1/tracks/{t.id}/artwork")
        assert resp.status_code in (200, 404)  # 404 if no artwork, 200 if fallback

    @pytest.mark.asyncio
    async def test_lyrics_miss_returns_empty_200(self, async_db, client, monkeypatch):
        """A genuine miss returns an empty 200 (not a 404) so the client can
        distinguish 'no lyrics' from a real error without console noise."""
        t = await insert_test_track(async_db, title="NoLyrics", artist="NoArtist")
        await async_db.commit()

        calls = _patch_lyrics_service(monkeypatch, result=None)

        resp = client.get(f"/api/v1/tracks/{t.id}/lyrics")
        assert resp.status_code == 200
        body = resp.json()
        assert body["synced"] is False
        assert body["lines"] == []
        assert len(calls) == 1  # LRCLIB was consulted

    @pytest.mark.asyncio
    async def test_lyrics_cached_in_db_avoids_lrclib(self, async_db, client, monkeypatch):
        """Once synced lyrics are cached on the track, the endpoint serves them
        without calling LRCLIB again."""
        t = await insert_test_track(async_db, title="Cached", artist="Band")
        t.synced_lyrics = {
            "synced": True,
            "lines": [{"time": 0.0, "text": "hello"}, {"time": 1.5, "text": "world"}],
            "plain_text": "hello\nworld",
            "source": "lrclib",
        }
        await async_db.commit()

        calls = _patch_lyrics_service(monkeypatch, result=None)

        resp = client.get(f"/api/v1/tracks/{t.id}/lyrics")
        assert resp.status_code == 200
        body = resp.json()
        assert body["synced"] is True
        assert body["lines"] == [
            {"time": 0.0, "text": "hello"},
            {"time": 1.5, "text": "world"},
        ]
        assert calls == []  # cache hit — LRCLIB was NOT consulted

    @pytest.mark.asyncio
    async def test_lyrics_fetched_then_persisted(self, async_db, client, monkeypatch):
        """First request fetches from LRCLIB and persists; a second request is a
        cache hit that no longer consults the network."""
        from app.services.lyrics import LyricLine, LyricsResult

        t = await insert_test_track(async_db, title="Fresh", artist="Singer")
        await async_db.commit()

        result = LyricsResult(
            synced=True,
            lines=[LyricLine(time=0.0, text="la"), LyricLine(time=2.0, text="la la")],
            plain_text="la\nla la",
            source="lrclib",
        )
        calls = _patch_lyrics_service(monkeypatch, result=result)

        resp1 = client.get(f"/api/v1/tracks/{t.id}/lyrics")
        assert resp1.status_code == 200
        assert resp1.json()["synced"] is True
        assert len(calls) == 1  # first request hit LRCLIB

        # Second request should be served from the persisted cache.
        resp2 = client.get(f"/api/v1/tracks/{t.id}/lyrics")
        assert resp2.status_code == 200
        assert resp2.json()["lines"] == [
            {"time": 0.0, "text": "la"},
            {"time": 2.0, "text": "la la"},
        ]
        assert len(calls) == 1  # still 1 — second request was a cache hit


# ---------------------------------------------------------------------------
# Similarity
# ---------------------------------------------------------------------------


class TestSimilarity:
    @pytest.mark.asyncio
    async def test_similar_no_embedding(self, async_db, client):
        t = await insert_test_track(async_db, title="NoEmbed")
        await async_db.commit()

        resp = client.get(f"/api/v1/tracks/{t.id}/similar")
        assert resp.status_code in (200, 404)

    @pytest.mark.asyncio
    async def test_discover_structure(self, async_db, client):
        t = await insert_test_track(async_db, title="DiscoverMe")
        await async_db.commit()

        resp = client.get(f"/api/v1/tracks/{t.id}/discover")
        assert resp.status_code == 200
        data = resp.json()
        assert "by_same_artist" in data or "similar" in data or isinstance(data, dict)


# ---------------------------------------------------------------------------
# Track list (paginated)
# ---------------------------------------------------------------------------


class TestTrackList:
    @pytest.mark.asyncio
    async def test_paginated_list(self, async_db, client):
        for i in range(5):
            await insert_test_track(async_db, title=f"ListTrack{i}", artist=f"Artist{i}")
        await async_db.commit()

        resp = client.get("/api/v1/tracks", params={"page": 1, "page_size": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) <= 3
        assert data["total"] >= 5

    @pytest.mark.asyncio
    async def test_search_filter(self, async_db, client):
        await insert_test_track(async_db, title="UniqueSearchTerm123")
        await async_db.commit()

        resp = client.get("/api/v1/tracks", params={"search": "UniqueSearchTerm123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_get_single_track(self, async_db, client):
        t = await insert_test_track(async_db, title="SingleGet")
        await async_db.commit()

        resp = client.get(f"/api/v1/tracks/{t.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "SingleGet"

    @pytest.mark.asyncio
    async def test_get_track_not_found(self, async_db, client):
        resp = client.get(f"/api/v1/tracks/{uuid4()}")
        assert resp.status_code == 404
