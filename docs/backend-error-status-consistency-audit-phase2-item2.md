# Backend Error-Shape + Status-Code Consistency Audit (Phase 2, Item 2)

Date: 2026-03-08

## Scope
This audit focuses on normalization across backend route families:
- Library/media retrieval (`tracks`, `artwork`, `videos`, `analysis`)
- CRUD/domain resources (`playlists`, `favorites`, `outputs`, `profiles`)
- Import/export and bulk operations (`library_import`, `export_import`, `download`)
- External integration surfaces (`lastfm`, `chat`, map/discovery endpoints)

Primary evidence:
- `/Users/jeff/Developer/familiar/backend/app/main.py`
- `/Users/jeff/Developer/familiar/backend/app/api/routes/**`
- `/Users/jeff/Developer/familiar/backend/app/api/deps.py`

## Current State (Observed)
- Global handlers normalize `RequestValidationError`, `SQLAlchemyError`, `FamiliarError`, and generic exceptions into `{error,status_code,message,detail?}`.
- Most route-level failures are raised via raw `HTTPException`, which bypasses that envelope and returns FastAPI default `{detail: ...}`.
- Result: two concurrent REST error shapes in production.

### Notable Status-Code Drift Examples
1. Upload/internal failure detail leakage:
   - `library_import.py` returns `500` with raw exception message in one path (`"Failed to save upload: {e}"`).
2. Empty result semantics vary:
   - `download.py` returns `404` for empty downloadable set (`"No downloadable tracks in playlist"`), which behaves more like a valid request with no exportable content.
3. Domain operation conflict/validation boundary mixed:
   - `artwork.py` uses `422` for generation precondition failure (`No analyzed tracks available for generation`), while related state-conflict path uses `409`.
4. Idempotent delete semantics vary by family:
   - `favorites` delete endpoint returns `200` with body; many other delete endpoints use `204`.

## Route-Family Normalization Matrix (Decision Complete)
1. Error envelope (all JSON REST endpoints):
- Target response shape for all non-2xx REST errors:
  - `{ "error": true, "status_code": <int>, "message": <string>, "detail": <string|object|array>, "request_id": <string?> }`
- Enforce via centralized `HTTPException` handler in `main.py` (in addition to existing global handlers).

2. Validation/auth/resource status policy:
- `400`: malformed input/invalid parameter values not covered by schema validator.
- `401`: missing/invalid profile/auth identity.
- `403`: authenticated but forbidden (reserve for future explicit authorization logic).
- `404`: concrete resource not found by ID/key.
- `409`: state conflict/precondition conflict with current server state.
- `413`: payload or computed export size exceeds enforced limits.
- `422`: schema/body validation failures from request model validation.
- `500`: unhandled internal failures (never include raw exception text in client detail).
- `503`: external dependency unavailable/misconfigured (LLM, Last.fm, map deps).

3. Family-specific normalization decisions:
- Import/export routes: convert internal save/process failures to sanitized `500` (no direct exception interpolation).
- Download/export routes: for “request valid but no exportable tracks”, standardize on `409` (conflict with operation preconditions) instead of `404`.
- Artwork generation routes: use `409` for generation preconditions tied to analysis/state readiness; reserve `422` for true request-shape validation only.
- Idempotent delete routes:
  - Keep `200` with body where clients rely on return payload (`favorites` can remain `200` by explicit policy),
  - otherwise use `204` with no body consistently.

## Recommended Implementation Batches
Batch A (immediate, low risk):
- Add `HTTPException` global handler to normalize envelope and include request ID.
- Remove raw exception-string leaks in known routes (`library_import` family first).
- Add an error-semantics reference table in backend docs.

Batch B (medium risk):
- Standardize status codes per matrix in high-traffic routes:
  - `download`, `artwork`, `library_import`, `export_import`, `lastfm`, `chat`.
- Keep behavioral compatibility by preserving existing `detail` text where possible.

Batch C (medium/high risk):
- Expand contract tests to assert:
  - normalized envelope for HTTPException paths,
  - route-family status code policies for empty sets/conflicts/preconditions,
  - no raw Python exception leakage in `500` responses.

## Acceptance Checks for This Audit Item
- [x] Error-shape normalization gaps identified with concrete route evidence.
- [x] Status-code inconsistencies mapped across route families.
- [x] Decision-complete normalization matrix defined (envelope + status policy).
- [x] Implementation batches sequenced by risk.

## Reproducibility Commands
- Error/status scan:
  - `rg "raise HTTPException|status_code=" backend/app/api/routes backend/app/main.py -n`
- Sanitization coverage scan:
  - `rg "sanitize_error_for_client|except Exception as e" backend/app/api/routes -n`
- Contract test baseline:
  - `cd backend && uv run pytest tests/test_api_contract_error_shapes.py -q --no-cov`
