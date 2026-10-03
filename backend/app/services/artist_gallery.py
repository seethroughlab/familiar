"""An artist's photo gallery (ADR-0149).

Many photos per artist, kept in ``artist_images``:

- **Wikimedia Commons, always.** Reached through the artist's Wikidata item — the QID from
  MusicBrainz's ``wikidata`` relation, using the stored ``Artist.musicbrainz_id`` when there is one.
  Every P18 image (the resolver in ``artist_image.py`` takes only the first) and the photographs in
  the item's P373 Commons category.
- **fanart.tv, only when ``fanarttv_api_key`` is set**, keyed by MusicBrainz ID: artist thumbnails
  and backgrounds.

Each row keeps what its licence asks to be shown beside the photo — author, licence, source page —
because the apps show it (point 3). Images stay external URLs (point 4). Fetching is background
work only (point 5): :func:`schedule_gallery_fetch` from the detail route when a gallery is missing
or stale, and :func:`sweep` from a deferrable scheduled job; both stand down while background work
is paused (ADR-0138).
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Artist, ArtistImage
from app.services.artist_image import (
    USER_AGENT,
    _wikidata_entity_id,
    _wikidata_labels_match_artist,
    strict_mb_artist_lookup,
)
from app.services.metadata import musicbrainz
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

#: At most this many photos are kept per artist (point 7).
GALLERY_MAX = 24
#: A gallery older than this is fetched again.
REFRESH_AFTER = timedelta(days=90)
#: Commons category photos smaller than this on their short side are left out (point 7). P18
#: portraits are curated on Wikidata already, so they get a lower bar.
MIN_SHORT_SIDE = 600
MIN_SHORT_SIDE_PORTRAIT = 300
#: The width asked of Commons for the thumbnail; the large URL is derived from it.
THUMB_WIDTH = 400
LARGE_WIDTH = 1600
#: How many category files to look at before filtering.
CATEGORY_LIMIT = 60
TIMEOUT = 10.0

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
FANART_API = "https://webservice.fanart.tv/v3/music/{mbid}"

PHOTO_MIME = {"image/jpeg", "image/png", "image/webp"}
#: File titles that are not photographs of the artist, whatever their category says.
NOT_A_PHOTO = re.compile(
    r"logo|signature|autograph|album[ _-]?cover|cover[ _-]?art|poster|flyer|ticket|setlist|"
    r"wordmark|\.svg$|\.gif$|\.tiff?$|\.pdf$",
    re.IGNORECASE,
)

#: Ranking tiers (point 7). The owner's chosen main photo is placed first when the gallery is read.
TIER_P18, TIER_FANART_THUMB, TIER_CATEGORY, TIER_FANART_BACKGROUND = 1, 2, 3, 4


@dataclass
class Candidate:
    source: str
    source_id: str
    kind: str
    url: str
    thumb_url: str
    width: int | None
    height: int | None
    author: str | None
    license: str | None
    license_url: str | None
    page_url: str | None
    tier: int


# --- Wikidata and Commons ------------------------------------------------------------------------


def _strip_html(value: str | None) -> str | None:
    """Commons' extmetadata carries HTML (a linked author, a licence wrapped in a span)."""
    if not value:
        return None
    text = html.unescape(re.sub(r"<[^>]+>", " ", value))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def wikidata_images(entity: dict) -> tuple[list[str], str | None]:
    """Every P18 file name, and the P373 Commons category, of a Wikidata entity."""
    claims = entity.get("claims") or {}

    def values(prop: str) -> list[str]:
        out = []
        for claim in claims.get(prop) or []:
            value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
            if isinstance(value, str) and value:
                out.append(value)
        return out

    category = values("P373")
    return values("P18"), (category[0] if category else None)


async def _wikidata_entity(client: httpx.AsyncClient, qid: str) -> dict | None:
    url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
    resp = await client.get(url, timeout=TIMEOUT)
    if resp.status_code != 200:
        return None
    return ((resp.json().get("entities") or {}).get(qid)) or None


def _large_url(original: str, thumb: str, width: int | None) -> str:
    """The ~1600px rendition: the original when it is no wider, else the thumb URL resized.

    Commons serves any width under ``/thumb/…/{N}px-name``, so the large URL is the thumbnail URL
    with its width swapped rather than a second API call.
    """
    if not width or width <= LARGE_WIDTH or f"/{THUMB_WIDTH}px-" not in thumb:
        return original
    return thumb.replace(f"/{THUMB_WIDTH}px-", f"/{LARGE_WIDTH}px-")


