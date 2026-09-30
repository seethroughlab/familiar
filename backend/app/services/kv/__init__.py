"""The key/value store the server keeps its transient state in (ADR-0133).

Twelve operations, which are exactly what the eighteen modules that use it call: a value with expiry,
an atomic "set if absent", capped lists, a key scan and a ping. No pub/sub, no streams, no Lua.
Anything that needs more than this has to add it to *both* implementations, and to the contract
test that runs against both (`tests/test_kv_store.py`).

- `ResilientRedisClient` (`app/services/redis_client.py`) is the Redis implementation, used when
  `REDIS_URL` is set. That is every Docker install.
- `PostgresKeyValueStore` (`app/services/kv/postgres.py`) is used when it is not, so a server
  outside Docker needs one database and nothing else.

`get_redis()` still returns whichever one is in use; its name outlived its meaning, and renaming
eighteen call sites was not part of the decision.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

#: What a value may be. Redis stores ints and floats as their decimal strings, and so does the
#: Postgres store; `get` always returns bytes.
Value = str | bytes | int | float


@runtime_checkable
class KeyValueStore(Protocol):
    def get(self, key: str) -> bytes | None: ...

    def set(
        self,
        key: str,
        value: Value,
        ex: int | None = None,
        px: int | None = None,
        nx: bool = False,
        xx: bool = False,
    ) -> bool | None: ...

    def delete(self, *keys: str | bytes) -> int: ...

    def exists(self, *keys: str | bytes) -> int: ...

    def expire(self, key: str, seconds: int) -> bool: ...

    def lpush(self, key: str, *values: Value) -> int: ...

    def lrange(self, key: str, start: int, end: int) -> list[bytes]: ...

    def ltrim(self, key: str, start: int, end: int) -> bool: ...

    def setex(self, key: str, seconds: int, value: Value) -> bool: ...

    def scan_iter(self, match: str | None = None, count: int | None = None) -> Iterator[bytes]: ...

    def ping(self) -> bool: ...
