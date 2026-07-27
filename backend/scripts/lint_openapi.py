#!/usr/bin/env python3
"""Lint the OpenAPI schema so typed clients can be generated from it (ADR-0007).

Validates, for the surface a generated client will actually cover:
  - No 2xx JSON response generates as an untyped ``object``
  - No response model has fields that generate as ``Any``
  - Every operation carries at least one tag (tags group the generated client)
  - No endpoint claims ``application/json`` while returning audio, images or SSE
  - operationIds are unique and short enough to read

The generated surface is the native v1 listening path (ADR-0001 scope). Library
management stays web-only (ADR-0002) and will never need a Swift client, so its
existing looseness is allowlisted below rather than blocking.

The allowlists are a burn-down list, not an approved state. Anything NEW fails,
which makes adding an untyped response a visible decision in review.

Exit code 0 on success, 1 with details on failure.
"""

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Tags whose operations a generated client will cover. Everything else is
# management surface that stays web-only.
GENERATED_SURFACE = {
    "tracks",
    "library",
    "playlists",
    "smart-playlists",
    "profiles",
    "favorites",
    "chat",
    "mixtapes",
    "ambient",
    # Radio and offline ranking (ADR-0005, ADR-0006). Native clients consume these
    # directly — the whole point of ADR-0006 is that they carry no ranking code.
    "queue",
    # Network audio outputs (WiiM, Sonos, AirPlay, Chromecast). Casting is a listening
    # feature, not a management one — a native client needs to send audio to speakers.
    "outputs",
}

# operationIds longer than this are unusable as generated method names. The
# default FastAPI scheme produced names up to 95 characters before ADR-0007.
MAX_OPERATION_ID_LENGTH = 60

# Media types that must never be advertised as application/json.
NON_JSON_PREFIXES = ("audio/", "image/", "video/", "text/event-stream", "application/zip")

# ---------------------------------------------------------------------------
# Burn-down allowlists — entries here are known-loose, not approved.
# ---------------------------------------------------------------------------

# Out-of-scope operations returning an untyped JSON object. All are management
# or analysis surfaces that a generated client will not call.
ALLOWED_UNTYPED_OPERATIONS = {
    ("GET", "/"),
    ("HEAD", "/api/v1/artwork/check/{artist}/{album}"),
    ("POST", "/api/v1/artwork/queue"),
    ("POST", "/api/v1/artwork/queue/batch"),
    ("POST", "/api/v1/artwork/regenerate"),
    ("POST", "/api/v1/artwork/regenerate-stale"),
    ("POST", "/api/v1/download/analyses"),
    ("GET", "/api/v1/download/analyses/{task_id}/download"),
    ("GET", "/api/v1/download/analyses/{task_id}/status"),
    ("GET", "/api/v1/download/playlist/{playlist_id}"),
    ("GET", "/api/v1/download/smart-playlist/{playlist_id}"),
    ("POST", "/api/v1/download/tracks"),
    ("POST", "/api/v1/export-import/backup"),
    ("POST", "/api/v1/export-import/export"),
    ("POST", "/api/v1/export-import/library/export"),
    ("POST", "/api/v1/external-albums/{external_album_id}/dismiss"),
    ("GET", "/api/v1/new-releases"),
    ("POST", "/api/v1/new-releases/check"),
    ("POST", "/api/v1/new-releases/check/batch"),
    ("GET", "/api/v1/new-releases/status"),
    ("POST", "/api/v1/new-releases/{release_id}/dismiss"),
    ("DELETE", "/api/v1/outputs/zones/{zone_id}/outputs/{output_id}"),
    ("POST", "/api/v1/outputs/zones/{zone_id}/outputs/{output_id}"),
    ("POST", "/api/v1/outputs/zones/{zone_id}/pause"),
    ("POST", "/api/v1/outputs/zones/{zone_id}/play"),
    ("POST", "/api/v1/outputs/zones/{zone_id}/stop"),
    ("POST", "/api/v1/pending-tracks/bulk/approve-all"),
    ("POST", "/api/v1/pending-tracks/bulk/skip-all"),
    ("POST", "/api/v1/pending-tracks/bulk/unskip-all"),
    ("POST", "/api/v1/pending-tracks/group/approve"),
    ("POST", "/api/v1/pending-tracks/group/metadata"),
    ("POST", "/api/v1/pending-tracks/group/replace-upgrades"),
    ("POST", "/api/v1/pending-tracks/group/skip"),
    ("POST", "/api/v1/pending-tracks/group/skip-downgrades"),
    ("POST", "/api/v1/pending-tracks/group/unskip"),
    ("GET", "/api/v1/s3-backup/history"),
    ("POST", "/api/v1/s3-backup/restore"),
    ("POST", "/api/v1/s3-backup/restore/check"),
    ("POST", "/api/v1/s3-backup/restore/download"),
    ("GET", "/api/v1/s3-backup/restore/status"),
    ("POST", "/api/v1/s3-backup/run"),
    ("POST", "/api/v1/tracks/analysis/bulk"),
    ("GET", "/api/v1/tracks/analysis/bulk/{task_id}"),
    ("GET", "/api/v1/tracks/analysis/bulk/{task_id}/report"),
    ("GET", "/api/v1/tracks/{track_id}/analysis"),
    ("POST", "/api/v1/tracks/{track_id}/analysis"),
    ("GET", "/api/v1/tracks/{track_id}/analysis/midi"),
    ("GET", "/api/v1/tracks/{track_id}/analysis/report"),
    ("GET", "/api/v1/tracks/{track_id}/analysis/similarity.png"),
    ("GET", "/api/v1/videos/{track_id}/stream"),
}

