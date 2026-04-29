"""Unit tests for the artist-image resolver (MB url-rels → Wikipedia thumbnail)."""

from typing import Any

import pytest
from sqlalchemy import select

from app.db.models import ExternalArtistImageCache
from app.services import artist_image as ai


@pytest.fixture
def mock_mb_with_wiki(monkeypatch):
    """search_artist + get_artist_by_id with an English Wikipedia url-rel."""

    def _search(name: str) -> dict[str, Any]:
        return {"name": name, "musicbrainz_artist_id": "mb-id-1", "score": 95}

    def _get(mb_id: str) -> dict[str, Any]:
        return {
            "musicbrainz_artist_id": mb_id,
            "name": "Cocteau Twins",
            "urls": [
                {"type": "discogs", "url": "https://www.discogs.com/artist/12345"},
                {"type": "wikipedia", "url": "https://en.wikipedia.org/wiki/Cocteau_Twins"},
            ],
        }

    monkeypatch.setattr(ai.musicbrainz, "search_artist", _search)
    monkeypatch.setattr(ai.musicbrainz, "get_artist_by_id", _get)


def test_wiki_title_extraction():
    assert ai._wiki_title_from_url("https://en.wikipedia.org/wiki/Cocteau_Twins") == (
        "en",
        "Cocteau_Twins",
    )
    assert ai._wiki_title_from_url(
        "https://de.wikipedia.org/wiki/Slowdive#History"
    ) == ("de", "Slowdive")
    assert ai._wiki_title_from_url("https://example.com/no-wiki") is None
    assert ai._wiki_title_from_url("https://en.wikipedia.org/") is None


def test_pick_wikipedia_url_prefers_english():
    urls = [
        {"type": "wikipedia", "url": "https://de.wikipedia.org/wiki/Slowdive"},
        {"type": "wikipedia", "url": "https://en.wikipedia.org/wiki/Slowdive"},
    ]
    assert ai._pick_wikipedia_url(urls) == "https://en.wikipedia.org/wiki/Slowdive"


def test_pick_wikipedia_url_falls_back_to_other_lang():
    urls = [{"type": "wikipedia", "url": "https://de.wikipedia.org/wiki/Slowdive"}]
    assert ai._pick_wikipedia_url(urls) == "https://de.wikipedia.org/wiki/Slowdive"


def test_pick_wikipedia_url_skips_non_wikipedia():
    urls = [{"type": "discogs", "url": "https://www.discogs.com/artist/123"}]
    assert ai._pick_wikipedia_url(urls) is None


def test_looks_musical_accepts_artist_descriptions():
    assert ai._looks_musical("British post-punk band from Glasgow")
    assert ai._looks_musical("American singer-songwriter and actress")
    assert ai._looks_musical("Hip-hop producer")
    assert ai._looks_musical("Electronic music duo")


def test_looks_musical_rejects_non_artist_descriptions():
    # Greek mythological figure
    assert not ai._looks_musical("queen of Troy in Greek mythology")
    # Architectural feature
    assert not ai._looks_musical("structural component of a roof")
    # Empty / None
    assert not ai._looks_musical(None)
    assert not ai._looks_musical("")


@pytest.fixture
def stub_wiki_direct(monkeypatch):
    """Make Wikipedia-direct lookup return a deterministic URL per artist."""

    async def _direct(name: str, client):
        return f"https://upload.wikimedia.org/{name.replace(' ', '_')}.jpg"

    monkeypatch.setattr(ai, "_resolve_via_wikipedia_direct", _direct)


@pytest.fixture
def stub_wiki_direct_miss(monkeypatch):
    """Wikipedia-direct returns None — exercises the MB fallback path."""

    async def _direct(name: str, client):
        return None

    monkeypatch.setattr(ai, "_resolve_via_wikipedia_direct", _direct)


