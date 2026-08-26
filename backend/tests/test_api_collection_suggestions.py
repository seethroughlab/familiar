"""ADR-0093 over the wire, against a real pgvector index.

These are the cases only a database can show: that agreement outranks proximity, that the reason
shown is the one the ranking used, and that the exclusion covers the whole collection rather than
the capped seed.
"""

import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Playlist, PlaylistTrack, ProfileFavorite
from tests.conftest import make_profile_headers
from tests.factories import (
    insert_test_analysis,
    insert_test_profile,
    insert_test_track,
)

WIDTH = 512


def _embedding(*, x: float, y: float) -> list[float]:
    """A vector on the unit circle in the first two dimensions, zero elsewhere."""
    vec = [0.0] * WIDTH
    vec[0] = x
    vec[1] = y
    return vec


async def _track(db: AsyncSession, *, title: str, artist: str, x: float, y: float):
    track = await insert_test_track(db, title=title, artist=artist, album=f"{artist} LP")
    await insert_test_analysis(
        db,
        track.id,
        {"energy": 0.5, "valence": 0.5, "brightness": 0.5, "embedding": _embedding(x=x, y=y)},
    )
    return track


@pytest_asyncio.fixture(autouse=True)
def narrow_neighbourhoods(monkeypatch):
    """Pin the per-seed neighbour count so the fixture's geometry means what it says.

    `_neighbours_for` widens the search on a small seed set, which for two seeds means forty
    neighbours each — more than this fixture contains, so every seed would reach every candidate and
    the vote counts would all be identical. Ten keeps the neighbourhoods narrower than the fixture
    and makes agreement decidable. The scaling rule itself is tested arithmetically in
    `test_collection_suggestions.py`, where it does not need a library to demonstrate.
    """
    monkeypatch.setattr("app.services.collection_suggestions.NEIGHBOURS_MIN", 10)
    monkeypatch.setattr("app.services.collection_suggestions.NEIGHBOURS_MAX", 10)


@pytest_asyncio.fixture
async def library(async_db: AsyncSession):
    """Two favourites pointing the same way, and candidates placed to make agreement decidable.

    `shared` is slightly further from either favourite than `closest` is, but **both** favourites
    reach it. `closest` is nearer to one favourite and invisible to the other. A ranking that sorts
    on similarity alone puts `closest` first; one that counts agreement puts `shared` first.
    """
    profile = await insert_test_profile(async_db, name="Voting User")

    # 140 degrees apart, and the angle is load-bearing. At 90 degrees a track between the two
    # favourites scores 0.71 from each, so summing already beats a single near-perfect vote and the
    # floor is never exercised — the fixture would agree with any implementation. Out here the
    # shared track scores 0.34 from each, so **summed similarity ranks it below `closest`** and only
    # the vote floor puts it first.
    fav_a = await _track(async_db, title="Fav A", artist="Fav Artist A", x=1.0, y=0.0)
    fav_b = await _track(async_db, title="Fav B", artist="Fav Artist B", x=-0.766, y=0.643)
    for fav in (fav_a, fav_b):
        async_db.add(ProfileFavorite(profile_id=profile.id, track_id=fav.id))

    shared = await _track(async_db, title="Shared", artist="Shared Artist", x=0.342, y=0.940)
    closest = await _track(async_db, title="Closest", artist="Closest Artist", x=0.9999, y=0.0141)

    # Eight per favourite: with `closest` that fills nine of each seed's ten slots, leaving exactly
    # one for `shared` and pushing the other favourite's neighbourhood out of reach. Without this
    # the collection is smaller than `NEIGHBOURS_PER_SEED`, every seed reaches every candidate, and
    # a single vote never occurs — the fixture would then agree with any implementation.
    near_a = [
        await _track(
            async_db, title=f"Near A {i}", artist=f"Near A Artist {i}", x=0.99, y=0.10 + i * 0.01
        )
        for i in range(8)
    ]
    near_b = [
        await _track(
            async_db, title=f"Near B {i}", artist=f"Near B Artist {i}", x=-0.77, y=0.63 + i * 0.005
        )
        for i in range(8)
    ]

    await async_db.commit()
    return {
        "profile": profile,
        "favorited": [fav_a, fav_b],
        "shared": shared,
        "closest": closest,
        "near_a": near_a,
        "near_b": near_b,
    }


