"""Tests for the radio suggestion path (ADR-0005 part 5).

These exercise the two data sources the pure scorer cannot fetch for itself — taste from
`ProfilePlayHistory`/`ProfileFavorite`, and negative signal from `PlayEvent` — plus the
endpoint that wires them together.

The single most important assertion here is that an `errored` PlayEvent never demotes a
track. `errored` means playback *failed*, not that the listener disliked it. Treating a
bad network night as a taste signal would let the recommender quietly learn to avoid
whatever happened to be playing when the connection dropped — a failure that would be
invisible for months and unattributable when finally noticed.
"""

from datetime import timedelta
from uuid import uuid4

import pytest

from app.services.ambient import (
    NEGATIVE_SIGNAL_WINDOW_DAYS,
    _fetch_negative_signal,
    _fetch_taste_scores,
    get_candidates,
)
from app.services.ranking_profiles import AMBIENT, RADIO
from app.utils.time import utcnow
from tests.factories import (
    insert_test_analysis,
    insert_test_play_event,
    insert_test_profile,
    insert_test_track,
)

pytestmark = pytest.mark.asyncio


async def _track_with_analysis(db, **kw):
    features = kw.pop("features", None) or {}
    track = await insert_test_track(db, **kw)
    await insert_test_analysis(
        db,
        track.id,
        {"energy": 0.5, "brightness": 0.5, "valence": 0.5, "key": "C", "bpm": 120.0, **features},
    )
    return track


# ---------------------------------------------------------------------------
# Negative signal
# ---------------------------------------------------------------------------


class TestNegativeSignal:
    async def test_errored_events_are_not_a_taste_signal(self, async_db):
        """The one that would silently poison the recommender."""
        profile = await insert_test_profile(async_db)
        track = await _track_with_analysis(async_db, title="Unlucky")
        for _ in range(5):
            await insert_test_play_event(
                async_db, profile.id, track.id, outcome="errored"
            )

        counts = await _fetch_negative_signal(async_db, profile.id, [track.id])

        assert counts.get(track.id, (0, 0)) == (0, 0), (
            "a track that failed to stream five times must not be demoted for it"
        )

    async def test_completed_events_are_not_negative(self, async_db):
        profile = await insert_test_profile(async_db)
        track = await _track_with_analysis(async_db)
        await insert_test_play_event(async_db, profile.id, track.id, outcome="completed")

        assert await _fetch_negative_signal(async_db, profile.id, [track.id]) == {}

    async def test_counts_skips_and_rejections_separately(self, async_db):
        profile = await insert_test_profile(async_db)
        track = await _track_with_analysis(async_db)
        for _ in range(3):
            await insert_test_play_event(async_db, profile.id, track.id, outcome="skipped")
        await insert_test_play_event(async_db, profile.id, track.id, outcome="rejected")

        assert (await _fetch_negative_signal(async_db, profile.id, [track.id]))[track.id] == (3, 1)

    async def test_events_older_than_the_window_are_ignored(self, async_db):
        """Taste changes; a track skipped repeatedly last year is not exiled forever."""
        profile = await insert_test_profile(async_db)
        track = await _track_with_analysis(async_db)
        await insert_test_play_event(
            async_db, profile.id, track.id, outcome="skipped",
            started_at=utcnow() - timedelta(days=NEGATIVE_SIGNAL_WINDOW_DAYS + 5),
        )

        assert await _fetch_negative_signal(async_db, profile.id, [track.id]) == {}

    async def test_events_inside_the_window_count(self, async_db):
        profile = await insert_test_profile(async_db)
        track = await _track_with_analysis(async_db)
        await insert_test_play_event(
            async_db, profile.id, track.id, outcome="skipped",
            started_at=utcnow() - timedelta(days=NEGATIVE_SIGNAL_WINDOW_DAYS - 5),
        )

        assert (await _fetch_negative_signal(async_db, profile.id, [track.id]))[track.id] == (1, 0)

    async def test_another_profile_s_dislikes_do_not_leak(self, async_db):
        mine = await insert_test_profile(async_db, name="Mine")
        theirs = await insert_test_profile(async_db, name="Theirs")
        track = await _track_with_analysis(async_db)
        for _ in range(4):
            await insert_test_play_event(async_db, theirs.id, track.id, outcome="rejected")

        assert await _fetch_negative_signal(async_db, mine.id, [track.id]) == {}


# ---------------------------------------------------------------------------
# Taste
# ---------------------------------------------------------------------------


class TestTasteScores:
    async def test_normalised_into_range(self, async_db):
        profile = await insert_test_profile(async_db)
        tracks = [await _track_with_analysis(async_db, title=f"T{i}") for i in range(4)]

        scores = await _fetch_taste_scores(async_db, profile.id, [t.id for t in tracks])

        assert scores, "expected a score per candidate"
        assert all(0.0 <= v <= 1.0 for v in scores.values()), scores
        assert max(scores.values()) == pytest.approx(1.0), "top candidate anchors the scale"

    async def test_a_favourite_outranks_an_otherwise_identical_track(self, async_db):
        from app.db.models import ProfileFavorite

        profile = await insert_test_profile(async_db)
        plain = await _track_with_analysis(async_db, title="Plain")
        loved = await _track_with_analysis(async_db, title="Loved")
        async_db.add(ProfileFavorite(profile_id=profile.id, track_id=loved.id))
        await async_db.flush()

        scores = await _fetch_taste_scores(async_db, profile.id, [plain.id, loved.id])

        # `rediscover` has favorites_boost 1.0, so a favourite alone need not win — but it
        # must never score lower than an identical non-favourite.
        assert scores[loved.id] >= scores[plain.id]

    async def test_empty_candidate_set_is_not_a_query(self, async_db):
        profile = await insert_test_profile(async_db)
        assert await _fetch_taste_scores(async_db, profile.id, []) == {}


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


