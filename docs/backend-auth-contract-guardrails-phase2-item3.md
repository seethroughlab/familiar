# Backend Auth/Profile Contract + CI Guardrails Audit (Phase 2, Item 3)

Date: 2026-03-08

## Scope
Finalize Phase 2 with:
- Auth/profile dependency-contract validation (`CurrentProfile` vs `RequiredProfile`).
- Required contract-test suite and CI gate definition for API contract/error-shape stability.

Evidence sources:
- `/Users/jeff/Developer/familiar/backend/app/api/deps.py`
- `/Users/jeff/Developer/familiar/backend/app/api/routes/**`
- `/Users/jeff/Developer/familiar/backend/tests/**`
- `/Users/jeff/Developer/familiar/backend/Makefile`
- `/Users/jeff/Developer/familiar/.github/workflows/ci.yml`

## Current State Summary
- Auth DI behavior in `deps.py`:
  - `RequiredProfile`: missing header -> `401`; invalid UUID -> `400`; unknown UUID -> `401`.
  - `CurrentProfile`: missing header -> `None`; invalid UUID -> `400`; unknown UUID -> `401`.
- Endpoint usage inventory:
  - `RequiredProfile` endpoints: 43.
  - `CurrentProfile` endpoints: 11.
- Existing tests assert some profile-contract behavior (playlists/profile/health), but coverage is partial and message/assertion style is inconsistent across route families.
- CI currently runs:
  - migration apply + preflight,
  - full backend tests,
  - but no explicit, isolated auth-contract matrix suite as a required gate.

## Decision-Complete Contract Rules
1. Header semantics:
- Missing `X-Profile-ID`:
  - `RequiredProfile` endpoints -> `401`.
  - `CurrentProfile` endpoints -> proceed as anonymous profile (`None`) unless route explicitly requires profile-specific action.

2. Invalid identity semantics:
- Invalid UUID format -> `400`.
- Valid UUID not found -> `401` with stable “re-register” guidance.

3. Error envelope policy:
- These auth errors must use the same canonical REST error envelope established in Phase 2 item 2 (not mixed raw `{detail}` shapes after normalization rollout).

4. Route usage policy:
- Endpoints with profile-owned resources or mutations must use `RequiredProfile`.
- Discovery/read-only endpoints that support anonymous browsing may use `CurrentProfile`.

## Required Contract Test Matrix (to add/enforce)
1. Auth dependency matrix tests:
- Parameterized tests over representative `RequiredProfile` endpoints:
  - no header -> `401`
  - invalid UUID -> `400`
  - unknown UUID -> `401`
- Parameterized tests over representative `CurrentProfile` endpoints:
  - no header -> success path (or documented route-specific failure, if intentionally profile-bound)
  - invalid UUID -> `400`
  - unknown UUID -> `401`

2. Error envelope consistency tests:
- Assert auth failures use canonical envelope keys and stable status codes.
- Include at least one endpoint from each major route family (`playlists`, `favorites`, `download`, `chat`, `tracks/listing`).

3. Status-code guard tests:
- Assert no regressions for chosen policy:
  - `RequiredProfile` missing header remains `401`.
  - invalid header format remains `400`.
  - unknown profile remains `401`.

## CI Guardrails (Required Gates)
Batch A (immediate):
- Add dedicated backend contract job command:
  - `make test-contract` (already exists) must be required in CI branch protection.
- Ensure command sequence remains:
  1. `alembic upgrade head`
  2. migration preflight assertion
  3. contract suite execution

Batch B:
- Split contract tests into:
  - `test_api_contract_error_shapes.py`
  - new `test_api_auth_contract_matrix.py`
- Run both in a fast pre-merge gate distinct from full backend suite.

Batch C:
- Add static guardrail scan in CI:
  - fail if new mutating/profile-owned routes omit `RequiredProfile`.
  - fail if route modules introduce raw, non-canonical auth error messages outside approved constants.

## Acceptance Checks for This Audit Item
- [x] Auth/profile dependency behavior validated from source (`deps.py`) and route usage inventory.
- [x] Decision-complete auth contract policy defined (`401/400/401` matrix + anonymous behavior).
- [x] Required contract tests and CI gates specified with execution order.
- [x] Phase 2 guardrails explicitly tied to migration preflight + contract tests.

## Reproducibility Commands
- Dependency and route usage scan:
  - `rg "CurrentProfile|RequiredProfile" backend/app/api/routes -n`
- Existing auth assertion coverage scan:
  - `rg "Profile ID required|Invalid profile ID format|Invalid profile ID" backend/tests -n`
- Contract gate command:
  - `cd backend && make test-contract`
