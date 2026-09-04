"""`sync_database_url` has to produce a DSN psycopg2 will actually accept.

Found on the demo server: every backup failed with

    (psycopg2.ProgrammingError) invalid dsn: invalid connection option "ssl"

because its `DATABASE_URL` ends `?ssl=require`. Dropping `+asyncpg` leaves the
query string untouched, and psycopg2 rejects the whole DSN rather than ignoring
an option it does not know. The NAS's URL has no such parameter, so its nightly
backups were green throughout — a code path that only fails against a
configuration the primary host does not use.
"""

from __future__ import annotations

import pytest

from app.config import Settings


def url(dsn: str) -> str:
    return Settings(database_url=dsn).sync_database_url


def test_the_asyncpg_driver_is_dropped():
    assert url("postgresql+asyncpg://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"


def test_a_url_with_no_query_string_is_untouched():
    assert url("postgresql+asyncpg://u:p@h/db") == "postgresql://u:p@h/db"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("require", "require"),
        ("true", "require"),
        ("1", "require"),
        ("verify-full", "verify-full"),
        ("prefer", "prefer"),
        ("disable", "disable"),
        ("false", "disable"),
    ],
)
def test_ssl_becomes_sslmode(value, expected):
    """Translated, never dropped.

    Discarding `ssl` would silently downgrade a TLS connection to plaintext,
    which is a worse outcome than the error it replaces.
    """
    out = url(f"postgresql+asyncpg://u:p@h/db?ssl={value}")
    assert f"sslmode={expected}" in out
    assert "ssl=" not in out.replace("sslmode=", "")


def test_an_unrecognised_ssl_value_still_requires_tls():
    """Fail closed: an unknown spelling must not become plaintext."""
    assert "sslmode=require" in url("postgresql+asyncpg://u:p@h/db?ssl=banana")


def test_asyncpg_only_options_are_removed():
    out = url(
        "postgresql+asyncpg://u:p@h/db?command_timeout=60&statement_cache_size=0&server_settings=x"
    )
    for gone in ("command_timeout", "statement_cache_size", "server_settings"):
        assert gone not in out, f"{gone} would make psycopg2 reject the DSN"


def test_options_libpq_understands_are_kept():
    out = url("postgresql+asyncpg://u:p@h/db?application_name=familiar&connect_timeout=5")
    assert "application_name=familiar" in out
    assert "connect_timeout=5" in out


def test_the_demo_shaped_url_is_accepted_by_psycopg2():
    """The exact failure, end to end: psycopg2 must parse the result."""
    psycopg2 = pytest.importorskip("psycopg2")
    out = url("postgresql+asyncpg://u:p@h:5432/db?ssl=require")
    # `parse_dsn` is what raised ProgrammingError on the demo.
    parsed = psycopg2.extensions.parse_dsn(out.replace("postgresql://", "postgresql://"))
    assert parsed["sslmode"] == "require"
    assert "ssl" not in parsed