@pytest.mark.asyncio
async def test_resolve_caches_positive_hit(async_db, stub_wiki_direct):
    """Wikipedia-direct hit: cache the URL with a fresh check timestamp."""
    url = await ai.resolve_artist_image(async_db, "Cocteau Twins")
    await async_db.commit()

    assert url == "https://upload.wikimedia.org/Cocteau_Twins.jpg"
    row = (
        await async_db.execute(
            select(ExternalArtistImageCache).where(ExternalArtistImageCache.name_normalized == "cocteau twins")
        )
    ).scalar_one()
    assert row.image_url == "https://upload.wikimedia.org/Cocteau_Twins.jpg"
    assert row.image_checked_at is not None


@pytest.mark.asyncio
async def test_resolve_writes_through_to_artist_when_alias_exists(
    async_db, stub_wiki_direct
):
    """Pass 4: a successful resolution mirrors onto Artist.image_url
    when an alias for the queried name is registered."""
    from app.db.models import Artist
    from app.services import artist_resolver

    artist = await artist_resolver.resolve_canonical_artist(
        async_db, "Cocteau Twins", do_mb_lookup=False
    )
    await async_db.commit()
    # Artist.image_url is initially NULL.
    assert artist.image_url is None

    url = await ai.resolve_artist_image(async_db, "Cocteau Twins")
    await async_db.commit()

    refreshed = await async_db.get(Artist, artist.id)
    assert refreshed.image_url == url
    assert refreshed.image_checked_at is not None


@pytest.mark.asyncio
async def test_negative_cache_does_not_overwrite_artist_image_url(
    async_db, stub_wiki_direct_miss, monkeypatch
):
    """Pass 4: a negative-cache result must not blank an
    Artist.image_url that was previously resolved positive."""
    monkeypatch.setattr(ai.musicbrainz, "search_artist", lambda name: None)
    monkeypatch.setattr(ai, "strict_mb_artist_lookup", lambda name: None)

    from app.db.models import Artist
    from app.services import artist_resolver

    artist = await artist_resolver.resolve_canonical_artist(
        async_db, "Some Obscure Artist", do_mb_lookup=False
    )
    artist.image_url = "https://existing.example/already.jpg"
    await async_db.commit()

    # Resolve runs, resolver chain returns None → negative cache.
    url = await ai.resolve_artist_image(async_db, "Some Obscure Artist")
    await async_db.commit()
    assert url is None

    refreshed = await async_db.get(Artist, artist.id)
    # Pre-existing positive value is preserved (no overwrite).
    assert refreshed.image_url == "https://existing.example/already.jpg"


@pytest.mark.asyncio
async def test_falls_back_to_musicbrainz_when_wikipedia_direct_misses(
    async_db, monkeypatch, stub_wiki_direct_miss, mock_mb_with_wiki
):
    """Direct Wikipedia returns None → MB url-rels chain fires."""

    async def _thumb(client, lang, title, artist_name=None):
        return f"https://commons.example/{title}.jpg"

    async def _wiki_search_miss(name, client, hint=None):
        return None

    monkeypatch.setattr(ai, "_fetch_wikipedia_thumbnail", _thumb)
    monkeypatch.setattr(ai, "_resolve_via_wikipedia_search", _wiki_search_miss)

    url = await ai.resolve_artist_image(async_db, "Cocteau Twins")
    await async_db.commit()
    assert url == "https://commons.example/Cocteau_Twins.jpg"


@pytest.mark.asyncio
async def test_resolve_caches_negative_hit(async_db, stub_wiki_direct_miss, monkeypatch):
    """Both paths miss: cache NULL with a fresh check timestamp."""
    monkeypatch.setattr(ai.musicbrainz, "search_artist", lambda name: None)

    url = await ai.resolve_artist_image(async_db, "Nonexistent Artist")
    await async_db.commit()
    assert url is None

    row = (
        await async_db.execute(
            select(ExternalArtistImageCache).where(
                ExternalArtistImageCache.name_normalized == "nonexistent artist"
            )
        )
    ).scalar_one()
    assert row.image_url is None
    assert row.image_checked_at is not None


