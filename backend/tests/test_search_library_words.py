"""search_library finds a query that spans fields: "<album> <artist>", as a host naturally asks.

It used to require the whole query inside one field, so "Inferno Boards of Canada" found nothing
on a library holding all eighteen tracks of Boards of Canada's Inferno (2026-10-25).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.db.models import Track, TrackStatus
from app.services.llm.executor import ToolExecutor


def _track(title: str, artist: str, album: str) -> Track:
    return Track(
        id=uuid4(),
        file_path=f"/music/{artist}/{album}/{title}.flac",
        file_hash=f"hash-{uuid4()}",
        title=title,
        artist=artist,
        album=album,
        status=TrackStatus.ACTIVE,
    )


@pytest.fixture
async def library(async_db):
    async_db.add_all([
        _track("Introit", "Boards Of Canada", "Inferno"),
        _track("Roygbiv", "Boards Of Canada", "Music Has the Right to Children"),
        _track("Inferno", "Some Other Band", "Hell"),
    ])
    await async_db.commit()
    return ToolExecutor(db=async_db, profile_id=uuid4())


async def _titles(executor: ToolExecutor, query: str) -> set[str]:
    result = await executor._search_library(query)
    return {t["title"] for t in result["tracks"]}


@pytest.mark.asyncio
class TestAQuerySpanningFields:
    async def test_album_and_artist_find_the_album(self, library):
        assert await _titles(library, "Inferno Boards of Canada") == {"Introit"}

    async def test_word_order_does_not_matter(self, library):
        assert await _titles(library, "boards of canada inferno") == {"Introit"}

    async def test_a_phrase_in_one_field_still_matches(self, library):
        assert await _titles(library, "Inferno") == {"Introit", "Inferno"}

    async def test_every_word_must_match(self, library):
        assert await _titles(library, "Inferno Aphex") == set()
