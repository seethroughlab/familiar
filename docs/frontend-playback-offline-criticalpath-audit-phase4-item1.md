# Phase 4 Audit (Item 1): Queue + Playback + Offline State Interactions

## Scope
This artifact covers Phase 4 checklist item 1 only:
- Audit queue + playback + offline state interactions.

## Systems Reviewed
- Queue/state core:
  - `packages/frontend/src/player/playerStore.ts`
  - `packages/frontend/src/player/useAudioEngine.ts`
  - `packages/frontend/src/stores/connectivityStore.ts`
- Engine integration:
  - `packages/web/src/WebAudioEngine.ts`
  - `packages/ios/src/CapacitorEngine.ts`
- Queue mutation entrypoints:
  - `packages/frontend/src/hooks/useTrackContextMenu.tsx`
  - queue construction callsites in `components/**`
- Existing regression coverage:
  - `packages/frontend/src/hooks/__tests__/useAudioEngine.integration.test.tsx`
  - `packages/frontend/src/player/__tests__/playerStore.test.ts`

## Critical-Path Findings

### 1) Offline queue rebuild can unexpectedly force playback on (`P0`)
Evidence:
- Offline rebuild effect rebuilds queue via `state.setQueue(...)` whenever offline filtering changes (`packages/frontend/src/player/useAudioEngine.ts:396-421`).
- `setQueue` always sets `isPlaying: finalStartIndex >= 0` (`packages/frontend/src/player/playerStore.ts:679-686`).

Impact:
- If user is paused and connectivity flips to forced offline, queue rebuild can implicitly resume playback.
- This is a critical UX/state regression risk in unstable network transitions.

### 2) Offline invariant is not enforced for incremental queue mutation APIs (`P1`)
Evidence:
- Offline invariant is enforced only in `setQueue`/`setQueueByTrackId`/`setLazyQueue` via `enforceOfflineQueueInvariant` (`packages/frontend/src/player/playerStore.ts:125-129`, `:637-723`, `:808-813`).
- `addToQueue` has no offline guard (`packages/frontend/src/player/playerStore.ts:361-389`).
- Default context-menu queue action calls `addToQueue` directly (`packages/frontend/src/hooks/useTrackContextMenu.tsx:148-153`).

Impact:
- While offline mode is active, users can still enqueue non-downloaded tracks through add-to-queue paths.
- This reintroduces load-error/skip behavior and weakens strict downloaded-only guarantees.

### 3) Native pending next/previous sync always uses stream URLs, not resolved offline URLs (`P1`)
Evidence:
- Pending track sync sends `tracksApi.getStreamUrl(...)` for next/previous (`packages/frontend/src/player/useAudioEngine.ts:450-467`).
- Engines already support offline resolution (`packages/web/src/WebAudioEngine.ts:547-558`, `packages/ios/src/CapacitorEngine.ts:251-262`).

Impact:
- In forced offline/no-service situations, lock-screen next/previous metadata can point at unreachable sources.
- Increases risk of disabled/greyed controls or stale remote-command behavior.

### 4) Crossfade transition is store-optimistic before engine success confirmation (`P1`)
Evidence:
- Hook advances store immediately in `executeCrossfade` (`packages/frontend/src/player/useAudioEngine.ts:225-227`).
- Capacitor crossfade can be rejected asynchronously (`packages/ios/src/CapacitorEngine.ts:200-204`).

Impact:
- Temporary mismatch can occur between store state and native playback state on crossfade rejection/failure.
- Can manifest as wrong current track state or control desync during failure edges.

### 5) Connectivity critical-path has no direct unit tests (`P1`)
Evidence:
- `connectivityStore` contains forced-offline transitions, backend probe scheduling, counters, and recovery logic (`packages/frontend/src/stores/connectivityStore.ts:78-130`, `:245-277`).
- No dedicated test file covers this store (`rg` over test files only found mocked usage in player/hook tests).

Impact:
- High-regression area (no-service detection, recovery, forced-offline latching) lacks direct regression protection.

### 6) Global hook-level transition/circuit-breaker state is process-global, not store-scoped (`P2`)
Evidence:
- Module globals in `useAudioEngine`: `queueTransition`, `failureAdvanceTimestamps` (`packages/frontend/src/player/useAudioEngine.ts:20-24`).

Impact:
- State persists across hook remounts and can leak across profile switches/tests unless process resets.
- Harder to reason about determinism under long sessions.

## Existing Strengths
- Queue-level offline filtering at queue creation time is in place (`setQueue`, `setQueueByTrackId`, `setLazyQueue`).
- Engine URL resolution in both Web and Capacitor paths already supports local/offline-first behavior (`WebAudioEngine.resolveTrackUrl`, `CapacitorEngine.resolveTrackUrl`).
- Integration tests already cover key parity paths:
  - auto-advance, previous semantics, preload fallback, lock-screen pending sync, offline-unavailable fallback (`packages/frontend/src/hooks/__tests__/useAudioEngine.integration.test.tsx:190-392`).

## Decision-Ready Remediation Targets (for implementation phase)

### Batch A (high priority)
1. Preserve play/pause intent during offline queue rebuild:
   - Add a queue-rebuild API that preserves `isPlaying` rather than calling `setQueue` directly.
2. Enforce offline invariant in incremental queue mutation:
   - Guard `addToQueue` in store (reject non-downloaded while offline).
3. Resolve pending next/previous URLs through engine/offline resolver before `syncPendingTracks`.

### Batch B
1. Make crossfade store transition atomic with engine confirmation:
   - Update queue index/current track on successful crossfade completion event path only.
2. Move circuit-breaker/transition trackers to store-scoped state for deterministic reset behavior.

### Batch C (test hardening)
1. Add dedicated `connectivityStore` test suite:
   - no-service forced-offline latch
   - `/health` recovery and `lastRecoveryAt`
   - counter increments and backoff scheduling
2. Add integration test:
   - offline queue rebuild while paused must remain paused
   - add-to-queue while offline rejects non-downloaded track
   - pending track sync uses local URL when offline.

## Reproducibility Commands
Run from repo root:

```bash
# Queue/offline interaction hotspots
rg -n "setQueue\\(|setQueueByTrackId\\(|setLazyQueue\\(|addToQueue\\(|offlineModeActive|offlineTrackIds" \
  packages/frontend/src/player packages/frontend/src/hooks packages/frontend/src/stores -g '*.ts' -g '*.tsx'

# Pending track sync URL source
rg -n "syncPendingTracks|getStreamUrl\\(" packages/frontend/src/player/useAudioEngine.ts

# Engine offline URL resolution
rg -n "resolveTrackUrl|getOfflineTrack|getOfflineTrackNativeUri" \
  packages/web/src/WebAudioEngine.ts packages/ios/src/CapacitorEngine.ts

# Existing integration coverage relevant to this audit
rg -n "auto-advances|remotePrevious|preload|pending|offline" \
  packages/frontend/src/hooks/__tests__/useAudioEngine.integration.test.tsx
```
