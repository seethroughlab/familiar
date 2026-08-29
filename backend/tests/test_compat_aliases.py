"""The moved paths still answer (ADR-0079).

**This file is the reason aliases are safe to have.** An alias is invisible — absent from
`openapi.json`, from `/docs`, from the generated client, and from everything `lint_openapi.py`
counts. Nothing else in the build would notice if one stopped working, and the clients that depend
on it are *already installed*: shipped iOS and macOS builds call `/queue/session` and
`/queue/suggestions`, and cannot be fixed by editing this repository.

So the two properties are asserted directly:

1. **The old path reaches the same handler**, with the same auth and validation behaviour. A 404
   here means a shipped app has silently lost a feature.
2. **The alias is invisible**, which is what stops it becoming a second public spelling of the API.

The bar is deliberately low per test — reaching the handler, not exercising its logic, which
`test_playback_session.py`, `test_queue_suggestions.py` and `test_offline_manifest.py` already do
against the new paths. What matters is *routing*, since that is the only thing the move can break.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.routes.compat import _ALIASES, SUNSET

# (method, old path, new path). Five paths, six routes — `/queue/session` answers GET and PUT.
MOVED = [
    ("GET", "/api/v1/queue/session", "/api/v1/listening/session"),
    ("PUT", "/api/v1/queue/session", "/api/v1/listening/session"),
    ("GET", "/api/v1/queue/session/archive", "/api/v1/listening/session/archive"),
    (
        "POST",
        "/api/v1/queue/session/archive/00000000-0000-0000-0000-000000000000/restore",
        "/api/v1/listening/session/archive/00000000-0000-0000-0000-000000000000/restore",
    ),
    ("POST", "/api/v1/queue/suggestions", "/api/v1/radio/suggestions"),
    ("POST", "/api/v1/queue/offline-manifest", "/api/v1/offline/manifest"),
    # ADR-0075. These two matter more than the four above: their caller is hand-written Swift
    # (`PlaybackCommandClient`), which builds the path as a string, so nothing would fail to
    # compile if the alias broke — it would fail in the field, on a channel an agent drives.
    ("GET", "/api/v1/playback/commands", "/api/v1/commands/stream"),
    (
        "POST",
        "/api/v1/playback/artifacts/00000000-0000-0000-0000-000000000000",
        "/api/v1/commands/artifacts/00000000-0000-0000-0000-000000000000",
    ),
]


def _ids(param):
    return f"{param[0]}-{param[1].replace('/api/v1/', '')}"


@pytest.mark.parametrize(("method", "old", "new"), MOVED, ids=[_ids(m) for m in MOVED])
def test_the_old_path_is_still_routed(client: TestClient, method: str, old: str, new: str) -> None:
    """The alias reaches a handler rather than the 404 a deleted route would give.

    Sent without a profile header, so every one of these answers 401 from `RequiredProfile`
    (ADR-0045). That is the point: a 401 proves the request got *into* the handler's dependency
    chain. A 404 would mean the path no longer resolves at all.
    """
    response = getattr(client, method.lower())(old)
    assert response.status_code != 404, (
        f"{method} {old} returned 404 — a shipped app calling this path has lost the feature. "
        f"The alias in app/api/routes/compat.py is missing or misregistered."
    )
    assert response.status_code == 401


@pytest.mark.parametrize(("method", "old", "new"), MOVED, ids=[_ids(m) for m in MOVED])
def test_the_old_and_new_paths_agree(client: TestClient, method: str, old: str, new: str) -> None:
    """Delegation, not duplication (ADR-0079 point 2).

    The same request to both spellings must be answered the same way. If these ever diverge, the
    alias has become a second implementation — the failure the point exists to prevent.
    """
    old_response = getattr(client, method.lower())(old)
    new_response = getattr(client, method.lower())(new)
    assert old_response.status_code == new_response.status_code

    # `request_id` is per-request by construction and says nothing about the handler.
    def _comparable(payload: dict) -> dict:
        return {k: v for k, v in payload.items() if k != "request_id"}

    assert _comparable(old_response.json()) == _comparable(new_response.json())


@pytest.mark.parametrize(("method", "old", "new"), MOVED, ids=[_ids(m) for m in MOVED])
def test_the_alias_announces_itself(client: TestClient, method: str, old: str, new: str) -> None:
    """`Deprecation` and `Sunset` on the old path only (ADR-0079 point 3).

    They go to machines, not people: a log query for these headers is how the removal decision in
    point 4 gets made on evidence. The new path must not carry them, or the signal is worthless.
    """
    old_response = getattr(client, method.lower())(old)
    assert old_response.headers.get("Deprecation") == "true"
    assert old_response.headers.get("Sunset") == SUNSET

    new_response = getattr(client, method.lower())(new)
    assert "Deprecation" not in new_response.headers
    assert "Sunset" not in new_response.headers


def test_the_aliases_are_absent_from_the_schema(client: TestClient) -> None:
    """Point 1: a newcomer reading the API cannot see these.

    Asserted over the whole schema rather than per path, so a future alias added without
    `include_in_schema=False` fails here too.
    """
    schema = client.get("/openapi.json").json()
    leaked = [
        path
        for path in schema["paths"]
        if path.startswith("/api/v1/queue/") or path.startswith("/api/v1/playback/")
    ]
    assert leaked == [], f"alias paths leaked into the published schema: {leaked}"


def test_every_registered_alias_is_covered_by_this_file() -> None:
    """The table above and the module must not drift.

    Without this, adding an alias to `compat.py` and forgetting to test it looks exactly like
    having tested it — and the thing untested is a path no other test, lint or build touches.
    """
    registered = {(tuple(methods)[0], path) for path, methods, _ in _ALIASES}
    covered = {(method, old.replace("/api/v1", "")) for method, old, _ in MOVED}
    # The restore alias carries a path parameter; compare its template rather than the filled id.
    def _template(method: str, path: str) -> tuple[str, str]:
        if "/restore" in path:
            return (method, "/queue/session/archive/{archive_id}/restore")
        if "/playback/artifacts/" in path:
            return (method, "/playback/artifacts/{request_id}")
        return (method, path)

    covered = {_template(m, p) for m, p in covered}
    assert registered == covered, (
        f"compat.py and this test disagree.\n"
        f"  registered but untested: {sorted(registered - covered)}\n"
        f"  tested but not registered: {sorted(covered - registered)}"
    )
