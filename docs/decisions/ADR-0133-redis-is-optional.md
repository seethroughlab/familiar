# ADR-0133: Redis Is Optional

Status: accepted

Date: 2026-09-29

Implementation:
- **2026-09-29, `familiar`: all six points.**
  - **Point 1.** `KeyValueStore` is a `runtime_checkable` Protocol in `app/services/kv/__init__.py`.
    `ResilientRedisClient` is unchanged and satisfies it. `get_redis()` keeps its name.
  - **Point 2.** `PostgresKeyValueStore` in `app/services/kv/postgres.py`: a `ThreadedConnectionPool`
    of four per process, one transaction per call, and one retry on a dropped connection. The
    tables are `kv_store`/`kv_list` (models in `app/db/models/kv.py`, migration
    `20260929_kv_store`). An expired key is purged before any write to it, ignored on read, and
    swept every ten minutes by a scheduler job that exists only when this store is in use.
  - **Point 3 as written.** `set(nx=True)` is `ON CONFLICT DO NOTHING` after the purge, and expiry
    is `now()` compared inside the statement.
  - **Point 4 is built differently from its text.** The choice is made per process from
    `settings.redis_url` (`build_store()` in `redis_client.py`), not once in `build_services`.
    The scan and analysis pools are *spawned*, so each builds its own store, and a choice held
    only by the parent's container would never reach them.
    `test_a_spawned_process_writes_where_the_parent_reads` pins it. `Settings.redis_url` now
    defaults to `None`. Every compose file already sets `REDIS_URL`, and `make doctor` reports an
    unset one as the Postgres store rather than a missing Redis. A developer who ran
    `make run` without `REDIS_URL`, and was silently using `localhost:6379`, now gets the Postgres
    store.
  - **Point 5.** `/health/system` reports `kv_store` instead of `redis` when there is no URL, and
    it is not in the critical set, because a Postgres outage already fails the `database` check.
  - **Point 6.** `tests/test_kv_store.py` runs 27 checks against both stores. They agree on
    every edge, including `nx` on a live key, expiry, negative list indices, a list trimmed to
    nothing, keys as bytes, and an int stored as its decimal. CI gains
    `backend-test-no-redis`, the core selection with no Redis service. Locally, the full suite
    passes both ways: 2,360 with Redis, and 2,333 plus 27 skipped (the Redis half) without.
  - **The Consequence about coalescing progress writes did not survive measurement.** The scanner
    already writes progress every 50 directories and every 10 files (`scanner.py:192,380`), so a
    26k-track scan is about 2,600 writes. The store does about 1,500 `set`s per second (0.67 ms,
    throwaway pgvector on the same Mac), so that is about 1.7 s of store time for the whole scan.
    Nothing was coalesced.
  - **Loose ends.** Three tests read Redis directly (`tests/test_scanner.py`). They now read
    through `get_redis()`, so they test whichever store is in use.

Extends [ADR-0132](ADR-0132-the-server-runs-without-docker.md)

## Context

After ADR-0132, a native server needs two server processes besides itself: PostgreSQL and Redis.
Postgres cannot be avoided (ADR-0132, Context). Redis can, and it is the harder of the two to
package. On the Mac it would be a second daemon to sign, start, stop and supervise in the
background of someone's computer (ADR-0136). There is also no supported Windows build, which
matters once ADR-0131's shelved Windows server returns.

How Familiar actually uses Redis, from the eighteen modules under `backend/app` that reach it:

- **Every access goes through one sync class**, `ResilientRedisClient`
  (`services/redis_client.py`). It has twelve operations: `get`, `set` (with `nx`/`ex`), `delete`,
  `exists`, `expire`, `lpush`, `lrange`, `ltrim`, `setex`, `scan_iter` and `ping`, plus the `client`
  escape hatch.
- **No pub/sub, no streams, no Lua.** A search for `pubsub` and `publish(` under `app/` finds nothing.
- **Two mutual-exclusion locks:** `familiar:sync:lock` (`services/background/sync.py:118`) and the
  S3 backup lock (`services/s3_backup.py:412`), both `SET NX EX`.
- **Progress passed across processes.** The library scan runs in a spawned pool process and writes
  its progress for the API to read (`services/tasks/library_sync_progress.py`,
  `SyncProgressReporter`). Analysis, download and mixtape progress use the same pattern. This is
  the one use an in-process dictionary could not replace.
- **Small persistent state:** the sync rotation cursor (`background/sync.py`) and Soulseek
  "settled" markers (`background/soulseek.py`).