def commons_candidate(page: dict, *, kind: str, tier: int) -> Candidate | None:
    """A Commons file page from ``prop=imageinfo``, as a gallery candidate, or None if it is not a
    photograph worth showing."""
    title = page.get("title") or ""
    infos = page.get("imageinfo") or []
    if not title or not infos:
        return None
    info = infos[0]
    if info.get("mime") not in PHOTO_MIME:
        return None
    width, height = info.get("width"), info.get("height")
    short = min(width or 0, height or 0)
    if short < (MIN_SHORT_SIDE_PORTRAIT if kind == "portrait" else MIN_SHORT_SIDE):
        return None
    if kind != "portrait" and NOT_A_PHOTO.search(title):
        return None
    original = info.get("url")
    thumb = info.get("thumburl") or original
    if not original or not thumb:
        return None
    meta = info.get("extmetadata") or {}
    return Candidate(
        source="commons",
        source_id=title,
        kind=kind,
        url=_large_url(original, thumb, width),
        thumb_url=thumb,
        width=width,
        height=height,
        author=_strip_html((meta.get("Artist") or {}).get("value")),
        license=_strip_html((meta.get("LicenseShortName") or {}).get("value")),
        license_url=_strip_html((meta.get("LicenseUrl") or {}).get("value")),
        page_url=info.get("descriptionurl"),
        tier=tier,
    )


async def _commons_pages(
    client: httpx.AsyncClient, *, titles: list[str] | None = None, category: str | None = None
) -> list[dict]:
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "iiextmetadatafilter": "Artist|LicenseShortName|LicenseUrl",
        "iiurlwidth": str(THUMB_WIDTH),
    }
    if titles:
        params["titles"] = "|".join(f"File:{t}" for t in titles)
    elif category:
        params.update(
            generator="categorymembers",
            gcmtitle=f"Category:{category}",
            gcmtype="file",
            gcmlimit=str(CATEGORY_LIMIT),
        )
    else:
        return []
    resp = await client.get(COMMONS_API, params=params, timeout=TIMEOUT)
    if resp.status_code != 200:
        return []
    pages = (resp.json().get("query") or {}).get("pages") or []
    if titles:
        # The API returns pages in its own order; P18 order is the entity's, which is the point.
        order = {f"File:{t}".replace("_", " "): i for i, t in enumerate(titles)}
        pages.sort(key=lambda p: order.get(p.get("title", ""), len(order)))
    return pages


# --- fanart.tv -----------------------------------------------------------------------------------


async def fanart_candidates(client: httpx.AsyncClient, mbid: str, key: str) -> list[Candidate]:
    resp = await client.get(FANART_API.format(mbid=mbid), params={"api_key": key}, timeout=TIMEOUT)
    if resp.status_code != 200:
        return []
    data = resp.json()
    out: list[Candidate] = []
    for field, kind, tier in (
        ("artistthumb", "portrait", TIER_FANART_THUMB),
        ("artistbackground", "background", TIER_FANART_BACKGROUND),
    ):
        items = sorted(data.get(field) or [], key=lambda i: -int(i.get("likes") or 0))
        for item in items:
            url = item.get("url")
            if not url or not item.get("id"):
                continue
            out.append(
                Candidate(
                    source="fanarttv",
                    source_id=str(item["id"]),
                    kind=kind,
                    url=url,
                    thumb_url=url.replace("/fanart/", "/preview/"),
                    width=None,
                    height=None,
                    author=None,
                    license="fanart.tv",
                    license_url="https://fanart.tv/terms-and-conditions/",
                    page_url=f"https://fanart.tv/artist/{mbid}",
                    tier=tier,
                )
            )
    return out


# --- The whole fetch -----------------------------------------------------------------------------


