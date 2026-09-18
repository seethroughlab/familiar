"""Create the test database if it is missing, and migrate it (ADR-0128 point 4).

    TEST_DATABASE_URL=postgresql+asyncpg://familiar:familiar@localhost:5432/familiar_test \\
        uv run python scripts/ensure_test_database.py

`make test` runs this first, so nobody edits a DSN by hand before a test run. Idempotent: an
existing database is left alone and `alembic upgrade head` is a no-op at head. The URL goes
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
    print(f"{'created' if created else 'found'} {make_url(url).database}")
    migrate(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