- **Capped logs:** the event log and failure list use `lpush`/`ltrim` (`background/events.py`,
  `tasks/common.py`), as does the backup history.
- **Caches:** the ego map, embedding map, mood tags, update check, artwork and library
  aggregations.
- **The health check treats Redis as critical.** `api/routes/health.py` opens its own connection
  and reports the whole server unhealthy without it.

All of that is a key/value store with expiry, lists and one atomic "set if absent". Postgres, which
is already running and already reachable from every spawned process, can provide all of it.

## Decision

1. **Redis becomes one of two implementations of the store `ResilientRedisClient` already
   defines.** The class's twelve operations become a Protocol, `KeyValueStore`. The existing
   class is its Redis implementation, unchanged. `get_redis()` keeps its name and callers for now;
   renaming eighteen modules is not part of this decision.

2. **The second implementation is Postgres**, in `services/kv/postgres.py`:
   - a table `kv_store (key text primary key, value bytea, expires_at timestamptz)`
   - a `kv_list` table for list operations, ordered by a sequence
   - a sync `psycopg2` connection, because the interface is sync and is called from spawned pools
   - expiry is checked on read and swept by the existing APScheduler, so nothing depends on a
     background process being present
   - ordinary logged tables, not `UNLOGGED`: the compose Redis keeps its data on the `redis_data`
     volume with Redis 7's default snapshots, so the rotation cursor and Soulseek "settled"
     markers survive a restart today. Losing them on a crash would re-trigger syncs.

3. **`set(nx=True, ex=…)` stays a key, not an advisory lock.** It is
   `INSERT … ON CONFLICT DO UPDATE … WHERE kv_store.expires_at < now()`. That keeps the two locks'
   existing semantics: an expiry that frees a lock whose holder died. A session-scoped
   `pg_advisory_lock` would instead be released by a connection drop and never by time, which
   differs for a scan process killed mid-sync. The comparison uses the database's own clock inside
   one statement, never the application's.

4. **The backend is chosen by configuration.** If `REDIS_URL` is set, Redis is used. If it is unset,
   the Postgres store is used. The choice is made once in `build_services` (`app/container.py`,
   ADR-0130), and `get_redis()` returns what the container chose. Docker keeps setting `REDIS_URL`,
   so every existing installation is unchanged.

5. **Health reports the store that is in use.** With the Postgres store, the `redis` check is
   replaced by a `kv_store` check, and its absence is not critical because the database check
   already covers it.

6. **The tests run against both.** The modules that touch the store today are exercised through
   a fixture parametrised over both implementations. A Postgres-only CI job runs the full suite
   with `REDIS_URL` unset.

## Alternatives Considered

- **Bundle Redis in every native package.** This is zero code change, and Redis is small.
  Rejected: there is no supported Windows build, so the shelved Windows server (ADR-0131) would need Memurai
  or an unmaintained port. On the Mac it is another sandboxed daemon with its own lifecycle, for a
  workload that fits in two tables of a database already running.
- **An in-process store (a dict, or `cachetools`).** This is the simplest possible replacement.
  Rejected because of progress across processes: the scan and analysis pools are spawned
  processes, and the API process must read what they write. A dict in the API process cannot see
  them.
- **SQLite in the data directory.** Every process can open the file, and it needs no server.
  Rejected because it adds a third storage engine with its own locking behaviour (`SQLITE_BUSY`
  under concurrent writers from a spawned pool) to replace the second, when the first can already
  do it.
- **Remove Redis everywhere, Docker included.** This would leave one implementation instead of two.
  Not rejected in principle, but not decided here: the NAS is the one deployment with real load,
  and the Postgres store has not been measured there. The Follow-up records how that would be
  decided.

## Consequences

- **Positive:** a native server needs one database and nothing else. Windows becomes plausible
  without a Redis port.
- **Positive:** the twelve-operation interface is now written down and tested as a contract. Any
  new use of `client` (the raw escape hatch) has to justify itself.
- **Tradeoff:** two implementations must stay behaviourally identical. The parametrised fixture is
  the only thing that guarantees it, and a new operation must be added to both.
- **Tradeoff:** progress updates become database writes. Sync progress writes on every file; on
  the Postgres store these need coalescing (at most one write per second per key) so that a
  26k-track scan does not add tens of thousands of writes.
- **Follow-up:** once the Postgres store has run on the NAS for a release, measure it. If it is
  indistinguishable, a later ADR can remove Redis from compose entirely.