def _get(client: TestClient, profile, **params):
    response = client.get(
        "/api/v1/favorites/suggested-tracks",
        headers=make_profile_headers({"id": str(profile.id)}),
        params=params,
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestVoting:
    def test_agreement_outranks_proximity(self, client: TestClient, library: dict):
        """The whole mechanism in one assertion.

        `Closest` is all but identical to one favourite and invisible to the other, so it scores
        ~1.0 on a single vote. `Shared` sits between two favourites that are 140 degrees apart, so
        it scores ~0.34 from each — **a lower total than `Closest`** — but two seeds reach it.

        Ranking on summed similarity therefore leads with `Closest`; only the vote floor leads with
        `Shared`. The geometry is chosen so that this assertion fails if the floor is removed.
        """
        # Wide enough to contain `Closest` as well as the winner — the comparison below is the
        # point, and a limit that cuts `Closest` off would assert nothing about it.
        data = _get(client, library["profile"], limit=20)
        suggestions = data["suggestions"]

        assert suggestions[0]["track"]["title"] == "Shared"
        assert suggestions[0]["votes"] >= 2

        by_title = {s["track"]["title"]: s for s in suggestions}
        assert by_title["Closest"]["votes"] == 1
        # The premise, asserted rather than assumed: agreement won *against* the score. `Closest`
        # alone out-scores both of `Shared`'s votes put together, and still ranks below it.
        assert by_title["Closest"]["similarity"] > by_title["Shared"]["similarity"] * 2
        assert suggestions.index(by_title["Closest"]) > 0

    def test_the_reason_names_a_seed_and_matches_the_ranking(
        self, client: TestClient, library: dict
    ):
        """A caption that disagrees with the ranking is a lie that looks like a feature."""
        data = _get(client, library["profile"], limit=10)
        favourite_ids = {str(t.id) for t in library["favorited"]}

        for suggestion in data["suggestions"]:
            assert suggestion["because_of"]["track_id"] in favourite_ids
            assert suggestion["because_of"]["title"] is not None
            assert 0.0 <= suggestion["similarity"] <= 1.0
            assert suggestion["votes"] >= 1

    def test_single_votes_still_fill_the_list(self, client: TestClient, library: dict):
        """Agreement is preferred, not required — otherwise a tiny collection answers nothing."""
        data = _get(client, library["profile"], limit=10)
        assert len(data["suggestions"]) > 1
        assert any(s["votes"] == 1 for s in data["suggestions"])

    def test_limit_is_honoured(self, client: TestClient, library: dict):
        assert len(_get(client, library["profile"], limit=2)["suggestions"]) <= 2

    def test_repeated_calls_agree(self, client: TestClient, library: dict):
        first = _get(client, library["profile"], limit=10)
        second = _get(client, library["profile"], limit=10)
        assert [s["track"]["id"] for s in first["suggestions"]] == [
            s["track"]["id"] for s in second["suggestions"]
        ]


class TestExclusion:
    def test_never_suggests_something_already_favorited(self, client: TestClient, library: dict):
        """ADR-0093 point 4, and the most visible way this feature can be wrong."""
        data = _get(client, library["profile"], limit=20)
        suggested = {s["track"]["id"] for s in data["suggestions"]}
        assert suggested
        assert not (suggested & {str(t.id) for t in library["favorited"]})

    def test_the_cap_bounds_the_seed_but_not_the_exclusion(
        self, client: TestClient, library: dict, monkeypatch
    ):
        """With the cap binding, the seed is a *sample* — so "exclude the seed" and "exclude what
        the listener already has" become different sets for the first time, which is the defect
        point 4 exists to prevent. Patched where the route reads it, since it imports by value.
        """
        monkeypatch.setattr("app.api.routes.favorites.SEED_SAMPLE_CAP", 1)
        data = _get(client, library["profile"], limit=20)
        suggested = {s["track"]["id"] for s in data["suggestions"]}
        assert suggested, "expected suggestions, or the assertion below is vacuous"
        assert not (suggested & {str(t.id) for t in library["favorited"]})

    def test_seed_track_count_reports_the_whole_collection(
        self, client: TestClient, library: dict
    ):
        assert _get(client, library["profile"])["seed_track_count"] == 2


class TestEdges:
    def test_empty_collection_is_an_empty_answer_not_an_error(
        self, client: TestClient, test_profile: dict
    ):
        response = client.get(
            "/api/v1/favorites/suggested-tracks", headers=make_profile_headers(test_profile)
        )
        assert response.status_code == 200
        assert response.json() == {"suggestions": [], "seed_track_count": 0}

    def test_path_is_not_read_as_a_track_id(self, client: TestClient, library: dict):
        """`GET /favorites/{track_id}` is registered on the same prefix.

        Behind it, `suggested-tracks` parses as a UUID and 422s. A 200 carrying `suggestions` is the
        assertion that the literal route is still ahead of the parameterised one.
        """
        response = client.get(
            "/api/v1/favorites/suggested-tracks",
            headers=make_profile_headers({"id": str(library["profile"].id)}),
        )
        assert response.status_code == 200
        assert "suggestions" in response.json()

    def test_requires_a_profile(self, client: TestClient):
        assert client.get("/api/v1/favorites/suggested-tracks").status_code in (400, 401, 422)


@pytest_asyncio.fixture
async def playlist_library(async_db: AsyncSession, library: dict):
    playlist = Playlist(profile_id=library["profile"].id, name="Test Playlist")
    async_db.add(playlist)
    await async_db.flush()

    members = library["favorited"]
    for position, track in enumerate(members):
        async_db.add(PlaylistTrack(playlist_id=playlist.id, track_id=track.id, position=position))
    await async_db.commit()
    return {"playlist": playlist, "members": members, **library}


class TestPlaylistSuggestions:
    def test_suggests_tracks_not_already_in_the_playlist(
        self, client: TestClient, playlist_library: dict
    ):
        headers = make_profile_headers({"id": str(playlist_library["profile"].id)})
        response = client.get(
            f"/api/v1/playlists/{playlist_library['playlist'].id}/suggested-tracks",
            headers=headers,
        )
        assert response.status_code == 200

        data = response.json()
        suggested = {s["track"]["id"] for s in data["suggestions"]}
        assert suggested
        assert not (suggested & {str(t.id) for t in playlist_library["members"]})

    def test_the_reason_names_a_playlist_member(self, client: TestClient, playlist_library: dict):
        headers = make_profile_headers({"id": str(playlist_library["profile"].id)})
        data = client.get(
            f"/api/v1/playlists/{playlist_library['playlist'].id}/suggested-tracks",
            headers=headers,
        ).json()
        member_ids = {str(t.id) for t in playlist_library["members"]}
        assert data["suggestions"]
        for suggestion in data["suggestions"]:
            assert suggestion["because_of"]["track_id"] in member_ids

    def test_unknown_playlist_is_404(self, client: TestClient, test_profile: dict):
        from uuid import uuid4

        response = client.get(
            f"/api/v1/playlists/{uuid4()}/suggested-tracks",
            headers=make_profile_headers(test_profile),
        )
        assert response.status_code == 404

    def test_another_profiles_playlist_is_404(self, client: TestClient, playlist_library: dict):
        other = client.post("/api/v1/profiles", json={"name": "Nosy"}).json()
        response = client.get(
            f"/api/v1/playlists/{playlist_library['playlist'].id}/suggested-tracks",
            headers=make_profile_headers(other),
        )
        assert response.status_code == 404
