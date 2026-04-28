"""Resolve artist photos via MusicBrainz url-rels → Wikipedia thumbnail.

Last.fm's similar-artist API returns a placeholder image URL for every artist,
so we route through MusicBrainz (which keeps relationships to Wikipedia) and
fetch the real thumbnail from the Wikipedia REST summary endpoint.

Results are cached in ``ExternalArtistImageCache`` keyed by normalized
artist name. A NULL ``image_url`` with a recent ``image_checked_at`` is
a negative cache (artist has no Wikipedia page or no thumbnail) and is
retried after the negative-cache TTL.

For library artists, ``Artist.image_url`` is the authoritative read
source. The resolver writes through to ``Artist.image_url`` whenever a
positive resolution lands and an ``ArtistAlias`` exists for the queried
name — so the next read hits the canonical row directly without
bouncing through the cache table.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import timedelta
from urllib.parse import quote, unquote

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Artist, ArtistAlias, ExternalArtistImageCache
from app.services.external_albums_helpers import normalize_artist_name
from app.services.metadata import musicbrainz
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

POSITIVE_CACHE_TTL = timedelta(days=30)
NEGATIVE_CACHE_TTL = timedelta(hours=12)  # short — so timed-out misses retry
WIKIPEDIA_TIMEOUT_SECONDS = 4.0
USER_AGENT = "Familiar/1.0 (https://github.com/jcrouse/familiar)"


def _wiki_title_from_url(url: str) -> tuple[str, str] | None:
    """Extract (lang, page_title) from a Wikipedia URL.

    Examples:
        https://en.wikipedia.org/wiki/Cocteau_Twins → ("en", "Cocteau_Twins")
        https://de.wikipedia.org/wiki/Slowdive → ("de", "Slowdive")
    """
    if "wikipedia.org/wiki/" not in url:
        return None
    try:
        host_path = url.split("://", 1)[1]
        host, _, path = host_path.partition("/")
        lang = host.split(".", 1)[0]
        if not lang or len(lang) > 5:
            return None
        if not path.startswith("wiki/"):
            return None
        title = path[len("wiki/") :].split("?", 1)[0].split("#", 1)[0]
        title = unquote(title)
        if not title:
            return None
        return lang, title
    except Exception:
        return None


def _pick_wikipedia_url(urls: list[dict[str, str]]) -> str | None:
    """Choose the best Wikipedia URL from MB url-relations. Prefer English."""
    en_url: str | None = None
    other_url: str | None = None
    for rel in urls:
        url = rel.get("url") or ""
        if "wikipedia.org/wiki/" not in url:
            continue
        if "//en.wikipedia.org/" in url and en_url is None:
            en_url = url
        elif other_url is None:
            other_url = url
    return en_url or other_url


async def _fetch_wikipedia_thumbnail(
    client: httpx.AsyncClient,
    lang: str,
    title: str,
    artist_name: str | None = None,
) -> str | None:
    """Fetch a Wikipedia page summary and return ``thumbnail.source`` if any.

    When ``artist_name`` is provided, also verifies the resolved page title
    represents that artist. Defends against stale MB url-rels that point to
    redirected/repurposed Wikipedia pages.
    """
    encoded = quote(title, safe="_()")
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{encoded}"
    try:
        resp = await client.get(url, timeout=WIKIPEDIA_TIMEOUT_SECONDS)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if artist_name is not None and not _title_matches_artist(
            data.get("title"), artist_name
        ):
            return None
        thumb = (data.get("thumbnail") or {}).get("source")
        if isinstance(thumb, str) and thumb.startswith("http"):
            return thumb
        return None
    except Exception:
        return None


# Music-relevant terms used to filter out name-collision Wikipedia pages
# (e.g. "Rafter" → architecture article, "Hecuba" → Greek mythology). When a
# direct Wikipedia hit's description doesn't mention any of these, fall back
# to MB url-rels which point to the artist-specific page.
_MUSIC_TERMS = (
    "music",
    "musician",
    "musical",
    "band",
    "rock",
    "metal",
    "punk",
    "rapper",
    "rap ",
    "hip-hop",
    "hip hop",
    "singer",
    "songwriter",
    "guitarist",
    "drummer",
    "bassist",
    "vocalist",
    "composer",
    "producer",
    "dj",
    "duo",
    "trio",
    "quartet",
    "orchestra",
    "ensemble",
    "choir",
    "record",
    "album",
    "song",
    "jazz",
    "blues",
    "folk",
    "country",
    "soul",
    "reggae",
    "techno",
    "electronic",
    "ambient",
    "indie",
    "shoegaze",
    "dream pop",
    "pop ",
    "performer",
    "recording artist",
    "lyricist",
    "instrumentalist",
)


def _looks_musical(description: str | None) -> bool:
    if not description:
        return False
    desc = description.lower()
    return any(term in desc for term in _MUSIC_TERMS)


def _title_matches_artist(title: str | None, artist_name: str) -> bool:
    """Whether a Wikipedia title represents the requested artist.

    Accepts an exact normalized match, or a Wikipedia disambiguation suffix
    of the form ``" (…)"``. So ``"Beck (musician)"`` matches ``"Beck"`` and
    ``"Paul Banks (musician, born 1978)"`` matches ``"Paul Banks"``, but
    ``"Annie Lennox"`` does NOT match ``"Annie"`` and ``"Jeff Beck"`` does
    NOT match ``"Beck"``. Catches stale MB url-rels and prefix-collision
    opensearch results that would otherwise attach the wrong person's photo.
    """
    if not title:
        return False
    norm_title = normalize_artist_name(title)
    norm_artist = normalize_artist_name(artist_name)
    if not norm_artist:
        return False
    if norm_title == norm_artist:
        return True
    return norm_title.startswith(norm_artist + " (")


def _wikidata_labels_match_artist(entity: dict, artist_name: str) -> bool:
    """Whether a Wikidata entity's labels/aliases match the artist name.

    Defends against stale MB→Wikidata relations pointing to a different
    entity. Checks the English canonical label first, then aliases in any
    language (artists with non-Latin primary names often have an English
    alias).
    """
    norm_artist = normalize_artist_name(artist_name)
    if not norm_artist:
        return False
    labels = entity.get("labels") or {}
    en = labels.get("en") or {}
    if normalize_artist_name(en.get("value") or "") == norm_artist:
        return True
    aliases = entity.get("aliases") or {}
    for lang_aliases in aliases.values():
        if isinstance(lang_aliases, list):
            for a in lang_aliases:
                if normalize_artist_name(a.get("value") or "") == norm_artist:
                    return True
    return False


async def _resolve_via_wikipedia_direct(
    name: str, client: httpx.AsyncClient
) -> str | None:
    """Try Wikipedia REST summary directly by artist name.

    Wikipedia auto-redirects ``/page/summary/{name}`` to the canonical title
    for most notable artists. We only accept the result when the page's
    description looks musical AND the resolved title actually represents
    the requested artist (catches Wikipedia auto-redirects to a same-named
    article on something else).
    """
    # Wikipedia REST expects the title to use underscores for spaces and to be
    # percent-encoded (otherwise commas/parentheses can return "Internal error").
    title = quote(name.replace(" ", "_"), safe="_()")
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    try:
        resp = await client.get(url, timeout=WIKIPEDIA_TIMEOUT_SECONDS)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("type") == "disambiguation":
            return None
        if not _looks_musical(data.get("description") or data.get("extract")):
            return None
        if not _title_matches_artist(data.get("title"), name):
            return None
        thumb = (data.get("thumbnail") or {}).get("source")
        if isinstance(thumb, str) and thumb.startswith("http"):
            return thumb
        return None
    except Exception:
        return None


async def _resolve_via_wikipedia_search(
    name: str,
    client: httpx.AsyncClient,
    hint: str | None = None,
) -> str | None:
    """Search Wikipedia and disambiguate via hint.

    Use cases:
    - "Paul Banks" direct lookup hits a disambiguation page; opensearch returns
      multiple legitimate musicians (born 1978 = Interpol, born 1973 = Shed
      Seven, etc.); the seed-artist hint picks the right one.
    - "Sun Electric" direct lookup also disambiguates; bare opensearch returns
      "Sun Electric (band)" which the title-match check accepts.

    We query opensearch with both the bare name and a ``{name} musician``
    qualifier — bare catches band-suffixed pages, the qualifier catches cases
    where the bare name leans too generic. Results are merged + deduped, then
    each candidate is run through the music-relevance + title-match filters.
    """
    candidates: list[tuple[str, str]] = []  # (title, raw_url)
    seen_titles: set[str] = set()

    async def _opensearch(query: str) -> list[str]:
        try:
            params = {
                "action": "opensearch",
                "search": query,
                "limit": "5",
                "namespace": "0",
                "format": "json",
            }
            resp = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params=params,
                timeout=WIKIPEDIA_TIMEOUT_SECONDS,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            if not isinstance(data, list) or len(data) < 4:
                return []
            return data[3] or []
        except Exception:
            return []

    for query in (name, f"{name} musician"):
        for url in await _opensearch(query):
            if "wikipedia.org/wiki/" not in url:
                continue
            title = url.split("/wiki/", 1)[1].split("?", 1)[0].split("#", 1)[0]
            if title in seen_titles:
                continue
            seen_titles.add(title)
            candidates.append((title, url))

    hint_norm = (hint or "").strip().lower()
    fallback: str | None = None  # first acceptable music page if no hint match

    for title, _ in candidates:
        try:
            url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
            resp = await client.get(url, timeout=WIKIPEDIA_TIMEOUT_SECONDS)
            if resp.status_code != 200:
                continue
            data = resp.json()
        except Exception:
            continue
        if data.get("type") == "disambiguation":
            continue
        desc = data.get("description") or ""
        extract = data.get("extract") or ""
        if not _looks_musical(f"{desc} {extract}"):
            continue
        # Title sanity check — opensearch sometimes returns adjacent articles
        # (e.g. "Paul Barnes" for query "Paul Banks musician"). Require the
        # canonical page title to actually represent the requested artist.
        if not _title_matches_artist(data.get("title"), name):
            continue
        thumb = (data.get("thumbnail") or {}).get("source")
        if not (isinstance(thumb, str) and thumb.startswith("http")):
            continue

        # If we have a disambiguation hint, prefer pages that mention it.
        if hint_norm and hint_norm in extract.lower():
            return thumb
        if fallback is None:
            fallback = thumb

    return fallback


_SPOTIFY_ARTIST_RE = re.compile(r"open\.spotify\.com/artist/[A-Za-z0-9]+")


def _pick_spotify_artist_url(urls: list[dict[str, str]]) -> str | None:
    """Return the first ``open.spotify.com/artist/<id>`` URL from MB url-rels."""
    for rel in urls:
        url = rel.get("url") or ""
        if _SPOTIFY_ARTIST_RE.search(url):
            return url
    return None


async def _resolve_via_spotify_oembed(
    spotify_url: str, client: httpx.AsyncClient, artist_name: str | None = None
) -> str | None:
    """Resolve an artist photo via Spotify's public oembed endpoint.

    No auth required — ``https://open.spotify.com/oembed?url={url}`` returns
    JSON with a ``thumbnail_url`` (320×320 square) and the canonical artist
    title. We verify the title matches the requested artist to defend against
    stale MB url-rels pointing at the wrong Spotify entity.
    """
    try:
        resp = await client.get(
            "https://open.spotify.com/oembed",
            params={"url": spotify_url},
            timeout=WIKIPEDIA_TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception:
        return None

    if artist_name is not None and not _title_matches_artist(
        data.get("title"), artist_name
    ):
        return None
    thumb = data.get("thumbnail_url")
    if isinstance(thumb, str) and thumb.startswith("http"):
        return thumb
    return None


_COMPOUND_SEP_RE = re.compile(
    r"\s*(?:,|&| feat\.?| featuring | with )\s*", re.IGNORECASE
)


def _split_compound_artist(name: str) -> list[str]:
    """Split a compound artist name into ordered candidate components.

    Examples:
        "Harold Budd, Simon Raymonde, Robin Guthrie & Elizabeth Fraser"
            → ["Harold Budd", "Simon Raymonde", "Robin Guthrie", "Elizabeth Fraser"]
        "Beyoncé feat. Jay-Z" → ["Beyoncé", "Jay-Z"]
        "Cocteau Twins" → ["Cocteau Twins"]   # no separators, single element
    """
    parts = [p.strip() for p in _COMPOUND_SEP_RE.split(name)]
    parts = [p for p in parts if p]
    return parts or [name.strip()]


_WIKIDATA_ENTITY_RE = re.compile(r"/wiki/(Q\d+)$")


def _wikidata_entity_id(urls: list[dict[str, str]]) -> str | None:
    for rel in urls:
        url = rel.get("url") or ""
        m = _WIKIDATA_ENTITY_RE.search(url.split("?", 1)[0].split("#", 1)[0])
        if m:
            return m.group(1)
    return None


async def _fetch_wikidata_p18(
    client: httpx.AsyncClient,
    entity_id: str,
    artist_name: str | None = None,
) -> str | None:
    """Look up a Wikidata entity's P18 (image) claim and return a Commons URL.

    Useful when the Wikipedia article has no inline thumbnail but Wikidata
    has a portrait stored against the entity (common for indie/electronic
    artists with terse Wikipedia stubs). When ``artist_name`` is provided,
    also verifies the entity's labels/aliases match — defends against stale
    MB→Wikidata relations pointing at the wrong entity.
    """
    url = f"https://www.wikidata.org/wiki/Special:EntityData/{entity_id}.json"
    try:
        resp = await client.get(url, timeout=WIKIPEDIA_TIMEOUT_SECONDS)
        if resp.status_code != 200:
            return None
        data = resp.json()
        entity = (data.get("entities") or {}).get(entity_id) or {}
        if artist_name is not None and not _wikidata_labels_match_artist(
            entity, artist_name
        ):
            return None
        claims = entity.get("claims") or {}
        p18 = claims.get("P18") or []
        if not p18:
            return None
        filename = (
            (p18[0].get("mainsnak") or {}).get("datavalue", {}).get("value")
        )
        if not isinstance(filename, str) or not filename:
            return None
        # Special:FilePath redirects to the live Commons URL with auto-thumb.
        encoded = quote(filename.replace(" ", "_"))
        return f"https://commons.wikimedia.org/wiki/Special:FilePath/{encoded}?width=330"
    except Exception:
        return None


def strict_mb_artist_lookup(name: str) -> str | None:
    """Look up an artist's MB ID, requiring an exact normalized-name match.

    ``musicbrainz.search_artist`` returns MB's top fuzzy hit, which can be a
    completely different artist for common first names ("Paul Banks" → "Paul
    McCartney", "Cale Parks" → "J.J. Cale"). Resolving an image off that
    would attach the wrong person's photo. Instead, scan the top results and
    accept only one whose canonical name normalizes to the query.
    """
    import musicbrainzngs

    target = normalize_artist_name(name)
    try:
        result = musicbrainzngs.search_artists(artist=name, limit=10)
    except Exception:
        return None
    for cand in result.get("artist-list", [])[:10]:
        try:
            score = int(cand.get("ext:score", 0))
        except (TypeError, ValueError):
            score = 0
        if score < 80:
            continue
        cand_name = cand.get("name") or ""
        if normalize_artist_name(cand_name) == target:
            return cand.get("id")
        # Some MB entries store an alternate sort name that matches better.
        cand_sort = cand.get("sort-name") or ""
        if cand_sort and normalize_artist_name(cand_sort) == target:
            return cand.get("id")
    return None


async def _resolve_via_musicbrainz(
    name: str, mb_id: str | None, client: httpx.AsyncClient
) -> str | None:
    """Run the MB → Wikipedia chain. Blocking MB calls run in a thread.

    Used as a fallback when Wikipedia direct lookup misses (e.g., disambiguation
    or no page at the canonical title). MB's url-rels often have an explicit
    Wikipedia link that bypasses the ambiguity.
    """
    if not mb_id:
        mb_id = await asyncio.to_thread(strict_mb_artist_lookup, name)
    if not mb_id:
        return None

    artist = await asyncio.to_thread(musicbrainz.get_artist_by_id, mb_id)
    if not artist:
        return None

    urls = artist.get("urls") or []

    # First: try the MB-linked Wikipedia page (it's the canonical artist page,
    # bypassing disambiguation that breaks direct lookup by name). The
    # title check defends against stale MB url-rels pointing at the wrong
    # page after a Wikipedia rename or redirect.
    wiki_url = _pick_wikipedia_url(urls)
    if wiki_url:
        parsed = _wiki_title_from_url(wiki_url)
        if parsed:
            lang, title = parsed
            thumb = await _fetch_wikipedia_thumbnail(
                client, lang, title, artist_name=name
            )
            if thumb:
                return thumb

    # Fallback: Wikidata P18 — covers artists whose Wikipedia article has no
    # inline thumbnail but whose Wikidata entity has a portrait. Same
    # stale-relation guard via the entity-label match.
    entity_id = _wikidata_entity_id(urls)
    if entity_id:
        thumb = await _fetch_wikidata_p18(client, entity_id, artist_name=name)
        if thumb:
            return thumb

    # Final fallback: Spotify oembed. Public, no auth. Catches artists
    # without Wikipedia/Wikidata image data (Sun Electric, An April March,
    # plenty of indie/electronic acts) but with a Spotify presence linked
    # from MB. Title-match guard prevents stale-relation mismatches.
    spotify_url = _pick_spotify_artist_url(urls)
    if spotify_url:
        return await _resolve_via_spotify_oembed(
            spotify_url, client, artist_name=name
        )

    return None


async def _resolve_via_wikipedia(
    name: str, client: httpx.AsyncClient, hint: str | None = None
) -> str | None:
    """Try Wikipedia direct first; on miss, fall back to opensearch and
    compound-name split.

    Order:
    1. Direct title lookup (auto-redirects to canonical title; fastest).
    2. Opensearch with hint disambiguation (handles same-name musicians).
    3. Compound-name split (collaborative project names like "Harold Budd,
       Simon Raymonde, Robin Guthrie & Elizabeth Fraser" have no single
       Wikipedia page; the first component is the primary artist whose photo
       we substitute as a sensible fallback).
    """
    url = await _resolve_via_wikipedia_direct(name, client)
    if url:
        return url
    url = await _resolve_via_wikipedia_search(name, client, hint=hint)
    if url:
        return url

    parts = _split_compound_artist(name)
    if len(parts) > 1:
        first = parts[0]
        # Only recurse if the split actually changed the query. Cap recursion
        # at one level by skipping the compound-split path on the inner call.
        url = await _resolve_via_wikipedia_direct(first, client)
        if url:
            return url
        return await _resolve_via_wikipedia_search(first, client, hint=hint)
    return None


async def resolve_artist_image(
    db: AsyncSession,
    artist_name: str,
    *,
    musicbrainz_artist_id: str | None = None,
    hint: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """Return a Wikipedia thumbnail URL for an artist, or None.

    Cache-first: returns immediately on a fresh hit (positive or negative).
    On miss/expiry, runs the MB → Wikipedia chain and persists the result.
    """
    normalized = normalize_artist_name(artist_name)
    cached = await db.get(ExternalArtistImageCache, normalized)

    if cached and cached.image_checked_at is not None:
        ttl = POSITIVE_CACHE_TTL if cached.image_url else NEGATIVE_CACHE_TTL
        if utcnow() - cached.image_checked_at < ttl:
            return cached.image_url

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(headers={"User-Agent": USER_AGENT})
    try:
        # Wikipedia first (direct + opensearch, fast). Fall back to MB
        # url-rels (slow, rate-limited) only when Wikipedia misses entirely.
        image_url = await _resolve_via_wikipedia(artist_name, client, hint=hint)
        if image_url is None:
            image_url = await _resolve_via_musicbrainz(
                artist_name, musicbrainz_artist_id, client,
            )
    finally:
        if owns_client:
            await client.aclose()

    now = utcnow()
    if cached is None:
        cached = ExternalArtistImageCache(
            name_normalized=normalized,
            artist_name=artist_name,
            image_url=image_url,
            image_checked_at=now,
        )
        db.add(cached)
    else:
        cached.image_url = image_url
        cached.image_checked_at = now

    # Write-through to Artist.image_url for library artists (positive
    # results only — a NULL image_url here is a negative-cache marker
    # and must not overwrite a previously-resolved Artist.image_url).
    if image_url is not None:
        await _write_through_to_artist(db, normalized, image_url, now)

    try:
        await db.flush()
    except Exception as e:
        logger.warning(f"Failed to persist artist image for {artist_name}: {e}")

    return image_url


async def _write_through_to_artist(
    db: AsyncSession,
    normalized: str,
    image_url: str,
    checked_at,
) -> None:
    """Mirror a freshly-resolved image onto ``Artist.image_url`` when an
    alias exists for the queried name. Library-artist endpoints read
    from ``Artist.image_url`` first; this keeps that column current
    without a second resolver pass."""
    alias = await db.get(ArtistAlias, normalized)
    if alias is None:
        return
    artist_row = await db.get(Artist, alias.artist_id)
    if artist_row is None:
        return
    artist_row.image_url = image_url
    artist_row.image_checked_at = checked_at


async def _read_cached(
    db: AsyncSession, names: list[str]
) -> tuple[dict[str, str | None], dict[str, ExternalArtistImageCache], dict[str, str]]:
    """Read cached images for ``names``. Returns (hits, rows_by_norm, norm→name)."""
    normalized_to_name = {normalize_artist_name(n): n for n in names}
    rows = (
        (
            await db.execute(
                select(ExternalArtistImageCache).where(
                    ExternalArtistImageCache.name_normalized.in_(
                        list(normalized_to_name)
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    cached_by_norm: dict[str, ExternalArtistImageCache] = {}
    cached_image: dict[str, str | None] = {}
    now = utcnow()
    for row in rows:
        norm = row.name_normalized
        cached_by_norm[norm] = row
        if row.image_checked_at is not None:
            ttl = POSITIVE_CACHE_TTL if row.image_url else NEGATIVE_CACHE_TTL
            if now - row.image_checked_at < ttl:
                cached_image[normalized_to_name[norm]] = row.image_url
    return cached_image, cached_by_norm, normalized_to_name


async def _persist_results(
    db: AsyncSession,
    fresh: dict[str, str | None],
    cached_by_norm: dict[str, ExternalArtistImageCache],
) -> None:
    write_now = utcnow()
    for name, url in fresh.items():
        norm = normalize_artist_name(name)
        existing = cached_by_norm.get(norm)
        if existing is None:
            db.add(
                ExternalArtistImageCache(
                    name_normalized=norm,
                    artist_name=name,
                    image_url=url,
                    image_checked_at=write_now,
                )
            )
        else:
            existing.image_url = url
            existing.image_checked_at = write_now
        # Write-through to Artist.image_url for library artists (positive
        # only — see resolve_artist_image for the rationale).
        if url is not None:
            await _write_through_to_artist(db, norm, url, write_now)
    try:
        await db.flush()
    except Exception as e:
        logger.warning(f"Failed to flush artist images: {e}")


async def resolve_many_artist_images(
    db: AsyncSession,
    items: list[tuple[str, str | None]] | list[str],
    *,
    wikipedia_timeout: float = 4.0,
) -> dict[str, str | None]:
    """Fast synchronous Wikipedia resolution for the ``/discover`` request path.

    Each item is ``(name, hint)`` where ``hint`` is an optional disambiguation
    string (typically the seed artist that surfaced this recommendation) used
    to pick the right page when multiple candidates share a name (e.g. three
    "Paul Banks" musicians). For backwards compat ``items`` may also be a flat
    ``list[str]``. Returns cached images + any Wikipedia hits resolved within
    ``wikipedia_timeout``. Names that miss are NOT negative-cached here — the
    caller schedules a background task to run the slow MB chain.
    """
    if not items:
        return {}

    # Normalize input to (name, hint) tuples.
    pairs: list[tuple[str, str | None]] = [
        (i, None) if isinstance(i, str) else i for i in items
    ]
    names = [name for name, _ in pairs]
    hint_by_name = {name: hint for name, hint in pairs}

    cached_image, cached_by_norm, _ = await _read_cached(db, names)
    misses = [n for n in names if n not in cached_image]
    results: dict[str, str | None] = dict(cached_image)
    if not misses:
        return results

    fresh: dict[str, str | None] = {}
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        wiki_tasks = {
            name: asyncio.create_task(
                _resolve_via_wikipedia(name, client, hint=hint_by_name.get(name))
            )
            for name in misses
        }
        try:
            await asyncio.wait_for(
                asyncio.gather(*wiki_tasks.values(), return_exceptions=True),
                timeout=wikipedia_timeout,
            )
        except TimeoutError:
            for t in wiki_tasks.values():
                if not t.done():
                    t.cancel()

        for name, task in wiki_tasks.items():
            if task.done() and not task.cancelled():
                try:
                    url = task.result()
                except Exception:
                    url = None
                if url is not None:
                    fresh[name] = url

    if fresh:
        await _persist_results(db, fresh, cached_by_norm)
        results.update(fresh)
    return results


async def _background_resolve_full_chain(
    items: list[tuple[str, str | None]],
) -> None:
    """Run the full Wikipedia + MB + Wikidata chain for ``items``, persisting results.

    Each item is ``(name, hint)`` where ``hint`` is the seed artist used for
    Wikipedia opensearch disambiguation. Spawns its own engine + session via
    ``create_task_engine_session()`` so it doesn't share the request's
    session. Negative-caches every input so subsequent dashboard loads hit
    the cache instantly. No time pressure: MB's 1 RPS is fine off the
    request path.
    """
    if not items:
        return

    # Late import to avoid a top-level circular dep with app.db.session
    from app.db.session import create_task_engine_session

    names = [name for name, _ in items]
    hint_by_name = {name: hint for name, hint in items}

    engine, session_maker = create_task_engine_session()
    try:
        async with session_maker() as db:
            cached_image, cached_by_norm, _ = await _read_cached(db, names)
            misses = [n for n in names if n not in cached_image]
            if not misses:
                return

            fresh: dict[str, str | None] = {}
            async with httpx.AsyncClient(
                headers={"User-Agent": USER_AGENT}
            ) as client:
                # Wikipedia direct + opensearch chain for each miss.
                wiki_tasks = {
                    name: asyncio.create_task(
                        _resolve_via_wikipedia(
                            name, client, hint=hint_by_name.get(name)
                        )
                    )
                    for name in misses
                }
                await asyncio.gather(
                    *wiki_tasks.values(), return_exceptions=True
                )

                still_missing: list[str] = []
                for name, task in wiki_tasks.items():
                    try:
                        url = task.result() if task.done() else None
                    except Exception:
                        url = None
                    if url is not None:
                        fresh[name] = url
                    else:
                        still_missing.append(name)

                # MB + Wikidata chain — slow (1 RPS) but no time budget.
                for name in still_missing:
                    try:
                        fresh[name] = await _resolve_via_musicbrainz(
                            name, None, client
                        )
                    except Exception as e:
                        logger.debug(f"background MB resolve failed for {name}: {e}")
                        fresh[name] = None

            await _persist_results(db, fresh, cached_by_norm)
            await db.commit()
    except Exception as e:
        logger.warning(f"Background artist image resolution failed: {e}")
    finally:
        await engine.dispose()


def schedule_background_resolve(
    items: list[tuple[str, str | None]] | list[str],
) -> asyncio.Task | None:
    """Fire-and-forget background resolution for ``items``.

    ``items`` is a list of ``(name, hint)`` tuples (or bare names — in which
    case hints are None). Safe to call from a request handler — the task
    lives independently of the request's session/lifecycle.
    """
    if not items:
        return None
    pairs: list[tuple[str, str | None]] = [
        (i, None) if isinstance(i, str) else i for i in items
    ]
    return asyncio.create_task(_background_resolve_full_chain(pairs))
