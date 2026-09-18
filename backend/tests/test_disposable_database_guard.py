"""The guard that keeps the suite off a real database (ADR-0128).

These tests import nothing from `app`; the guard must be checkable without assembling the
server, because it runs before the server is importable.
"""

from __future__ import annotations

import os

import pytest

from tests import _disposable_database as guard


def test_the_installed_url_is_the_one_the_app_reads() -> None:
    """The guard ran before `app.config` was imported, so settings hold the test URL."""
    from app.config import settings

    assert settings.database_url == os.environ[guard.TEST_ENV]
    assert guard.database_name(settings.database_url).endswith(guard.REQUIRED_SUFFIX)


def test_absent_is_refused_with_setup_instructions() -> None:
    with pytest.raises(guard.NotDisposable) as exc:
        guard.check(None)
    assert "make test" in str(exc.value)
    assert "ADR-0128" in str(exc.value)


def test_the_development_database_name_is_refused() -> None:
    """The exact URL `app/config.py` defaults to must not pass."""
    with pytest.raises(guard.NotDisposable) as exc:
        guard.check("postgresql+asyncpg://familiar:familiar@localhost:5432/familiar")
    assert "'familiar'" in str(exc.value)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://u:p@h:5434/familiar_test",
        "postgresql+asyncpg://u:p@h/familiar_test?ssl=require",
        "postgresql://u:p@h/x_test?command_timeout=60&statement_cache_size=0",
    ],
)
def test_a_test_suffixed_name_passes_regardless_of_query_string(url: str) -> None:
    assert guard.check(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://u:p@h/familiar_test_backup",
        "postgresql+asyncpg://u:p@h/test_familiar",
        "postgresql+asyncpg://u:p@h/familiar?dbname=familiar_test",
        "postgresql+asyncpg://u:p@h/",
    ],
)
def test_near_misses_are_refused(url: str) -> None:
    with pytest.raises(guard.NotDisposable):
        guard.check(url)


def test_install_overwrites_database_url_and_never_reads_it() -> None:
    """DATABASE_URL pointing at a real database is irrelevant — and replaced."""
    env = {
        guard.APP_ENV: "postgresql+asyncpg://u:p@nas/familiar",
        guard.TEST_ENV: "postgresql+asyncpg://u:p@h/familiar_test",
    }
    assert guard.install(env) == env[guard.TEST_ENV]
    assert env[guard.APP_ENV] == env[guard.TEST_ENV]


def test_install_does_not_fall_back_to_database_url() -> None:
    env = {guard.APP_ENV: "postgresql+asyncpg://u:p@h/familiar_test"}
    with pytest.raises(guard.NotDisposable):
        guard.install(env)
    assert env[guard.APP_ENV] == "postgresql+asyncpg://u:p@h/familiar_test"
