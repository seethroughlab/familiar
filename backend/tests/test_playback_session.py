"""Tests for the server-owned playback queue (ADR-0003).

Two guarantees carry the whole design, and both fail silently rather than loudly:

- **A lost conflict is never destroyed.** When two devices diverge offline, the later
  write wins and the loser is archived. If that archiving breaks, a listener loses a
  queue they built and nothing anywhere says so — `test_a_losing_write_is_archived` and
  `test_the_superseded_queue_is_archived_when_a_write_wins` cover both directions.

- **An omitted reservoir must never be silently mismatched.** A write may leave out
  `reservoir_ids` to avoid resending ~1 MB of UUIDs, saying only "it hashes to this". If
  the server accepted a mismatched hash and kept the wrong reservoir, the queue would
  simply stop after the materialised window with no error —
  `test_a_stale_reservoir_hash_is_rejected` is the guard.

The version field is what separates an ordinary sequential write from a genuine
divergence, so `test_a_sequential_write_does_not_archive` matters too: without it the
archive would fill with every device's own history within minutes of playback.
"""

from uuid import uuid4

import pytest

from app.api.routes.queue import ARCHIVE_LIMIT, reservoir_digest
from tests.conftest import make_profile_headers

pytestmark = pytest.mark.asyncio

SESSION_URL = "/api/v1/queue/session"


@pytest.fixture(autouse=True)
def queue_sync_flag(monkeypatch):
    """Control the server-side flag in-process, defaulting it on.

    It ships off (ADR-0003 point 7), so without this every request here would be a 503.
    Patching the accessor rather than calling `update()`: `get()` reloads from disk on
    every call, so mutating the returned model does nothing, and `update()` would write
    to the developer's real `data/settings.json`.
    """
    from app.services.app_settings import AppSettingsService

    state = {"enabled": True}
    original = AppSettingsService.get

    def patched(self):
        settings = original(self)
        settings.queue_sync_enabled = state["enabled"]
        return settings

    monkeypatch.setattr(AppSettingsService, "get", patched)
    return state


class TestFlag:
    async def test_the_endpoints_are_off_when_the_flag_is(
        self, client, test_profile, queue_sync_flag
    ):
        queue_sync_flag["enabled"] = False
        # 503 rather than silently accepting: a server that took writes and did nothing
        # with them would look like a client bug and be debugged on the wrong side.
        assert _get(client, test_profile).status_code == 503
        assert _put(client, test_profile).status_code == 503
        assert client.get(
            f"{SESSION_URL}/archive", headers=make_profile_headers(test_profile)
        ).status_code == 503


def _body(**overrides):
    """A minimal valid session write."""
    body = {
        "track_ids": [],
        "cursor": -1,
        "shuffle_order": [],
        "shuffle_index": -1,
        "shuffle": False,
        "repeat": "off",
        "consume": False,
        "queue_source": None,
        "reservoir_cursor": -1,
        "position_seconds": 0.0,
        "version": 0,
    }
    body.update(overrides)
    return body


def _put(client, profile, **overrides):
    return client.put(SESSION_URL, json=_body(**overrides), headers=make_profile_headers(profile))


def _get(client, profile):
    return client.get(SESSION_URL, headers=make_profile_headers(profile))


class TestAuth:
    async def test_get_requires_a_profile(self, client):
        assert client.get(SESSION_URL).status_code == 401

    async def test_put_requires_a_profile(self, client):
        assert client.put(SESSION_URL, json=_body()).status_code == 401

    async def test_archive_requires_a_profile(self, client):
        assert client.get(f"{SESSION_URL}/archive").status_code == 401


