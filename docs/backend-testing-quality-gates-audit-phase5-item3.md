# Phase 5 Audit (Item 3): Minimum Backend Quality Gates by Risk Category

Date: 2026-03-08

## Scope
This artifact covers Phase 5 checklist item 3 only:
- Define minimum quality gates for API, migrations, and background pipelines by risk category.

## Inputs
- Risk map: `/Users/jeff/Developer/familiar/docs/backend-testing-quality-gates-audit-phase5-item1.md`
- Flaky/gate audit: `/Users/jeff/Developer/familiar/docs/backend-testing-quality-gates-audit-phase5-item2.md`
- Current CI: `/Users/jeff/Developer/familiar/.github/workflows/ci.yml`
- Current release workflow: `/Users/jeff/Developer/familiar/.github/workflows/release.yml`

## Risk Categories
- `P0`: Platform-critical backend regression risk (migration/head mismatch, broken stream/playback API contracts, sync pipeline deadlock/crash).
- `P1`: High-coupling regression amplifier (background queue/retry behavior, error contract drift, auth/profile boundary inconsistencies).
- `P2`: Medium product-quality risk (diagnostics payload quality, non-critical API behavior drift, ranking/recommendation stability).
- `P3`: Low-risk maintenance/cleanup.

## Minimum Gate Matrix

| Risk Category | Required PR-Blocking Gates | Required Release Gates | Allowed Exceptions |
|---|---|---|---|
| P0 | 1) `backend-lint` 2) `backend-test` split buckets: `contract+migrations` + `background/sync` 3) migration preflight (`alembic upgrade head` + `assert_database_at_head`) | 1) Release blocked unless latest `CI` on target commit succeeded 2) Contract suite (`test_api_contract_error_shapes.py`) and migration suite pass on release candidate | None without explicit owner + rollback plan |
| P1 | 1) `backend-lint` + mypy 2) API bucket tests for changed route families 3) background/sync bucket for changes in `app/services/background|tasks` | 1) Manual review of background diagnostics timeline counters for changed sync/resilience code 2) Contract diff review for changed response/error surfaces | Time-boxed waiver only with linked issue and due date |
| P2 | 1) Targeted tests for touched modules + baseline backend-test pass | 1) Spot-check QA for changed non-critical endpoints/diagnostics | Allowed with follow-up ticket |
| P3 | 1) Lint + typecheck + changed-module tests | None beyond standard CI | Allowed when no runtime path changed |

## Concrete Gate Definitions

### PR-Blocking Baseline (all backend-affecting PRs)
1. `backend-lint` (ruff + mypy) must pass.
2. Migration preflight must pass in CI before backend tests.
3. Backend tests must pass in at least two explicit buckets:
- `contract+migrations`: `test_api_contract_error_shapes.py`, `test_migrations.py`
- `core+api`: remaining API/unit suites

### Additional PR-Blocking for P0/P1 File Touches
Trigger files:
- `backend/app/api/routes/tracks/**`
- `backend/app/services/background/**`
- `backend/app/services/tasks/**`
- `backend/app/db/migration_preflight.py`
- `backend/migrations/versions/**`

Required extra checks:
1. `background/sync` bucket: `test_background.py`, `test_sync_integration.py`, `test_sync_guardrails.py`, `test_background_events.py`, `test_scanner.py`.
2. `contract+migrations` bucket must be green.
3. No new runtime-dependent skips in blocking suites.

### Flake Budget Policy
1. Blocking buckets fail if any test only passes on retry.
2. Blocking buckets fail if skip count exceeds budget:
- Global budget: `<= 3`
- Media-critical suites budget: `0` in CI environments expected to include ffmpeg/librosa.
3. Randomized tests in blocking buckets require deterministic seed and logged seed value.

## CI Implementation Targets (Decision-Complete)

### Gate A (Immediate)
1. Split current monolithic backend pytest CI step into buckets:
- `contract+migrations`
- `background/sync`
- `core+api`
- `integration/slow` (can remain required or transitional required-on-default-branch)
2. Add retry-only-pass detector (fail if rerun required for blocking buckets).
3. Add skip-budget checker in CI output parsing.

### Gate B (Near-Term)
1. Enforce deterministic seed policy for tests using `np.random`.
2. Harden migration tests to assert each subprocess step return code immediately.
3. Add protected-endpoint auth/profile contract matrix test as dedicated blocking suite.

### Gate C (Higher Effort)
1. Raise coverage bars by risk bucket instead of single global 38%:
- `contract+migrations`: >= 70%
- `background/sync`: >= 65%
- `core+api`: >= 55%
- global floor can remain temporarily while bucket bars enforce critical-path quality.
2. Reduce session-scoped client coupling for high-risk suites.

## Branch Protection Recommendations
1. Require status checks:
- `backend-lint`
- `backend-test-contract-migrations`
- `backend-test-background-sync`
- `backend-test-core-api`
- (optional transitional) `backend-test-integration-slow`
2. Require merge queue / linear history for backend-touching PRs once bucket jobs are stable.
3. Require release workflow precondition that the above status checks succeeded on the release commit.

## Exit Criteria
Phase 5 item 3 is complete when:
1. This gate matrix is linked in the roadmap and approved as baseline policy.
2. Phase 5 checklist item 3 is checked.
3. Gate A implementation tasks are scheduled as the next execution batch.

## Reproducibility Commands
Run from repo root:

```bash
# Inspect current backend CI and release gates
sed -n '1,340p' .github/workflows/ci.yml
sed -n '1,260p' .github/workflows/release.yml

# Identify high-risk backend paths for conditional gate triggers
rg -n "services/background|services/tasks|api/routes/tracks|migration_preflight|migrations/versions" backend/app backend/migrations

# Find randomized or skip-heavy tests for policy enforcement
rg -n "np\.random|pytest\.skip|pytest\.mark\.skip|pytest\.mark\.skipif" backend/tests
```
