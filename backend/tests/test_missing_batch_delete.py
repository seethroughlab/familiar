"""`DELETE /library/missing/batch` must reach the batch handler.

It did not, from the day it was written until 2026-09-14: `DELETE /missing/{track_id}` was declared
first, so Starlette matched `batch` as a track id and the endpoint answered 400 "Invalid track ID"
for every call. Nothing noticed because nothing called it — the first caller was a script deleting
24 missing tracks, which fell back to 24 single deletes.

`routes/__init__.py` already records this ordering rule for `pending_review`'s `group` and `bulk`
routers. The first test pins the order in the router itself; the second pins the observable
behaviour, so a future reshuffle that keeps the order but breaks the route some other way still
fails here.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.routes import library_missing


def _delete_paths() -> list[str]:
    return [
        r.path
        for r in library_missing.router.routes
        if getattr(r, "methods", None) and "DELETE" in r.methods
    ]


class TestBatchIsDeclaredBeforeTheParameter:
    def test_literal_batch_precedes_track_id(self):
        paths = _delete_paths()  # router-relative; the /library prefix is the parent's
        assert "/missing/batch" in paths
        assert paths.index("/missing/batch") < paths.index("/missing/{track_id}")


class TestBatchIsReachable:
    def test_an_empty_batch_is_a_completed_batch_not_an_invalid_id(self, client: TestClient):
        response = client.request("DELETE", "/api/v1/library/missing/batch", json={"track_ids": []})
        assert response.status_code == 200, response.text
        assert response.json() == {"status": "completed", "deleted": 0, "errors": []}

    def test_a_bad_id_is_reported_inside_the_batch(self, client: TestClient):
        """The batch handler collects per-id errors; the single handler raises. Only one of them
        turns "not-a-uuid" into an `errors` entry."""
        response = client.request(
            "DELETE", "/api/v1/library/missing/batch", json={"track_ids": ["not-a-uuid"]}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["deleted"] == 0
        assert body["errors"] == ["not-a-uuid: invalid ID"]
