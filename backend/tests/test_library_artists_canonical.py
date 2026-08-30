"""Pass 2 cutover tests: artist endpoints read via canonical_artist_id."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.api.routes.library_artists import (
    _resolve_artist_via_alias,
    get_artist_detail,
    list_artists,
)
from app.db.models import ArtistAlias, Track, TrackStatus
from app.services import artist_resolver as ar


def _new_track(*, file: str, artist_id, artist_str: str = "x", album: str = "Album") -> Track:
    return Track(
        id=uuid4(),
        file_path=f"/music/{file}.mp3",
        file_hash=f"hash-{file}",
        title=file,
        artist=artist_str,
        album=album,
        canonical_artist_id=artist_id,
        status=TrackStatus.ACTIVE,
    )


@pytest.mark.asyncio
async def test_list_artists_groups_by_canonical_id(async_db):
    """Three tracks tagged with name variants of the same canonical
    artist collapse into a single tile."""
    canonical = await ar.resolve_canonical_artist(
        async_db, "The Beatles", do_mb_lookup=False
    )
    # Manually register both string variants as aliases.
    async_db.add(
        ArtistAlias(
            alias_normalized="beatles",
            alias="Beatles",
            artist_id=canonical.id,
            source="manual_merge",
        )
    )
    async_db.add(
        ArtistAlias(
            alias_normalized="beatles, the",
            alias="Beatles, The",
            artist_id=canonical.id,
            source="manual_merge",
        )
    )
    # Tracks tagged with the three variants — all point to canonical.
    async_db.add(_new_track(file="t1", artist_id=canonical.id, artist_str="Beatles", album="A"))
    async_db.add(_new_track(file="t2", artist_id=canonical.id, artist_str="The Beatles", album="A"))
    async_db.add(_new_track(file="t3", artist_id=canonical.id, artist_str="Beatles, The", album="B"))
    await async_db.commit()

    response = await list_artists(db=async_db)

    assert response.total == 1
    assert len(response.items) == 1
    item = response.items[0]
    assert item.name == "The Beatles"
    assert item.id == str(canonical.id)
    assert item.track_count == 3
    assert item.album_count == 2


@pytest.mark.asyncio
async def test_list_artists_sorts_by_sort_name(async_db):
    """The Beatles sort_name is 'Beatles, The' — sorts under B."""
    a = await ar.resolve_canonical_artist(async_db, "Aerosmith", do_mb_lookup=False)
    b = await ar.resolve_canonical_artist(async_db, "The Beatles", do_mb_lookup=False)
    c = await ar.resolve_canonical_artist(async_db, "Cocteau Twins", do_mb_lookup=False)
    async_db.add(_new_track(file="t1", artist_id=a.id))
    async_db.add(_new_track(file="t2", artist_id=b.id))
    async_db.add(_new_track(file="t3", artist_id=c.id))
    await async_db.commit()

    response = await list_artists(db=async_db)

    names = [item.name for item in response.items]
    # Aerosmith ("Aerosmith"), The Beatles ("Beatles, The"), Cocteau Twins.
    assert names == ["Aerosmith", "The Beatles", "Cocteau Twins"]


@pytest.mark.asyncio
async def test_list_artists_search_matches_canonical_name(async_db):
    a = await ar.resolve_canonical_artist(
        async_db, "The Beatles", do_mb_lookup=False
    )
    b = await ar.resolve_canonical_artist(
        async_db, "Cocteau Twins", do_mb_lookup=False
    )
    async_db.add(_new_track(file="t1", artist_id=a.id))
    async_db.add(_new_track(file="t2", artist_id=b.id))
    await async_db.commit()

    response = await list_artists(db=async_db, search="beatles")

    assert response.total == 1
    assert response.items[0].name == "The Beatles"


@pytest.mark.asyncio
async def test_get_artist_detail_resolves_alias_and_returns_canonical(async_db):
    """`/library/artists/Beatles` resolves to the canonical 'The Beatles'."""
    canonical = await ar.resolve_canonical_artist(
        async_db, "The Beatles", do_mb_lookup=False
    )
    async_db.add(
        ArtistAlias(
            alias_normalized="beatles",
            alias="Beatles",
            artist_id=canonical.id,
            source="manual_merge",
        )
    )
    async_db.add(_new_track(file="t1", artist_id=canonical.id))
    async_db.add(_new_track(file="t2", artist_id=canonical.id))
    await async_db.commit()

    # URL "Beatles" resolves through the alias → canonical "The Beatles".
    result = await get_artist_detail(db=async_db, artist_name="Beatles")

    assert result.name == "The Beatles"  # canonical, not URL input
    assert result.id == str(canonical.id)
    assert result.track_count == 2


@pytest.mark.asyncio
async def test_get_artist_detail_404_for_unknown_alias(async_db):
    """An artist string with no alias row → 404, not silent string-match."""
    from app.api.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        await get_artist_detail(db=async_db, artist_name="Nobody")


@pytest.mark.asyncio
async def test_get_artist_detail_or_matches_album_artist(async_db):
    """Pass 3: a track tagged ``artist="John Lennon" album_artist="The Beatles"``
    surfaces under both canonical artists in get_artist_detail."""
    beatles = await ar.resolve_canonical_artist(
        async_db, "The Beatles", do_mb_lookup=False
    )
    lennon = await ar.resolve_canonical_artist(
        async_db, "John Lennon", do_mb_lookup=False
    )
    # Compilation track with split artist / album_artist.
    track = Track(
        id=uuid4(),
        file_path="/music/imagine.mp3",
        file_hash="hash-imagine",
        title="Imagine",
        artist="John Lennon",
        album="Imagine",
        album_artist="The Beatles",
        canonical_artist_id=lennon.id,
        canonical_album_artist_id=beatles.id,
        status=TrackStatus.ACTIVE,
    )
    async_db.add(track)
    # Plus a vanilla Beatles track so the artist row isn't empty.
    async_db.add(_new_track(file="t1", artist_id=beatles.id, album="Help!"))
    await async_db.commit()

    # Detail page for "The Beatles" surfaces both tracks.
    beatles_detail = await get_artist_detail(
        db=async_db, artist_name="The Beatles"
    )
    assert beatles_detail.track_count == 2

    # Detail page for "John Lennon" sees only his track.
    lennon_detail = await get_artist_detail(
        db=async_db, artist_name="John Lennon"
    )
    assert lennon_detail.track_count == 1


@pytest.mark.asyncio
async def test_resolve_artist_via_alias_diacritic_fallback(async_db):
    """When the URL preserves diacritics (Björk) and the alias is the
    NFKD-stripped form (bjork), the resolver still finds it via the
    raw lower-trim fallback."""
    canonical = await ar.resolve_canonical_artist(
        async_db, "Björk", do_mb_lookup=False
    )
    await async_db.commit()
    # The resolver registered alias "bjork" (NFKD-stripped).

    # URL form preserves the diacritic — should still resolve.
    found = await _resolve_artist_via_alias(async_db, "Björk")
    assert found is not None
    assert found.id == canonical.id

    # NFKD-stripped form also resolves.
    found2 = await _resolve_artist_via_alias(async_db, "Bjork")
    assert found2 is not None
    assert found2.id == canonical.id


@pytest.mark.asyncio
async def test_summary_carries_the_table_columns(async_db):
    """Duration, year range and date-added come back on the list (ADR-0094).

    All three are aggregates over the join that already computes the counts, so the point of this
    test is that they are actually selected and mapped — a column that is computed and dropped on
    the floor is the defect ADR-0094 was written about in the first place.
    """
    artist = await ar.resolve_canonical_artist(async_db, "Aggregates", do_mb_lookup=False)
    early = _new_track(file="a0", artist_id=artist.id, artist_str="Aggregates")
    early.duration_seconds = 100.0
    early.year = 1994
    late = _new_track(file="a1", artist_id=artist.id, artist_str="Aggregates", album="Later")
    late.duration_seconds = 50.0
    late.year = 2003
    async_db.add_all([early, late])
    await async_db.commit()

    listed = await list_artists(async_db)
    row = next(a for a in listed.items if a.name == "Aggregates")
    assert row.total_duration_seconds == 150.0
    assert row.year_min == 1994
    assert row.year_max == 2003
    assert row.date_added is not None


@pytest.mark.asyncio
async def test_play_columns_are_null_without_a_profile(async_db):
    """Per-profile columns have no answer when there is no profile.

    Null rather than 0: "never played" and "no listener to ask about" are different, and reporting
    0 for the second would make an unplayed artist and an unknown one indistinguishable in a column
    people will sort by.
    """
    artist = await ar.resolve_canonical_artist(async_db, "Unknown Listener", do_mb_lookup=False)
    async_db.add(_new_track(file="u0", artist_id=artist.id, artist_str="Unknown Listener"))
    await async_db.commit()

    listed = await list_artists(async_db)
    row = next(a for a in listed.items if a.name == "Unknown Listener")
    assert row.play_count is None
    assert row.last_played_at is None


@pytest.mark.asyncio
async def test_sorting_by_duration_puts_the_longest_first(async_db):
    """`sort_by=duration` orders by total listening time, biggest first."""
    short = await ar.resolve_canonical_artist(async_db, "Short", do_mb_lookup=False)
    long = await ar.resolve_canonical_artist(async_db, "Long", do_mb_lookup=False)
    s0 = _new_track(file="s0", artist_id=short.id, artist_str="Short")
    s0.duration_seconds = 10.0
    l0 = _new_track(file="l0", artist_id=long.id, artist_str="Long")
    l0.duration_seconds = 900.0
    async_db.add_all([s0, l0])
    await async_db.commit()

    listed = await list_artists(async_db, sort_by="duration")
    names = [a.name for a in listed.items]
    assert names.index("Long") < names.index("Short")


@pytest.mark.asyncio
async def test_an_unknown_sort_falls_back_to_name_rather_than_erroring(async_db):
    """A sort the server does not know orders by name instead of failing.

    This is what makes a client typo survivable — and also why `ArtistSort.wireValue` is asserted
    on the Swift side: the fallback means a wrong value is silently ignored rather than reported.
    """
    for who in ("Zed", "Alpha"):
        a = await ar.resolve_canonical_artist(async_db, who, do_mb_lookup=False)
        async_db.add(_new_track(file=f"{who}0", artist_id=a.id, artist_str=who))
    await async_db.commit()

    listed = await list_artists(async_db, sort_by="not_a_column")
    names = [a.name for a in listed.items if a.name in {"Zed", "Alpha"}]
    assert names == ["Alpha", "Zed"]
