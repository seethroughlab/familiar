"""Tests run only against disposable databases (ADR-0128).

`tests/conftest.py` calls `install()` from `pytest_configure`, which runs before collection —
and collection is when test modules run their `from app.main import app`. That order is the
whole point: `app.config.settings` reads `DATABASE_URL` when it is constructed, and
`app.db.session` builds an engine from it at import, so a check that runs after either has
happened is a check on a connection already made. `conftest.py` itself imports `app` only
inside fixtures for the same reason. The `async_db` fixture then deletes every row from
eighteen tables in whatever database that engine points at — which, before this module
existed, was the developer's own library if `DATABASE_URL` named it.

Three rules, none of which has an opt-out:

1. Tests read `TEST_DATABASE_URL`, never `DATABASE_URL`. Absent means stop, with instructions.
2. The database's name must end in `_test`. CI's service database is `familiar_test` for this
   reason; a "but it's disposable, honest" flag would make CI configuration a bypass instead
   of evidence.
3. Once accepted, the test URL is installed as `DATABASE_URL` for this process, so every
   reader in `app` — `settings`, the session module, Alembic's `env.py`, the CLI backfills —
   sees the disposable database and nothing else.

This module imports nothing from `app`, on purpose.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

TEST_ENV = "TEST_DATABASE_URL"
APP_ENV = "DATABASE_URL"
REQUIRED_SUFFIX = "_test"

SETUP = """\
Backend tests need a disposable PostgreSQL database named with a `_test` suffix, given as
TEST_DATABASE_URL. They will not fall back to DATABASE_URL, because the suite deletes rows.

The short path, from backend/:

    make test            # starts a throwaway Postgres + Redis, migrates, runs the suite
    make test-services   # just the containers, if you want to run pytest yourself

Then, to run pytest directly:

    TEST_DATABASE_URL=postgresql+asyncpg://familiar:familiar@localhost:5434/familiar_test \\
    REDIS_URL=redis://localhost:6380/0 uv run pytest tests/ -x -q

See docs/decisions/ADR-0128-tests-run-only-against-disposable-databases.md."""


class NotDisposable(Exception):
    """The configured test database cannot be shown to be disposable."""


def database_name(url: str) -> str:
    """The database a SQLAlchemy/libpq URL names, ignoring any query string."""
    return urlparse(url).path.lstrip("/")


def check(url: str | None) -> str:
    """Return `url` if it names a disposable database; raise `NotDisposable` otherwise."""
    if not url:
        raise NotDisposable(f"{TEST_ENV} is not set.\n\n{SETUP}")
    name = database_name(url)
    if not name:
        raise NotDisposable(f"{TEST_ENV} names no database: {url!r}\n\n{SETUP}")
    if not name.endswith(REQUIRED_SUFFIX):
        raise NotDisposable(
            f"{TEST_ENV} names the database {name!r}, which does not end in "
            f"{REQUIRED_SUFFIX!r}. The suite deletes rows, so it only runs against a database "
            f"whose name says it is disposable.\n\n{SETUP}"
        )
    return url


def install(environ: dict[str, str] | None = None) -> str:
    """Validate `TEST_DATABASE_URL` and install it as `DATABASE_URL` for this process.

    Returns the installed URL. `environ` is injectable for tests of this module; the
    default is the real process environment.
    """
    env = os.environ if environ is None else environ
    url = check(env.get(TEST_ENV))
    env[APP_ENV] = url
    return url