# In-scope model fields that are genuinely free-form, with the reason. These are
# not burn-down candidates — they carry data whose shape the API does not own.
ALLOWED_LOOSE_FIELDS = {
    "ChatResponse.tool_calls": "arbitrary LLM tool-call payloads",
    "ChatResponse.queued_tracks": "shape mirrors whatever the LLM queued",
    "ChatResponse.playback_action": "open-ended player command from the LLM",
    "RuleSchema.value": "polymorphic by design — string, number, date, bool or list",
    "TrackMetadataResponse.user_overrides": "free-form user metadata overrides",
    "MixTapeResponse.progress": "opaque render-progress JSON read back from Redis",
    "IdentifyCandidateResponse.features": "third-party AcoustID feature blob",
    "ImportTrackPreview.incoming_quality": "quality descriptor varies by source format",
    "ImportTrackPreview.existing_quality": "quality descriptor varies by source format",
}

# Schema names FastAPI had to fully qualify because two modules declare the same
# model name. Ugly in a generated client; out of scope to fix here.
ALLOWED_MANGLED_SCHEMAS = {
    "app__api__routes__library_import__preview__ImportPreviewResponse",
    "app__api__routes__export_import__profile__ImportPreviewResponse",
}


def _is_loose(schema: dict[str, Any]) -> bool:
    """True when a schema fragment generates as ``Any`` in a typed client."""
    if not schema:
        return True
    # dict[str, Any] renders as additionalProperties: true
    if schema.get("additionalProperties") is True:
        return True
    if (
        schema.get("type") == "object"
        and "properties" not in schema
        and "additionalProperties" not in schema
    ):
        return True
    items = schema.get("items")
    if schema.get("type") == "array":
        if not items:
            return True
        if isinstance(items, dict) and _is_loose(items):
            return True
    for key in ("anyOf", "oneOf", "allOf"):
        for member in schema.get(key, []):
            # A nullable field is anyOf[T, null]; null alone is not looseness.
            if isinstance(member, dict) and member.get("type") == "null":
                continue
            if isinstance(member, dict) and _is_loose(member):
                return True
    return False


