"""iTunes Search API client for audio preview URLs.

Apple's iTunes Search API provides free 30-second AAC previews
with no API key required and excellent catalog coverage.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
REQUEST_TIMEOUT = 10.0


async def search_preview(artist: str, title: str) -> dict | None:
    """Search iTunes for a track and return preview info.

    Returns dict with preview_url, itunes_track_id, itunes_url, artwork_url
    or None if no match found.
    """
    query = f"{artist} {title}"
    params = {
        "term": query,
        "media": "music",
        "entity": "song",
        "limit": "5",
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(ITUNES_SEARCH_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("iTunes search failed for '%s': %s", query, e)
        return None

    results = data.get("results", [])
    if not results:
        return None

    # Pick best match: prefer exact artist+title match
    artist_lower = artist.lower()
    title_lower = title.lower()

    best = None
    best_score = -1

    for r in results:
        if r.get("kind") != "song":
            continue
        if not r.get("previewUrl"):
            continue

        score = 0
        r_artist = (r.get("artistName") or "").lower()
        r_title = (r.get("trackName") or "").lower()

        # Exact matches score highest
        if r_artist == artist_lower:
            score += 10
        elif artist_lower in r_artist or r_artist in artist_lower:
            score += 5

        if r_title == title_lower:
            score += 10
        elif title_lower in r_title or r_title in title_lower:
            score += 5

        if score > best_score:
            best_score = score
            best = r

    if not best or best_score < 5:
        # Require at least a partial match on one field
        return None

    return {
        "preview_url": best["previewUrl"],
        "itunes_track_id": best.get("trackId"),
        "itunes_url": best.get("trackViewUrl"),
        "artwork_url": best.get("artworkUrl100"),
    }
