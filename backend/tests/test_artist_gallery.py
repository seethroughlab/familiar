"""An artist's photo gallery (ADR-0149).

The responses below are shaped like Wikidata's entity JSON, the Commons API's ``prop=imageinfo``
(``formatversion=2``) and fanart.tv's ``/v3/music/{mbid}``, cut to the fields the service reads.
Each source answers through an ``httpx.MockTransport``, so no test reaches the network.
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.db.models import Artist, ArtistAlias, ArtistImage, Track, TrackStatus
from app.services import artist_gallery as gallery
from app.services import artist_image
from app.services.artist_resolver import normalize_artist_name
from tests.conftest import make_profile_headers

MBID = "87c5dedd-371d-4a53-9f7f-80522fb7f3cb"
QID = "Q42"
NAME = "Björk"


def _info(title: str, *, mime="image/jpeg", w=2400, h=3000, author='<a href="//x">Jane Doe</a>',
          lic="CC BY-SA 4.0") -> dict:
    name = title.replace(" ", "_")
    return {
        "title": f"File:{title}",
        "imageinfo": [{
            "url": f"https://upload.wikimedia.org/wikipedia/commons/a/ab/{name}",
            "thumburl": f"https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/{name}/400px-{name}",
            "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{name}",
            "mime": mime, "width": w, "height": h,
            "extmetadata": {
                "Artist": {"value": author},
                "LicenseShortName": {"value": lic},
                "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"},
            },
        }],
    }


ENTITY = {
    "entities": {QID: {
        "labels": {"en": {"value": NAME}},
        "claims": {
            "P18": [{"mainsnak": {"datavalue": {"value": "Bjork Cannes 2000.jpg"}}},
                    {"mainsnak": {"datavalue": {"value": "Bjork 2007 portrait.jpg"}}}],
            "P373": [{"mainsnak": {"datavalue": {"value": "Björk"}}}],
        },
    }}
}
# Returned out of order on purpose: P18 order is the entity's, not the API's.
P18_PAGES = {"query": {"pages": [_info("Bjork 2007 portrait.jpg"), _info("Bjork Cannes 2000.jpg")]}}
CATEGORY_PAGES = {"query": {"pages": [
    _info("Bjork live Roskilde.jpg"),
    _info("Bjork Cannes 2000.jpg"),                       # also a P18 image: kept once
    _info("Bjork logo.png", mime="image/png"),            # a logo
    _info("Bjork signature.svg", mime="image/svg+xml"),   # not a photograph
    _info("Bjork tiny.jpg", w=500, h=400),                # too small for a category photo
    _info("Homogenic cover art.jpg"),                     # an album cover
]}}
FANART = {
    "artistthumb": [{"id": "11", "url": "https://assets.fanart.tv/fanart/music/x/artistthumb/a.jpg", "likes": "2"},
                    {"id": "12", "url": "https://assets.fanart.tv/fanart/music/x/artistthumb/b.jpg", "likes": "9"}],
    "artistbackground": [{"id": "21", "url": "https://assets.fanart.tv/fanart/music/x/artistbackground/c.jpg", "likes": "1"}],
}


def _client(*, fanart_calls: list | None = None, entity=ENTITY) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "wikidata.org" in url:
            return httpx.Response(200, json=entity)
        if "commons.wikimedia.org/w/api.php" in url:
            if request.url.params.get("generator") == "categorymembers":
                return httpx.Response(200, json=CATEGORY_PAGES)
            return httpx.Response(200, json=P18_PAGES)
        if "fanart.tv" in url:
            if fanart_calls is not None:
                fanart_calls.append(url)
            return httpx.Response(200, json=FANART)
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def no_image_resolver_traffic(monkeypatch):
    """Opening an artist with no picture schedules the existing resolver, which reaches Wikipedia.
    Here it would also race the test: it once wrote Björk's Wikipedia thumbnail over a main picture
    the test had just chosen (the bug the conditional UPDATE in `_write_through_to_artist` fixes)."""
    monkeypatch.setattr(artist_image, "schedule_background_resolve", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def musicbrainz_knows_the_artist(monkeypatch):
    monkeypatch.setattr(
        gallery.musicbrainz, "get_artist_by_id",
        lambda mbid: {"urls": [{"type": "wikidata", "url": f"https://www.wikidata.org/wiki/{QID}"}]},
    )
    monkeypatch.setattr(gallery, "strict_mb_artist_lookup", lambda name: MBID)


async def _candidates(*, key: str | None = None, calls: list | None = None):
    async with _client(fanart_calls=calls) as client:
        return gallery.rank(await gallery.gather_candidates(client, NAME, MBID, key))


async def test_every_p18_image_is_kept_in_the_entitys_order():
    """The resolver takes `p18[0]` only; the gallery wants them all, and in Wikidata's order."""
    ranked = await _candidates()
    portraits = [c.source_id for c in ranked if c.kind == "portrait"]
    assert portraits == ["File:Bjork Cannes 2000.jpg", "File:Bjork 2007 portrait.jpg"]


