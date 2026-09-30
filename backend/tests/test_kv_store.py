"""One contract, two stores: Redis and the Postgres tables that stand in for it (ADR-0133 point 6).

Every caller was written against Redis and is never told which store it has, so the Postgres store
must answer as Redis does, including the edges: `nx` on a live key, expiry, negative list indices,
a list that empties out, keys that come back as bytes. Each test runs against both. The Redis run
is skipped when no Redis is reachable, so a machine with only Postgres still checks the store it
will actually use.
"""

from __future__ import annotations

import multiprocessing
import os
import time
import uuid

import pytest

from app.config import settings
from app.services.kv import KeyValueStore
from app.services.kv.postgres import PostgresKeyValueStore, _glob_to_like, _slice_bounds


def _redis_store() -> KeyValueStore:
    url = os.environ.get("REDIS_URL") or settings.redis_url
    if not url:
        pytest.skip("no REDIS_URL: the Redis half of the contract needs a Redis")
    from app.services.redis_client import ResilientRedisClient

    client = ResilientRedisClient(url, socket_connect_timeout=1, socket_timeout=1)
    if not client.ping():
        pytest.skip(f"Redis at {url} is not reachable")
    return client


@pytest.fixture(params=["postgres", "redis"])
def store(request):
    if request.param == "redis":
        s = _redis_store()
    else:
        s = PostgresKeyValueStore(settings.sync_database_url)
        if not s.ping():
            pytest.skip("test database is not reachable")
    yield s
    for key in list(s.scan_iter(f"{PREFIX}*")):
        s.delete(key)
    if isinstance(s, PostgresKeyValueStore):
        s.close()


PREFIX = f"kvtest:{uuid.uuid4().hex[:8]}:"


def k(name: str) -> str:
    return PREFIX + name


class TestValues:
    def test_a_missing_key_is_none(self, store):
        assert store.get(k("absent")) is None

    def test_values_come_back_as_bytes(self, store):
        store.set(k("s"), "text")
        store.set(k("b"), b"\x00\xff")
        store.set(k("i"), 7)  # the sync rotation cursor is stored this way
        assert store.get(k("s")) == b"text"
        assert store.get(k("b")) == b"\x00\xff"
        assert store.get(k("i")) == b"7"

    def test_a_bool_is_refused(self, store):
        with pytest.raises(Exception):  # noqa: B017 - redis-py raises DataError, Postgres TypeError
            store.set(k("bool"), True)

    def test_set_replaces(self, store):
        store.set(k("x"), "one")
        assert store.set(k("x"), "two") is True
        assert store.get(k("x")) == b"two"


class TestLocks:
    """`SET NX EX` is the sync lock and the backup lock."""

    def test_nx_takes_a_free_key_and_refuses_a_held_one(self, store):
        assert store.set(k("lock"), "1", nx=True, ex=60) is True
        assert store.set(k("lock"), "2", nx=True, ex=60) is None
        assert store.get(k("lock")) == b"1"

    def test_an_expired_lock_can_be_taken_again(self, store):
        assert store.set(k("lock"), "1", nx=True, px=150) is True
        time.sleep(0.4)
        assert store.set(k("lock"), "2", nx=True, ex=60) is True
        assert store.get(k("lock")) == b"2"

    def test_xx_only_touches_an_existing_key(self, store):
        assert store.set(k("xx"), "v", xx=True) is None
        assert store.get(k("xx")) is None
        store.set(k("xx"), "v")
        assert store.set(k("xx"), "w", xx=True) is True
        assert store.get(k("xx")) == b"w"


class TestExpiry:
    def test_an_expired_key_is_absent_to_everything(self, store):
        store.set(k("e"), "v", px=150)
        assert store.get(k("e")) == b"v"
        time.sleep(0.4)
        assert store.get(k("e")) is None
        assert store.exists(k("e")) == 0
        assert store.delete(k("e")) == 0
        assert k("e").encode() not in list(store.scan_iter(f"{PREFIX}*"))

    def test_setex(self, store):
        assert store.setex(k("sx"), 60, "v") is True
        assert store.get(k("sx")) == b"v"

    def test_expire_needs_a_live_key(self, store):
        assert store.expire(k("nope"), 60) is False
        store.set(k("ex"), "v")
        assert store.expire(k("ex"), 1) is True
        time.sleep(1.3)
        assert store.get(k("ex")) is None


class TestKeys:
    def test_delete_counts_the_keys_that_existed(self, store):
        store.set(k("d1"), "v")
        store.lpush(k("d2"), "a")
        assert store.delete(k("d1"), k("d2"), k("d3")) == 2
        assert store.exists(k("d1"), k("d2")) == 0

    def test_delete_takes_keys_as_scan_returns_them(self, store):
        store.set(k("bytes"), "v")
        [key] = [key for key in store.scan_iter(f"{PREFIX}bytes")]
        assert isinstance(key, bytes)
        assert store.delete(key) == 1

    def test_exists_counts_a_key_each_time_it_is_named(self, store):
        store.set(k("x"), "v")
        assert store.exists(k("x"), k("x"), k("missing")) == 2

    def test_scan_matches_a_glob(self, store):
        store.set(k("map:a"), "1")
        store.set(k("map:b"), "2")
        store.set(k("other"), "3")
        found = sorted(store.scan_iter(f"{PREFIX}map:*"))
        assert found == [k("map:a").encode(), k("map:b").encode()]

    def test_ping(self, store):
        assert store.ping() is True