class TestRetrieval:
    async def test_missing_tracks_are_never_suggested(self, async_db):
        """A file that is gone from disk 404s on stream; suggesting it is the bug
        `Track.active_filter()` exists to prevent."""
        from app.db.models.base import TrackStatus

        profile = await insert_test_profile(async_db)
        seed = await _track_with_analysis(async_db, title="Seed")
        gone = await _track_with_analysis(async_db, title="Gone")
        gone.status = TrackStatus.MISSING
        await async_db.flush()

        candidates, _, _ = await get_candidates(
            async_db, current_track_id=seed.id, profile=RADIO, profile_id=profile.id, limit=20
        )

        assert gone.id not in {c.descriptor.track_id for c in candidates}

    async def test_the_seed_and_recent_tracks_are_excluded(self, async_db):
        profile = await insert_test_profile(async_db)
        seed = await _track_with_analysis(async_db, title="Seed")
        recent = await _track_with_analysis(async_db, title="Recent")
        other = await _track_with_analysis(async_db, title="Other")

        candidates, _, _ = await get_candidates(
            async_db, current_track_id=seed.id, recent_track_ids=[recent.id],
            profile=RADIO, profile_id=profile.id, limit=20,
        )
        ids = {c.descriptor.track_id for c in candidates}

        assert seed.id not in ids
        assert recent.id not in ids
        assert other.id in ids

    async def test_an_unknown_seed_collapses_rather_than_raising(self, async_db):
        profile = await insert_test_profile(async_db)
        candidates, pool_size, collapsed = await get_candidates(
            async_db, current_track_id=uuid4(), profile=RADIO, profile_id=profile.id
        )
        assert candidates == [] and pool_size == 0 and collapsed is True

    async def test_ambient_runs_without_a_profile_id(self, async_db):
        """Ambient passes neither argument and must be unaffected."""
        seed = await _track_with_analysis(async_db, title="Seed")
        await _track_with_analysis(async_db, title="Other")

        candidates, _, _ = await get_candidates(async_db, current_track_id=seed.id)

        assert candidates, "ambient retrieval still returns candidates"

    async def test_rejected_track_ranks_below_an_equivalent_clean_one(self, async_db):
        profile = await insert_test_profile(async_db)
        seed = await _track_with_analysis(async_db, title="Seed")
        clean = await _track_with_analysis(async_db, title="Clean", artist="A")
        disliked = await _track_with_analysis(async_db, title="Disliked", artist="A")
        for _ in range(3):
            await insert_test_play_event(async_db, profile.id, disliked.id, outcome="rejected")

        candidates, _, _ = await get_candidates(
            async_db, current_track_id=seed.id, profile=RADIO, profile_id=profile.id, limit=20
        )
        scores = {c.descriptor.track_id: c.compatibility_score for c in candidates}

        assert scores[disliked.id] < scores[clean.id]

    async def test_ambient_ignores_the_same_history(self, async_db):
        """Both terms are zero-weighted under AMBIENT, so history must not move it."""
        profile = await insert_test_profile(async_db)
        seed = await _track_with_analysis(async_db, title="Seed")
        clean = await _track_with_analysis(async_db, title="Clean", artist="A")
        disliked = await _track_with_analysis(async_db, title="Disliked", artist="A")
        for _ in range(5):
            await insert_test_play_event(async_db, profile.id, disliked.id, outcome="rejected")

        candidates, _, _ = await get_candidates(
            async_db, current_track_id=seed.id, profile=AMBIENT, profile_id=profile.id, limit=20
        )
        scores = {c.descriptor.track_id: c.compatibility_score for c in candidates}

        assert scores[disliked.id] == pytest.approx(scores[clean.id])


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


class TestEndpoint:
    async def test_requires_a_profile(self, client):
        r = client.post("/api/v1/queue/suggestions", json={"current_track_id": str(uuid4())})
        assert r.status_code == 401

    async def test_unknown_profile_name_is_a_validation_error_not_a_500(
        self, client, test_profile
    ):
        """`get_profile` raises ValueError; unmapped that would be a 500."""
        from tests.conftest import make_profile_headers

        r = client.post(
            "/api/v1/queue/suggestions",
            json={"current_track_id": str(uuid4()), "profile": "jazz-o-matic"},
            headers=make_profile_headers(test_profile),
        )
        # `ValidationError` from app.api.exceptions maps to 400, not 422 — 422 is
        # FastAPI's own body-validation status.
        assert r.status_code == 400, r.text
        assert "jazz-o-matic" in r.text

    async def test_malformed_uuid_is_422_not_500(self, client, test_profile):
        from tests.conftest import make_profile_headers

        r = client.post(
            "/api/v1/queue/suggestions",
            json={"current_track_id": "not-a-uuid"},
            headers=make_profile_headers(test_profile),
        )
        assert r.status_code == 422, r.text

    async def test_unknown_seed_returns_an_empty_collapsed_pool(self, client, test_profile):
        from tests.conftest import make_profile_headers

        r = client.post(
            "/api/v1/queue/suggestions",
            json={"current_track_id": str(uuid4())},
            headers=make_profile_headers(test_profile),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["suggestions"] == []
        assert body["pool_collapsed"] is True