async def test_category_files_that_are_not_photographs_are_left_out():
    ranked = await _candidates()
    photos = [c.source_id for c in ranked if c.kind == "photo"]
    assert photos == ["File:Bjork live Roskilde.jpg"]  # logo, svg, too small, cover: all gone
    assert [c.source_id for c in ranked].count("File:Bjork Cannes 2000.jpg") == 1


async def test_attribution_is_kept_without_its_html():
    """Point 3: what the licence requires shown, as text an app can show."""
    c = (await _candidates())[0]
    assert c.author == "Jane Doe"
    assert c.license == "CC BY-SA 4.0"
    assert c.page_url == "https://commons.wikimedia.org/wiki/File:Bjork_Cannes_2000.jpg"
    assert c.thumb_url.endswith("/400px-Bjork_Cannes_2000.jpg")
    assert c.url.endswith("/1600px-Bjork_Cannes_2000.jpg")  # wider than 1600: the resized thumb


async def test_fanart_is_not_asked_without_a_key():
    calls: list = []
    ranked = await _candidates(key=None, calls=calls)
    assert calls == []
    assert {c.source for c in ranked} == {"commons"}


async def test_with_a_key_fanart_ranks_between_the_portraits_and_the_category():
    ranked = await _candidates(key="k")
    order = [(c.source, c.kind) for c in ranked]
    assert order == [
        ("commons", "portrait"), ("commons", "portrait"),
        ("fanarttv", "portrait"), ("fanarttv", "portrait"),
        ("commons", "photo"),
        ("fanarttv", "background"),
    ]
    fanart_thumbs = [c for c in ranked if c.source == "fanarttv" and c.kind == "portrait"]
    assert [c.source_id for c in fanart_thumbs] == ["12", "11"]  # by likes
    assert "/preview/" in fanart_thumbs[0].thumb_url


async def test_a_stale_relation_to_the_wrong_entity_contributes_nothing():
    """The resolver's label guard applies: a MusicBrainz link to another artist's item is ignored."""
    wrong = {"entities": {QID: {**ENTITY["entities"][QID], "labels": {"en": {"value": "Someone Else"}}}}}
    async with _client(entity=wrong) as client:
        assert await gallery.gather_candidates(client, NAME, MBID, None) == []


def test_the_gallery_is_capped():
    many = [gallery.Candidate("commons", f"File:{i}.jpg", "photo", "u", "t", 800, 800, None, None,
                              None, None, gallery.TIER_CATEGORY) for i in range(40)]
    assert len(gallery.rank(many)) == gallery.GALLERY_MAX


# --- Stored, curated, served ---------------------------------------------------------------------


async def _artist(db, *, mbid: str | None = MBID) -> Artist:
    artist = Artist(id=uuid4(), name=NAME, sort_name=NAME, musicbrainz_id=mbid)
    db.add(artist)
    await db.flush()
    db.add(ArtistAlias(alias_normalized=normalize_artist_name(NAME), alias=NAME,
                       artist_id=artist.id, source="tag"))
    db.add(Track(id=uuid4(), file_path=f"/music/{uuid4().hex}.mp3", file_hash=uuid4().hex,
                 title="Joga", artist=NAME, album="Homogenic", canonical_artist_id=artist.id,
                 status=TrackStatus.ACTIVE))
    await db.commit()
    return artist


async def _fetch(db, artist, *, key=None):
    async with _client() as client:
        count = await gallery.fetch_gallery(db, artist, client, fanart_key=key)
    await db.commit()
    return count


async def test_a_hidden_photo_stays_hidden_when_the_gallery_is_fetched_again(async_db):
    artist = await _artist(async_db)
    assert await _fetch(async_db, artist) == 3
    first = (await async_db.execute(
        select(ArtistImage).where(ArtistImage.artist_id == artist.id).order_by(ArtistImage.rank)
    )).scalars().first()
    first.hidden = True
    await async_db.commit()

    assert await _fetch(async_db, artist) == 2
    rows = (await async_db.execute(select(ArtistImage).where(ArtistImage.artist_id == artist.id))).scalars().all()
    assert len(rows) == 3
    assert [r.hidden for r in rows if r.source_id == first.source_id] == [True]
    assert artist.gallery_fetched_at is not None


