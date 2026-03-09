# Backend API Contracts & Error Semantics Audit (Phase 2, Item 1)

Date: 2026-03-08

## Scope
Audit focus:
- Request/response contract consistency across backend routes.
- Error-shape behavior across validation, explicit `HTTPException`, and unhandled exceptions.
- Auth/profile contract behavior via dependency injection.

Evidence sources:
- `/Users/jeff/Developer/familiar/backend/app/main.py`
- `/Users/jeff/Developer/familiar/backend/app/api/deps.py`
- `/Users/jeff/Developer/familiar/backend/app/api/exceptions.py`
- `/Users/jeff/Developer/familiar/backend/app/api/routes/**`
- `/Users/jeff/Developer/familiar/backend/tests/test_api_contract_error_shapes.py`

## Contract Baseline (Observed)
- Most route-level errors are raised as `HTTPException(..., detail=<string>)`.
- Validation errors are normalized by global handler into:
  - `{ "error": true, "status_code": 422, "message": "Validation error", "detail": "<string>" }`
  - Source: `validation_exception_handler` in `main.py`.
- `FamiliarError` has a dedicated global handler returning the same `create_error_response(...)` envelope.
- Generic unhandled exceptions are normalized to `{ error, status_code, message }`, with `detail` only in debug mode.
- Profile contract is DI-based:
  - `get_current_profile` (optional profile)
  - `require_profile` (strict 401/400 behavior)
  - Source: `api/deps.py`.

## Findings (Ranked)
1. P1: Error envelope is not unified across all error paths.
   - FastAPI-native `HTTPException` paths still return the default `{"detail": ...}` shape, while `FamiliarError` and validation handlers use `{error,status_code,message,detail}`.
   - Impact: frontend/test clients need dual parsing logic.

2. P1: Custom exception hierarchy exists but is mostly unused by routes.
   - `api/exceptions.py` defines rich typed errors, but route modules predominantly raise raw `HTTPException`.
   - `rg` found no `raise <FamiliarError subclass>` usages in `backend/app`.
   - Impact: weak centralization of error semantics and status mapping.

3. P1: Contract tests are environment-coupled to migration state.
   - Running `uv run pytest tests/test_api_contract_error_shapes.py -q --no-cov` failed on 2026-03-08 before route assertions due to startup preflight:
     - `RuntimeError: Migration preflight failed ... current=['baseline']; heads=['20260307_drop_is_wishlist']`.
   - Impact: contract suite can fail for infra drift instead of contract regressions.

4. P2: Route response-model coverage is inconsistent.
   - Multiple endpoints do not declare `response_model`/`response_class`, especially in streaming/control endpoints.
   - Impact: weaker OpenAPI contract precision and easier response-shape drift.

5. P2: Error semantics diverge for streaming/SSE endpoints.
   - Chat SSE emits `{"type":"error","message":...}` events, which intentionally differ from JSON REST error shape.
   - Impact: acceptable for SSE, but needs explicit contract documentation to avoid frontend assumptions leaking across transports.

## Decision-Ready Remediation Batches
Batch A (immediate, low risk):
- Define a single documented error contract by transport:
  - REST JSON endpoints: canonical envelope.
  - SSE endpoints: canonical event error payload.
- Add a centralized `HTTPException` handler in `main.py` to normalize REST error responses.
- Keep `detail` as required field for backward compatibility, with stable `message` mirror.

Batch B (medium risk):
- Migrate high-traffic routes from raw `HTTPException` to typed `FamiliarError` subclasses where practical.
- Add/standardize `response_model` for non-streaming JSON endpoints currently untyped.

Batch C (medium/high risk):
- Expand contract tests to assert:
  - Envelope parity (`HTTPException` vs `FamiliarError` vs validation).
  - Dependency contract semantics for profile-required vs optional-profile endpoints.
  - SSE error event schema for `/chat/stream`.

## Acceptance Checks for This Audit Item
- [x] Request/response schema consistency inspected across route modules.
- [x] Error-shape handling paths identified and categorized.
- [x] Auth/profile dependency contract behavior verified from `deps.py`.
- [x] Reproducible evidence captured, including failing contract-test run context.

## Reproducibility Commands
- Contract error tests:
  - `cd backend && uv run pytest tests/test_api_contract_error_shapes.py -q --no-cov`
- Route error scan:
  - `rg "raise HTTPException|response_model=" backend/app/api/routes -n`
- Exception usage scan:
  - `rg "raise (ValidationError|NotFoundError|FamiliarError|ServiceUnavailableError|ConflictError)" backend/app -n`
- Route response model gap scan:
  - `python3` decorator scan over `backend/app/api/routes/**/*.py` for endpoints missing `response_model`.