def _referenced_schemas(node: Any, found: set[str]) -> None:
    """Collect every component schema name reachable from a fragment."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            found.add(ref.rsplit("/", 1)[-1])
        for value in node.values():
            _referenced_schemas(value, found)
    elif isinstance(node, list):
        for value in node:
            _referenced_schemas(value, found)


def _success_response(operation: dict[str, Any]) -> dict[str, Any] | None:
    codes = sorted(c for c in operation.get("responses", {}) if c.startswith("2"))
    return operation["responses"][codes[0]] if codes else None


def lint_openapi(schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    components = schema.get("components", {}).get("schemas", {})
    seen_operation_ids: dict[str, str] = {}
    in_scope_schemas: set[str] = set()

    for path, methods in sorted(schema.get("paths", {}).items()):
        for method, operation in sorted(methods.items()):
            where = f"{method.upper()} {path}"
            tags = operation.get("tags") or []
            in_scope = bool(set(tags) & GENERATED_SURFACE)

            operation_id = operation.get("operationId", "")
            if operation_id:
                if operation_id in seen_operation_ids:
                    errors.append(
                        f"{where}: duplicate operationId '{operation_id}' "
                        f"(also {seen_operation_ids[operation_id]}) — breaks client generation"
                    )
                seen_operation_ids[operation_id] = where
                if len(operation_id) > MAX_OPERATION_ID_LENGTH:
                    errors.append(
                        f"{where}: operationId is {len(operation_id)} chars "
                        f"(max {MAX_OPERATION_ID_LENGTH}) — '{operation_id}'"
                    )

            if not tags and path.startswith("/api/"):
                errors.append(f"{where}: no tag — generated clients group by tag")

            response = _success_response(operation)
            if response is None:
                continue
            content = response.get("content") or {}

            declared_json = "application/json" in content
            declared_binary = [
                ct for ct in content if ct.startswith(NON_JSON_PREFIXES)
            ]
            if declared_json and declared_binary:
                errors.append(
                    f"{where}: declares application/json alongside {declared_binary} — "
                    "a generated client would try to JSON-decode it"
                )

            if not declared_json:
                continue

            body = content["application/json"].get("schema") or {}
            if in_scope:
                _referenced_schemas(body, in_scope_schemas)
            if _is_loose(body) and (method.upper(), path) not in ALLOWED_UNTYPED_OPERATIONS:
                scope = "in generated surface" if in_scope else "out of scope"
                errors.append(
                    f"{where}: 2xx response generates as untyped object ({scope}). "
                    "Give it a response_model, or add it to ALLOWED_UNTYPED_OPERATIONS "
                    "with a reason."
                )

    # Expand transitively — a typed response whose model has Any fields is still Any.
    pending = set(in_scope_schemas)
    while pending:
        name = pending.pop()
        nested: set[str] = set()
        _referenced_schemas(components.get(name, {}), nested)
        for child in nested - in_scope_schemas:
            in_scope_schemas.add(child)
            pending.add(child)

    for name in sorted(in_scope_schemas):
        for field, field_schema in (components.get(name, {}).get("properties") or {}).items():
            key = f"{name}.{field}"
            if _is_loose(field_schema) and key not in ALLOWED_LOOSE_FIELDS:
                errors.append(
                    f"{key}: field generates as Any in the generated surface. "
                    "Type it, or add it to ALLOWED_LOOSE_FIELDS with a reason."
                )

    for name in sorted(components):
        if "__" in name and name not in ALLOWED_MANGLED_SCHEMAS:
            errors.append(
                f"schema '{name}': name was fully qualified because two modules declare "
                "the same model name — a generated client uses this verbatim as a type name"
            )

    return errors


def main() -> int:
    try:
        from app.main import app
    except Exception as exc:  # pragma: no cover - import failure is the message
        print(f"OpenAPI lint FAILED: could not import the app: {exc}")
        return 1

    schema = app.openapi()
    errors = lint_openapi(schema)

    if errors:
        print(f"OpenAPI lint FAILED ({len(errors)} error(s)):\n")
        for err in errors:
            print(f"  - {err}")
        return 1

    operations = sum(len(m) for m in schema.get("paths", {}).values())
    print(
        f"OpenAPI lint OK: {operations} operations validated "
        f"({len(GENERATED_SURFACE)} tags in the generated surface, "
        f"{len(ALLOWED_UNTYPED_OPERATIONS)} allowlisted for burn-down)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
