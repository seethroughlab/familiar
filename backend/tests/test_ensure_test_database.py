"""`scripts/ensure_test_database.py` rebuilds a test database that migrations have worn out.

PostgreSQL never reuses a dropped column's number and a table may number at most 1,600, so a
database migrated down and up often enough stops accepting migrations at all. That happened to the
shared `familiar_test` on 2026-11-10. This wears a scratch database out on purpose and checks that
the script notices, and that recreating it clears the condition.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.engine import make_url

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ensure_test_database.py"


def _script():
    spec = importlib.util.spec_from_file_location("ensure_test_database", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def _scratch_url() -> str:
    url = make_url(os.environ["TEST_DATABASE_URL"])
    name = f"{url.database.removesuffix('_test')}_wornout_test"
    return url.set(database=name).render_as_string(hide_password=False)


async def _admin(url: str) -> asyncpg.Connection:
    parts = make_url(url)
    return await asyncpg.connect(
        host=parts.host, port=parts.port or 5432, user=parts.username,
        password=parts.password, database="postgres",
    )


@pytest.mark.asyncio
async def test_a_worn_out_database_is_found_and_recreated():
    script = _script()
    url = _scratch_url()
    parts = make_url(url)
    admin = await _admin(url)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{parts.database}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{parts.database}"')
        db = await asyncpg.connect(
            host=parts.host, port=parts.port or 5432, user=parts.username,
            password=parts.password, database=parts.database,
        )
        try:
            await db.execute("CREATE TABLE fresh (id int)")
            assert await script.worn_out(url) is None
            # What a migration round trip does to a column, the threshold's worth of times.
            await db.execute(
                "DO $$ BEGIN FOR i IN 1.." + str(script.WORN_OUT_AT) + " LOOP "
                "EXECUTE 'ALTER TABLE fresh ADD COLUMN c int'; "
                "EXECUTE 'ALTER TABLE fresh DROP COLUMN c'; END LOOP; END $$"
            )
        finally:
            await db.close()

        found = await script.worn_out(url)
        assert found and found[0] == "fresh" and found[1] > script.WORN_OUT_AT

        await script.recreate_database(url)
        assert await script.worn_out(url) is None
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{parts.database}" WITH (FORCE)')
        await admin.close()


def test_the_round_trip_tests_never_touch_the_shared_database():
    """The cause, not just the cure: every downgrade in that file goes to its own database."""
    source = (Path(__file__).parent / "test_migrations.py").read_text()
    for name in ("test_migration_downgrade_upgrade_cycle", "test_reversible_migration_round_trip"):
        body = source.split(f"def {name}(", 1)[1].split("\ndef ", 1)[0]
        calls = body.count("_alembic_run(")
        assert calls and body.count("database_url=round_trip_database") == calls, name
