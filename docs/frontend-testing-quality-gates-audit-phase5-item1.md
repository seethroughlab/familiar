# Phase 5 Audit (Item 1): Risk Areas vs Missing Unit/Integration/E2E Coverage

## Scope
This artifact covers Phase 5 checklist item 1 only:
- Map risk areas to missing unit/integration/e2e coverage.

## Evidence Sources
- Frontend unit/integration suites (`packages/frontend/src/**/__tests__`)
- Web E2E suites (`packages/web/e2e/*.spec.ts`)
- CI workflow execution (`.github/workflows/ci.yml`)
- Prior risk audits:
  - [frontend-playback-offline-criticalpath-audit-phase4-item1.md](/Users/jeff/Developer/familiar/docs/frontend-playback-offline-criticalpath-audit-phase4-item1.md)
  - [frontend-webaudio-capacitor-regressionrisk-audit-phase4-item2.md](/Users/jeff/Developer/familiar/docs/frontend-webaudio-capacitor-regressionrisk-audit-phase4-item2.md)
  - [frontend-playback-offline-guardrails-phase4-item3.md](/Users/jeff/Developer/familiar/docs/frontend-playback-offline-guardrails-phase4-item3.md)

## Current Coverage Snapshot
- Frontend test files: 33 (`packages/frontend/src`).
- Strongly-covered domains:
  - Player store semantics and queue behavior.
  - `useAudioEngine` integration parity paths.
  - Engine contract behavior for Capacitor bridge.
  - Core offline/connectivity store transitions (new but still minimal).
  - Track row interaction split (desktop select vs mobile play).
- E2E coverage exists for:
  - Playback basics, crossfade web behavior, playlists, profiles, settings/admin, library sync, AI chat.
- CI currently runs:
  - frontend lint + guardrail static check + web build + web e2e
  - **does not run frontend unit/integration tests (`vitest`) in CI**
  - **does not run iOS native tests (`xcodebuild test`) in CI**

## Risk-to-Coverage Map

| Risk Area | Existing Coverage | Missing Coverage | Gap Severity | Needed Layer |
|---|---|---|---|---|
| No-service transition + forced-offline recovery | `connectivityStore.test.ts`, `useAudioEngine.integration.test.tsx` | Real browser-level no-service simulation in E2E (online=true + fetch failures + recovery without restart) | P1 | E2E + integration hardening |
| Offline invariant (downloaded-only browse + queue + play) | Store-level queue filtering tests, integration fallback tests | Cross-surface list coverage (Artists/Albums/Favorites/Downloads) under offline mode in E2E; anti-regression assertions for non-downloaded invisibility | P1 | E2E |
| Lock-screen command availability (Capacitor native path) | `engineContract.test.ts` event mapping; iOS AppTests locally | CI-run native command tests, failure-path assertions under real command center flow | P1 | Native unit + CI gate |
| Pending-track sync local URL parity | Integration test for resolver-backed offline URLs; static guardrail check | Runtime parity checks in E2E/canary assertions (ratio remains 1.0 offline) | P1 | Integration + canary policy |
| Skip-storm circuit breaker behavior | Integration-level fallback/circuit checks | E2E stress scenario (rapid repeated failures over window) to catch loop regressions from orchestration changes | P1 | E2E |
| Crossfade state alignment on native reject path | `engineContract.test.ts` callback completion on reject | Integration assertion that store track promotion is consistent after native reject path in full hook flow | P1 | Integration |
| Frontend diagnostics/reporting correctness | UI exists (`SystemStatus`) | Tests for canary metric rendering + markdown export payload correctness | P2 | Component/unit |
| Playlist/mobile interaction regression (play wrong track index) | Shared row interaction tests | E2E mobile list + shuffle + favorites path with index/source integrity assertions | P1 | E2E |
| API/query error-shape consistency in UI | Phase 2 audit + API tests | Feature-level integration tests asserting consistent user-facing error states across list surfaces | P2 | Integration/component |
| Visualizer parity and dropout resilience | Prior parity discussions; limited automated checks | Deterministic fixture-based visualizer output comparisons + dropout window assertions in Capacitor path | P1 | Integration/native |

## High-Risk Gaps to Prioritize (Batch A for Phase 5)
1. Add a dedicated CI frontend test job that runs:
   - `pnpm --filter @familiar/frontend test`
   - focused playback/offline suites as a minimum gate.
2. Add an iOS CI test gate:
   - `xcodebuild ... -only-testing:AppTests/NativeAudioEngineRemoteCommandAvailabilityTests test`.
3. Add web E2E no-service scenario:
   - start playback, force stream failures while browser online, assert forced-offline fallback + recovery.
4. Add E2E offline invariant scenario:
   - offline mode active => non-downloaded tracks absent across key list surfaces.
5. Add integration test for native crossfade reject:
   - verify no store/native desync on rejection path.

## Coverage Gating Risks in CI (Current)
1. Unit/integration frontend regressions can merge because CI does not execute `vitest`.
2. Native lock-screen regressions can merge because CI does not execute iOS AppTests.
3. Playwright retries (`retries: 2` in CI) can mask flaky failures unless failure-rate trends are tracked.

## Reproducibility Commands
Run from repo root:

```bash
# Inventory frontend tests
rg --files packages/frontend/src | rg "__tests__|\\.test\\.ts$|\\.test\\.tsx$"

# Inventory web e2e tests
rg -n "test\\(" packages/web/e2e -g "*.spec.ts"

# Inspect what CI actually runs
sed -n '1,320p' .github/workflows/ci.yml

# Playback/offline focused test files
rg -n "offline|remote|crossfade|pending|network-unreachable|fallback" \
  packages/frontend/src/hooks/__tests__/useAudioEngine.integration.test.tsx \
  packages/frontend/src/player/audio/__tests__/engineContract.test.ts \
  packages/frontend/src/stores/__tests__/connectivityStore.test.ts
```

## Completion Note
Phase 5 item 1 is complete once this risk map is linked in the roadmap and used as the source list for item 2 (flaky/weak-gate audit) and item 3 (minimum gate proposal).
