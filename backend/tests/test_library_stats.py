"""`/library/stats` must agree with the endpoints that show the same things.

Written after the dashboard for ADR-0058 was pointed at the real 26k library and every total on
this endpoint turned out to be wrong — not by a rounding error, but by counting a different thing
than the screen each figure links to:

| field | stats said | the list endpoint said |
|---|---|---|
| `total_tracks` | 26,488 | 26,422 (`status == ACTIVE`) |
| `total_albums` | 3,873 (`count(distinct album)`) | 3,927 (grouped by album_artist + album) |
| `total_artists` | 3,664 (`count(distinct artist)`) | 3,477 (canonical `Artist`) |

**These assert agreement, not arithmetic.** A test that hard-coded "3 albums" would pass just as
happily with either counting method, which is exactly how the endpoint drifted for as long as it
did. Comparing the two sides means a change to either one has to move both.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.api.routes.library import get_library_stats
from app.api.routes.library_albums import list_albums
from app.api.routes.library_artists import list_artists
from app.db.models import Track, TrackAnalysis, TrackStatus
from app.services import artist_resolver as ar


def _track(
    *,
    file: str,
    artist_id,
    artist: str = "Artist",
    album: str = "Album",
    album_artist: str | None = None,
    status: TrackStatus = TrackStatus.ACTIVE,
) -> Track:
    return Track(
        id=uuid4(),
        file_path=f"/music/{file}.mp3",
        file_hash=f"hash-{file}",
        title=file,
        artist=artist,
        album=album,
        album_artist=album_artist,
        canonical_artist_id=artist_id,
        status=status,
    )


@pytest.mark.asyncio
async def test_album_total_agrees_with_the_album_list(async_db):
    """Two artists with an identically-titled album are two albums, not one.

    `count(distinct Track.album)` said one. The album list, which groups by
    (album_artist, album), said two — and it is the one a person can click through and count.
    """
    a = await ar.resolve_canonical_artist(async_db, "Alpha", do_mb_lookup=False)
    b = await ar.resolve_canonical_artist(async_db, "Beta", do_mb_lookup=False)
    async_db.add(_track(file="t1", artist_id=a.id, artist="Alpha", album="Greatest Hits"))
    async_db.add(_track(file="t2", artist_id=b.id, artist="Beta", album="Greatest Hits"))
    await async_db.commit()

    stats = await get_library_stats(db=async_db)
    albums = await list_albums(db=async_db)

    assert stats.total_albums == albums.total == 2


@pytest.mark.asyncio
async def test_album_total_is_case_insensitive_like_the_album_list(async_db):
    """"Alice In Ultraland" and "Alice in Ultraland" are one album on both sides."""
    a = await ar.resolve_canonical_artist(async_db, "Alpha", do_mb_lookup=False)
    async_db.add(_track(file="t1", artist_id=a.id, artist="Alpha", album="Alice In Ultraland"))
    async_db.add(_track(file="t2", artist_id=a.id, artist="Alpha", album="Alice in Ultraland"))
    await async_db.commit()

    stats = await get_library_stats(db=async_db)
    albums = await list_albums(db=async_db)

    assert stats.total_albums == albums.total == 1


@pytest.mark.asyncio
async def test_artist_total_agrees_with_the_artist_list(async_db):
    """Tag variants of one canonical artist count once, as they do on the artist screen."""
    canonical = await ar.resolve_canonical_artist(async_db, "The Beatles", do_mb_lookup=False)
    async_db.add(_track(file="t1", artist_id=canonical.id, artist="Beatles"))
    async_db.add(_track(file="t2", artist_id=canonical.id, artist="The Beatles"))
    async_db.add(_track(file="t3", artist_id=canonical.id, artist="Beatles, The"))
    await async_db.commit()

    stats = await get_library_stats(db=async_db)
    artists = await list_artists(db=async_db)

    assert stats.total_artists == artists.total == 1


@pytest.mark.asyncio
async def test_non_active_tracks_are_not_library_size(async_db):
    """A deleted file is not in the library, on any of the three totals.

    The real library reported 66 missing/deleted tracks as part of its size.
    """
    a = await ar.resolve_canonical_artist(async_db, "Alpha", do_mb_lookup=False)
    b = await ar.resolve_canonical_artist(async_db, "Ghost", do_mb_lookup=False)
    async_db.add(_track(file="live", artist_id=a.id, artist="Alpha", album="Real"))
    async_db.add(
        _track(
            file="gone",
            artist_id=b.id,
            artist="Ghost",
            album="Vanished",
            status=TrackStatus.MISSING,
        )
    )
    await async_db.commit()

    stats = await get_library_stats(db=async_db)

    assert stats.total_tracks == 1
    assert stats.total_albums == 1
    assert stats.total_artists == 1


@pytest.mark.asyncio
async def test_pending_analysis_is_never_negative(async_db):
    """An analysis belonging to a track that left the library is not credit against the backlog.

    This is the failure the active-filter fix would otherwise have *introduced*: scoping
    `total_tracks` to active while leaving the analysis counts unscoped rendered -41 pending on
    the real library.
    """
    from app.config import FEATURES_VERSION

    a = await ar.resolve_canonical_artist(async_db, "Alpha", do_mb_lookup=False)
    live = _track(file="live", artist_id=a.id, artist="Alpha")
    gone = _track(file="gone", artist_id=a.id, artist="Alpha", status=TrackStatus.MISSING)
    async_db.add_all([live, gone])
    await async_db.flush()
    # Both analysed; only one is still in the library.
    async_db.add(TrackAnalysis(track_id=live.id, features_version=FEATURES_VERSION))
    async_db.add(TrackAnalysis(track_id=gone.id, features_version=FEATURES_VERSION))
    await async_db.commit()

    stats = await get_library_stats(db=async_db)

    assert stats.total_tracks == 1
    assert stats.analyzed_tracks == 1
    assert stats.pending_analysis == 0


@pytest.mark.asyncio
async def test_artwork_coverage_denominator_matches_the_album_total(async_db, tmp_path, monkeypatch):
    """Coverage counts the same albums the dashboard tile counts (ADR-0058 point 6).

    The easy implementation counts canonical `Album` rows, which is a different number from the
    one shown beside it — a coverage percentage over a denominator nobody can see is exactly the
    plausible-looking figure point 6 forbids.
    """
    from app.api.routes.artwork import get_artwork_coverage

    # Patched on the *route* module, not the service: `artwork.py` does `from app.services.artwork
    # import get_artwork_path` at module level, so patching the service leaves the route's own
    # global bound to the original and the test passes without controlling anything.
    monkeypatch.setattr(
        "app.api.routes.artwork.get_artwork_path",
        lambda key, size="full": tmp_path / f"{key}-{size}.jpg",
    )

    a = await ar.resolve_canonical_artist(async_db, "Alpha", do_mb_lookup=False)
    b = await ar.resolve_canonical_artist(async_db, "Beta", do_mb_lookup=False)
    # Two same-titled albums by different artists, one of them spanning a case variant.
    async_db.add(_track(file="t1", artist_id=a.id, artist="Alpha", album="Greatest Hits"))
    async_db.add(_track(file="t2", artist_id=b.id, artist="Beta", album="Greatest Hits"))
    async_db.add(_track(file="t3", artist_id=a.id, artist="Alpha", album="greatest hits"))
    # A non-active track must not add an album to either count.
    async_db.add(
        _track(
            file="gone",
            artist_id=b.id,
            artist="Beta",
            album="Vanished",
            status=TrackStatus.MISSING,
        )
    )
    await async_db.commit()

    stats = await get_library_stats(db=async_db)
    coverage = await get_artwork_coverage(db=async_db)

    assert coverage.total_albums == stats.total_albums == 2
    assert coverage.without_artwork == 2
    assert coverage.with_artwork == 0
    assert coverage.generated == 0


@pytest.mark.asyncio
async def test_artwork_coverage_counts_files_and_placeholders_apart(async_db, tmp_path, monkeypatch):
    """An album with a generated placeholder is covered *and* counted as generated.

    Folding placeholders into `with_artwork` would report a library with no real cover art at all
    as fully covered — the number would be true of the filesystem and false of what a person sees.
    """
    from app.api.routes import artwork as artwork_route

    monkeypatch.setattr(
        artwork_route,
        "get_artwork_path",
        lambda key, size="full": tmp_path / f"{key}-{size}.jpg",
    )
    # "Alpha / Real Art" gets a file; the placeholder marker names only the second album.
    monkeypatch.setattr(
        "app.services.artwork.is_generated_artwork",
        lambda key: key in generated_keys,
    )

    a = await ar.resolve_canonical_artist(async_db, "Alpha", do_mb_lookup=False)
    async_db.add(_track(file="t1", artist_id=a.id, artist="Alpha", album="Real Art"))
    async_db.add(_track(file="t2", artist_id=a.id, artist="Alpha", album="Placeholder"))
    async_db.add(_track(file="t3", artist_id=a.id, artist="Alpha", album="Nothing"))
    await async_db.commit()

    # Work out the keys the endpoint will compute, then create thumbs for two of the three.
    from app.services.artwork import compute_album_hash

    real_key = compute_album_hash("Alpha", "Real Art")
    placeholder_key = compute_album_hash("Alpha", "Placeholder")
    generated_keys = {placeholder_key}
    for key in (real_key, placeholder_key):
        (tmp_path / f"{key}-thumb.jpg").write_bytes(b"x")

    coverage = await artwork_route.get_artwork_coverage(db=async_db)

    assert coverage.total_albums == 3
    assert coverage.with_artwork == 2
    assert coverage.generated == 1
    assert coverage.without_artwork == 1
