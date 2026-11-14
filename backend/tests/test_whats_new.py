"""ADR-0179: each profile has a what's-new list, and the server records how far it has looked."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.models import (
    Artist,
    ArtistAlias,
    ExternalAlbumCache,
    ProfilePlayHistory,
    Track,
    TrackStatus,
)
from app.services.new_releases import DISCOVERY_CONTEXT
from app.utils.time import utcnow
from tests.conftest import make_profile_headers

URL = "/api/v1/library/discover/whats-new"


def _now() -> datetime:
    return utcnow().replace(tzinfo=None)


def _release(db, *, name: str, found: datetime, artist: str = "Tycho", **extra) -> ExternalAlbumCache:
    row = ExternalAlbumCache(
        release_id=f"rg-{uuid4().hex[:12]}",
        discovery_context=DISCOVERY_CONTEXT,
        artist_name=artist,
        artist_name_normalized=artist.lower(),
        release_name=name,
        release_date=extra.pop("release_date", _now() - timedelta(days=3)),
        discovered_at=found,
        **extra,
    )
    db.add(row)
    return row


def _get(client: TestClient, profile: dict) -> dict:
    response = client.get(URL, headers=make_profile_headers(profile))
    assert response.status_code == 200, response.text
    return response.json()


def _seen(client: TestClient, profile: dict, through: str) -> dict:
    response = client.post(f"{URL}/seen", json={"through": through}, headers=make_profile_headers(profile))
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def notices(monkeypatch):
    """The notices the seen route sends, instead of the process's command channel."""
    sent: list[tuple[UUID, dict]] = []

    class Channel:
        def notify(self, profile_id, notice):
            sent.append((profile_id, notice))
            return 1

    monkeypatch.setattr("app.api.routes.library_discover.get_channel", lambda: Channel())
    return sent


@pytest.mark.asyncio
class TestState:
    async def test_never_run_is_not_nothing_new(self, async_db, client, test_profile):
        await async_db.commit()
        data = _get(client, test_profile)
        assert data["state"] == "never_run"
        assert data["new_count"] == 0 and data["items"] == []

    async def test_disabled_discovery_says_so(self, async_db, client, test_profile, monkeypatch):
        _release(async_db, name="Weather", found=_now())
        await async_db.commit()

        from app.services import app_settings

        real = app_settings.get_app_settings_service()
        off = real.get().model_copy(update={"discovery_enabled": False})
        monkeypatch.setattr(real, "get", lambda: off)
        data = _get(client, test_profile)
        assert data["state"] == "disabled" and data["items"] == []


@pytest.mark.asyncio
class TestNew:
    async def test_the_backlog_at_first_read_is_not_announced(self, async_db, client, test_profile):
        _release(async_db, name="Dive", found=_now() - timedelta(days=2))
        await async_db.commit()

        data = _get(client, test_profile)

        assert data["state"] == "ok" and data["new_count"] == 0
        assert [i["is_new"] for i in data["items"]] == [False]

    async def test_a_release_found_afterwards_is_new_with_a_reason(self, async_db, client, test_profile):
        _release(async_db, name="Dive", found=_now() - timedelta(days=2))
        await async_db.commit()
        _get(client, test_profile)  # the baseline

        _release(async_db, name="Weather", found=_now())
        await async_db.commit()
        data = _get(client, test_profile)

        assert data["new_count"] == 1
        newest = data["items"][0]
        assert (newest["release_name"], newest["is_new"]) == ("Weather", True)
        assert newest["reason"]["kind"] == "library_artist"
        assert newest["reason"]["text"] == "Tycho is in your library"
        assert "bandcamp.com" in newest["bandcamp_url"]

    async def test_dismissed_owned_and_old_releases_are_left_out(self, async_db, client, test_profile):
        _release(async_db, name="Baseline", found=_now() - timedelta(days=5))
        await async_db.commit()
        _get(client, test_profile)

        _release(async_db, name="Shown", found=_now())
        _release(async_db, name="Dismissed", found=_now(), dismissed=True)
        _release(async_db, name="Owned", found=_now(), local_album_match=True)
        _release(async_db, name="Old", found=_now(), release_date=_now() - timedelta(days=400))
        await async_db.commit()
        data = _get(client, test_profile)

        assert data["new_count"] == 1
        assert {i["release_name"] for i in data["items"]} == {"Shown", "Baseline"}

    async def test_the_reason_counts_this_profiles_plays(self, async_db, client, test_profile):
        artist = Artist(name="Tycho", sort_name="Tycho")
        async_db.add(artist)
        await async_db.flush()
        async_db.add(ArtistAlias(alias_normalized="tycho", alias="Tycho", artist_id=artist.id, source="tag"))
        track = Track(
            id=uuid4(), file_path="/music/a.mp3", file_hash="hash-a", title="A", artist="Tycho",
            canonical_artist_id=artist.id, status=TrackStatus.ACTIVE,
        )
        async_db.add(track)
        await async_db.flush()
        async_db.add(ProfilePlayHistory(profile_id=UUID(test_profile["id"]), track_id=track.id, play_count=42))
        _release(async_db, name="Weather", found=_now())
        await async_db.commit()

        reason = _get(client, test_profile)["items"][0]["reason"]

        assert reason["text"] == "You've played Tycho 42 times"
        assert reason["play_count"] == 42


