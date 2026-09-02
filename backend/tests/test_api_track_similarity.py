"""Similar-track endpoints and the files they must not offer.

`GET /tracks/{id}/similar` and `GET /tracks/{id}/discover` both rank by cosine distance over the
512-dim CLAP embedding, and **neither excluded MISSING tracks** — files no longer on disk, which
404 the moment anything tries to stream them. Every other similarity query in the codebase already
carried `Track.active_filter()`: `services/ambient.py`, `playlist_generation`,
`collection_suggestions` and both LLM search handlers. These two were the outliers.

The shape is worth naming because it has now been found three times in one week — twice in
`services/ambient.py`'s seed paths, once here. A query that ranks tracks and forgets the status
filter looks completely normal, returns plausible results, and fails only when someone presses play.
"""

from uuid import uuid4

from app.db.models.base import TrackStatus
from tests.factories import insert_test_analysis, insert_test_track

# Two embeddings a fixed distance apart. Values rather than randomness so "nearest" is decidable
# rather than incidental.
NEAR = [1.0] + [0.0] * 511
FAR = [0.0, 1.0] + [0.0] * 510


async def _analysed(db, *, status: TrackStatus = TrackStatus.ACTIVE, embedding=None, **kw):
    track = await insert_test_track(db, **kw)
    track.status = status
    await insert_test_analysis(
        db,
        track.id,
        {"energy": 0.5, "key": "C", "bpm": 120.0, "embedding": embedding or NEAR},
    )
    await db.commit()
    return track


async def test_similar_tracks_never_offers_a_file_that_is_gone(async_db, client):
    """A MISSING neighbour is the closest match and must still not be returned.

    Closest on purpose: if the filter were absent, this is the row that would come back first, so
    the test fails loudly rather than passing because the ordering happened to bury it.
    """
    seed = await _analysed(async_db, title="Seed", embedding=NEAR)
    await _analysed(async_db, title="Gone", status=TrackStatus.MISSING, embedding=NEAR)
    present = await _analysed(async_db, title="Here", embedding=FAR)

    response = client.get(f"/api/v1/tracks/{seed.id}/similar")
    assert response.status_code == 200

    titles = [t["title"] for t in response.json()]
    assert "Gone" not in titles, "a similar track that 404s on stream is not a suggestion"
    assert "Here" in titles
    assert str(present.id) in [t["id"] for t in response.json()]


async def test_track_discover_never_offers_a_file_that_is_gone(async_db, client):
    """The same query, in the endpoint that wraps it alongside artists and purchase links."""
    seed = await _analysed(async_db, title="Seed", embedding=NEAR)
    await _analysed(async_db, title="Gone", status=TrackStatus.MISSING, embedding=NEAR)
    await _analysed(async_db, title="Here", embedding=FAR)

    response = client.get(f"/api/v1/tracks/{seed.id}/discover")
    assert response.status_code == 200

    titles = [t["title"] for t in response.json()["similar_tracks"]]
    assert "Gone" not in titles
    assert "Here" in titles


async def test_the_seed_itself_is_never_its_own_neighbour(async_db, client):
    """Pre-existing behaviour, asserted because the new filter sits directly beside it and a
    careless edit to either `where` would be invisible."""
    seed = await _analysed(async_db, title="Seed", embedding=NEAR)
    await _analysed(async_db, title="Here", embedding=FAR)

    response = client.get(f"/api/v1/tracks/{seed.id}/similar")
    assert str(seed.id) not in [t["id"] for t in response.json()]


async def test_an_unanalysed_seed_is_a_404_rather_than_an_empty_list(async_db, client):
    """Distinguishable answers: nothing to compare against is not the same as nothing similar."""
    track = await insert_test_track(async_db, title="Unanalysed")
    await async_db.commit()

    response = client.get(f"/api/v1/tracks/{track.id}/similar")
    assert response.status_code == 404


def test_similar_tracks_rejects_a_malformed_id(client):
    response = client.get("/api/v1/tracks/not-a-uuid/similar")
    assert response.status_code == 422


def test_similar_tracks_for_an_unknown_id_is_a_404(client):
    response = client.get(f"/api/v1/tracks/{uuid4()}/similar")
    assert response.status_code == 404
