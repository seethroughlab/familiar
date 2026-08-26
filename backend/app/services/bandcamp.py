"""Bandcamp search service for finding albums to purchase.

**Search uses Bandcamp's own JSON endpoint, not the search page.** That page became a JavaScript
shell: a request for `/search?q=ambient+drone` returns **HTTP 200 and about 3 KB containing no
results at all**. The scraper that read it therefore matched nothing and returned an empty list —
not once with an error, because a 200 with unfamiliar markup is not an exception. Both
`search_bandcamp` and `recommend_bandcamp_purchases` had been answering "no results" for every
query, indistinguishable from a genuinely empty search.

`autocomplete_elastic` is what bandcamp.com's own front end calls. Album detail below still parses
HTML, which still works — a release page is server-rendered where search no longer is.
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class BandcampResult:
    """A Bandcamp search result."""
    result_type: str  # album, track, artist
    name: str
    artist: str | None
    album: str | None  # For tracks
    url: str
    image_url: str | None
    genre: str | None
    release_date: str | None


class BandcampService:
    """Service for searching Bandcamp."""

    BASE_URL = "https://bandcamp.com"
    #: What bandcamp.com's own front end calls. The human-facing `/search` page renders its results
    #: client-side and is not scrapable.
    SEARCH_URL = "https://bandcamp.com/api/bcsearch_public_api/1/autocomplete_elastic"

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            }
        )

    async def search(
        self,
        query: str,
        item_type: str = "a",  # a=album, t=track, b=artist/band
        limit: int = 10,
    ) -> list[BandcampResult]:
        """Search Bandcamp for albums, tracks, or artists.

        Args:
            query: Search query
            item_type: 'a' for albums, 't' for tracks, 'b' for artists/bands
            limit: Maximum results to return

        Returns:
            List of BandcampResult objects
        """
        body = {
            "search_text": query,
            # The endpoint's `search_filter` uses the same letters this method already took.
            "search_filter": item_type,
            "full_page": False,
        }

        try:
            response = await self.client.post(self.SEARCH_URL, json=body)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            # Logged, not swallowed. Returning [] here is indistinguishable from "nothing matched",
            # which is exactly how this integration stayed broken without anyone noticing.
            logger.warning("Bandcamp search failed for %r: %r", query, exc)
            return []

        try:
            payload = response.json()
        except ValueError:
            logger.warning(
                "Bandcamp search returned %d bytes that are not JSON — the endpoint has probably "
                "changed. Query was %r.",
                len(response.text),
                query,
            )
            return []

        raw = (payload.get("auto") or {}).get("results") or []
        results = [r for r in (self._parse_result(item) for item in raw[:limit]) if r]

        if raw and not results:
            # A response full of items that none of which parsed means the shape moved under us.
            # Distinct from an empty search, and the caller must not see them as the same thing.
            logger.warning(
                "Bandcamp returned %d results for %r and none could be parsed — the response "
                "shape has changed.",
                len(raw),
                query,
            )
        return results

    def _parse_result(self, item: dict[str, Any]) -> "BandcampResult | None":
        """Map one `autocomplete_elastic` result onto `BandcampResult`."""
        try:
            kind = {"a": "album", "t": "track", "b": "artist"}.get(str(item.get("type")), "album")
            name = item.get("name")
            # A band has no `item_url_path`; its page *is* the root.
            url = item.get("item_url_path") or item.get("item_url_root")
            if not name or not url:
                return None

            tags = item.get("tag_names") or []
            return BandcampResult(
                result_type=kind,
                # A band result names the band in `name` and has no `band_name`.
                name=str(name),
                artist=str(item["band_name"]) if item.get("band_name") else None,
                album=str(item["album_name"]) if item.get("album_name") else None,
                url=str(url),
                image_url=str(item["img"]) if item.get("img") else None,
                genre=(
                    str(item.get("genre_name"))
                    if item.get("genre_name")
                    else (str(tags[0]) if tags else None)
                ),
                # Not carried by this endpoint. `get_album_details` has it for a specific release.
                release_date=None,
            )
        except Exception:  # noqa: BLE001 - one malformed row must not lose the whole search
            logger.warning("Could not parse a Bandcamp result: %r", item, exc_info=True)
            return None

    async def get_album_details(self, url: str) -> dict[str, Any] | None:  # type: ignore[return]
        """Get details about a specific album.

        Args:
            url: Bandcamp album URL

        Returns:
            Dict with album details or None if not found
        """
        try:
            response = await self.client.get(url)
            response.raise_for_status()
        except httpx.HTTPError:
            return None

        soup = BeautifulSoup(response.text, "html.parser")

        try:
            # Get album name
            title = soup.select_one("h2.trackTitle")
            album_name = title.get_text(strip=True) if title else None

            # Get artist
            artist_link = soup.select_one("#name-section a")
            artist = artist_link.get_text(strip=True) if artist_link else None

            # Get price
            price_el = soup.select_one(".buyItemNy498 .base-text-color")
            price = price_el.get_text(strip=True) if price_el else "Name your price"

            # Get track list
            tracks = []
            track_rows = soup.select(".track_list .track_row_view")
            for row in track_rows:
                track_title = row.select_one(".title-col .title")
                if track_title:
                    tracks.append(track_title.get_text(strip=True))

            # Get cover art
            art = soup.select_one("#tralbumArt img")
            image_url = art.get("src") if art else None

            # Get tags
            tags = [t.get_text(strip=True) for t in soup.select(".tralbumData.tralbum-tags a")]

            return {
                "name": album_name,
                "artist": artist,
                "url": url,
                "price": price,
                "tracks": tracks,
                "track_count": len(tracks),
                "image_url": image_url,
                "tags": tags,
            }
        except Exception:
            return None

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()
