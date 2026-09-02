"""Tests for the restored ambient routes (ADR-0106).

`test_ambient_scoring.py` characterises the engine and is untouched by the revival — that suite
passing is the check that restoring the routes changed no ranking. This one covers the route layer
and, more usefully, the four defects the deleted version carried. Each of those is a real failure
that shipped, so each gets a test that would have caught it:

- a malformed track id was a 500, because the route took `str` and called bare `UUID(...)`
- `/ambient/seed` accepted no intensity and ranked the opening candidates as `balanced` regardless
- `/ambient/seed` reported `pool_collapsed: False` unconditionally, so a filter that left nothing
  looked identical to one that left plenty
- `pick_surprise_seed` and `find_seed_by_artist` never excluded MISSING tracks, so a session could
  be seeded on a file that is no longer on disk and 404s the moment it is streamed

The last of those was live on `main` until this change: `get_candidates` was fixed for exactly
this and carries a comment saying so; the two seed paths were missed.
"""

from typing import get_args
from uuid import uuid4

from app.api.routes.listening.ambient import FilterPreset, Intensity
from app.db.models.base import TrackStatus
from app.services.ambient import (
    FILTER_PRESETS,
    find_seed_by_artist,
    get_track_descriptor,
    pick_surprise_seed,
)
from app.services.ranking_profiles import AMBIENT
from tests.factories import insert_test_analysis, insert_test_track

AMBIENT_FRIENDLY = {
    # Clears `pick_surprise_seed`'s gate: instrumentalness >= 0.5, speechiness <= 0.5,
    # energy <= 0.7, duration >= 60.
    "energy": 0.3,
    "brightness": 0.4,
    "valence": 0.5,
    "key": "C",
    "bpm": 100.0,
    "instrumentalness": 0.9,
    "speechiness": 0.1,
    "acousticness": 0.5,
}


async def _ambient_track(db, *, status: TrackStatus = TrackStatus.ACTIVE, **kw):
    features = {**AMBIENT_FRIENDLY, **kw.pop("features", {})}
    track = await insert_test_track(db, duration_seconds=240.0, **kw)
    track.status = status
    await insert_test_analysis(db, track.id, features)
    await db.flush()
    return track


# ---------------------------------------------------------------------------
# The seed paths must not surface files that are no longer on disk
# ---------------------------------------------------------------------------

async def test_surprise_seed_skips_missing_tracks(async_db):
    """A MISSING track is a file that 404s on stream; seeding on one cannot start a session.

    Worse than the candidate case `get_candidates` already guards: a bad candidate costs one
    skipped transition, a bad *seed* means nothing plays at all.
    """
    await _ambient_track(async_db, title="Gone", status=TrackStatus.MISSING)

    assert await pick_surprise_seed(async_db) is None


async def test_surprise_seed_prefers_an_active_track_over_a_missing_one(async_db):
    """The MISSING track is the better ambient fit, so a filter that works is the only reason
    the active one is returned."""
    await _ambient_track(
        async_db,
        title="Gone",
        status=TrackStatus.MISSING,
        # Higher instrumentalness and lower energy: wins `ambient_fitness` outright.
        features={"instrumentalness": 1.0, "speechiness": 0.0, "energy": 0.25},
    )
    present = await _ambient_track(async_db, title="Here")

    seed = await pick_surprise_seed(async_db)
    assert seed is not None
    assert seed.track_id == present.id


async def test_seed_by_artist_skips_missing_tracks(async_db):
    await _ambient_track(async_db, artist="Ghost Artist", status=TrackStatus.MISSING)

    assert await find_seed_by_artist(async_db, "Ghost Artist") is None


async def test_seed_by_artist_returns_the_active_track(async_db):
    await _ambient_track(async_db, artist="Split Artist", title="Gone", status=TrackStatus.MISSING)
    present = await _ambient_track(async_db, artist="Split Artist", title="Here")

    seed = await find_seed_by_artist(async_db, "Split Artist")
    assert seed is not None
    assert seed.track_id == present.id


# ---------------------------------------------------------------------------
# The descriptor the client actually needs
# ---------------------------------------------------------------------------

