"""ListenBrainz fresh releases, filtered to the library (ADR-0099 point 11).

Chosen over Bandcamp after both were probed against the live services on
2026-08-31. Bandcamp's search returns no release dates at all — from either the
search or the album endpoint — and answers "Coil" with *Dödsrit — Mortal Coil*.
ListenBrainz returns 7,713 releases in one call, each carrying MusicBrainz ids, of
which 225 matched this library.
"""

from datetime import datetime

from app.services.discovery.listenbrainz import (
    VARIOUS_ARTISTS_MBID,
    WANTED_TYPES,
    select_for_library,
)

LIBRARY = {"artist-mbid-1": "Boards of Canada", "artist-mbid-2": "Tycho"}


def _release(**over):
    base = {
        "release_group_mbid": "rg-1",
        "release_name": "Some Record",
        "release_group_primary_type": "Album",
        "artist_mbids": ["artist-mbid-1"],
        "artist_credit_name": "BoC",
        "release_date": "2026-08-17",
        "caa_release_mbid": None,
    }
    base.update(over)
    return base


def test_a_release_by_a_library_artist_is_selected():
    got = select_for_library([_release()], LIBRARY)
    assert len(got) == 1
    assert got[0]["release_id"] == "rg-1"
    assert got[0]["musicbrainz_artist_id"] == "artist-mbid-1"


def test_the_librarys_own_spelling_of_the_artist_wins():
    """So the release joins the rows already filed under that artist.

    ListenBrainz credits it as "BoC"; the library calls it "Boards of Canada". Using
    the remote spelling would file a new release under a name nothing else uses.
    """
    got = select_for_library([_release(artist_credit_name="BoC")], LIBRARY)
    assert got[0]["artist_name"] == "Boards of Canada"


def test_a_release_by_an_artist_not_in_the_library_is_ignored():
    got = select_for_library([_release(artist_mbids=["someone-else"])], LIBRARY)
    assert got == []


def test_various_artists_is_excluded():
    """81 of 225 live matches were compilations credited to this placeholder.

    It is a credit, not an artist anyone follows, and leaving it in turns the surface
    into a firehose of unrelated compilations.
    """
    got = select_for_library(
        [_release(artist_mbids=[VARIOUS_ARTISTS_MBID, "artist-mbid-1"])], LIBRARY
    )
    assert got == []


def test_singles_and_broadcasts_are_excluded_but_eps_are_not():
    releases = [
        _release(release_group_mbid="a", release_group_primary_type="Album"),
        _release(release_group_mbid="b", release_group_primary_type="EP"),
        _release(release_group_mbid="c", release_group_primary_type="Single"),
        _release(release_group_mbid="d", release_group_primary_type="Broadcast"),
        _release(release_group_mbid="e", release_group_primary_type=None),
    ]
    ids = {r["release_id"] for r in select_for_library(releases, LIBRARY)}
    assert ids == {"a", "b"}
    assert WANTED_TYPES == {"Album", "EP"}


def test_a_release_with_no_release_group_is_dropped():
    """Without it there is no identity to dedupe on.

    `release_group_mbid` is the same id `external_album_cache.release_id` holds for
    MusicBrainz rows, which is what lets a release found by both sources collapse
    onto one row. A release lacking it would be filed as a permanent duplicate.
    """
    assert select_for_library([_release(release_group_mbid=None)], LIBRARY) == []


def test_the_release_date_is_parsed_not_passed_through():
    got = select_for_library([_release(release_date="2026-08-17")], LIBRARY)
    assert isinstance(got[0]["release_date"], datetime)
    assert got[0]["release_date"].year == 2026


def test_an_unparseable_date_does_not_drop_the_release():
    """A record with a bad date is still a record. `plausible_release_date` and the
    `nullslast` ordering already handle a missing date downstream."""
    got = select_for_library([_release(release_date="not a date")], LIBRARY)
    assert len(got) == 1
    assert got[0]["release_date"] is None


def test_artwork_url_is_built_only_when_cover_art_exists():
    with_art = select_for_library([_release(caa_release_mbid="caa-1")], LIBRARY)
    assert "caa-1" in with_art[0]["artwork_url"]
    assert select_for_library([_release()], LIBRARY)[0]["artwork_url"] is None
