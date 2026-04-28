"""Tests for the canonical artist resolver."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import delete, select

from app.db.models import Artist, ArtistAlias
from app.services import artist_resolver as ar


@pytest.fixture(autouse=True)
async def _cleanup_artists(async_db):
    """Wipe Artist + ArtistAlias before/after each resolver test.

    The shared async_db fixture cleans Track and friends, but the
    canonical-artist tables aren't in its cleanup list yet.
    """
    await async_db.execute(delete(ArtistAlias))
    await async_db.execute(delete(Artist))
    await async_db.commit()
    yield
    await async_db.execute(delete(ArtistAlias))
    await async_db.execute(delete(Artist))
    await async_db.commit()


@pytest.mark.asyncio
async def test_creates_artist_and_alias_for_unknown_tag(async_db):
    artist = await ar.resolve_canonical_artist(async_db, "Cocteau Twins")
    await async_db.commit()

    assert artist is not None
    assert artist.name == "Cocteau Twins"
    assert artist.sort_name == "Cocteau Twins"
    assert artist.musicbrainz_id is None

    alias = await async_db.get(ArtistAlias, "cocteau twins")
    assert alias is not None
    assert alias.artist_id == artist.id
    assert alias.source == "tag"


@pytest.mark.asyncio
async def test_alias_hit_returns_existing_artist(async_db):
    first = await ar.resolve_canonical_artist(async_db, "Cocteau Twins")
    await async_db.commit()
    second = await ar.resolve_canonical_artist(async_db, "Cocteau Twins")
    await async_db.commit()
    assert first.id == second.id

    # Only one artist row, only one alias row.
    artist_count = await async_db.scalar(
        select(Artist.id).where(Artist.id == first.id)
    )
    assert artist_count is not None
    aliases = (
        await async_db.execute(
            select(ArtistAlias).where(ArtistAlias.artist_id == first.id)
        )
    ).scalars().all()
    assert len(aliases) == 1


@pytest.mark.asyncio
async def test_the_prefix_normalized_to_sort_name(async_db):
    artist = await ar.resolve_canonical_artist(async_db, "The Beatles")
    await async_db.commit()
    assert artist.name == "The Beatles"
    assert artist.sort_name == "Beatles, The"


@pytest.mark.asyncio
async def test_mbid_match_merges_two_tag_strings(async_db, monkeypatch):
    """Two distinct tag strings carrying the same MBID collapse to one Artist row."""

    def fake_get_by_id(mb_id: str) -> dict[str, Any]:
        return {"name": "The Beatles", "sort_name": "Beatles, The"}

    monkeypatch.setattr(
        ar.musicbrainz, "get_artist_by_id", fake_get_by_id
    )

    a = await ar.resolve_canonical_artist(
        async_db, "Beatles", musicbrainz_artist_id="mb-beatles-1"
    )
    await async_db.commit()
    b = await ar.resolve_canonical_artist(
        async_db, "The Beatles", musicbrainz_artist_id="mb-beatles-1"
    )
    await async_db.commit()

    assert a.id == b.id
    assert a.musicbrainz_id == "mb-beatles-1"
    # Both strings registered as aliases pointing to the same Artist.
    aliases = (
        await async_db.execute(
            select(ArtistAlias).where(ArtistAlias.artist_id == a.id)
        )
    ).scalars().all()
    alias_norms = {al.alias_normalized for al in aliases}
    assert alias_norms == {"beatles", "the beatles"}


@pytest.mark.asyncio
async def test_strict_mb_lookup_path(async_db, monkeypatch):
    """When ``do_mb_lookup`` is on, a tag without an MBID gets one from MB."""

    monkeypatch.setattr(
        ar, "strict_mb_artist_lookup", lambda name: "mb-cocteau-1"
    )

    def fake_get_by_id(mb_id: str) -> dict[str, Any]:
        return {"name": "Cocteau Twins", "sort_name": "Cocteau Twins"}

    monkeypatch.setattr(
        ar.musicbrainz, "get_artist_by_id", fake_get_by_id
    )

    artist = await ar.resolve_canonical_artist(
        async_db, "Cocteau Twins", do_mb_lookup=True
    )
    await async_db.commit()
    assert artist.musicbrainz_id == "mb-cocteau-1"

    alias = await async_db.get(ArtistAlias, "cocteau twins")
    assert alias is not None
    assert alias.source == "mb"


@pytest.mark.asyncio
async def test_strict_mb_lookup_skipped_when_off(async_db, monkeypatch):
    """``do_mb_lookup=False`` (the scanner default) skips MB and creates a standalone."""
    called = {"n": 0}

    def fake_lookup(name: str) -> str | None:
        called["n"] += 1
        return "mb-should-not-call"

    monkeypatch.setattr(ar, "strict_mb_artist_lookup", fake_lookup)

    artist = await ar.resolve_canonical_artist(
        async_db, "Cocteau Twins", do_mb_lookup=False
    )
    await async_db.commit()
    assert artist.musicbrainz_id is None
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_create_if_missing_false_returns_none(async_db):
    """Dry-run mode: nothing matches and no side effects."""
    artist = await ar.resolve_canonical_artist(
        async_db, "Brand New Artist", create_if_missing=False
    )
    assert artist is None
    # No artist or alias row written.
    rows = (await async_db.execute(select(Artist))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_blank_input_returns_none(async_db):
    assert await ar.resolve_canonical_artist(async_db, "") is None
    assert await ar.resolve_canonical_artist(async_db, "   ") is None


@pytest.mark.asyncio
async def test_normalization_strips_diacritics_for_alias(async_db):
    """Beyoncé and Beyonce normalize to the same alias key."""
    a = await ar.resolve_canonical_artist(async_db, "Beyoncé")
    await async_db.commit()
    b = await ar.resolve_canonical_artist(async_db, "Beyonce")
    await async_db.commit()
    assert a.id == b.id


@pytest.mark.asyncio
async def test_tag_mbid_pointing_at_wrong_artist_is_rejected(
    async_db, monkeypatch
):
    """A track tagged 'Beatles' with an MBID that MB resolves to 'Bob Nanna'
    must NOT be attached to a Bob Nanna canonical row. The resolver
    falls through to the standalone-create path."""

    # Pre-existing Artist row owned by the wrong MBID.
    existing = ar.Artist(
        name="Bob Nanna",
        sort_name="Nanna, Bob",
        musicbrainz_id="mb-bob-nanna",
    )
    async_db.add(existing)
    await async_db.commit()

    artist = await ar.resolve_canonical_artist(
        async_db, "Beatles", musicbrainz_artist_id="mb-bob-nanna"
    )
    await async_db.commit()

    # New canonical Artist created for the tag, NOT merged into Bob Nanna.
    assert artist.id != existing.id
    assert artist.name == "Beatles"
    # And the alias points to the new Artist.
    alias = await async_db.get(ar.ArtistAlias, "beatles")
    assert alias is not None
    assert alias.artist_id == artist.id


@pytest.mark.asyncio
async def test_tag_mbid_unknown_to_db_rejects_when_mb_name_mismatches(
    async_db, monkeypatch
):
    """When path 1 has to fetch MB to learn the MBID's name, it must
    still reject the MBID if the returned name doesn't match the tag."""

    def fake_get_by_id(mb_id: str) -> dict:
        return {"name": "Bob Nanna", "sort_name": "Nanna, Bob"}

    monkeypatch.setattr(ar.musicbrainz, "get_artist_by_id", fake_get_by_id)

    artist = await ar.resolve_canonical_artist(
        async_db, "Beatles", musicbrainz_artist_id="mb-bob-nanna"
    )
    await async_db.commit()

    # Created a standalone Beatles row, not a Bob Nanna row.
    assert artist.name == "Beatles"
    assert artist.musicbrainz_id is None  # corrupt MBID rejected