@pytest.mark.asyncio
async def test_resolve_uses_cache_within_ttl(async_db, monkeypatch):
    """A second call within TTL doesn't re-hit Wikipedia or MB."""
    call_count = {"direct": 0}

    async def _counting_direct(name, client):
        call_count["direct"] += 1
        return "https://upload.wikimedia.org/cocteau.jpg"

    monkeypatch.setattr(ai, "_resolve_via_wikipedia_direct", _counting_direct)

    await ai.resolve_artist_image(async_db, "Cocteau Twins")
    await async_db.commit()
    await ai.resolve_artist_image(async_db, "Cocteau Twins")
    await async_db.commit()

    assert call_count["direct"] == 1


@pytest.mark.asyncio
async def test_resolve_many_returns_results_for_resolved_artists(
    async_db, stub_wiki_direct
):
    out = await ai.resolve_many_artist_images(
        async_db, ["Cocteau Twins", "Slowdive"], wikipedia_timeout=10.0
    )
    await async_db.commit()
    assert out["Cocteau Twins"] == "https://upload.wikimedia.org/Cocteau_Twins.jpg"
    assert out["Slowdive"] == "https://upload.wikimedia.org/Slowdive.jpg"


@pytest.mark.asyncio
async def test_resolve_many_does_not_negative_cache_misses_inline(
    async_db, monkeypatch
):
    """Sync path should NOT write a negative cache for misses — that's the
    background task's job. Otherwise the next dashboard load won't retry."""

    async def _miss(name, client):
        return None

    monkeypatch.setattr(ai, "_resolve_via_wikipedia_direct", _miss)

    await ai.resolve_many_artist_images(
        async_db, ["Some Obscure Artist"], wikipedia_timeout=2.0
    )
    await async_db.commit()

    row = (
        await async_db.execute(
            select(ExternalArtistImageCache).where(
                ExternalArtistImageCache.name_normalized == "some obscure artist"
            )
        )
    ).scalar_one_or_none()
    # Either no row, or no image_checked_at — i.e. not negative-cached.
    assert row is None or row.image_checked_at is None


def test_wikidata_entity_id_extracts_q_number():
    urls = [
        {"type": "wikidata", "url": "https://www.wikidata.org/wiki/Q12345"},
    ]
    assert ai._wikidata_entity_id(urls) == "Q12345"


def test_wikidata_entity_id_returns_none_when_absent():
    urls = [{"type": "discogs", "url": "https://www.discogs.com/artist/12345"}]
    assert ai._wikidata_entity_id(urls) is None


def test_strict_mb_lookup_rejects_fuzzy_match(monkeypatch):
    """MB search returning a different artist (Paul McCartney for Paul Banks)
    must NOT be accepted — that's how we ended up with McCartney's photo."""
    import musicbrainzngs

    def fake_search(*, artist, limit):
        return {
            "artist-list": [
                {
                    "id": "mb-mccartney",
                    "name": "Paul McCartney",
                    "sort-name": "McCartney, Paul",
                    "ext:score": "100",
                },
            ]
        }

    monkeypatch.setattr(musicbrainzngs, "search_artists", fake_search)
    assert ai.strict_mb_artist_lookup("Paul Banks") is None


def test_strict_mb_lookup_finds_correct_artist_lower_in_results(monkeypatch):
    """When MB ranks the wrong artist first, the correct one (further down
    the list) must still be picked as long as it normalizes to the query."""
    import musicbrainzngs

    def fake_search(*, artist, limit):
        return {
            "artist-list": [
                {"id": "wrong-1", "name": "Paul McCartney", "ext:score": "100"},
                {"id": "wrong-2", "name": "Paul Simon", "ext:score": "92"},
                {"id": "right", "name": "Paul Banks", "ext:score": "88"},
            ]
        }

    monkeypatch.setattr(musicbrainzngs, "search_artists", fake_search)
    assert ai.strict_mb_artist_lookup("Paul Banks") == "right"


def test_strict_mb_lookup_skips_low_score_matches(monkeypatch):
    import musicbrainzngs

    def fake_search(*, artist, limit):
        return {
            "artist-list": [
                {"id": "low", "name": "Paul Banks", "ext:score": "55"},
            ]
        }

    monkeypatch.setattr(musicbrainzngs, "search_artists", fake_search)
    assert ai.strict_mb_artist_lookup("Paul Banks") is None


