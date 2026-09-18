"""The suite runs only against a database it is allowed to empty (ADR-0128).

`async_db` deletes every row from eighteen tables before and after each test, and the
session-scoped `TestClient` writes through the real application. Both used to read
`settings.database_url`, whose development default is the ordinary `familiar` database — so the
documented `uv run pytest` command, run with a developer's normal environment, erased their
library. Nothing at the call site said so.

This module is the proof the fixtures now require, and it is deliberately dull: a URL is read
from `TEST_DATABASE_URL` only (never `DATABASE_URL`, and with no fallback to it), its database
name must end in `_test`, and only then is it installed as the URL the application will read.
The check runs from the rootdir `conftest.py`, before `app.config` is imported, because a check
after that import is too late — `settings` is built at import time and the session fixtures may
already have connected (ADR-0128 point 3).

Pure functions over a mapping, so the rule is unit-tested without a database.
"""

from __future__ import annotations

from collections.abc import MutableMapping

from sqlalchemy.engine import make_url

TEST_URL_VARIABLE = "TEST_DATABASE_URL"
APPLICATION_URL_VARIABLE = "DATABASE_URL"
DISPOSABLE_SUFFIX = "_test"

SETUP_INSTRUCTIONS = """\
Backend tests need TEST_DATABASE_URL, and it is not set (ADR-0128).

The suite deletes rows from every table it touches, so it will not run against the database
in DATABASE_URL. From backend/, run

    make test

which creates familiar_test beside the development database, migrates it and sets the
variable for you — or set TEST_DATABASE_URL yourself, to a database whose name ends in _test.
"""


class DisposableDatabaseError(RuntimeError):
    """The test database is missing or is not provably disposable."""


def disposable_database_url(environ: MutableMapping[str, str]) -> str:
    """The URL the suite may use, or a `DisposableDatabaseError` saying why there is none."""
    url = environ.get(TEST_URL_VARIABLE, "").strip()
    if not url:
        raise DisposableDatabaseError(SETUP_INSTRUCTIONS)
    try:
        name = make_url(url).database or ""
    except Exception as error:  # noqa: BLE001 — any parse failure is the same answer
        raise DisposableDatabaseError(
            f"{TEST_URL_VARIABLE} is not a database URL: {url!r} ({error})"
        ) from error
    if not name.endswith(DISPOSABLE_SUFFIX):
        raise DisposableDatabaseError(
            f"{TEST_URL_VARIABLE} names the database {name!r}, whose name does not end in "
            f"{DISPOSABLE_SUFFIX!r}. The suite empties the database it is pointed at, so it only "
            f"runs against one named as disposable (ADR-0128 point 2). There is no opt-out: "
            f"name the database honestly, or point the variable at one that is."
        )
    return url


def install(environ: MutableMapping[str, str]) -> str:
    """Prove the test database and make it the one the application reads.

    Overwrites `DATABASE_URL` for this process: until ADR-0130's `create_app(settings, …)`
    exists, the application and alembic both read `settings.database_url`, and that is built
    from the environment at import. Whatever `DATABASE_URL` held — a developer's real
    library — is what this replaces, on purpose.
    """
    url = disposable_database_url(environ)
    environ[APPLICATION_URL_VARIABLE] = url
    return url
