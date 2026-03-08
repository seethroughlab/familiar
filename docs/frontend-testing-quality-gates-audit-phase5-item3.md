# Phase 5 Audit (Item 3): Minimum Quality Gates by Risk Category

## Scope
This artifact covers Phase 5 checklist item 3 only:
- Propose minimum quality gates by risk category.

## Inputs
- Risk map: [frontend-testing-quality-gates-audit-phase5-item1.md](/Users/jeff/Developer/familiar/docs/frontend-testing-quality-gates-audit-phase5-item1.md)
- Flaky/gate audit: [frontend-testing-quality-gates-audit-phase5-item2.md](/Users/jeff/Developer/familiar/docs/frontend-testing-quality-gates-audit-phase5-item2.md)
- Current CI: [ci.yml](/Users/jeff/Developer/familiar/.github/workflows/ci.yml)

## Risk Categories
- `P0` Platform-critical regression risk (playback unavailable, lock-screen controls broken, offline invariant broken).
- `P1` High-coupling regression amplifier (queue/offline recovery, crossfade transition integrity, index/source mapping).
- `P2` Medium product-quality risk (error-shape consistency, diagnostics correctness, non-critical UI flows).
- `P3` Low-risk maintenance/cleanup.

## Minimum Gate Matrix

| Risk Category | Required Automated Gates (PR-blocking) | Required Release Gates (pre-TestFlight / deploy) | Allowed Exceptions |
|---|---|---|---|
| P0 | 1) Frontend lint + guardrails (`eslint`, `check:audio-guardrails`) 2) Frontend Vitest playback/offline suites 3) E2E deterministic playback smoke 4) iOS AppTests remote-command availability suite | 1) Capacitor device sanity run on latest build 2) Diagnostics canary review (`remote_command_enablement_mismatch=0`, `pending_sync_local_url_ratio=1.0` while offline) | None without explicit owner signoff and rollback plan |
| P1 | 1) Frontend Vitest full `@familiar/frontend` run 2) E2E playlists + queue/navigation deterministic suite 3) No retry-only pass in changed test files | 1) One manual exploratory pass for changed critical path (offline/no-service or playback transition) | Time-boxed waiver for unrelated flaky test only with ticket + due date |
| P2 | 1) Lint/build + targeted tests touching changed modules | 1) Spot-check QA for user-facing error states if API/query logic changed | Can defer expanded tests to next batch with linked issue |
| P3 | 1) Lint/build | None beyond standard CI | Allowed if no production-path code changed |

## Concrete Gate Definitions

### PR-Blocking Baseline (all frontend-affecting PRs)
1. `backend-lint`, `backend-test`, `frontend-lint`, `frontend-build`, `e2e-test` pass.
2. Add `frontend-test` job running `pnpm --filter @familiar/frontend run test`.
3. Fail if E2E contains no-op assertion patterns (`expect(... || true).toBe(true)`).

### Additional PR-Blocking for P0/P1 File Touches
1. If PR touches:
   - `packages/frontend/src/hooks/useAudioEngine.tsx`
   - `packages/frontend/src/stores/playerStore.ts`
   - `packages/frontend/src/services/offlineService.ts`
   - `packages/ios/src/CapacitorEngine.ts`
   - `packages/ios/native/App/**/*.swift`
2. Then require:
   - Focused integration tests for offline/pending/crossfade/queue.
   - iOS remote-command AppTests job (once CI lane added).
   - E2E playback/offline deterministic subset with zero dynamic skips.

### Flake Budget Policy
1. CI must fail if any test only passes on retry in blocking suites.
2. Blocking suites must not contain `test.skip(...)` based on runtime data availability.
3. Fixed `waitForTimeout` calls in blocking suites capped to setup-only paths; no assertion-critical sleeps.

## CI Implementation Targets (Decision-Complete)

### Gate A (Immediate)
1. Add `frontend-test` job to CI.
2. Add static grep check for no-op assertions in E2E.
3. Add static grep check preventing new `test.skip` in blocking specs (`audio-playback`, `playlists`, future `offline-invariant` spec).

### Gate B (Near-Term)
1. Add deterministic fixture seeding for blocking E2E suites to remove data-dependent skips.
2. Add retry-only-pass detector for Playwright JSON report.
3. Split non-deterministic tests (AI real-network chat) into non-blocking nightly workflow.

### Gate C (Higher Effort)
1. Add iOS AppTests job for:
   - `NativeAudioEngineRemoteCommandAvailabilityTests`
   - lock-screen command enablement regression cases.
2. Add release script preflight that refuses TestFlight upload when P0 gates are red.

## Branch Protection Recommendations
1. Require pass status checks for:
   - `backend-lint`
   - `backend-test`
   - `frontend-lint`
   - `frontend-test` (new)
   - `frontend-build`
   - `e2e-test`
2. Once available, add required `ios-app-tests` for PRs touching P0/P1 playback/offline files.

## Exit Criteria
Phase 5 is considered complete when:
1. This minimum gate matrix is approved as the project standard.
2. Roadmap Phase 5 checklist item 3 is checked.
3. Gate A tasks are scheduled as next execution batch.

## Reproducibility Commands
Run from repo root:

```bash
# Verify current CI jobs/gates
sed -n '1,400p' .github/workflows/ci.yml

# Inventory critical-path files likely to trigger P0/P1 gates
rg -n "useAudioEngine|playerStore|offlineService|CapacitorEngine|NativeAudioEngine" \
  packages/frontend/src packages/ios/src packages/ios/native/App

# Detect no-op assertions in E2E
rg -n "expect\\(.*\\|\\| true\\)\\.toBe\\(true\\)" packages/web/e2e -g "*.spec.ts"

# Detect dynamic skips in E2E
rg -n "test\\.skip\\(|\\.describe\\.skip\\(" packages/web/e2e -g "*.spec.ts"
```
