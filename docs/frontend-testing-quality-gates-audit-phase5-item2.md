# Phase 5 Audit (Item 2): Flaky Tests and Weak CI Gates

## Scope
This artifact covers Phase 5 checklist item 2 only:
- Identify flaky tests and weak CI gates.

## Evidence Sources
- CI workflow: [ci.yml](/Users/jeff/Developer/familiar/.github/workflows/ci.yml)
- Playwright config: [playwright.config.ts](/Users/jeff/Developer/familiar/packages/web/playwright.config.ts)
- E2E suites:
  - [audio-playback.spec.ts](/Users/jeff/Developer/familiar/packages/web/e2e/audio-playback.spec.ts)
  - [playlists.spec.ts](/Users/jeff/Developer/familiar/packages/web/e2e/playlists.spec.ts)
  - [crossfade-playback.spec.ts](/Users/jeff/Developer/familiar/packages/web/e2e/crossfade-playback.spec.ts)
  - [ai-chat.spec.ts](/Users/jeff/Developer/familiar/packages/web/e2e/ai-chat.spec.ts)
- Prior artifact:
  - [frontend-testing-quality-gates-audit-phase5-item1.md](/Users/jeff/Developer/familiar/docs/frontend-testing-quality-gates-audit-phase5-item1.md)

## Snapshot Findings
- Playwright suites contain `96` fixed sleeps (`waitForTimeout`) across `10` E2E specs.
- E2E includes `29` skip points (`test.skip` / `describe.skip`) across `6` specs.
- CI uses Playwright retries in CI (`retries: 2`), which can hide unstable tests.
- CI does not currently run frontend Vitest tests (`@familiar/frontend test`).
- CI does not currently run iOS native AppTests (lock-screen/remote-command guardrails remain out of gate).

## Flaky Test Risk Inventory

| Severity | Finding | Evidence |
|---|---|---|
| P1 | Timing-based assertions dominate critical playback E2E paths and can fail under runner jitter. | [audio-playback.spec.ts:52](/Users/jeff/Developer/familiar/packages/web/e2e/audio-playback.spec.ts:52), [audio-playback.spec.ts:72](/Users/jeff/Developer/familiar/packages/web/e2e/audio-playback.spec.ts:72), [crossfade-playback.spec.ts:181](/Users/jeff/Developer/familiar/packages/web/e2e/crossfade-playback.spec.ts:181) |
| P1 | Entire crossfade suite is skipped, leaving a known critical path unexercised in CI. | [crossfade-playback.spec.ts:75](/Users/jeff/Developer/familiar/packages/web/e2e/crossfade-playback.spec.ts:75) |
| P1 | Data-dependent skips make pass/fail outcome dependent on fixture state instead of product behavior. | [audio-playback.spec.ts:17](/Users/jeff/Developer/familiar/packages/web/e2e/audio-playback.spec.ts:17), [playlists.spec.ts:191](/Users/jeff/Developer/familiar/packages/web/e2e/playlists.spec.ts:191) |
| P2 | Some assertions are effectively no-op and cannot catch regressions. | [playlists.spec.ts:265](/Users/jeff/Developer/familiar/packages/web/e2e/playlists.spec.ts:265), [ai-chat.spec.ts:119](/Users/jeff/Developer/familiar/packages/web/e2e/ai-chat.spec.ts:119) |
| P2 | AI chat E2E is always skipped in CI due nondeterministic external dependency, reducing confidence in prompt-to-play behavior. | [ai-chat.spec.ts:13](/Users/jeff/Developer/familiar/packages/web/e2e/ai-chat.spec.ts:13) |

## Weak CI Gate Inventory

| Severity | Weak Gate | Why It Matters | Evidence |
|---|---|---|---|
| P1 | No frontend unit/integration gate in CI | Store and hook regressions can merge even when local Vitest fails. | [ci.yml](/Users/jeff/Developer/familiar/.github/workflows/ci.yml) |
| P1 | No iOS native AppTests gate in CI | Lock-screen remote-command regressions remain unguarded until manual device testing. | [ci.yml](/Users/jeff/Developer/familiar/.github/workflows/ci.yml) |
| P2 | Playwright retries set to 2 in CI without flake-budget enforcement | Intermittent failure can be masked by retry pass. | [playwright.config.ts:8](/Users/jeff/Developer/familiar/packages/web/playwright.config.ts:8) |
| P2 | Playwright suite allows many dynamic skips | CI can pass while meaningful scenarios are not executed. | [audio-playback.spec.ts:17](/Users/jeff/Developer/familiar/packages/web/e2e/audio-playback.spec.ts:17), [playlists.spec.ts:21](/Users/jeff/Developer/familiar/packages/web/e2e/playlists.spec.ts:21) |

## Decision-Ready Remediation Backlog

### Batch A (Immediate, low-risk)
1. Add `frontend-test` CI job: `pnpm --filter @familiar/frontend run test`.
2. Add CI check that fails on no-op assertions (`|| true` patterns) in E2E specs.
3. Replace top fixed sleeps in `audio-playback.spec.ts` with event/state waits (`expect.poll`, `waitForFunction` on player state).

### Batch B (Near-term)
1. Convert dynamic data skips to deterministic seeded fixtures for playback and playlists tests.
2. Re-enable crossfade coverage in CI with a minimal deterministic fixture and focused assertions.
3. Add flake budget check: fail if any test passes only on retry.

### Batch C (Higher effort)
1. Add iOS AppTests job in CI for remote-command availability and lock-screen command enablement.
2. Split external-network AI chat tests into nightly/non-blocking workflow, keep CI-blocking path mocked/deterministic.

## Reproducibility Commands
Run from repo root:

```bash
# Count timing sleeps in E2E specs
rg -n "waitForTimeout\\(" packages/web/e2e -g "*.spec.ts" | wc -l

# Count skip points in E2E specs
rg -n "test\\.skip\\(|\\.describe\\.skip\\(" packages/web/e2e -g "*.spec.ts" | wc -l

# Locate weak/no-op assertions
rg -n "expect\\(.*\\|\\| true\\)\\.toBe\\(true\\)" packages/web/e2e -g "*.spec.ts"

# Inspect CI gate coverage
sed -n '1,360p' .github/workflows/ci.yml
```

## Completion Note
Phase 5 item 2 is complete once this artifact is linked in the roadmap and Phase 5 checklist item 2 is checked.