class TestLists:
    """The event log, task failures and backup history: LPUSH, LTRIM, LRANGE, EXPIRE."""

    def test_lpush_puts_the_newest_first(self, store):
        assert store.lpush(k("l"), "a", "b") == 2
        assert store.lpush(k("l"), "c") == 3
        assert store.lrange(k("l"), 0, -1) == [b"c", b"b", b"a"]

    @pytest.mark.parametrize(
        ("start", "end", "expected"),
        [(0, 0, [b"e"]), (1, 2, [b"d", b"c"]), (-2, -1, [b"b", b"a"]), (3, 100, [b"b", b"a"]),
         (10, 20, []), (2, 1, [])],
    )
    def test_lrange_indices_are_redis_indices(self, store, start, end, expected):
        store.lpush(k("r"), "a", "b", "c", "d", "e")
        assert store.lrange(k("r"), start, end) == expected

    def test_the_cap_the_callers_use(self, store):
        for i in range(15):
            store.lpush(k("cap"), str(i))
            store.ltrim(k("cap"), 0, 9)
        items = store.lrange(k("cap"), 0, -1)
        assert len(items) == 10
        assert items[0] == b"14"
        assert items[-1] == b"5"

    def test_a_list_trimmed_to_nothing_stops_existing(self, store):
        store.lpush(k("gone"), "a")
        store.ltrim(k("gone"), 5, 10)
        assert store.exists(k("gone")) == 0
        assert store.lrange(k("gone"), 0, -1) == []

    def test_a_list_expires(self, store):
        store.lpush(k("le"), "a")
        assert store.expire(k("le"), 1) is True
        time.sleep(1.3)
        assert store.lrange(k("le"), 0, -1) == []
        # And a push after expiry starts a new list rather than extending the old one.
        assert store.lpush(k("le"), "b") == 1

    def test_pushing_onto_a_value_is_refused(self, store):
        store.set(k("str"), "v")
        with pytest.raises(Exception):  # noqa: B017 - redis-py ResponseError, Postgres TypeError
            store.lpush(k("str"), "a")

    def test_set_replaces_a_list(self, store):
        store.lpush(k("lst"), "a")
        store.set(k("lst"), "v")
        assert store.get(k("lst")) == b"v"


# -- Postgres only -------------------------------------------------------------------------------


@pytest.fixture
def pg():
    s = PostgresKeyValueStore(settings.sync_database_url)
    if not s.ping():
        pytest.skip("test database is not reachable")
    yield s
    for key in list(s.scan_iter(f"{PREFIX}*")):
        s.delete(key)
    s.close()


def test_sweep_deletes_expired_keys_and_their_list_items(pg):
    pg.set(k("sw"), "v", px=100)
    pg.lpush(k("swl"), "a")
    pg.expire(k("swl"), 1)
    pg.set(k("keep"), "v")
    time.sleep(1.3)
    assert pg.sweep() >= 2

    def rows(cur):
        cur.execute("SELECT count(*) FROM kv_store WHERE key LIKE %s", (PREFIX + "%",))
        stored = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM kv_list WHERE key LIKE %s", (PREFIX + "%",))
        return stored, cur.fetchone()[0]

    assert pg._run(rows) == (1, 0)


def _child_writes(key: str) -> None:
    # A fresh interpreter, as the scan pool's workers are: it builds its own store from the
    # environment and must land where the parent reads.
    from app.services.redis_client import get_redis

    get_redis().set(key, "from the child", ex=60)


def test_a_spawned_process_writes_where_the_parent_reads(pg, monkeypatch):
    """Why the store is chosen from configuration, not handed down: pools are spawned."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    ctx = multiprocessing.get_context("spawn")
    proc = ctx.Process(target=_child_writes, args=(k("child"),))
    proc.start()
    proc.join(60)
    assert proc.exitcode == 0
    assert pg.get(k("child")) == b"from the child"


def test_the_store_follows_redis_url(monkeypatch):
    from app.services import redis_client

    monkeypatch.setattr(settings, "redis_url", None)
    assert isinstance(redis_client.build_store(), PostgresKeyValueStore)
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:1/0")
    assert isinstance(redis_client.build_store(), redis_client.ResilientRedisClient)


def test_glob_translation():
    assert _glob_to_like("a:*") == "a:%"
    assert _glob_to_like("a_b%?") == "a\\_b\\%_"
    with pytest.raises(ValueError):
        _glob_to_like("a[bc]")


def test_slice_bounds_match_redis():
    assert _slice_bounds(5, 0, -1) == (0, 5)
    assert _slice_bounds(5, -100, 1) == (0, 2)
    assert _slice_bounds(0, 0, -1) is None


def test_health_reports_the_postgres_store_and_does_not_ask_for_redis(client, pg, monkeypatch):
    """ADR-0133 point 5: with no REDIS_URL there is no Redis to be down."""
    from app.services import redis_client

    monkeypatch.setattr(settings, "redis_url", None)
    monkeypatch.setattr(redis_client, "_store", pg)
    body = client.get("/api/v1/health/system").json()
    services = {s["name"]: s for s in body["services"]}
    assert "redis" not in services
    assert services["kv_store"]["status"] == "healthy"
