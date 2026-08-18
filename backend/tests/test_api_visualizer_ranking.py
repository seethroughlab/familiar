"""Tests for `POST /tracks/{id}/visualizer-ranking` (ADR-0064).

The scoring itself is covered without a database in `test_visualizer_affinity.py`. What needs the
database is the wiring: that a real `TrackAnalysis` reaches the scorer, and — the assertion that
matters most here — that **an unanalysed track is a 200 with `ranked: false`, not a 404**.

That distinction is the whole no-analysis contract. A library part-way through a sync has a
meaningful fraction of unanalysed tracks, and if this endpoint errored on them the client would
treat an ordinary state as a failure. A track that does not exist is still a genuine 404.
"""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import make_profile_headers
from tests.factories import insert_test_analysis, insert_test_track

pytestmark = pytest.mark.asyncio


def url(track_id) -> str:
    return f"/api/v1/tracks/{track_id}/visualizer-ranking"


AMBIENT_VIS = {
    "id": "reactive-terrain",
    "affinity": {"tags": ["ambient", "dreamy"], "ranges": [{"feature": "energy", "maximum": 0.4}]},
}
LOUD_VIS = {
    "id": "beat-tiles",
    "affinity": {"tags": ["metal"], "ranges": [{"feature": "energy", "minimum": 0.7}]},
}


class TestRanking:
    async def test_ranks_a_calm_track_toward_the_calm_visualizer(
        self, client, test_profile, async_db: AsyncSession
    ):
        track = await insert_test_track(async_db, title="Slow One")
        await insert_test_analysis(
            async_db,
            track.id,
            {
                "energy": 0.15,
                "bpm": 72.0,
                "mood_tags": [{"tag": "ambient", "category": "mood", "confidence": 0.9}],
            },
        )
        await async_db.commit()

        r = client.post(
            url(track.id),
            json={"candidates": [LOUD_VIS, AMBIENT_VIS]},
            headers=make_profile_headers(test_profile),
        )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ranked"] is True
        assert [v["id"] for v in body["visualizers"]] == ["reactive-terrain", "beat-tiles"]
        assert "ambient" in body["visualizers"][0]["matched_tags"]
        assert "energy" in body["visualizers"][0]["matched_ranges"]

    async def test_the_response_is_typed_rather_than_a_bare_dict(
        self, client, test_profile, async_db: AsyncSession
    ):
        """Shape assertion — this is what the generated Swift client models (ADR-0007)."""
        track = await insert_test_track(async_db)
        await insert_test_analysis(async_db, track.id, {"energy": 0.5})
        await async_db.commit()

        r = client.post(
            url(track.id),
            json={"candidates": [{"id": "lyrics"}]},
            headers=make_profile_headers(test_profile),
        )

        assert r.status_code == 200, r.text
        assert set(r.json()) == {"visualizers", "ranked"}
        assert set(r.json()["visualizers"][0]) == {
            "id",
            "score",
            "matched_tags",
            "matched_ranges",
            "unmatched_ranges",
            "ignored",
        }

    async def test_a_candidate_with_no_affinity_is_accepted(
        self, client, test_profile, async_db: AsyncSession
    ):
        track = await insert_test_track(async_db)
        await insert_test_analysis(async_db, track.id, {"energy": 0.5})
        await async_db.commit()

        r = client.post(
            url(track.id),
            json={"candidates": [{"id": "music-video"}]},
            headers=make_profile_headers(test_profile),
        )
        assert r.status_code == 200, r.text
        assert r.json()["visualizers"][0]["id"] == "music-video"

    async def test_unrecognised_declarations_are_reported_not_refused(
        self, client, test_profile, async_db: AsyncSession
    ):
        track = await insert_test_track(async_db)
        await insert_test_analysis(
            async_db,
            track.id,
            {"energy": 0.5, "mood_tags": [{"tag": "calm", "category": "mood", "confidence": 0.8}]},
        )
        await async_db.commit()

        r = client.post(
            url(track.id),
            json={
                "candidates": [
                    {
                        "id": "odd",
                        "affinity": {
                            "tags": ["calm", "not-a-real-tag"],
                            # `form_string` holds a string; `vibes` does not exist.
                            "ranges": [
                                {"feature": "form_string", "minimum": 0},
                                {"feature": "vibes", "maximum": 1},
                            ],
                        },
                    }
                ]
            },
            headers=make_profile_headers(test_profile),
        )

        assert r.status_code == 200, r.text
        ignored = r.json()["visualizers"][0]["ignored"]
        assert set(ignored) == {"not-a-real-tag", "form_string", "vibes"}
        # Still ranked, and still matched on the part that was understood.
        assert r.json()["visualizers"][0]["matched_tags"] == ["calm"]


class TestNoAnalysis:
    async def test_an_unanalysed_track_is_200_and_unranked(
        self, client, test_profile, async_db: AsyncSession
    ):
        """The load-bearing case: ordinary on a syncing library, so it must not be an error."""
        track = await insert_test_track(async_db, title="Not Analysed Yet")
        await async_db.commit()

        r = client.post(
            url(track.id),
            json={"candidates": [LOUD_VIS, AMBIENT_VIS]},
            headers=make_profile_headers(test_profile),
        )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ranked"] is False
        # Submitted order preserved, so the client can keep showing what it already had.
        assert [v["id"] for v in body["visualizers"]] == ["beat-tiles", "reactive-terrain"]

    async def test_an_analysis_row_with_no_features_is_also_unranked(
        self, client, test_profile, async_db: AsyncSession
    ):
        track = await insert_test_track(async_db)
        await insert_test_analysis(async_db, track.id, None)
        await async_db.commit()

        r = client.post(
            url(track.id),
            json={"candidates": [AMBIENT_VIS]},
            headers=make_profile_headers(test_profile),
        )
        assert r.status_code == 200, r.text
        assert r.json()["ranked"] is False


class TestErrors:
    async def test_an_unknown_track_is_404(self, client, test_profile):
        r = client.post(
            url(uuid4()),
            json={"candidates": [AMBIENT_VIS]},
            headers=make_profile_headers(test_profile),
        )
        assert r.status_code == 404, r.text

    async def test_a_malformed_track_id_is_422(self, client, test_profile):
        r = client.post(
            url("not-a-uuid"),
            json={"candidates": []},
            headers=make_profile_headers(test_profile),
        )
        assert r.status_code == 422, r.text

    async def test_no_candidates_ranks_to_an_empty_list(
        self, client, test_profile, async_db: AsyncSession
    ):
        track = await insert_test_track(async_db)
        await insert_test_analysis(async_db, track.id, {"energy": 0.5})
        await async_db.commit()

        r = client.post(
            url(track.id), json={"candidates": []}, headers=make_profile_headers(test_profile)
        )
        assert r.status_code == 200, r.text
        assert r.json()["visualizers"] == []
