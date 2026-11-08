"""A compilation is one record, not a shared title (ADR-0167).

Every case here is from the live library on 2026-11-08. The rule this replaced labelled
Portishead's *Third* "Various Artists" because Soft Machine also has a *Third*. That fused the
two records into one album with one cover.
"""

from itertools import count

import pytest

from app.services.compilations import (
    VARIOUS_ARTISTS,
    CompilationEvidence,
    compilation_track_ids,
)

_ids = count()


def album(title: str, artist: str, folder: str, numbers, disc: int | None = None):
    """One artist's tracks under ``title`` in ``folder``, numbered as given (None = unnumbered)."""
    return [
        CompilationEvidence(
            id=next(_ids),
            album=title,
            artist=artist,
            folder=folder,
            disc_number=disc,
            track_number=n,
        )
        for n in numbers
    ]


def ids(tracks):
    return {t.id for t in tracks}


class TestNotACompilation:
    def test_two_artists_own_albums_that_share_a_title(self):
        portishead = album("Third", "Portishead", "/music/Portishead/Third", range(1, 11))
        soft_machine = album(
            "Third", "The Soft Machine", "/music/The Soft Machine/Third", range(1, 5)
        )

        assert compilation_track_ids(portishead + soft_machine) == set()

    def test_the_same_album_twice_under_two_spellings(self):
        """*TRST* in /music/TR_ST and /music/Trust: a duplicate, not a compilation."""
        a = album("TRST", "TR/ST", "/music/TR_ST/TRST", range(1, 12))
        b = album("TRST", "Trust", "/music/Trust/TRST", range(1, 12))

        assert compilation_track_ids(a + b) == set()

    def test_greatest_hits_leaves_out_the_artists_with_their_own(self):
        cars = album("Greatest Hits", "The Cars", "/music/The Cars/Greatest Hits", range(1, 13))
        pumpkins = album(
            "Greatest Hits",
            "Smashing Pumpkins",
            "/music/Smashing Pumpkins/Greatest Hits",
            range(1, 12),
        )
        strays = album("Greatest Hits", "A Ha", "/music/A Ha/Greatest Hits", [1]) + album(
            "Greatest Hits", "Happy Mondays", "/music/Happy Mondays/Greatest Hits", [5]
        )

        labelled = compilation_track_ids(cars + pumpkins + strays)

        assert labelled.isdisjoint(ids(cars) | ids(pumpkins))
        # The one-track strays are grouped together, as they always were.
        assert labelled == ids(strays)

    def test_featured_credits_do_not_make_a_second_artist(self):
        tracks = album(
            "Heligoland", "Massive Attack", "/music/Massive Attack/Heligoland", [1, 2]
        ) + album(
            "Heligoland",
            "Massive Attack feat. Damon Albarn",
            "/music/Massive Attack/Heligoland",
            [3],
        )

        assert compilation_track_ids(tracks) == set()

    def test_a_guest_credited_track_does_not_make_an_album_a_compilation(self):
        """Plaid's *Not for Threes*, one track credited to Björk, in Plaid's folder."""
        folder = "/music/Plaid/Not for Threes"
        tracks = album("Not for Threes", "Plaid", folder, range(1, 10)) + album(
            "Not for Threes", "Plaid & Björk", folder, [10]
        )

        assert compilation_track_ids(tracks) == set()

    def test_a_variant_spelling_in_another_folder_does_not_either(self):
        """*Psyence Fiction*: 12 UNKLE tracks, and one more filed under U.N.K.L.E."""
        tracks = album(
            "Psyence Fiction", "UNKLE", "/music/UNKLE/Psyence Fiction", range(1, 13)
        ) + album("Psyence Fiction", "U.N.K.L.E.", "/music/U.N.K.L.E_/Psyence Fiction", [None])

        assert compilation_track_ids(tracks) == set()

    def test_one_artist_alone_is_never_a_compilation(self):
        assert compilation_track_ids(album("Third", "Portishead", "/x", range(1, 11))) == set()