@pytest.mark.asyncio
class TestSeen:
    async def _with_one_new(self, async_db, client, profile) -> str:
        _release(async_db, name="Dive", found=_now() - timedelta(days=2))
        await async_db.commit()
        _get(client, profile)
        _release(async_db, name="Weather", found=_now())
        await async_db.commit()
        return _get(client, profile)["items"][0]["discovered_at"]

    async def test_seeing_clears_new_and_tells_the_other_devices(self, async_db, client, test_profile, notices):
        through = await self._with_one_new(async_db, client, test_profile)

        _seen(client, test_profile, through)

        assert _get(client, test_profile)["new_count"] == 0
        assert notices == [(UUID(test_profile["id"]), {"type": "whats_new_changed"})]

    async def test_seen_only_moves_forward(self, async_db, client, test_profile, notices):
        through = await self._with_one_new(async_db, client, test_profile)
        _seen(client, test_profile, through)

        earlier = (datetime.fromisoformat(through) - timedelta(days=30)).isoformat()
        answer = _seen(client, test_profile, earlier)

        assert answer["seen_through"] == through
        assert _get(client, test_profile)["new_count"] == 0
        assert len(notices) == 1, "a write that changed nothing tells nobody"

    async def test_one_profile_seeing_does_not_clear_another(self, async_db, client, test_profile, notices):
        other = client.post("/api/v1/profiles", json={"name": f"Other {uuid4().hex[:8]}"}).json()
        _release(async_db, name="Dive", found=_now() - timedelta(days=2))
        await async_db.commit()
        _get(client, test_profile)
        _get(client, other)
        _release(async_db, name="Weather", found=_now())
        await async_db.commit()

        _seen(client, test_profile, _get(client, test_profile)["items"][0]["discovered_at"])

        assert _get(client, test_profile)["new_count"] == 0
        assert _get(client, other)["new_count"] == 1

    async def test_a_release_found_after_what_was_shown_stays_new(self, async_db, client, test_profile, notices):
        through = await self._with_one_new(async_db, client, test_profile)
        _release(async_db, name="Later", found=_now() + timedelta(seconds=5))
        await async_db.commit()

        _seen(client, test_profile, through)

        assert _get(client, test_profile)["new_count"] == 1


@pytest.mark.asyncio
async def test_the_mcp_tool_gives_the_same_answer_and_marks_nothing_seen(async_db, client, test_profile):
    from app.services.llm.executor import ToolExecutor

    _release(async_db, name="Dive", found=_now() - timedelta(days=2))
    await async_db.commit()
    _get(client, test_profile)
    _release(async_db, name="Weather", found=_now())
    await async_db.commit()

    executor = ToolExecutor(db=async_db, profile_id=UUID(test_profile["id"]))
    result = await executor.execute("get_whats_new", {"limit": 5})

    assert result["state"] == "ok" and result["new_count"] == 1
    assert result["items"][0]["release_name"] == "Weather"
    assert _get(client, test_profile)["new_count"] == 1, "reading through the tool is not looking"