@pytest.mark.asyncio
async def test_wikipedia_search_picks_hint_match_over_first(monkeypatch):
    """Multiple "Paul Banks" musicians on Wikipedia: hint=Interpol must pick
    the page whose extract mentions Interpol, not just the first result."""

    # opensearch returns three Paul Banks variants (URLs only matter — we
    # then fetch each summary and pick the one mentioning the hint).
    pages = {
        "Paul_Banks_(musician,_born_1973)": {
            "type": "standard",
            "title": "Paul Banks (musician, born 1973)",
            "description": "Musical artist",
            "extract": "Paul Adrian Banks is an English musician with Shed Seven.",
            "thumbnail": {"source": "https://wikimedia.test/shed.jpg"},
        },
        "Paul_Banks_(musician,_born_1978)": {
            "type": "standard",
            "title": "Paul Banks (musician, born 1978)",
            "description": "British-American singer",
            "extract": "Paul Julian Banks is a singer best known as the frontman of Interpol.",
            "thumbnail": {"source": "https://wikimedia.test/interpol.jpg"},
        },
    }

    class StubClient:
        async def get(self, url, params=None, timeout=None):
            class R:
                status_code = 200
                def __init__(self, data):
                    self._data = data
                def json(self):
                    return self._data

            if "action=opensearch" in url or (params and params.get("action") == "opensearch"):
                return R([
                    "Paul Banks musician",
                    ["Paul Banks (musician, born 1973)", "Paul Banks (musician, born 1978)"],
                    ["", ""],
                    [
                        "https://en.wikipedia.org/wiki/Paul_Banks_(musician,_born_1973)",
                        "https://en.wikipedia.org/wiki/Paul_Banks_(musician,_born_1978)",
                    ],
                ])
            for key, data in pages.items():
                if key in url:
                    return R(data)
            return R({"type": "missing"})

    url = await ai._resolve_via_wikipedia_search(
        "Paul Banks", StubClient(), hint="Interpol"  # type: ignore[arg-type]
    )
    assert url == "https://wikimedia.test/interpol.jpg"


@pytest.mark.asyncio
async def test_wikipedia_search_handles_band_suffix(monkeypatch):
    """For artists like Sun Electric, the direct lookup hits a disambiguation
    page; the canonical page lives at "Sun Electric (band)". Bare opensearch
    must surface that, and the title-match check must accept the (band) suffix."""

    pages = {
        "Sun_Electric_(band)": {
            "type": "standard",
            "title": "Sun Electric (band)",
            "description": "German electronic music duo",
            "extract": "Sun Electric was a German electronic music duo.",
            "thumbnail": {"source": "https://wikimedia.test/sun-electric.jpg"},
        },
        "Sun_Electric": {
            "type": "disambiguation",
            "title": "Sun Electric",
            "description": "Topics referred to by the same term",
            "extract": "Sun Electric may refer to:",
        },
    }

    class StubClient:
        async def get(self, url, params=None, timeout=None):
            class R:
                status_code = 200
                def __init__(self, data):
                    self._data = data
                def json(self):
                    return self._data

            if params and params.get("action") == "opensearch":
                # Bare query returns disambiguation + (band); "musician"
                # qualifier returns nothing (matches real Wikipedia behavior).
                if "musician" in (params.get("search") or ""):
                    return R(["Sun Electric musician", [], [], []])
                return R([
                    "Sun Electric",
                    ["Sun Electric", "Sun Electric (band)"],
                    ["", ""],
                    [
                        "https://en.wikipedia.org/wiki/Sun_Electric",
                        "https://en.wikipedia.org/wiki/Sun_Electric_(band)",
                    ],
                ])
            for key, data in pages.items():
                if key in url:
                    return R(data)
            return R({"type": "missing"})

    url = await ai._resolve_via_wikipedia_search(
        "Sun Electric", StubClient(), hint=None  # type: ignore[arg-type]
    )
    assert url == "https://wikimedia.test/sun-electric.jpg"