def rank(candidates: list[Candidate]) -> list[Candidate]:
    """Point 7's order, duplicates dropped, cut to :data:`GALLERY_MAX`. Within a tier, the source's
    own order is kept: P18 as the entity lists it, fanart.tv by likes, the category as listed."""
    seen: set[tuple[str, str]] = set()
    out: list[Candidate] = []
    for c in sorted(candidates, key=lambda c: c.tier):  # sorted() is stable
        key = (c.source, c.source_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out[:GALLERY_MAX]


async def gather_candidates(
    client: httpx.AsyncClient, artist_name: str, mbid: str | None, fanart_key: str | None
) -> list[Candidate]:
    """Everything both sources offer for one artist, unranked."""
    candidates: list[Candidate] = []
    if not mbid:
        return candidates

    mb = await asyncio.to_thread(musicbrainz.get_artist_by_id, mbid)
    qid = _wikidata_entity_id((mb or {}).get("urls") or [])
    if qid:
        entity = await _wikidata_entity(client, qid)
        # The resolver's guard against a stale MusicBrainz relation to the wrong entity.
        if entity and _wikidata_labels_match_artist(entity, artist_name):
            p18, category = wikidata_images(entity)
            if p18:
                for page in await _commons_pages(client, titles=p18):
                    c = commons_candidate(page, kind="portrait", tier=TIER_P18)
                    if c:
                        candidates.append(c)
            if category:
                for page in await _commons_pages(client, category=category):
                    c = commons_candidate(page, kind="photo", tier=TIER_CATEGORY)
                    if c:
                        candidates.append(c)

    if fanart_key:
        candidates += await fanart_candidates(client, mbid, fanart_key)
    return candidates


async def store(db: AsyncSession, artist: Artist, ranked: list[Candidate]) -> int:
    """Upsert the ranked photos by ``(source, source_id)``, keeping ``hidden``. A row the sources no
    longer offer is dropped unless it is hidden: a hidden row is the owner's decision, kept so the
    photo stays hidden if a source offers it again. Returns how many are stored and visible."""
    now = utcnow()
    existing = {
        (row.source, row.source_id): row
        for row in (
            await db.execute(select(ArtistImage).where(ArtistImage.artist_id == artist.id))
        ).scalars()
    }
    wanted: set[tuple[str, str]] = set()
    kept: list[ArtistImage] = []
    for position, c in enumerate(ranked):
        key = (c.source, c.source_id)
        wanted.add(key)
        row = existing.get(key)
        if row is None:
            row = ArtistImage(artist_id=artist.id, source=c.source, source_id=c.source_id, hidden=False)
            db.add(row)
        row.kind, row.url, row.thumb_url = c.kind, c.url, c.thumb_url
        row.width, row.height = c.width, c.height
        row.author, row.license, row.license_url, row.page_url = (
            c.author, c.license, c.license_url, c.page_url,
        )
        row.rank, row.fetched_at = position, now
        kept.append(row)
    for key, row in existing.items():
        if key not in wanted and not row.hidden:
            await db.delete(row)
    artist.gallery_fetched_at = now
    return sum(1 for row in kept if not row.hidden)


async def fetch_gallery(
    db: AsyncSession, artist: Artist, client: httpx.AsyncClient, *, fanart_key: str | None
) -> int:
    """Fetch and store one artist's gallery. The caller commits."""
    mbid = artist.musicbrainz_id or await asyncio.to_thread(strict_mb_artist_lookup, artist.name)
    candidates = await gather_candidates(client, artist.name, mbid, fanart_key)
    return await store(db, artist, rank(candidates))


# --- Scheduling ----------------------------------------------------------------------------------

_in_flight: set[UUID] = set()


def is_stale(artist: Artist) -> bool:
    fetched = artist.gallery_fetched_at
    return fetched is None or utcnow() - fetched > REFRESH_AFTER


def is_fetching(artist_id: UUID) -> bool:
    return artist_id in _in_flight


def _fanart_key() -> str | None:
    from app.services.app_settings import get_app_settings_service

    return get_app_settings_service().get_effective("fanarttv_api_key")


async def _fetch_in_background(artist_ids: list[UUID]) -> None:
    from app.db.session import create_task_engine_session

    engine, session_maker = create_task_engine_session()
    try:
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
            key = _fanart_key()
            for artist_id in artist_ids:
                try:
                    async with session_maker() as db:
                        artist = await db.get(Artist, artist_id)
                        if artist is None:
                            continue
                        count = await fetch_gallery(db, artist, client, fanart_key=key)
                        await db.commit()
                        logger.info("Artist gallery: %s, %d photos", artist.name, count)
                except Exception as e:
                    logger.warning("Artist gallery fetch failed for %s: %s", artist_id, e)
                finally:
                    _in_flight.discard(artist_id)
    finally:
        for artist_id in artist_ids:
            _in_flight.discard(artist_id)
        await engine.dispose()


def schedule_gallery_fetch(artist: Artist) -> asyncio.Task | None:
    """Fetch an artist's gallery in the background, if it is missing or stale and nothing is
    fetching it already. Never awaited on the request path. Stands down while background work is
    paused (ADR-0138), like the sweep."""
    from app.config import settings
    from app.services.background.pause import background_pause

    if not settings.artist_gallery_fetch:
        return None
    if background_pause.paused or artist.id in _in_flight or not is_stale(artist):
        return None
    _in_flight.add(artist.id)
    return asyncio.create_task(_fetch_in_background([artist.id]))


async def sweep(db: AsyncSession, limit: int = 60) -> int:
    """One tick of the library-wide fetch: up to ``limit`` artists whose gallery is missing or
    stale, those with a MusicBrainz ID first (they cost no search). Returns how many it fetched."""
    from app.config import settings

    if not settings.artist_gallery_fetch:
        return 0
    cutoff = utcnow() - REFRESH_AFTER
    rows = (
        await db.execute(
            select(Artist.id)
            .where(or_(Artist.gallery_fetched_at.is_(None), Artist.gallery_fetched_at < cutoff))
            .order_by(Artist.musicbrainz_id.is_(None), Artist.gallery_fetched_at.nulls_first())
            .limit(limit)
        )
    ).scalars().all()
    ids = [i for i in rows if i not in _in_flight]
    _in_flight.update(ids)
    await _fetch_in_background(ids)
    return len(ids)