async def test_descriptor_carries_what_the_drone_and_the_window_need(async_db):
    """`key` tunes the drone; `duration_seconds` and `energy_shape` place the snippet.

    None of the three is on `TrackFeaturesResponse`, which is why ADR-0106 point 3 refused to
    serve this from `/radio/suggestions`. A null `key` is the quiet failure worth guarding: the
    client's `keyToMidiNote` falls back to C3, so every drone sounds plausible and none of them
    follows the music.
    """
    track = await _ambient_track(async_db, features={"energy_shape": "declining"})

    descriptor = await get_track_descriptor(async_db, track.id)

    assert descriptor is not None
    assert descriptor.key == "C"
    assert descriptor.duration_seconds == 240.0
    assert descriptor.energy_shape == "declining"


async def test_descriptor_is_none_for_an_unknown_track(async_db):
    assert await get_track_descriptor(async_db, uuid4()) is None


# ---------------------------------------------------------------------------
# The wire contract
# ---------------------------------------------------------------------------

def test_malformed_track_id_is_a_422_not_a_500(client, test_profile):
    """The defect `radio.py` documented and the deleted ambient routes kept.

    They declared `track_id: str` and called bare `UUID(track_id)`, so a malformed id raised
    `ValueError` inside the handler and surfaced as a 500. `radio.py:39-40` chose `UUID` for
    exactly this reason while the ambient routes were still shipping the bug next door.
    """
    response = client.get("/api/v1/ambient/descriptor/not-a-uuid")
    assert response.status_code == 422


def test_candidates_rejects_a_malformed_current_track_id(client):
    response = client.post(
        "/api/v1/ambient/candidates",
        json={"current_track_id": "not-a-uuid"},
    )
    assert response.status_code == 422


def test_an_unknown_filter_preset_is_refused_by_the_schema(client):
    """`Literal` rather than `Field(pattern=...)`, so the generated Swift client gets an enum.

    A regex constraint generates as a bare `String`, which is how `ServerRadioSuggestionsSource`
    came to need a comment warning that "RADIO" is not "radio".
    """
    response = client.post(
        "/api/v1/ambient/candidates",
        json={"current_track_id": str(uuid4()), "filter_preset": "lush"},
    )
    assert response.status_code == 422


def test_an_unknown_intensity_is_refused_by_the_schema(client):
    response = client.post(
        "/api/v1/ambient/candidates",
        json={"current_track_id": str(uuid4()), "intensity": "loud"},
    )
    assert response.status_code == 422


def test_a_seed_that_resolves_to_nothing_is_a_404(client):
    response = client.post("/api/v1/ambient/seed", json={"track_id": str(uuid4())})
    assert response.status_code == 404


def test_an_unknown_seed_track_collapses_rather_than_erroring(client):
    """`pool_collapsed` is a normal answer, not a failure — the contract
    `ServerRadioSuggestionsSource` already relies on radio preserving."""
    response = client.post(
        "/api/v1/ambient/candidates",
        json={"current_track_id": str(uuid4())},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["pool_collapsed"] is True
    assert body["candidates"] == []


# ---------------------------------------------------------------------------
# The route's vocabulary and the service's cannot drift
# ---------------------------------------------------------------------------

def test_filter_presets_match_the_service():
    """The `Literal` and `FILTER_PRESETS` are two statements of one list.

    They are in different modules, and a preset accepted by the schema but unknown to
    `_build_filter_conditions` silently applies no filter at all — the request succeeds and the
    setting does nothing, which is the hardest kind of wrong to notice.
    """
    assert set(get_args(FilterPreset)) == set(FILTER_PRESETS)


def test_intensities_match_the_ranking_profile():
    """`quiet` and `immersive` override weights; `balanced` is the unmodified base.

    `weights_for` returns the base weights for an unknown intensity rather than raising, so a
    typo here would be a silently ignored setting rather than an error.
    """
    declared = set(get_args(Intensity))
    assert declared == set(AMBIENT.intensity_overrides) | {"balanced"}
    assert AMBIENT.weights_for("balanced") == AMBIENT.weights
