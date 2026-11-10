"""Task failures as an operator reads them: what failed, how much, what to do (ADR-0174).

A background task that fails records `{task, error, track, timestamp}` (`tasks/common.py`). Until
ADR-0174 the Analysis page printed those raw, one line per occurrence: a driver exception repeated
thirty times reads as thirty problems and says nothing about what to do. This module gives each
failure a stable `kind` and groups them, with a plain summary and a next action. The raw message
stays available, redacted, behind the summary (points 3 to 5).

`kind` is a stable code, which makes it part of the API contract: add kinds, never rename one. The
analysis kinds reuse `analysis_lifecycle.FailureReason`, so a track's failed state (ADR-0172) and its
task failure name the same thing the same way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.analysis_lifecycle import FailureReason, classify

#: What each kind means to someone who can act on it.
KINDS: dict[str, tuple[str, str]] = {
    FailureReason.UNDECODABLE.value: (
        "The audio file could not be decoded",
        "Check the file plays elsewhere, then replace or re-rip it. It is tried again when the file "
        "changes.",
    ),
    FailureReason.FILE_MISSING.value: (
        "The file is no longer where the library says it is",
        "Run a library sync: it finds a moved file by its contents, or marks it missing.",
    ),
    FailureReason.WORKER_CRASHED.value: (
        "The analysis worker stopped in the middle of a track",
        "Usually memory. Check the server's memory limit; the track is tried again.",
    ),
    FailureReason.TIMEOUT.value: (
        "A task took longer than it is allowed",
        "It is tried again on the next run. A very long file may need leaving out.",
    ),
    "database": (
        "The database refused or dropped a query",
        "Check the database is running under Server → Health, then run the task again.",
    ),
    "network": (
        "An outside service could not be reached",
        "Check the server's internet connection. It is tried again on the next run.",
    ),
    FailureReason.ERROR.value: (
        "An unexpected error",
        "Copy the details and report it; nothing here says what else to try.",
    ),
}

_DATABASE = re.compile(
    r"sqlalchemy|asyncpg|psycopg|OperationalError|IntegrityError|InterfaceError|"
    r"DBAPIError|connection to server .* failed|database .* does not exist",
    re.IGNORECASE,
)
_NETWORK = re.compile(
    r"ConnectError|ConnectTimeout|ReadTimeout|RemoteProtocolError|Name or service not known|"
    r"Temporary failure in name resolution|Connection refused|Max retries exceeded|"
    r"HTTP (?:5\d\d|429)|Service Unavailable",
    re.IGNORECASE,
)


def failure_kind(error: str | None) -> str:
    """The stable kind for a failure message. Database and network are told apart before the
    analysis reasons, because their messages also say "timeout" and "connection"."""
    text = error or ""
    if _DATABASE.search(text):
        return "database"
    if _NETWORK.search(text):
        return "network"
    return classify(text).value


# ── Redaction (point 5): nothing usable as a credential reaches the browser ─────────────────────

_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    # A DSN or URL with a password: keep the user, drop the secret.
    (re.compile(r"(\w+://[^:/\s@]+):[^@\s]+@"), r"\1:***@"),
    # Header and bearer forms of the server token, and API keys by their usual names.
    (re.compile(r"(X-Familiar-Token[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE), r"\1***"),
    (
        re.compile(
            r"((?:api[_-]?key|access[_-]?token|token|secret|password|passwd|apikey)"
            r"[\"']?\s*[:=]\s*[\"']?)[^\s\"'&,}]+",
            re.IGNORECASE,
        ),
        r"\1***",
    ),
    # Provider key shapes that need no label to be recognised.
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "sk-***"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AKIA***"),
]


def redact(text: str | None) -> str:
    """The message with passwords, tokens and keys replaced by `***`."""
    out = text or ""
    for pattern, replacement in _REDACTIONS:
        out = pattern.sub(replacement, out)
    return out


# ── Grouping (point 4) ──────────────────────────────────────────────────────────────────────────


@dataclass
class FailureGroup:
    kind: str
    task: str
    summary: str
    next_action: str
    count: int = 0
    #: Distinct tracks or artists affected, where the failure named one.
    affected: int = 0
    last_at: str | None = None
    #: The most recent occurrences, newest first, redacted.
    examples: list[dict[str, Any]] = field(default_factory=list)


MAX_EXAMPLES = 5


def group_failures(records: list[dict[str, Any]]) -> list[FailureGroup]:
    """Group recorded failures (newest first) by kind and task, most frequent first.

    A record written before ADR-0174 has no `kind`; it is classified here from its message, as the
    analysis migration did for stored failures.
    """
    groups: dict[tuple[str, str], FailureGroup] = {}
    affected: dict[tuple[str, str], set[str]] = {}
    for record in records:
        kind = record.get("kind") or failure_kind(record.get("error"))
        task = record.get("task") or "unknown"
        key = (kind, task)
        if key not in groups:
            summary, next_action = KINDS.get(kind, KINDS[FailureReason.ERROR.value])
            groups[key] = FailureGroup(kind=kind, task=task, summary=summary, next_action=next_action)
            affected[key] = set()
        group = groups[key]
        group.count += 1
        timestamp = record.get("timestamp")
        if timestamp and (group.last_at is None or timestamp > group.last_at):
            group.last_at = timestamp
        if record.get("track"):
            affected[key].add(record["track"])
        if len(group.examples) < MAX_EXAMPLES:
            group.examples.append(
                {
                    "error": redact(record.get("error")),
                    "track": record.get("track"),
                    "timestamp": timestamp,
                }
            )
    for key, group in groups.items():
        group.affected = len(affected[key])
    return sorted(groups.values(), key=lambda g: (g.count, g.last_at or ""), reverse=True)
