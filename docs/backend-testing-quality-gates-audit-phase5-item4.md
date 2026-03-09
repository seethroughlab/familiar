# Phase 5 Audit (Item 4): Backend Branch-Protection + Release Criteria Proposal

Date: 2026-03-08

## Scope
This artifact covers Phase 5 checklist item 4 only:
- Propose branch-protection and release criteria for backend reliability.

## Inputs
- `/Users/jeff/Developer/familiar/docs/backend-testing-quality-gates-audit-phase5-item1.md`
- `/Users/jeff/Developer/familiar/docs/backend-testing-quality-gates-audit-phase5-item2.md`
- `/Users/jeff/Developer/familiar/docs/backend-testing-quality-gates-audit-phase5-item3.md`
- `/Users/jeff/Developer/familiar/.github/workflows/ci.yml`
- `/Users/jeff/Developer/familiar/.github/workflows/release.yml`

## Proposed Branch-Protection Baseline (Master)
1. Require pull request before merge.
2. Require at least 1 code owner review for backend-touching PRs (`backend/**`, `.github/workflows/**`).
3. Dismiss stale approvals when new commits are pushed.
4. Require conversation resolution before merge.
5. Require linear history (or merge queue once available).
6. Restrict direct pushes to `master` (except explicitly authorized admins in emergencies).

## Required Status Checks (Backend Reliability)
Minimum required checks on `master`:
1. `backend-lint`
2. `backend-test-contract-migrations` (new split job)
3. `backend-test-background-sync` (new split job)
4. `backend-test-core-api` (new split job)
5. `frontend-lint` (kept required due full-stack coupling)
6. `frontend-build` (kept required due backend-served static build)

Transitional required check (until stabilized):
1. `backend-test-integration-slow`

Optional (recommended once stable):
1. Require merge queue with all above checks passing at queue tip.

## Conditional Additional Requirements (Path-Based Risk Trigger)
If PR touches any of:
- `backend/migrations/versions/**`
- `backend/app/db/migration_preflight.py`
- `backend/app/services/background/**`
- `backend/app/services/tasks/**`
- `backend/app/api/routes/tracks/**`

Then require:
1. `backend-test-contract-migrations` pass.
2. `backend-test-background-sync` pass.
3. No skip-budget violations in blocking buckets.

## Release Criteria (Tags + Manual Dispatch)
A backend release may proceed only when all are true for the target commit/tag:
1. Latest `CI` workflow succeeded (all required status checks green).
2. Migration gate passed on target revision:
- `alembic upgrade head`
- `assert_database_at_head()`
3. Contract gate passed:
- `tests/test_api_contract_error_shapes.py`
4. Background resilience gate passed:
- `test_background.py`
- `test_sync_integration.py`
- `test_sync_guardrails.py`
- `test_background_events.py`
5. No unresolved P0/P1 backend incidents in tracker linked to changed backend areas.

## Release Workflow Guardrail Changes (Decision-Complete)
`release.yml` should be updated with:
1. A preflight job that verifies CI success on target commit SHA before image push.
2. An explicit migration/contract/background smoke gate job before `build-and-push`.
3. `create-release` must depend on successful preflight + build jobs.
4. Block release on skip-budget violations in blocking suites.

## Exception Policy
1. P0/P1 gate bypass requires:
- Explicit incident ticket.
- Owner + approver named.
- Time-bounded rollback plan documented.
- Follow-up remediation issue created before merge/release.
2. P2/P3 exceptions allowed with deferred test ticket and due date.

## Enforcement Rollout Plan
Batch A (Immediate):
1. Add required branch checks matching current/near-term CI job names.
2. Enforce review + stale approval dismissal + conversation resolution.
3. Restrict direct push to `master`.

Batch B (Near-Term):
1. Split backend CI into named buckets required by protection rules.
2. Add release preflight CI-success verification in `release.yml`.

Batch C (Higher Effort):
1. Add path-aware conditional gates via workflow logic.
2. Enable merge queue once flake budget is stable.

## Acceptance Criteria
1. Branch-protection settings reflect the required checks and review rules above.
2. Release workflow cannot publish containers unless CI and backend preflight gates are green.
3. Exception path is explicit, auditable, and time-bounded.

## Reproducibility Commands
Run from repo root:

```bash
# Inspect CI jobs and status check names
sed -n '1,360p' .github/workflows/ci.yml

# Inspect release workflow dependencies/gates
sed -n '1,320p' .github/workflows/release.yml

# Verify high-risk backend path patterns for conditional requirements
rg -n "migrations/versions|migration_preflight|services/background|services/tasks|api/routes/tracks" backend/app backend/migrations
```

## Completion Note
Phase 5 item 4 is complete when this proposal is linked in the backend roadmap and adopted as the baseline governance policy for backend merges/releases.