class TestACompilation:
    def test_several_artists_in_one_folder(self):
        folder = "/music/Compilations/Snow Robots vol 2"
        tracks = album("Snow Robots vol 2", "Solvent", folder, [1]) + album(
            "Snow Robots vol 2", "Lowfish", folder, [2]
        )

        assert compilation_track_ids(tracks) == ids(tracks)

    def test_one_artist_per_folder_numbered_as_one_sequence(self):
        """*Parts in the Post* lives in 17 artist folders, and *Hohokum* in 13."""
        tracks = (
            album("Hohokum Soundtrack", "Tycho", "/music/Tycho/Hohokum Soundtrack", [3, 9, 14, 17])
            + album("Hohokum Soundtrack", "Kiln", "/music/Kiln/Hohokum Soundtrack", [2, 7, 11])
            + album("Hohokum Soundtrack", "Shigeto", "/music/Shigeto/Hohokum Soundtrack", [5, 12])
        )

        assert compilation_track_ids(tracks) == ids(tracks)

    def test_numbers_repeat_but_no_artist_has_an_album_of_their_own(self):
        """*The Wire 20 Years*: 40 artists, one track each, discs untagged so numbers repeat."""
        tracks = []
        for i in range(40):
            tracks += album(
                "The Wire 20 Years",
                f"Artist {i}",
                f"/music/Artist {i}/The Wire 20 Years",
                [i % 20 + 1],
            )

        assert compilation_track_ids(tracks) == ids(tracks)

    def test_disc_numbers_keep_two_discs_from_colliding(self):
        tracks = album("Box", "A", "/music/A/Box", [1, 2, 3, 4], disc=1) + album(
            "Box", "B", "/music/B/Box", [1, 2, 3, 4], disc=2
        )

        assert compilation_track_ids(tracks) == ids(tracks)

    def test_unnumbered_tracks_cannot_collide(self):
        tracks = album("Mix", "A", "/music/A/Mix", [None] * 4) + album(
            "Mix", "B", "/music/B/Mix", [None] * 4
        )

        assert compilation_track_ids(tracks) == ids(tracks)

    def test_titles_match_regardless_of_case_and_padding(self):
        folder = "/music/Herbert/Around the House"
        tracks = album("Around the House", "Herbert", folder, [1]) + album(
            " around THE house", "Dani Siciliano", folder, [2]
        )

        assert compilation_track_ids(tracks) == ids(tracks)


@pytest.mark.asyncio
async def test_the_scanner_labels_only_blank_album_artists_and_not_a_shared_title(async_db):
    db = async_db
    """The detector writes "Various Artists" into a blank album artist only, by the new rule."""
    from sqlalchemy import select

    from app.db.models import Track
    from app.services.scanner import LibraryScanner
    from tests.factories import insert_test_track

    made = {}
    for name, artist, folder, number, album_artist in [
        ("p1", "Portishead", "/music/Portishead/Third", 1, None),
        ("p2", "Portishead", "/music/Portishead/Third", 2, None),
        ("p3", "Portishead", "/music/Portishead/Third", 3, None),
        ("s1", "The Soft Machine", "/music/The Soft Machine/Third", 1, None),
        ("s2", "The Soft Machine", "/music/The Soft Machine/Third", 2, None),
        ("s3", "The Soft Machine", "/music/The Soft Machine/Third", 3, None),
        ("c1", "Solvent", "/music/Compilations/Snow Robots", 1, None),
        ("c2", "Lowfish", "/music/Compilations/Snow Robots", 2, ""),
        ("c3", "Lowfish", "/music/Compilations/Snow Robots", 3, "Lowfish"),
    ]:
        album_title = "Snow Robots" if name.startswith("c") else "Third"
        t = await insert_test_track(
            db,
            title=name,
            artist=artist,
            album=album_title,
            album_artist=album_artist,
            file_path=f"{folder}/{name}.mp3",
        )
        t.track_number = number
        made[name] = t
    await db.commit()

    result = await LibraryScanner(db).detect_compilation_albums()

    rows = dict((await db.execute(select(Track.title, Track.album_artist))).all())
    assert rows["p1"] is None and rows["s1"] is None, "a shared title is not a compilation"
    assert rows["c1"] == VARIOUS_ARTISTS and rows["c2"] == VARIOUS_ARTISTS
    assert rows["c3"] == "Lowfish", "a tagged album artist is never replaced"
    assert result == {"albums_detected": 1, "tracks_updated": 2}
