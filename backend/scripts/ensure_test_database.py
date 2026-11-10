"""Create the test database if it is missing, and migrate it (ADR-0128 point 4).

    TEST_DATABASE_URL=postgresql+asyncpg://familiar:familiar@localhost:5432/familiar_test \\
        uv run python scripts/ensure_test_database.py

`make test` runs this first, so nobody edits a DSN by hand before a test run. Idempotent: an
existing database is left alone and `alembic upgrade head` is a no-op at head — **unless it is worn
out**: a table whose column numbers are close to PostgreSQL's 1,600 limit is dropped and recreated
(`worn_out`), since a test database is disposable by definition and nothing else repairs it. The URL goes
through the same guard the suite uses, so this cannot create or migrate anything not named as
disposable — the guard, not this script, is where the rule lives.

The database is created from a maintenance connection to the same server: `postgres` first,
then the user's own database. `CREATE DATABASE` cannot run inside a transaction, which is why
this is asyncpg directly rather than SQLAlchemy.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import asyncpg
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from tests.disposable_database import DisposableDatabaseError, disposable_database_url  # noqa: E402


async def ensure_database(url: str) -> bool:
    """Create the database the URL names if it does not exist. True when it was created."""
    parts = make_url(url)
    name = parts.database
    assert name, "the guard accepted a URL with no database name"
    last_error: Exception | None = None
    for maintenance in ("postgres", parts.username or "postgres"):
        try:
            connection = await asyncpg.connect(
                host=parts.host,
                port=parts.port or 5432,
                user=parts.username,
                password=parts.password,
                database=maintenance,
            )
        except asyncpg.InvalidCatalogNameError as error:
            last_error = error
            continue
        except OSError as error:
            # Connection refused is the common case — the compose stack is not up — and a forty-line
            # asyncpg traceback says that worse than one sentence does.
            raise SystemExit(
                f"nothing is listening at {parts.host}:{parts.port or 5432} ({error.__class__.__name__}).\n"
                "Start the database — from the repo root, `docker compose -f docker/docker-compose.yml up -d` —\n"
                "or, from backend/, `make test-services test` for a throwaway one on port 5434,\n"
                "or set TEST_DATABASE_URL to a PostgreSQL that is running (the name must still end in _test)."
            ) from None
        try:
            exists = await connection.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", name
            )
            if exists:
                return False
            # Quoted identifier: the name came through the guard, but a name is not a value.
            await connection.execute(f'CREATE DATABASE "{name}"')
            return True
        finally:
            await connection.close()
    raise SystemExit(f"could not open a maintenance connection to create {name!r}: {last_error}")


#: PostgreSQL never reuses a dropped column's number, and a table may number at most 1,600. A test
#: database migrated down and up enough times runs out: on 2026-11-10 the shared `familiar_test` had
#: `track_analysis` at 1,599 (1,587 of them dropped), and every migration failed with "tables can
#: have at most 1600 columns". The round-trip tests now use their own database; this repairs the
#: databases they already wore out, well before the limit stops a migration from adding one.
WORN_OUT_AT = 1200


async def worn_out(url: str) -> tuple[str, int] | None:
    """The table with the highest column number, if it is past `WORN_OUT_AT`; otherwise None."""
    parts = make_url(url)
    connection = await asyncpg.connect(
        host=parts.host,
        port=parts.port or 5432,
        user=parts.username,
        password=parts.password,
        database=parts.database,
    )
    try:
        row = await connection.fetchrow(
            """
            SELECT c.relname AS name, max(a.attnum) AS attnum
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r' AND a.attnum > 0
            GROUP BY c.relname ORDER BY 2 DESC LIMIT 1
            """
        )
    finally:
        await connection.close()
    if row and row["attnum"] >= WORN_OUT_AT:
        return row["name"], row["attnum"]
    return None


async def recreate_database(url: str) -> None:
    """Drop and create the database the URL names. Only ever reached through the guard."""
    parts = make_url(url)
    connection = await asyncpg.connect(
        host=parts.host,
        port=parts.port or 5432,
        user=parts.username,
        password=parts.password,
        database="postgres",
    )
    try:
        # Not `WITH (FORCE)`: several sessions share one test database, and ending another's run
        # halfway would be worse than asking for a retry.
        await connection.execute(f'DROP DATABASE IF EXISTS "{parts.database}"')
        await connection.execute(f'CREATE DATABASE "{parts.database}"')
    except asyncpg.ObjectInUseError:
        raise SystemExit(
            f"{parts.database} needs recreating but another session is connected to it. Run this "
            "again once that test run finishes, or point TEST_DATABASE_URL at another *_test name."
        ) from None
    finally:
        await connection.close()


def migrate(url: str) -> None:
    environment = {**os.environ, "DATABASE_URL": url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=environment,
        check=True,
    )


def main() -> int:
    try:
        url = disposable_database_url(os.environ)
    except DisposableDatabaseError as error:
        print(error, file=sys.stderr)
        return 2
    created = asyncio.run(ensure_database(url))
    name = make_url(url).database
    print(f"{'created' if created else 'found'} {name}")
    if not created and (table := asyncio.run(worn_out(url))):
        print(
            f"{name} is worn out ({table[0]} is at column {table[1]} of PostgreSQL's 1,600, from "
            "migrations run down and up); recreating it"
        )
        asyncio.run(recreate_database(url))
    migrate(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