class TestReadAndWrite:
    async def test_an_absent_session_reads_as_empty_rather_than_404(self, client, test_profile):
        # "No queue yet" is the ordinary starting state, not an error.
        r = _get(client, test_profile)
        assert r.status_code == 200, r.text
        assert r.json()["version"] == 0
        assert r.json()["track_ids"] == []

    async def test_a_first_write_creates_the_session(self, client, test_profile):
        ids = [str(uuid4()) for _ in range(3)]
        r = _put(client, test_profile, track_ids=ids, cursor=1)
        assert r.status_code == 200, r.text
        assert r.json()["track_ids"] == ids
        assert r.json()["cursor"] == 1
        assert r.json()["version"] == 1

    async def test_a_write_round_trips(self, client, test_profile):
        ids = [str(uuid4()) for _ in range(4)]
        source = {"type": "library", "filters": {"genre": "jazz", "year_from": 1990}}
        _put(
            client, test_profile,
            track_ids=ids, cursor=2, shuffle=True, shuffle_order=[2, 0, 1, 3],
            shuffle_index=0, repeat="all", consume=True, queue_source=source,
            position_seconds=42.5,
        )

        body = _get(client, test_profile).json()
        assert body["track_ids"] == ids
        assert body["cursor"] == 2
        assert body["shuffle"] is True
        assert body["shuffle_order"] == [2, 0, 1, 3]
        assert body["repeat"] == "all"
        assert body["consume"] is True
        assert body["position_seconds"] == 42.5
        # The library filters have to survive intact — toggleShuffle replays them verbatim.
        assert body["queue_source"]["filters"]["genre"] == "jazz"
        assert body["queue_source"]["filters"]["year_from"] == 1990

    async def test_a_sequential_write_bumps_the_version(self, client, test_profile):
        assert _put(client, test_profile, version=0).json()["version"] == 1
        assert _put(client, test_profile, version=1).json()["version"] == 2
        assert _put(client, test_profile, version=2).json()["version"] == 3

    async def test_position_alone_can_be_advanced(self, client, test_profile):
        ids = [str(uuid4())]
        _put(client, test_profile, track_ids=ids)
        r = _put(client, test_profile, track_ids=ids, version=1, position_seconds=90.0)
        assert r.json()["position_seconds"] == 90.0

    async def test_radio_is_not_an_accepted_queue_source(self, client, test_profile):
        # 'radio' and 'ambient' are listening contexts, not queue sources (ADR-0003
        # point 8). Accepting them here would let PlayContext leak into queue state.
        r = _put(client, test_profile, queue_source={"type": "radio"})
        assert r.status_code == 422, r.text


class TestReservoir:
    async def test_the_reservoir_round_trips(self, client, test_profile):
        reservoir = [str(uuid4()) for _ in range(50)]
        r = _put(client, test_profile, reservoir_ids=reservoir, reservoir_cursor=10)
        assert r.json()["reservoir_ids"] == reservoir
        assert r.json()["reservoir_cursor"] == 10
        assert r.json()["reservoir_hash"] == reservoir_digest(reservoir)

    async def test_an_unchanged_reservoir_can_be_referenced_by_hash(self, client, test_profile):
        reservoir = [str(uuid4()) for _ in range(50)]
        first = _put(client, test_profile, reservoir_ids=reservoir, reservoir_cursor=10)
        digest = first.json()["reservoir_hash"]

        # The point of the whole scheme: advance the cursor without resending ~1 MB.
        r = _put(
            client, test_profile,
            version=1, reservoir_hash=digest, reservoir_cursor=30,
        )
        assert r.status_code == 200, r.text
        assert r.json()["reservoir_ids"] == reservoir
        assert r.json()["reservoir_cursor"] == 30

    async def test_a_stale_reservoir_hash_is_rejected(self, client, test_profile):
        _put(client, test_profile, reservoir_ids=[str(uuid4()) for _ in range(10)])

        # Keeping the stored reservoir here would truncate the queue at the materialised
        # window, and nothing would report it — so this has to fail loudly.
        r = _put(client, test_profile, version=1, reservoir_hash="0" * 64)
        assert r.status_code == 409, r.text

    async def test_omitting_both_ids_and_hash_is_fine_when_there_is_no_reservoir(
        self, client, test_profile
    ):
        r = _put(client, test_profile, track_ids=[str(uuid4())])
        assert r.status_code == 200, r.text
        assert r.json()["reservoir_ids"] is None

    async def test_the_hash_is_order_sensitive(self):
        a, b = str(uuid4()), str(uuid4())
        # A reshuffle changes the reservoir even though the set is identical, so a
        # set-insensitive hash would let a stale order be referenced as current.
        assert reservoir_digest([a, b]) != reservoir_digest([b, a])


