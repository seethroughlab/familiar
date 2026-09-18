"""The rule that keeps the suite off a real database (ADR-0128), tested without one."""

import pytest

from tests.disposable_database import (
    APPLICATION_URL_VARIABLE,
    TEST_URL_VARIABLE,
    DisposableDatabaseError,
    disposable_database_url,
    install,
)

DEV = "postgresql+asyncpg://familiar:familiar@localhost:5432/familiar"
DISPOSABLE = "postgresql+asyncpg://familiar:familiar@localhost:5432/familiar_test"


def test_the_application_url_is_never_a_fallback() -> None:
    """Point 1: an absent test URL is an error with instructions, not a reason to try the
    development database — even when that one is set and would work."""
    with pytest.raises(DisposableDatabaseError) as caught:
        disposable_database_url({APPLICATION_URL_VARIABLE: DEV})
    assert "make test" in str(caught.value)
    assert TEST_URL_VARIABLE in str(caught.value)


def test_a_database_not_named_as_disposable_is_refused() -> None:
    """Point 2: the name is the proof. `familiar` is what CI used to be called, which is why
    CI proved nothing."""
    with pytest.raises(DisposableDatabaseError) as caught:
        disposable_database_url({TEST_URL_VARIABLE: DEV})
    assert "'familiar'" in str(caught.value)
    assert "_test" in str(caught.value)


def test_a_disposable_database_is_accepted_and_installed() -> None:
    environ = {TEST_URL_VARIABLE: DISPOSABLE, APPLICATION_URL_VARIABLE: DEV}
    assert install(environ) == DISPOSABLE
    assert environ[APPLICATION_URL_VARIABLE] == DISPOSABLE, (
        "the application reads DATABASE_URL until ADR-0130's factory; the guard must replace it"
    )


def test_a_blank_or_unparseable_url_is_an_error_not_a_default() -> None:
    with pytest.raises(DisposableDatabaseError):
        disposable_database_url({TEST_URL_VARIABLE: "   "})
    with pytest.raises(DisposableDatabaseError):
        disposable_database_url({TEST_URL_VARIABLE: "not a url"})
