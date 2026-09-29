"""`KeyValueStore` on PostgreSQL, for a server with no Redis (ADR-0133).

**Semantics follow Redis, not convenience.** Callers were written against Redis and are not told
which store they have, so each operation does what the Redis command does:
- `set(nx=True)` returns `None` when the key is live
- an expired key is absent to every operation
- `lrange`/`ltrim` take inclusive, possibly negative, indices
- a list that becomes empty stops existing
- `scan_iter` yields bytes

`tests/test_kv_store.py` runs one contract against this and against Redis.

**Expiry is the database's clock, inside the statement.** `now()` is compared with `expires_at` in
SQL, never with a Python timestamp, so a lock's lifetime cannot drift with the application host.
Expired rows are ignored on read, removed before any write to the same key, and swept periodically
(`sweep`) so an unread key does not live forever.

**Sync, deliberately.** The interface is sync because the Redis client is, and because it is called
from spawned analysis and scan processes that have no event loop. Each process gets its own small
connection pool; a call takes one connection, runs one transaction, and returns it.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, TypeVar

import psycopg2
import psycopg2.pool

from app.services.kv import Value

logger = logging.getLogger(__name__)

T = TypeVar("T")

LIVE = "(expires_at IS NULL OR expires_at > now())"


def _encode(value: Value) -> bytes:
    # bool is an int in Python, and redis-py refuses it rather than storing "True"; so does this.
    if isinstance(value, bool) or value is None:
        raise TypeError(f"invalid value type {type(value).__name__}; use bytes, str, int or float")
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode()
    if isinstance(value, int | float):
        return repr(value).encode() if isinstance(value, float) else str(value).encode()
    raise TypeError(f"invalid value type {type(value).__name__}; use bytes, str, int or float")


def _key(key: str | bytes) -> str:
    return key.decode() if isinstance(key, bytes) else key


def _seconds(ex: int | None, px: int | None) -> float | None:
    if ex is not None:
        return float(ex)
    if px is not None:
        return px / 1000
    return None


def _glob_to_like(pattern: str) -> str:
    """Redis glob to SQL LIKE, for the `*` and `?` the callers use. Character classes are refused."""
    if "[" in pattern:
        raise ValueError(f"character classes are not supported in scan patterns: {pattern!r}")
    escaped = pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped.replace("*", "%").replace("?", "_")


def _slice_bounds(length: int, start: int, end: int) -> tuple[int, int] | None:
    """Redis's inclusive, negative-aware range over a list of `length`, as a Python slice."""
    if start < 0:
        start = max(length + start, 0)
    if end < 0:
        end = length + end
    end = min(end, length - 1)
    if start > end or start >= length:
        return None
    return start, end + 1