@pytest.mark.asyncio
async def test_tag_mbid_accepted_with_loose_the_match(async_db, monkeypatch):
    """A tag of 'Beatles' (no leading 'The') with the correct MB MBID
    that returns 'The Beatles' must be accepted — the article check
    folds them as the same name."""

    def fake_get_by_id(mb_id: str) -> dict:
        return {"name": "The Beatles", "sort_name": "Beatles, The"}

    monkeypatch.setattr(ar.musicbrainz, "get_artist_by_id", fake_get_by_id)

    artist = await ar.resolve_canonical_artist(
        async_db, "Beatles", musicbrainz_artist_id="mb-the-beatles"
    )
    await async_db.commit()

    assert artist.name == "The Beatles"
    assert artist.sort_name == "Beatles, The"
    assert artist.musicbrainz_id == "mb-the-beatles"


def test_canonicalize_for_match():
    """Article variants normalize to the same canonical form."""
    assert ar._canonicalize_for_match("The Beatles") == "beatles"
    assert ar._canonicalize_for_match("Beatles") == "beatles"
    assert ar._canonicalize_for_match("Beatles, The") == "beatles"
    assert ar._canonicalize_for_match("Beyoncé") == "beyonce"
    # Distinct artists do NOT collapse.
    assert ar._canonicalize_for_match("Beatles") != ar._canonicalize_for_match(
        "Bob Nanna"
    )
