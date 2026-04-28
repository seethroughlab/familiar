"""Tests for the canonical-artists backfill CLI."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.cli import backfill_artists as bf
from app.db.models import (
    Artist,
    ArtistAlias,
    Track,
    TrackStatus,
)
from app.services import artist_resolver as ar


@pytest.fixture(autouse=True)
async def _cleanup_artists(async_db):
    """Wipe canonical-artist tables before/after each backfill test."""
    await async_db.execute(delete(ArtistAlias))
    await async_db.execute(delete(Artist))
    await async_db.commit()
    yield
    await async_db.execute(delete(ArtistAlias))
    await async_db.execute(delete(Artist))
    await async_db.commit()


def _seed_track(*, file_name: str, artist: str, mbid: str | None = None) -> Track:
    """Build a minimal active Track row for backfill input."""
    return Track(
        id=uuid4(),
        file_path=f"/music/{file_name}.mp3",
        file_hash=f"hash-{file_name}",
        title=file_name,
        artist=artist,
        album="Album",
        musicbrainz_artist_id=mbid,
        status=TrackStatus.ACTIVE,
    )


async def _seed(async_db, tracks: list[Track]) -> None:
    for t in tracks:
        async_db.add(t)
    await async_db.commit()


def _patch_mb(monkeypatch, *, name_to_mbid: dict[str, str | None]):
    def fake_strict(name: str) -> str | None:
        return name_to_mbid.get(name)

    def fake_get(mb_id: str) -> dict[str, Any]:
        # Reverse map from MBID → canonical name; sort_name = name for tests.
        for name, mid in name_to_mbid.items():
            if mid == mb_id:
                return {"name": name, "sort_name": name}
        return {"name": "Unknown", "sort_name": "Unknown"}

    monkeypatch.setattr(ar, "strict_mb_artist_lookup", fake_strict)
    monkeypatch.setattr(ar.musicbrainz, "get_artist_by_id", fake_get)


@pytest.mark.asyncio
async def test_backfill_collapses_mbid_aliases(async_db, monkeypatch):
    """Three tag spellings carrying the same MBID merge into one Artist."""
    await _seed(
        async_db,
        [
            _seed_track(file_name="t1", artist="Beatles", mbid="mb-beatles"),
            _seed_track(file_name="t2", artist="The Beatles", mbid="mb-beatles"),
            _seed_track(file_name="t3", artist="Beatles, The", mbid="mb-beatles"),
        ],
    )
    _patch_mb(monkeypatch, name_to_mbid={"The Beatles": "mb-beatles"})

    # Use the resolver directly (the backfill module's helpers expect its
    # own engine/session; the per-pair logic is identical, so call the
    # public resolver in a loop here).
    pairs = await bf._distinct_artist_strings(async_db)
    assert len(pairs) == 3
    for tag, mbid in pairs:
        await ar.resolve_canonical_artist(
            async_db, tag, musicbrainz_artist_id=mbid, do_mb_lookup=True
        )
    await async_db.commit()

    artists = (await async_db.execute(select(Artist))).scalars().all()
    assert len(artists) == 1
    aliases = (
        await async_db.execute(select(ArtistAlias))
    ).scalars().all()
    alias_norms = {a.alias_normalized for a in aliases}
    assert alias_norms == {"beatles", "the beatles", "beatles, the"}


@pytest.mark.asyncio
async def test_backfill_sets_canonical_artist_id_on_tracks(async_db, monkeypatch):
    await _seed(
        async_db,
        [
            _seed_track(file_name="t1", artist="Beatles", mbid="mb-beatles"),
            _seed_track(file_name="t2", artist="The Beatles", mbid="mb-beatles"),
            _seed_track(file_name="t3", artist="Other Artist"),
        ],
    )
    _patch_mb(monkeypatch, name_to_mbid={"The Beatles": "mb-beatles"})

    for tag, mbid in await bf._distinct_artist_strings(async_db):
        await ar.resolve_canonical_artist(
            async_db, tag, musicbrainz_artist_id=mbid, do_mb_lookup=True
        )
    await async_db.commit()

    rows_updated = await bf._set_canonical_artist_ids(async_db)
    await async_db.commit()
    assert rows_updated == 3

    tracks = (await async_db.execute(select(Track))).scalars().all()
    by_artist = {t.title: t.canonical_artist_id for t in tracks}
    assert by_artist["t1"] == by_artist["t2"]  # same canonical
    assert by_artist["t1"] != by_artist["t3"]  # different artist
    assert all(v is not None for v in by_artist.values())


# Pass-1 ArtistInfo→Artist migration tests retired in Pass 4 along with
# the ArtistInfo table itself. The migration ran once on the live DB
# (via the Pass 1 backfill); subsequent test runs no longer exercise
# that code path.


@pytest.mark.asyncio
async def test_set_canonical_handles_diacritic_tags(async_db, monkeypatch):
    """Tags with diacritics (Björk, Sigur Rós) must get canonical_artist_id
    even though their lower-trim form differs from the NFKD-stripped
    alias_normalized that the resolver registers. The bulk SQL UPDATE
    misses these (no unaccent in pg); the Python pass-2 catches them."""
    await _seed(
        async_db,
        [
            _seed_track(file_name="t1", artist="Björk"),
            _seed_track(file_name="t2", artist="Sigur Rós"),
            _seed_track(file_name="t3", artist="Plain Artist"),
        ],
    )
    _patch_mb(monkeypatch, name_to_mbid={})

    for tag, mbid in await bf._distinct_artist_strings(async_db):
        await ar.resolve_canonical_artist(
            async_db, tag, musicbrainz_artist_id=mbid, do_mb_lookup=False
        )
    await async_db.commit()

    rows_updated = await bf._set_canonical_artist_ids(async_db)
    await async_db.commit()
    assert rows_updated == 3

    leftover = (
        await async_db.execute(
            select(Track).where(Track.canonical_artist_id.is_(None))
        )
    ).scalars().all()
    assert leftover == []


@pytest.mark.asyncio
async def test_backfill_populates_canonical_album_artist_id(async_db, monkeypatch):
    """Pass 3: backfill sets canonical_album_artist_id from album_artist tags.

    Three cases:
      - track tagged with both artist + album_artist (different) →
        both FKs populated, pointing at different Artist rows
      - track tagged with album_artist only on a diacritic name (Björk) →
        Python pass-2 catches the diacritic mismatch
      - track with no album_artist → canonical_album_artist_id stays NULL
    """
    track1 = Track(
        id=uuid4(),
        file_path="/music/t1.mp3",
        file_hash="hash-t1",
        title="Imagine",
        artist="John Lennon",
        album="Imagine",
        album_artist="The Beatles",
        status=TrackStatus.ACTIVE,
    )
    track2 = Track(
        id=uuid4(),
        file_path="/music/t2.mp3",
        file_hash="hash-t2",
        title="Hyperballad",
        artist="Björk",
        album="Post",
        album_artist="Björk",
        status=TrackStatus.ACTIVE,
    )
    track3 = Track(
        id=uuid4(),
        file_path="/music/t3.mp3",
        file_hash="hash-t3",
        title="Single",
        artist="Solo Artist",
        album="Solo",
        album_artist=None,
        status=TrackStatus.ACTIVE,
    )
    await _seed(async_db, [track1, track2, track3])
    _patch_mb(monkeypatch, name_to_mbid={})

    # Resolver loop for artist + album_artist strings.
    for tag, mbid in await bf._distinct_artist_strings(async_db):
        await ar.resolve_canonical_artist(
            async_db, tag, musicbrainz_artist_id=mbid, do_mb_lookup=False
        )
    for tag in await bf._distinct_album_artist_strings(async_db):
        await ar.resolve_canonical_artist(
            async_db, tag, do_mb_lookup=False
        )
    await async_db.commit()

    # Bulk-set both FK columns.
    await bf._set_canonical_artist_ids(async_db)
    rows = await bf._set_canonical_album_artist_ids(async_db)
    await async_db.commit()
    assert rows == 2  # only t1 and t2 have non-empty album_artist

    # Refresh and assert.
    refreshed = (await async_db.execute(select(Track))).scalars().all()
    by_title = {t.title: t for t in refreshed}

    # t1: artist='John Lennon' (canonical), album_artist='The Beatles' (different canonical).
    t1 = by_title["Imagine"]
    assert t1.canonical_artist_id is not None
    assert t1.canonical_album_artist_id is not None
    assert t1.canonical_artist_id != t1.canonical_album_artist_id

    # t2: diacritic case — both FKs point to the same Björk Artist row.
    t2 = by_title["Hyperballad"]
    assert t2.canonical_artist_id is not None
    assert t2.canonical_album_artist_id is not None
    assert t2.canonical_artist_id == t2.canonical_album_artist_id

    # t3: no album_artist → canonical_album_artist_id stays NULL.
    t3 = by_title["Single"]
    assert t3.canonical_artist_id is not None
    assert t3.canonical_album_artist_id is None


@pytest.mark.asyncio
async def test_backfill_idempotent(async_db, monkeypatch):
    """Running the resolver loop twice produces the same artist/alias counts."""
    await _seed(
        async_db,
        [
            _seed_track(file_name="t1", artist="Cocteau Twins"),
            _seed_track(file_name="t2", artist="Slowdive"),
        ],
    )
    _patch_mb(monkeypatch, name_to_mbid={})

    async def _run_once():
        for tag, mbid in await bf._distinct_artist_strings(async_db):
            await ar.resolve_canonical_artist(
                async_db,
                tag,
                musicbrainz_artist_id=mbid,
                do_mb_lookup=False,
            )
        await async_db.commit()
        await bf._set_canonical_artist_ids(async_db)
        await async_db.commit()

    await _run_once()
    artists_first = (
        await async_db.execute(select(Artist))
    ).scalars().all()
    aliases_first = (
        await async_db.execute(select(ArtistAlias))
    ).scalars().all()

    await _run_once()
    artists_second = (
        await async_db.execute(select(Artist))
    ).scalars().all()
    aliases_second = (
        await async_db.execute(select(ArtistAlias))
    ).scalars().all()

    assert len(artists_first) == len(artists_second) == 2
    assert len(aliases_first) == len(aliases_second) == 2