@pytest.fixture
def no_background_fetch(monkeypatch):
    """The detail route schedules; these tests record that rather than spawn a real task."""
    scheduled: list = []
    monkeypatch.setattr(gallery, "schedule_gallery_fetch", lambda artist: scheduled.append(artist.id) or object())
    return scheduled


async def test_opening_an_artist_schedules_a_fetch_and_does_not_wait_for_it(async_db, client, test_profile,
                                                                             no_background_fetch):
    artist = await _artist(async_db)
    response = client.get(f"/api/v1/library/artists/{NAME}", headers=make_profile_headers(test_profile))
    assert response.status_code == 200
    body = response.json()
    assert body["images"] == []
    assert body["images_state"] == "fetching"
    assert no_background_fetch == [artist.id]


async def test_hide_and_main_round_trip_through_the_detail(async_db, client, test_profile, no_background_fetch,
                                                           monkeypatch):
    artist = await _artist(async_db)
    await _fetch(async_db, artist)
    headers = make_profile_headers(test_profile)
    images = client.get(f"/api/v1/library/artists/{NAME}", headers=headers).json()["images"]
    assert [i["kind"] for i in images] == ["portrait", "portrait", "photo"]
    assert images[0]["author"] == "Jane Doe"

    hidden = client.post(f"/api/v1/library/artists/{NAME}/images/{images[0]['id']}/hide", headers=headers)
    assert hidden.status_code == 200 and hidden.json()["hidden"] is True
    after = client.get(f"/api/v1/library/artists/{NAME}", headers=headers).json()
    assert images[0]["id"] not in [i["id"] for i in after["images"]]

    # The main picture leads the gallery, is written to image_url, and the resolver leaves it.
    main = client.post(f"/api/v1/library/artists/{NAME}/images/{images[2]['id']}/main", headers=headers)
    assert main.status_code == 200
    detail = client.get(f"/api/v1/library/artists/{NAME}", headers=headers).json()
    assert detail["image_url"] == images[2]["thumb_url"]
    assert detail["images"][0]["id"] == images[2]["id"]

    await async_db.refresh(artist)
    assert artist.image_chosen is True
    await artist_image._write_through_to_artist(async_db, normalize_artist_name(NAME), "https://other.jpg", None)
    await async_db.commit()
    await async_db.refresh(artist)
    assert artist.image_url == images[2]["thumb_url"]


async def test_a_resolve_already_holding_the_row_cannot_overwrite_a_chosen_picture(async_db):
    """The race itself: a background session loads the artist, the owner chooses a main picture
    elsewhere, then the background resolve writes. The choice must survive."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    artist = await _artist(async_db)
    maker = async_sessionmaker(async_db.bind, class_=AsyncSession, expire_on_commit=False)
    async with maker() as background:
        stale = await background.get(Artist, artist.id)  # loaded before the choice
        assert stale.image_chosen is False

        artist.image_url, artist.image_chosen = "https://chosen.jpg", True
        await async_db.commit()

        await artist_image._write_through_to_artist(background, normalize_artist_name(NAME), "https://resolved.jpg", None)
        await background.commit()

    await async_db.refresh(artist)
    assert artist.image_url == "https://chosen.jpg"


async def test_a_photo_of_another_artist_is_a_404(async_db, client, test_profile, no_background_fetch):
    artist = await _artist(async_db)
    await _fetch(async_db, artist)
    other = Artist(id=uuid4(), name="Sugarcubes", sort_name="Sugarcubes")
    async_db.add(other)
    await async_db.flush()
    row = (await async_db.execute(select(ArtistImage).where(ArtistImage.artist_id == artist.id))).scalars().first()
    async_db.add(ArtistAlias(alias_normalized="sugarcubes", alias="Sugarcubes", artist_id=other.id, source="tag"))
    await async_db.commit()
    response = client.post(f"/api/v1/library/artists/Sugarcubes/images/{row.id}/hide",
                           headers=make_profile_headers(test_profile))
    assert response.status_code == 404


def test_no_fetch_is_scheduled_while_background_work_is_paused(monkeypatch):
    """ADR-0138: a Mac on battery does not fetch, from the sweep or from opening an artist."""
    from app.config import settings
    from app.services.background.pause import background_pause

    monkeypatch.setattr(settings, "artist_gallery_fetch", True)  # the suite turns it off

    artist = Artist(id=uuid4(), name=NAME, sort_name=NAME)
    background_pause.pause("On battery")
    try:
        assert gallery.schedule_gallery_fetch(artist) is None
    finally:
        background_pause.resume()
