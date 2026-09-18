"""Rootdir conftest: the disposable-database guard, and nothing else (ADR-0128).

Here rather than in `tests/conftest.py` because pytest loads this file first — before that one
imports `app.config` and `app.main` — and the guard has to run before either. A guard that runs
after `settings` is built from the environment has already lost.
"""

import os

import pytest

from tests.disposable_database import DisposableDatabaseError, install

try:
    install(os.environ)
except DisposableDatabaseError as error:
    # `UsageError` stops pytest before collection, with the message and without a traceback:
    # the instructions are the point, and a stack trace would bury them.
    raise pytest.UsageError(str(error)) from None
