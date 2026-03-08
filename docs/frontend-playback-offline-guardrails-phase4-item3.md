# Phase 4 Audit (Item 3): Guardrails for No-Service, Offline Invariants, and Lock-Screen Behavior

## Scope
This artifact covers Phase 4 checklist item 3 only:
- Propose guardrails for no-service, offline invariants, and lock-screen behavior.

## Inputs
- Phase 4 item 1: [frontend-playback-offline-criticalpath-audit-phase4-item1.md](/Users/jeff/Developer/familiar/docs/frontend-playback-offline-criticalpath-audit-phase4-item1.md)
- Phase 4 item 2: [frontend-webaudio-capacitor-regressionrisk-audit-phase4-item2.md](/Users/jeff/Developer/familiar/docs/frontend-webaudio-capacitor-regressionrisk-audit-phase4-item2.md)
- Primary implementation surfaces:
  - `packages/frontend/src/stores/connectivityStore.ts`
  - `packages/frontend/src/player/playerStore.ts`
  - `packages/frontend/src/player/useAudioEngine.ts`
  - `packages/ios/src/CapacitorEngine.ts`
  - `packages/ios/native/App/NativeAudioEngine.swift`
  - `packages/ios/native/App/FamiliarAudioPlugin.swift`

## Decision Summary
Adopt a three-layer guardrail model:
1. Runtime invariants that fail safe (stop/skip bounded, never corrupt queue/control state).
2. Automated parity tests and CI gates that block regressions.
3. Observability + release gates for no-service and lock-screen regression detection.

These guardrails are decision-complete and directly mappable to existing code paths without architecture rewrite.

## Guardrail Set

### A) No-Service / Reachability Guardrails

#### A1. Authoritative forced-offline latch
- Rule:
  - If `offlineModeActive` is true (manual offline OR no-service forced offline), streaming URL fallback is forbidden.
  - Exit forced offline only after backend reachability succeeds.
- Enforce in:
  - `connectivityStore` state transitions
  - `resolveTrackUrl` call paths (Web + Capacitor)
  - `useAudioEngine` error recovery branch
- Fail-safe:
  - If resolver cannot provide local media path, emit typed `offline-unavailable` and stop bounded fallback scan.

#### A2. Bounded fallback and skip-storm circuit breaker
- Rule:
  - On repeated `network-unreachable` load failures, attempt only downloaded candidates and hard-stop after breaker threshold.
- Enforce in:
  - `useAudioEngine` auto-advance/recovery path
- Guard criteria:
  - Maximum consecutive auto-advances per window.
  - On breach: stop playback, surface one user-visible reason, do not continue looping.

#### A3. Recovery correctness
- Rule:
  - Reachability recovery automatically clears forced offline, but does not interrupt currently playing downloaded track.
- Enforce in:
  - `connectivityStore` probe/recovery path
  - `useAudioEngine` resume eligibility checks

### B) Offline Invariant Guardrails

#### B1. Downloaded-only queue invariant
- Rule:
  - While `offlineModeActive`, every queue mutation API must enforce downloaded-only filtering.
- Enforce in:
  - `setQueue`, `setQueueByTrackId`, `setLazyQueue`, `addToQueue` and any future queue mutators.
- CI gate:
  - New queue mutator APIs must call a shared invariant helper or fail lint rule review checklist.

#### B2. Downloaded-only listing invariant
- Rule:
  - Shared list providers must filter to `offlineTrackIds` before rendering when offline is active.
- Enforce in:
  - Track-list data shaping layer and offline-aware hooks.
- UX fallback:
  - If resulting list is empty, show explicit offline empty-state, not API error state.

#### B3. Pending next/previous URL resolver parity
- Rule:
  - Pending track sync payloads must use resolver-backed URLs (local when offline), never raw stream URL builders.
- Enforce in:
  - `useAudioEngine` pending-sync path.
- Why:
  - Prevent lock-screen controls from using unreachable URLs in no-service conditions.

### C) Lock-Screen Guardrails (Capacitor)

#### C1. Availability parity contract
- Rule:
  - `canGoNext`/`canGoPrevious` in store and lock-screen command enablement must always match after queue/currentTime transitions.
- Enforce in:
  - shared pending-track sync effect and native command-center updates.

#### C2. Dual-path command safety
- Rule:
  - If native command-handler immediate play fails, must emit deterministic fallback event for JS path with no dead controls.
