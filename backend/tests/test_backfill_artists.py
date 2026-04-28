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
    ArtistInfo,
    Track,
    TrackStatus,
)
from app.services import artist_resolver as ar
from app.utils.time import utcnow


@pytest.fixture(autouse=True)
async def _cleanup_artists(async_db):
    """Wipe canonical-artist tables before/after each backfill test."""
    await async_db.execute(delete(ArtistAlias))
    await async_db.execute(delete(Artist))
    await async_db.execute(delete(ArtistInfo))
    await async_db.commit()
    yield
    await async_db.execute(delete(ArtistAlias))
    await async_db.execute(delete(Artist))
    await async_db.execute(delete(ArtistInfo))
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


@pytest.mark.asyncio
async def test_artist_info_migrated_onto_canonical(async_db, monkeypatch):
    """ArtistInfo cached image/bio gets copied onto the matching Artist."""
    await _seed(
        async_db,
        [_seed_track(file_name="t1", artist="Cocteau Twins")],
    )
    async_db.add(
        ArtistInfo(
            artist_name_normalized="cocteau twins",
            artist_name="Cocteau Twins",
            image_url="https://example.test/cocteau.jpg",
            image_checked_at=utcnow(),
            bio_summary="Scottish dream pop band.",
            similar_artists=[{"name": "Slowdive"}],
            tags=["dream-pop"],
        )
    )
    await async_db.commit()
    _patch_mb(monkeypatch, name_to_mbid={})

    for tag, mbid in await bf._distinct_artist_strings(async_db):
        await ar.resolve_canonical_artist(
            async_db, tag, musicbrainz_artist_id=mbid, do_mb_lookup=False
        )
    await async_db.commit()

    matched, skipped = await bf._migrate_artist_info(async_db)
    await async_db.commit()
    assert matched == 1
    assert skipped == 0

    artist = (
        await async_db.execute(
            select(Artist).where(Artist.name == "Cocteau Twins")
        )
    ).scalar_one()
    assert artist.image_url == "https://example.test/cocteau.jpg"
    assert artist.bio_summary == "Scottish dream pop band."
    assert artist.similar_artists == [{"name": "Slowdive"}]
    assert artist.tags == ["dream-pop"]


@pytest.mark.asyncio
async def test_artist_info_migration_handles_shared_mbid_across_rows(
    async_db, monkeypatch
):
    """Two ArtistInfo rows carrying the same MBID for different name spellings
    must not blow up the migration with a unique-constraint violation.

    Real-world example: 'Kahimi Karie' and 'カヒミ・カリィ' both have the same
    MB artist id stored in their respective ArtistInfo rows, but they
    resolve to two distinct canonical Artist rows because no track tag
    carried the MBID for the resolver to merge them.
    """
    await _seed(
        async_db,
        [
            _seed_track(file_name="t1", artist="Kahimi Karie"),
            _seed_track(file_name="t2", artist="カヒミ・カリィ"),
        ],
    )
    shared_mbid = "938802a8-fc8d-43a3-bc2b-68180f748055"
    async_db.add(
        ArtistInfo(
            artist_name_normalized="kahimi karie",
            artist_name="Kahimi Karie",
            musicbrainz_id=shared_mbid,
            bio_summary="English bio",
        )
    )
    async_db.add(
        ArtistInfo(
            artist_name_normalized="カヒミ・カリィ",
            artist_name="カヒミ・カリィ",
            musicbrainz_id=shared_mbid,
            bio_summary="Japanese bio",
        )
    )
    await async_db.commit()
    _patch_mb(monkeypatch, name_to_mbid={})

    for tag, mbid in await bf._distinct_artist_strings(async_db):
        await ar.resolve_canonical_artist(
            async_db, tag, musicbrainz_artist_id=mbid, do_mb_lookup=False
        )
    await async_db.commit()

    matched, skipped = await bf._migrate_artist_info(async_db)
    await async_db.commit()
    assert matched == 2

    # Both Artist rows got their bio, neither carries the conflicting MBID.
    artists = (
        await async_db.execute(select(Artist).order_by(Artist.name))
    ).scalars().all()
    assert len(artists) == 2
    assert all(a.bio_summary is not None for a in artists)
    assert all(a.musicbrainz_id is None for a in artists)


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