class TestConflicts:
    async def test_a_sequential_write_does_not_archive(self, client, test_profile):
        # One device advancing its own queue is not a conflict. If it were, the archive
        # would fill with a device's own history within minutes of playback.
        _put(client, test_profile, track_ids=[str(uuid4())])
        _put(client, test_profile, version=1, track_ids=[str(uuid4())])
        _put(client, test_profile, version=2, track_ids=[str(uuid4())])

        archive = client.get(f"{SESSION_URL}/archive", headers=make_profile_headers(test_profile))
        assert archive.json()["sessions"] == []

    async def test_the_superseded_queue_is_archived_when_a_write_wins(self, client, test_profile):
        phone = [str(uuid4()) for _ in range(2)]
        desktop = [str(uuid4()) for _ in range(3)]
        _put(client, test_profile, track_ids=phone, updated_at="2026-07-27T10:00:00")

        # The desktop was offline and wrote from version 0 — a genuine divergence, and
        # its clock says later, so it wins.
        r = _put(client, test_profile, version=0, track_ids=desktop,
                 updated_at="2026-07-27T11:00:00")
        assert r.status_code == 200, r.text
        assert r.json()["track_ids"] == desktop
        assert r.json()["superseded"] is False

        archive = client.get(
            f"{SESSION_URL}/archive", headers=make_profile_headers(test_profile)
        ).json()["sessions"]
        assert len(archive) == 1
        assert archive[0]["track_ids"] == phone

    async def test_a_losing_write_is_archived_and_the_winner_returned(self, client, test_profile):
        phone = [str(uuid4()) for _ in range(2)]
        stale = [str(uuid4()) for _ in range(3)]
        _put(client, test_profile, track_ids=phone, updated_at="2026-07-27T11:00:00")

        # An older offline edit arriving late. It loses, but must not vanish.
        r = _put(client, test_profile, version=0, track_ids=stale,
                 updated_at="2026-07-27T10:00:00")
        assert r.status_code == 200, r.text
        # The client is handed the winner so it can adopt rather than retry.
        assert r.json()["track_ids"] == phone
        assert r.json()["superseded"] is True

        archive = client.get(
            f"{SESSION_URL}/archive", headers=make_profile_headers(test_profile)
        ).json()["sessions"]
        assert len(archive) == 1
        assert archive[0]["track_ids"] == stale

    async def test_a_losing_write_does_not_change_the_live_session(self, client, test_profile):
        phone = [str(uuid4()) for _ in range(2)]
        _put(client, test_profile, track_ids=phone, updated_at="2026-07-27T11:00:00")
        before = _get(client, test_profile).json()

        _put(client, test_profile, version=0, track_ids=[str(uuid4())],
             updated_at="2026-07-27T10:00:00")

        after = _get(client, test_profile).json()
        assert after["track_ids"] == before["track_ids"]
        assert after["version"] == before["version"]

    async def test_a_wildly_future_clock_cannot_keep_winning(self, client, test_profile):
        from datetime import datetime, timedelta

        from app.api.routes.queue import MAX_CLOCK_SKEW
        from app.utils.time import utcnow

        _put(client, test_profile, track_ids=[str(uuid4())])

        # A device a year ahead still wins this write — it is later, and the server has no
        # way to know the clock is wrong rather than the edit being genuinely newer.
        r = _put(client, test_profile, version=0, track_ids=[str(uuid4())],
                 updated_at="2099-01-01T00:00:00")
        assert r.json()["superseded"] is False

        # What the clamp guarantees is that the skew does not *persist*: the stored time
        # is bounded to now + MAX_CLOCK_SKEW, so every other device is locked out for
        # minutes rather than for a year.
        stored = datetime.fromisoformat(r.json()["updated_at"])
        assert stored < utcnow() + MAX_CLOCK_SKEW + timedelta(seconds=5)

    async def test_the_archive_is_bounded(self, client, test_profile):
        _put(client, test_profile, track_ids=[str(uuid4())], updated_at="2026-07-27T12:00:00")
        # Every one of these loses against the live session, so every one is archived.
        for i in range(ARCHIVE_LIMIT + 5):
            _put(client, test_profile, version=0, track_ids=[str(uuid4())],
                 updated_at=f"2026-07-27T10:{i:02d}:00")

        archive = client.get(
            f"{SESSION_URL}/archive", headers=make_profile_headers(test_profile)
        ).json()["sessions"]
        assert len(archive) == ARCHIVE_LIMIT


