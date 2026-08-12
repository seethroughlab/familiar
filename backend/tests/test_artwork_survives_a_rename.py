"""Renaming an album in Familiar does not take its cover away (ADR-0052).

This is the claim the whole change exists to deliver, so it is asserted directly rather
than inferred from the parts.

The mechanism is worth stating because it is the opposite of the obvious one:

- ``compute_album_hash`` reads the **database** columns. Correcting an album name in
  Familiar changes ``track.album``, so the hash moves and the cover is lost.
- ``canonical_album_id`` is resolved from the **file's** tags. Familiar never writes to
  files, so the id does not move and the cover stays.

What this does *not* cover — a file retagged in another application — is asserted too,
so the boundary is recorded rather than assumed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete

from app.db.models import Album, AlbumAlias
from app.services import metadata_overrides
from app.services.album_resolver import resolve_canonical_album
from app.services.artwork import album_key_for_track, compute_album_hash
from tests.factories import insert_test_track


@pytest.fixture(autouse=True)
async def _cleanup_albums(async_db):
    await async_db.execute(delete(AlbumAlias))
    await async_db.execute(delete(Album))
    await async_db.commit()
    yield
    await async_db.execute(delete(AlbumAlias))
    await async_db.execute(delete(Album))
    await async_db.commit()


@pytest.mark.asyncio
async def test_the_artwork_key_survives_a_rename_in_familiar(async_db):
    track = await insert_test_track(
        async_db, artist="Rachel's", album="Selenograpy", file_path="/music/r/1.mp3"
    )
    album = await resolve_canonical_album(
        async_db, "Selenograpy", album_artist_id=track.canonical_artist_id
    )
    track.canonical_album_id = album.id
    await async_db.commit()

    before = album_key_for_track(track)

    # What the metadata editor does: correct the library, never the file.
    track.album = "Selenography"
    track.metadata_overrides = metadata_overrides.record(
        track.metadata_overrides, {"album": "Selenography"}
    )
    await async_db.commit()

    assert album_key_for_track(track) == before, "the cover moved when the album was renamed"


@pytest.mark.asyncio
async def test_the_old_hash_would_have_moved(async_db):
    """The counterfactual, so the test above cannot pass for an accidental reason."""
    assert compute_album_hash("Rachel's", "Selenograpy") != compute_album_hash(
        "Rachel's", "Selenography"
    )


@pytest.mark.asyncio
async def test_a_rescan_of_the_unchanged_file_keeps_the_album(async_db):
    """The scanner re-resolves from the file's tags, which a rename in Familiar did not
    touch — so the same album comes back."""
    track = await insert_test_track(
        async_db, artist="Rachel's", album="Selenograpy", file_path="/music/r/1.mp3"
    )
    album = await resolve_canonical_album(
        async_db, "Selenograpy", album_artist_id=track.canonical_artist_id
    )
    track.canonical_album_id = album.id
    await async_db.commit()

    # The file still says "Selenograpy" — that is what a rescan reads.
    again = await resolve_canonical_album(
        async_db, "Selenograpy", album_artist_id=track.canonical_artist_id
    )
    assert again.id == album.id


@pytest.mark.asyncio
async def test_a_file_retagged_elsewhere_becomes_a_different_album(async_db):
    """The limit, recorded rather than papered over.

    A hash fails this case too. ADR-0052 decision point 4 states it, and notes the fix
    that was considered and rejected — treating the track's existing album as evidence,
    which is wrong whenever somebody genuinely moves a track between albums.
    """
    track = await insert_test_track(
        async_db, artist="Rachel's", album="Selenograpy", file_path="/music/r/1.mp3"
    )
    original = await resolve_canonical_album(
        async_db, "Selenograpy", album_artist_id=track.canonical_artist_id
    )
    await async_db.commit()

    retagged = await resolve_canonical_album(
        async_db, "Selenography", album_artist_id=track.canonical_artist_id
    )
    await async_db.commit()
    assert retagged.id != original.id


@pytest.mark.asyncio
async def test_an_unresolved_track_still_gets_a_key(async_db):
    """The fallback that makes the rollout safe: before the backfill, every track has a
    null canonical_album_id and behaves exactly as it did before."""
    track = await insert_test_track(
        async_db, artist="A", album="B", file_path="/music/a/1.mp3"
    )
    track.canonical_album_id = None
    await async_db.commit()
    assert album_key_for_track(track) == compute_album_hash("A", "B")