@pytest.mark.asyncio
async def test_wikipedia_search_falls_back_to_first_match_without_hint(monkeypatch):
    """No hint: take the first music-tagged candidate with a thumbnail."""
    pages = {
        "Cocteau_Twins": {
            "type": "standard",
            "title": "Cocteau Twins",
            "description": "Scottish rock band",
            "extract": "Cocteau Twins were a Scottish rock band.",
            "thumbnail": {"source": "https://wikimedia.test/cocteau.jpg"},
        },
    }

    class StubClient:
        async def get(self, url, params=None, timeout=None):
            class R:
                status_code = 200
                def __init__(self, data):
                    self._data = data
                def json(self):
                    return self._data

            if "action=opensearch" in url or (params and params.get("action") == "opensearch"):
                return R([
                    "Cocteau Twins musician",
                    ["Cocteau Twins"],
                    [""],
                    ["https://en.wikipedia.org/wiki/Cocteau_Twins"],
                ])
            for key, data in pages.items():
                if key in url:
                    return R(data)
            return R({"type": "missing"})

    url = await ai._resolve_via_wikipedia_search(
        "Cocteau Twins", StubClient(), hint=None  # type: ignore[arg-type]
    )
    assert url == "https://wikimedia.test/cocteau.jpg"


def test_title_matches_artist_exact():
    assert ai._title_matches_artist("Cocteau Twins", "Cocteau Twins")
    assert ai._title_matches_artist("Beck", "Beck")


def test_title_matches_artist_with_disambiguator():
    # Wikipedia adds parenthetical/comma disambiguators; treat them as match.
    assert ai._title_matches_artist("Beck (musician)", "Beck")
    assert ai._title_matches_artist("Paul Banks (musician, born 1978)", "Paul Banks")


def test_title_matches_artist_rejects_substring_collisions():
    # The "Beck" → "Jeff Beck" trap: substring containment must NOT pass.
    assert not ai._title_matches_artist("Jeff Beck", "Beck")
    assert not ai._title_matches_artist("Lloyd Banks", "Paul Banks")


def test_title_matches_artist_rejects_prefix_collisions():
    # "Annie" → "Annie Lennox" trap: a longer same-prefix title must NOT
    # pass (different artist, name happens to share a first word). Only
    # parenthetical disambiguators are accepted as suffixes.
    assert not ai._title_matches_artist("Annie Lennox", "Annie")
    assert not ai._title_matches_artist("John Lennon", "John")
    assert not ai._title_matches_artist("Anna Meredith", "Anna")
    # Comma-style suffixes are also not Wikipedia's pattern — reject.
    assert not ai._title_matches_artist("Beck, Bogert & Appice", "Beck")


def test_title_matches_artist_handles_diacritics():
    # normalize_artist_name strips diacritics — should still match.
    assert ai._title_matches_artist("Beyoncé", "Beyonce")


def test_wikidata_labels_match_artist_via_label():
    entity = {"labels": {"en": {"value": "Cocteau Twins"}}}
    assert ai._wikidata_labels_match_artist(entity, "Cocteau Twins")


def test_wikidata_labels_match_artist_via_alias():
    entity = {
        "labels": {"en": {"value": "Cocteaus, The"}},
        "aliases": {"en": [{"value": "Cocteau Twins"}]},
    }
    assert ai._wikidata_labels_match_artist(entity, "Cocteau Twins")


def test_wikidata_labels_match_artist_rejects_mismatch():
    entity = {"labels": {"en": {"value": "Paul McCartney"}}}
    assert not ai._wikidata_labels_match_artist(entity, "Paul Banks")


def test_split_compound_artist_handles_separators():
    assert ai._split_compound_artist("Cocteau Twins") == ["Cocteau Twins"]
    assert ai._split_compound_artist("Beyoncé feat. Jay-Z") == ["Beyoncé", "Jay-Z"]
    assert ai._split_compound_artist(
        "Harold Budd, Simon Raymonde, Robin Guthrie & Elizabeth Fraser"
    ) == ["Harold Budd", "Simon Raymonde", "Robin Guthrie", "Elizabeth Fraser"]
    assert ai._split_compound_artist("DJ Shadow with Cut Chemist") == [
        "DJ Shadow",
        "Cut Chemist",
    ]


