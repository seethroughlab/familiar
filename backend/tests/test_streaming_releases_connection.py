"""A streaming endpoint must not hold a database connection for the length of its response.

On 2026-08-02 a bulk download of 1,720 favourites produced **2,416** identical errors:

    QueuePool limit of size 20 overflow 20 reached, connection timed out, timeout 30.00

A FastAPI ``yield`` dependency lives until the response has finished *sending*, so every in-flight
download pinned one of the pool's 40 connections for its whole transfer. The Mac client then stored
834 of the resulting 500 bodies as ``.mp3`` files, and nothing noticed until one was played.

These tests cover the two halves of the fix. Neither needs a database: the interesting behaviour is
when the session is released and whether the dependency then goes looking for another connection.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.deps import get_db, release_connection


class TestReleaseConnection:
    """The handler's half: give the connection back before the body is sent."""

    @pytest.mark.asyncio
    async def test_it_closes_the_session(self):
        session = AsyncMock()
        await release_connection(session)
        session.close.assert_awaited_once()


class TestGetDbAfterAnEarlyRelease:
    """The dependency's half, and the part that is easy to get wrong.

    ``get_db`` used to commit unconditionally after the handler returned. Left that way, an early
    release would hand the connection back and the commit would immediately take *another* one — at
    the end of the stream rather than the start, which is the same bug wearing a different hat.
    """

    @pytest.mark.asyncio
    async def test_it_does_not_commit_a_session_the_handler_released(self, monkeypatch):
        session = AsyncMock()
        # What a released session reports: no transaction to commit.
        session.in_transaction = MagicMock(return_value=False)
        monkeypatch.setattr("app.api.deps.async_session_maker", _maker_yielding(session))

        agen = get_db()
        await agen.asend(None)
        with pytest.raises(StopAsyncIteration):
            await agen.asend(None)

        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_it_still_commits_an_ordinary_request(self, monkeypatch):
        """The overwhelming majority of endpoints return JSON and never release early."""
        session = AsyncMock()
        session.in_transaction = MagicMock(return_value=True)
        monkeypatch.setattr("app.api.deps.async_session_maker", _maker_yielding(session))

        agen = get_db()
        await agen.asend(None)
        with pytest.raises(StopAsyncIteration):
            await agen.asend(None)

        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_failure_still_rolls_back(self, monkeypatch):
        session = AsyncMock()
        session.in_transaction = MagicMock(return_value=True)
        monkeypatch.setattr("app.api.deps.async_session_maker", _maker_yielding(session))

        agen = get_db()
        await agen.asend(None)
        with pytest.raises(RuntimeError):
            await agen.athrow(RuntimeError("boom"))

        session.rollback.assert_awaited_once()
        session.commit.assert_not_awaited()


def _maker_yielding(session):
    """Stand in for ``async_session_maker()``, whose result is an async context manager."""
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=context)
