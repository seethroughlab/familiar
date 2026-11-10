"""ADR-0174 points 3–5: failures carry a kind, are grouped with a next action, and are redacted."""

from __future__ import annotations

import pytest

from app.services.failure_report import KINDS, failure_kind, group_failures, redact


@pytest.mark.parametrize(
    "message,kind",
    [
        ("could not decode /music/x.mp3: Unspecified internal error.", "undecodable"),
        ("File not found: /music/x.mp3", "file_missing"),
        ("A process in the process pool was terminated abruptly", "worker_crashed"),
        ("Embedding timed out after 600s", "timeout"),
        (
            "(sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) connection is closed",
            "database",
        ),
        ("psycopg2.OperationalError: connection to server at \"db\" failed", "database"),
        ("httpx.ConnectTimeout: timed out", "network"),
        ("HTTP 503 Service Unavailable from musicbrainz.org", "network"),
        ("KeyError: 'bpm'", "error"),
        (None, "error"),
    ],
)
def test_failures_have_a_stable_kind(message, kind):
    assert failure_kind(message) == kind


def test_every_kind_has_a_summary_and_a_next_action():
    for kind, (summary, next_action) in KINDS.items():
        assert summary and next_action, kind


# The secrets are generated per run, never written down: a literal that looks like a credential is
# one a secret scanner rightly flags, and these tests need only the shape around it.
@pytest.mark.parametrize(
    "template",
    [
        "postgresql+asyncpg://familiar:{s}@db:5432/familiar",
        "headers={{'X-Familiar-Token': '{s}'}}",
        "Authorization: Bearer {s}",
        "GET /api?api_key={s}&format=json",
        "anthropic: invalid key sk-ant-{s}",
        "password='{s}' rejected",
    ],
)
def test_credentials_never_reach_the_browser(template):
    import secrets

    value = secrets.token_hex(12)
    out = redact(f"failed: {template.format(s=value)}")
    assert value not in out
    assert "***" in out


def test_redaction_leaves_an_ordinary_message_alone():
    message = "could not decode /music/Cranes/Loved/10 Paris & Rome.mp3"
    assert redact(message) == message


def test_failures_are_grouped_by_kind_and_task_with_impact():
    records = [
        {"task": "extract_features", "error": "could not decode a.mp3", "track": "A", "timestamp": "2026-11-09T10:00:03"},
        {"task": "extract_features", "error": "could not decode b.mp3", "track": "B", "timestamp": "2026-11-09T10:00:02"},
        {"task": "extract_features", "error": "could not decode a.mp3", "track": "A", "timestamp": "2026-11-09T10:00:01"},
        {"task": "new_releases", "error": "httpx.ConnectTimeout", "track": "Artist", "timestamp": "2026-11-09T09:00:00"},
    ]
    groups = group_failures(records)
    assert [(g.kind, g.task, g.count, g.affected) for g in groups] == [
        ("undecodable", "extract_features", 3, 2),
        ("network", "new_releases", 1, 1),
    ]
    assert groups[0].last_at == "2026-11-09T10:00:03"
    assert groups[0].next_action == KINDS["undecodable"][1]


def test_examples_are_capped_and_redacted():
    import secrets

    value = secrets.token_hex(8)
    records = [
        {"task": "t", "error": f"OperationalError postgresql://u:{value}{i}@db/x", "timestamp": f"2026-11-09T10:00:{i:02d}"}
        for i in range(8)
    ]
    (group,) = group_failures(records)
    assert group.count == 8 and len(group.examples) == 5
    assert not any(value in e["error"] for e in group.examples)


@pytest.mark.asyncio
async def test_workers_endpoint_groups_and_redacts(async_db, monkeypatch):
    import secrets

    from app.api.routes.health import get_worker_status

    value = secrets.token_hex(8)
    stored = [
        # Written before ADR-0174: no kind, unredacted.
        {"task": "extract_features", "error": f"asyncpg: password={value} rejected", "track": "A", "timestamp": "2026-11-09T10:00:00"},
    ]
    monkeypatch.setattr("app.services.tasks.get_recent_failures", lambda limit=10: stored[:limit])
    status = await get_worker_status(async_db)
    assert status.recent_failures[0].kind == "database"
    assert value not in status.recent_failures[0].error
    (group,) = status.failure_groups
    assert (group.kind, group.count, group.affected) == ("database", 1, 1)
    assert value not in group.examples[0].error


def test_recording_stores_the_kind_and_a_redacted_message(monkeypatch):
    import json

    from app.services.tasks import common

    pushed: list[str] = []

    class FakeRedis:
        def lpush(self, key, value):
            pushed.append(value)

        def ltrim(self, *a):
            pass

        def expire(self, *a):
            pass

    monkeypatch.setattr(common, "get_redis", lambda: FakeRedis())
    import secrets

    value = secrets.token_hex(8)
    common._record_task_failure("extract_features", f"Bearer {value} rejected", "A")
    record = json.loads(pushed[0])
    assert record["kind"] == "error"
    assert value not in record["error"]