def test_pick_spotify_artist_url_finds_artist_link():
    urls = [
        {"type": "discogs", "url": "https://www.discogs.com/artist/12"},
        {"type": "free streaming", "url": "https://open.spotify.com/artist/abc123XYZ"},
        {"type": "youtube", "url": "https://www.youtube.com/channel/foo"},
    ]
    assert ai._pick_spotify_artist_url(urls) == (
        "https://open.spotify.com/artist/abc123XYZ"
    )


def test_pick_spotify_artist_url_skips_album_track_urls():
    urls = [
        {"type": "x", "url": "https://open.spotify.com/album/notanartist"},
        {"type": "x", "url": "https://open.spotify.com/track/notanartist"},
    ]
    assert ai._pick_spotify_artist_url(urls) is None


@pytest.mark.asyncio
async def test_spotify_oembed_returns_thumbnail_when_title_matches():
    class StubClient:
        async def get(self, url, params=None, timeout=None):
            class R:
                status_code = 200
                def json(self):
                    return {
                        "title": "Sun Electric",
                        "thumbnail_url": "https://image-cdn.spotify.test/sun.jpg",
                    }
            return R()

    url = await ai._resolve_via_spotify_oembed(
        "https://open.spotify.com/artist/0aJ1FZmpkkzD6RiZe33EFR",
        StubClient(),  # type: ignore[arg-type]
        artist_name="Sun Electric",
    )
    assert url == "https://image-cdn.spotify.test/sun.jpg"


@pytest.mark.asyncio
async def test_spotify_oembed_rejects_title_mismatch():
    """Defends against stale MB → Spotify relations pointing at the wrong artist."""
    class StubClient:
        async def get(self, url, params=None, timeout=None):
            class R:
                status_code = 200
                def json(self):
                    return {
                        "title": "Some Other Band",
                        "thumbnail_url": "https://image-cdn.spotify.test/wrong.jpg",
                    }
            return R()

    url = await ai._resolve_via_spotify_oembed(
        "https://open.spotify.com/artist/abc",
        StubClient(),  # type: ignore[arg-type]
        artist_name="Sun Electric",
    )
    assert url is None


@pytest.mark.asyncio
async def test_compound_name_falls_back_to_first_artist(monkeypatch):
    """A 4-name collaborative project has no single Wikipedia page; the
    chain should fall through to the first named artist's photo."""
    direct_calls: list[str] = []

    async def _direct(name, client):
        direct_calls.append(name)
        if name == "Harold Budd":
            return "https://wikimedia.test/budd.jpg"
        return None

    async def _search(name, client, hint=None):
        return None

    monkeypatch.setattr(ai, "_resolve_via_wikipedia_direct", _direct)
    monkeypatch.setattr(ai, "_resolve_via_wikipedia_search", _search)

    url = await ai._resolve_via_wikipedia(
        "Harold Budd, Simon Raymonde, Robin Guthrie & Elizabeth Fraser",
        client=None,  # type: ignore[arg-type]
    )
    assert url == "https://wikimedia.test/budd.jpg"
    # Direct should have been called with the full name first, then the split first.
    assert direct_calls == [
        "Harold Budd, Simon Raymonde, Robin Guthrie & Elizabeth Fraser",
        "Harold Budd",
    ]


def test_url_encoding_preserves_punctuation():
    # The Wikipedia REST endpoint chokes on raw commas — encoding fixes it.
    # We test indirectly via _resolve_via_wikipedia_direct's own encoding logic
    # by checking quote() output for representative names.
    from urllib.parse import quote

    title = quote("Project Jenny, Project Jan".replace(" ", "_"), safe="_()")
    assert "%2C" in title  # comma is encoded
    title2 = quote("Cocteau Twins".replace(" ", "_"), safe="_()")
    assert title2 == "Cocteau_Twins"
