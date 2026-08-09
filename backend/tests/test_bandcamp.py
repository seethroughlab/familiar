"""Tests for Bandcamp search.

**These exist because of a failure that looked exactly like success.** Bandcamp's `/search` page
became a JavaScript shell — HTTP 200, ~3 KB, no results in the HTML — so the scraper matched
nothing and returned `[]`. A 200 with unfamiliar markup raises nothing, so `search_bandcamp` and
`recommend_bandcamp_purchases` answered "no results" for every query, for however long it had been
broken, and nothing anywhere said so.

The tests therefore assert two different things:

1. A real response parses (the ordinary case).
2. **A broken integration is reported, not returned as an empty list.** "Nothing matched your
   query" and "this no longer works" must not be the same answer.

Recorded fixtures rather than the network, so CI does not depend on Bandcamp being up — which is
also the condition these tests exist to detect.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from app.services.bandcamp import BandcampService

# One real result of each type, as `autocomplete_elastic` returns them.
ALBUM = {
    "type": "a",
    "id": 477965531,
    "name": "Inferno",
    "band_name": "Boards of Canada",
    "item_url_root": "https://boardsofcanada.bandcamp.com",
    "item_url_path": "https://boardsofcanada.bandcamp.com/album/inferno",
    "img": "https://f4.bcbits.com/img/3190407865_3.jpg",
    "tag_names": None,
}
TRACK = {
    "type": "t",
    "name": "SISTERS (Boards of Canada remix)",
    "band_name": "Odd Nosdam",
    "album_name": "SISTERS (Boards of Canada remix)",
    "item_url_path": "https://nosdam.bandcamp.com/track/sisters-boards-of-canada-remix",
    "img": "https://f4.bcbits.com/img/4202052153_3.jpg",
}
BAND = {
    "type": "b",
    "name": "Boards of Canada",
    # A band result has no `item_url_path` — its page *is* the root.
    "item_url_root": "https://boardsofcanada.bandcamp.com",
    "tag_names": ["Alternative"],
    "genre_name": "Alternative",
    "img": "https://f4.bcbits.com/img/3190407865_23.jpg",
}


def service_returning(payload, *, status: int = 200, text: str | None = None) -> BandcampService:
    """A service whose HTTP client answers with one canned response."""
    def handler(request: httpx.Request) -> httpx.Response:
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=payload)

    service = BandcampService()
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return service


def wrap(results: list[dict]) -> dict:
    return {"auto": {"results": results}}


class TestParsing:
    @pytest.mark.asyncio
    async def test_parses_an_album(self):
        results = await service_returning(wrap([ALBUM])).search("boards of canada")
        assert len(results) == 1
        album = results[0]
        assert album.result_type == "album"
        assert album.name == "Inferno"
        assert album.artist == "Boards of Canada"
        assert album.url == "https://boardsofcanada.bandcamp.com/album/inferno"

    @pytest.mark.asyncio
    async def test_parses_a_track_with_its_album(self):
        results = await service_returning(wrap([TRACK])).search("sisters", item_type="t")
        assert results[0].result_type == "track"
        assert results[0].album == "SISTERS (Boards of Canada remix)"

    @pytest.mark.asyncio
    async def test_a_band_falls_back_to_its_root_url(self):
        """A band result carries no `item_url_path`; without the fallback it would be dropped."""
        results = await service_returning(wrap([BAND])).search("boards", item_type="b")
        assert results[0].result_type == "artist"
        assert results[0].url == "https://boardsofcanada.bandcamp.com"
        assert results[0].genre == "Alternative"

    @pytest.mark.asyncio
    async def test_limit_is_honoured(self):
        results = await service_returning(wrap([ALBUM] * 10)).search("x", limit=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_one_malformed_row_does_not_lose_the_others(self):
        results = await service_returning(wrap([{"type": "a"}, ALBUM])).search("x")
        assert len(results) == 1, "the good row should survive its neighbour"


class TestBrokenIntegrationIsReported:
    """The half that matters. An empty list must not be the answer to "this is broken"."""

    @pytest.mark.asyncio
    async def test_the_javascript_shell_is_reported(self, caplog):
        """The exact failure that shipped: 200, a few KB, and nothing parseable.

        Bandcamp answers the *old* search URL this way today. If the JSON endpoint ever goes the
        same way, this is the line that says so instead of the search quietly going dark.
        """
        shell = "<!DOCTYPE html><html><body><div id='pgBd'></div></body></html>"
        with caplog.at_level(logging.WARNING):
            results = await service_returning(None, text=shell).search("ambient drone")
        assert results == []
        assert any("not JSON" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_a_changed_result_shape_is_reported(self, caplog):
        """Fifty results, none parseable, means the shape moved — not that nothing matched."""
        moved = [{"kind": "album", "title": "Inferno"} for _ in range(50)]
        with caplog.at_level(logging.WARNING):
            results = await service_returning(wrap(moved)).search("boards of canada")
        assert results == []
        assert any("shape has changed" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_an_http_failure_is_reported(self, caplog):
        with caplog.at_level(logging.WARNING):
            results = await service_returning(wrap([]), status=503).search("x")
        assert results == []
        assert any("search failed" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_a_genuinely_empty_search_is_silent(self, caplog):
        """Guard the guard: a real "nothing matched" must not cry wolf.

        Without this, the tests above would pass just as well against a service that warned on
        every call, which would train whoever reads the log to ignore it.
        """
        with caplog.at_level(logging.WARNING):
            results = await service_returning(wrap([])).search("asdfghjkl no such band")
        assert results == []
        assert not caplog.records, f"unexpected warnings: {[r.getMessage() for r in caplog.records]}"


class TestRequestShape:
    @pytest.mark.asyncio
    async def test_posts_the_query_the_endpoint_expects(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(request.content))
            return httpx.Response(200, json=wrap([ALBUM]))

        service = BandcampService()
        service.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        await service.search("ambient drone", item_type="t")

        assert seen["search_text"] == "ambient drone"
        # The method's `item_type` and the endpoint's `search_filter` share a vocabulary; this
        # pins that, since a silent mismatch would return albums for a track search.
        assert seen["search_filter"] == "t"
