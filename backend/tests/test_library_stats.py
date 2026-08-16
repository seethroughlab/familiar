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