class PostgresKeyValueStore:
    """The twelve `KeyValueStore` operations over `kv_store` and `kv_list`."""

    def __init__(self, dsn: str, *, maxconn: int = 4) -> None:
        self._dsn = dsn
        self._maxconn = maxconn
        self._pool: psycopg2.pool.ThreadedConnectionPool | None = None
        self._lock = threading.Lock()

    # -- connections --------------------------------------------------------------------------

    def _get_pool(self) -> psycopg2.pool.ThreadedConnectionPool:
        with self._lock:
            if self._pool is None:
                self._pool = psycopg2.pool.ThreadedConnectionPool(1, self._maxconn, self._dsn)
            return self._pool

    @contextmanager
    def _cursor(self) -> Iterator[Any]:
        """One transaction: committed on success, rolled back on error."""
        pool = self._get_pool()
        conn = pool.getconn()
        broken = False
        try:
            with conn:  # commit / rollback
                with conn.cursor() as cur:
                    yield cur
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            broken = True
            raise
        finally:
            pool.putconn(conn, close=broken or conn.closed != 0)

    def _run(self, op: Callable[[Any], T]) -> T:
        """Run `op` in a transaction, once more on a dropped connection (a restarted database)."""
        try:
            with self._cursor() as cur:
                return op(cur)
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            logger.warning("kv_store connection failed (%s); retrying once", e)
            with self._cursor() as cur:
                return op(cur)

    @staticmethod
    def _purge_expired(cur: Any, key: str) -> None:
        # Before any write, so an expired key is replaced rather than extended or appended to.
        cur.execute(f"DELETE FROM kv_store WHERE key = %s AND NOT {LIVE}", (key,))

    # -- values -------------------------------------------------------------------------------

    def get(self, key: str) -> bytes | None:
        def op(cur: Any) -> bytes | None:
            cur.execute(
                f"SELECT value FROM kv_store WHERE key = %s AND kind = 'string' AND {LIVE}", (key,)
            )
            row = cur.fetchone()
            return bytes(row[0]) if row else None

        return self._run(op)

    def set(
        self,
        key: str,
        value: Value,
        ex: int | None = None,
        px: int | None = None,
        nx: bool = False,
        xx: bool = False,
    ) -> bool | None:
        data = _encode(value)
        seconds = _seconds(ex, px)
        expires = "now() + make_interval(secs => %s)" if seconds is not None else "NULL"
        params_expiry: tuple[Any, ...] = (seconds,) if seconds is not None else ()

        def op(cur: Any) -> bool | None:
            self._purge_expired(cur, key)
            if nx:
                cur.execute(
                    f"INSERT INTO kv_store (key, kind, value, expires_at) "
                    f"VALUES (%s, 'string', %s, {expires}) ON CONFLICT (key) DO NOTHING RETURNING key",
                    (key, data, *params_expiry),
                )
                return True if cur.fetchone() else None
            cur.execute("DELETE FROM kv_list WHERE key = %s", (key,))
            if xx:
                cur.execute(
                    f"UPDATE kv_store SET kind = 'string', value = %s, expires_at = {expires} "
                    f"WHERE key = %s",
                    (data, *params_expiry, key),
                )
                return True if cur.rowcount else None
            cur.execute(
                f"INSERT INTO kv_store (key, kind, value, expires_at) VALUES (%s, 'string', %s, {expires}) "
                f"ON CONFLICT (key) DO UPDATE SET kind = 'string', value = EXCLUDED.value, "
                f"expires_at = EXCLUDED.expires_at",
                (key, data, *params_expiry),
            )
            return True

        return self._run(op)

    def setex(self, key: str, seconds: int, value: Value) -> bool:
        return bool(self.set(key, value, ex=seconds))

    def delete(self, *keys: str | bytes) -> int:
        if not keys:
            return 0
        names = [_key(k) for k in keys]

        def op(cur: Any) -> int:
            cur.execute(
                f"DELETE FROM kv_store WHERE key = ANY(%s) RETURNING {LIVE}", (names,)
            )
            return sum(1 for (live,) in cur.fetchall() if live)

        return self._run(op)

    def exists(self, *keys: str | bytes) -> int:
        if not keys:
            return 0
        names = [_key(k) for k in keys]

        def op(cur: Any) -> int:
            # Redis counts a key once per time it is named, so join rather than filter.
            cur.execute(
                f"SELECT count(*) FROM unnest(%s::text[]) AS k(name) "
                f"JOIN kv_store s ON s.key = k.name WHERE {LIVE}",
                (names,),
            )
            return int(cur.fetchone()[0])

        return self._run(op)

    def expire(self, key: str, seconds: int) -> bool:
        def op(cur: Any) -> bool:
            cur.execute(
                f"UPDATE kv_store SET expires_at = now() + make_interval(secs => %s) "
                f"WHERE key = %s AND {LIVE}",
                (float(seconds), key),
            )
            return bool(cur.rowcount)

        return self._run(op)

    # -- lists --------------------------------------------------------------------------------
    # The lists here are capped by their callers (ten to a few hundred entries), so ranges are
    # computed over the whole list in Python rather than in SQL.

    @staticmethod
    def _list_seqs(cur: Any, key: str) -> list[tuple[int, bytes]]:
        cur.execute(
            f"SELECT l.seq, l.value FROM kv_list l JOIN kv_store s ON s.key = l.key "
            f"WHERE l.key = %s AND s.kind = 'list' AND {LIVE.replace('expires_at', 's.expires_at')} "
            f"ORDER BY l.seq DESC",
            (key,),
        )
        return [(seq, bytes(value)) for seq, value in cur.fetchall()]

    def lpush(self, key: str, *values: Value) -> int:
        encoded = [_encode(v) for v in values]

        def op(cur: Any) -> int:
            self._purge_expired(cur, key)
            cur.execute(
                "INSERT INTO kv_store (key, kind) VALUES (%s, 'list') "
                "ON CONFLICT (key) DO NOTHING",
                (key,),
            )
            cur.execute("SELECT kind FROM kv_store WHERE key = %s", (key,))
            if cur.fetchone()[0] != "list":
                raise TypeError(f"WRONGTYPE {key!r} holds a value, not a list")
            # One at a time, in order: each takes the next seq, so the last pushed is the head.
            for data in encoded:
                cur.execute("INSERT INTO kv_list (key, value) VALUES (%s, %s)", (key, data))
            cur.execute("SELECT count(*) FROM kv_list WHERE key = %s", (key,))
            return int(cur.fetchone()[0])

        return self._run(op)

    def lrange(self, key: str, start: int, end: int) -> list[bytes]:
        def op(cur: Any) -> list[bytes]:
            items = self._list_seqs(cur, key)
            bounds = _slice_bounds(len(items), start, end)
            return [] if bounds is None else [value for _, value in items[bounds[0] : bounds[1]]]

        return self._run(op)

    def ltrim(self, key: str, start: int, end: int) -> bool:
        def op(cur: Any) -> bool:
            items = self._list_seqs(cur, key)
            bounds = _slice_bounds(len(items), start, end)
            keep = set() if bounds is None else {seq for seq, _ in items[bounds[0] : bounds[1]]}
            drop = [seq for seq, _ in items if seq not in keep]
            if drop:
                cur.execute("DELETE FROM kv_list WHERE seq = ANY(%s)", (drop,))
            if not keep:
                cur.execute("DELETE FROM kv_store WHERE key = %s AND kind = 'list'", (key,))
            return True

        return self._run(op)

    # -- keys ---------------------------------------------------------------------------------

    def scan_iter(self, match: str | None = None, count: int | None = None) -> Iterator[bytes]:
        """Keys matching a Redis glob, as bytes like redis-py. `count` is accepted and ignored."""
        like = _glob_to_like(match) if match else "%"

        def op(cur: Any) -> list[bytes]:
            cur.execute(f"SELECT key FROM kv_store WHERE key LIKE %s AND {LIVE}", (like,))
            return [row[0].encode() for row in cur.fetchall()]

        return iter(self._run(op))

    def ping(self) -> bool:
        try:
            return self._run(lambda cur: cur.execute("SELECT 1") or True)
        except Exception:
            return False

    # -- housekeeping -------------------------------------------------------------------------

    def sweep(self) -> int:
        """Delete expired keys (and, by cascade, their list items). Returns how many."""

        def op(cur: Any) -> int:
            cur.execute(f"DELETE FROM kv_store WHERE NOT {LIVE}")
            return int(cur.rowcount)

        return self._run(op)

    def close(self) -> None:
        with self._lock:
            if self._pool is not None:
                self._pool.closeall()
                self._pool = None