class TestRestore:
    async def test_an_archived_queue_can_be_made_current(self, client, test_profile):
        lost = [str(uuid4()) for _ in range(3)]
        kept = [str(uuid4()) for _ in range(2)]
        _put(client, test_profile, track_ids=kept, updated_at="2026-07-27T11:00:00")
        _put(client, test_profile, version=0, track_ids=lost, updated_at="2026-07-27T10:00:00")

        archive_id = client.get(
            f"{SESSION_URL}/archive", headers=make_profile_headers(test_profile)
        ).json()["sessions"][0]["id"]

        r = client.post(
            f"{SESSION_URL}/archive/{archive_id}/restore",
            headers=make_profile_headers(test_profile),
        )
        assert r.status_code == 200, r.text
        assert r.json()["track_ids"] == lost
        assert _get(client, test_profile).json()["track_ids"] == lost

    async def test_restoring_archives_what_it_replaces(self, client, test_profile):
        lost = [str(uuid4()) for _ in range(3)]
        kept = [str(uuid4()) for _ in range(2)]
        _put(client, test_profile, track_ids=kept, updated_at="2026-07-27T11:00:00")
        _put(client, test_profile, version=0, track_ids=lost, updated_at="2026-07-27T10:00:00")

        archive_id = client.get(
            f"{SESSION_URL}/archive", headers=make_profile_headers(test_profile)
        ).json()["sessions"][0]["id"]
        client.post(
            f"{SESSION_URL}/archive/{archive_id}/restore",
            headers=make_profile_headers(test_profile),
        )

        # Restoring must not destroy either — the queue it displaced takes its place,
        # and the restored one is no longer an archive entry.
        archive = client.get(
            f"{SESSION_URL}/archive", headers=make_profile_headers(test_profile)
        ).json()["sessions"]
        assert [s["track_ids"] for s in archive] == [kept]

    async def test_an_unknown_archive_id_is_404(self, client, test_profile):
        r = client.post(
            f"{SESSION_URL}/archive/{uuid4()}/restore",
            headers=make_profile_headers(test_profile),
        )
        assert r.status_code == 404, r.text


class TestIsolation:
    async def test_sessions_do_not_leak_between_profiles(self, client, test_profile):
        mine = [str(uuid4())]
        _put(client, test_profile, track_ids=mine)

        other = client.post("/api/v1/profiles", json={"name": f"Other {uuid4().hex[:8]}"}).json()
        assert _get(client, other).json()["track_ids"] == []
        assert _get(client, test_profile).json()["track_ids"] == mine


class TestLimits:
    async def test_an_oversized_queue_is_rejected(self, client, test_profile):
        r = _put(client, test_profile, track_ids=[str(uuid4())] * 10_001)
        assert r.status_code == 422, r.status_code

    async def test_a_malformed_track_id_is_a_422_not_a_500(self, client, test_profile):
        r = _put(client, test_profile, track_ids=["not-a-uuid"])
        assert r.status_code == 422, r.status_code
