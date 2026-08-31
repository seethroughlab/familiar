"""ListenBrainz fresh releases, filtered to artists in this library (ADR-0099 §11).

**One request, then local filtering.** MusicBrainz discovery asks a question per
artist and is bounded by a one-request-per-second limit; this asks once for
everything released recently and intersects the answer with the library. Measured
2026-08-31 against the live library: 7,713 releases in the last 30 days, 2,625
library artists carrying a MusicBrainz id, **225 matches** — for a single HTTP call.

**It shares MusicBrainz identifiers, which is the whole reason to prefer it.**
`release_group_mbid` is the same id `external_album_cache.release_id` already holds
for MusicBrainz-sourced rows, so a release found by both sources collapses onto one
row through the existing partial unique index. No fuzzy artist matching anywhere,
which is where cross-source discovery usually goes wrong — and where Bandcamp
failed this same evaluation: its search has no release dates at all and returns
*Dödsrit — Mortal Coil* when asked for *Coil*.

It also rate-limits **explicitly**, returning `X-RateLimit-Remaining` and
`X-RateLimit-Reset-In`, against MusicBrainz's silent 503 with a retry buried in a
library's `INFO` log. A source that says how much budget is left can be treated
honestly; one that does not has to be inferred from timeouts.

No token is required for the sitewide endpoint. The personalised
`/1/user/{user}/fresh_releases` would need a ListenBrainz account with listening
history in it, which a Last.fm scrobbler does not have — so the personalisation
here comes from *our* library rather than from theirs, which is both better and
free.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

FRESH_RELEASES_URL = "https://api.listenbrainz.org/1/explore/fresh-releases/"

#: How far back to ask. Thirty days is the window that produced 225 matches; the job
#: runs far more often than that, so the overlap is deliberate — a release added to
#: MusicBrainz late still gets seen.
DEFAULT_DAYS = 30

#: The response is large (≈1.4 MB for 14 days, more for 30), so the timeout is
#: generous relative to the rest of discovery. It is one call, not one per artist.
REQUEST_TIMEOUT_SECONDS = 45.0

#: MusicBrainz's "Various Artists" placeholder. **Excluded, and it is not a detail:**
#: 81 of the 225 live matches were compilations credited to it. It is a credit, not
#: an artist anyone follows, and leaving it in makes the surface look like a firehose
#: of unrelated compilations.
VARIOUS_ARTISTS_MBID = "89ad4ac3-39f7-470e-963a-56509c546377"

#: Album and EP only. Of the live matches, 54 were singles — mostly promotional — and
#: a handful were broadcasts. `recommendations.py` already draws this line at
#: album+ep for its own MusicBrainz queries, so this agrees with it rather than
#: inventing a second rule.
WANTED_TYPES = {"Album", "EP"}


def _parse_release_date(value: Any) -> datetime | None:
    """ListenBrainz returns ISO dates; anything else is not worth a guess."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


async def fetch_fresh_releases(
    *, days: int = DEFAULT_DAYS, client: httpx.AsyncClient | None = None
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Every release ListenBrainz considers fresh, plus its rate-limit headers.

    Returns the raw list unfiltered — deciding what is relevant needs the library,
    which this module does not reach into. The headers are returned rather than
    logged because the caller records them as health.
    """
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        response = await client.get(
            FRESH_RELEASES_URL,
            params={"days": days, "sort": "release_date"},
            headers={"User-Agent": "Familiar (https://github.com/seethroughlab/familiar)"},
        )
        rate = {
            key: value
            for key, value in response.headers.items()
            if key.lower().startswith("x-ratelimit")
        }
        response.raise_for_status()
        payload = response.json().get("payload") or {}
        releases = payload.get("releases") or []
        if not isinstance(releases, list):
            # A 200 with an unexpected shape is a failure, not an empty result. The
            # difference matters: one is "nothing new", the other is "we cannot read
            # this any more", and they must not both render as silence.
            raise ValueError(f"unexpected payload shape: {type(releases).__name__}")
        return releases, rate
    finally:
        if owns_client:
            await client.aclose()


def select_for_library(
    releases: list[dict[str, Any]],
    library_artist_mbids: dict[str, str],
) -> list[dict[str, Any]]:
    """Releases by artists this library owns, normalised for the cache writer.

    ``library_artist_mbids`` maps a MusicBrainz artist id to the library's own name
    for that artist — the local name is preferred over ListenBrainz's
    ``artist_credit_name`` so a release lands under the same spelling the rest of the
    library uses, and joins the existing rows for that artist.
    """
    selected: list[dict[str, Any]] = []
    for release in releases:
        if release.get("release_group_primary_type") not in WANTED_TYPES:
            continue
        release_group = release.get("release_group_mbid")
        if not release_group:
            # Without it there is no stable identity, and the partial unique index
            # that dedupes against MusicBrainz rows has nothing to key on.
            continue

        artist_mbids = release.get("artist_mbids") or []
        if VARIOUS_ARTISTS_MBID in artist_mbids:
            continue

        matched = next((mbid for mbid in artist_mbids if mbid in library_artist_mbids), None)
        if matched is None:
            continue

        selected.append(
            {
                "artist_name": library_artist_mbids[matched],
                "musicbrainz_artist_id": matched,
                "release_id": release_group,
                "release_name": release.get("release_name") or "Unknown",
                "release_type": (release.get("release_group_primary_type") or "").lower() or None,
                "release_date": _parse_release_date(release.get("release_date")),
                "artwork_url": (
                    f"https://coverartarchive.org/release/{release['caa_release_mbid']}/front-250"
                    if release.get("caa_release_mbid")
                    else None
                ),
            }
        )
    return selected