- Enforce in:
  - `NativeAudioEngine.swift` command handlers + plugin event bridge.

#### C3. Previous-button semantic lock
- Rule:
  - Previous action semantics are immutable across surfaces:
  - `currentTime > 3s` => restart current.
  - `currentTime <= 3s` => move to previous history track when available.
- Enforce in:
  - shared store semantics + native remote previous handling tests.

## Required Test Gates

### Unit/Store
1. `connectivityStore`:
  - forced offline latching from no-service failures
  - backend recovery clears latch and sets `lastRecoveryAt`
  - counter increments for unreachable and recovery events
2. `playerStore`:
  - all queue mutators maintain downloaded-only invariant under offline mode

### Integration (useAudioEngine/store)
1. No-service but `navigator.onLine=true`:
  - enters forced offline and skips only downloaded candidates
2. Skip-storm breaker:
  - repeated failures stop boundedly with one clear terminal state
3. Pending sync URL parity:
  - offline mode syncs local URLs (not stream URLs)
4. Previous semantics parity:
  - >3s restart current; <=3s move to previous

### Native-focused iOS tests (scaffold + incremental implementation)
1. Command enablement reflects pending-track availability changes.
2. Native-next failure emits fallback event; JS fallback keeps controls active.
3. Lock-screen previous obeys 3-second rule and does not remain grey when valid history exists.

## CI/Policy Guardrails

### CI checks to add
1. `pnpm test` for frontend packages must include:
  - `connectivityStore` suite
  - `useAudioEngine` offline/no-service/lock-screen regression suite
2. iOS test target execution in release pipeline:
  - run command-center contract tests (or fail pre-release gate)
3. Contract rule check:
  - forbid direct `tracksApi.getStreamUrl` in pending-track sync path.

### PR checklist additions
1. If playback/offline/queue code changed, author must link affected guardrail test updates.
2. If native command-center code changed, author must run lock-screen contract tests and attach result.
3. Any new queue mutator must document offline invariant enforcement.

## Observability Guardrails

### Required counters/events
- `network_unreachable_load_failures`
- `offline_mode_forced`
- `offline_queue_rebuild_count`
- `skip_storm_circuit_breaker_triggered`
- `recovery_to_online_success`
- `remote_command_enablement_mismatch`
- `pending_sync_local_url_ratio`

### Alert thresholds (initial)
1. Any non-zero `remote_command_enablement_mismatch` in TestFlight canary cohort blocks broad rollout.
2. `skip_storm_circuit_breaker_triggered` spikes > baseline require rollback to prior audio flag.
3. `pending_sync_local_url_ratio < 1.0` while offline indicates parity break.

## Release Gating Criteria
Phase 4 guardrails are considered implemented only when all conditions hold:
1. All required tests above are green in CI.
2. No `P1` open regression in no-service/offline/lock-screen categories.
3. TestFlight canary run (24h minimum) shows:
  - zero lock-screen control disablement regressions,
  - zero skip storms,
  - successful forced-offline recovery without restart.

## Implementation Batches

### Batch A (Immediate)
1. Resolver-backed pending sync URLs.
2. Queue mutator invariant completion (`addToQueue` and any gaps).
3. Connectivity + no-service unit/integration tests.

### Batch B
1. Native command enablement/fallback contract tests.
2. Structured native error category propagation to shared `EngineEvent.code`.

### Batch C
1. CI policy/lint checks for pending sync + mutator invariant compliance.
2. Canary observability dashboard + release-block conditions.

## Reproducibility Commands
Run from repo root:

```bash
# Guardrail-relevant hotspots
rg -n "offlineModeActive|network-unreachable|offline-unavailable|setQueue\\(|addToQueue\\(|syncPendingTracks|remotePrevious|remoteNext" \
  packages/frontend/src/player packages/frontend/src/stores packages/ios/src -g '*.ts' -g '*.tsx'

# Native command-center and plugin bridge paths
rg -n "setupRemoteCommandCenter|remoteNext|remotePrevious|syncPendingTracks|audioEngineDidEncounterError" \
  packages/ios/native/App/NativeAudioEngine.swift packages/ios/native/App/FamiliarAudioPlugin.swift

# Existing and new regression test targets
rg -n "offline|no-service|previous|pending|remote|crossfade|circuit" \
  packages/frontend/src/**/__tests__ packages/ios/native/App/*.swift
```
