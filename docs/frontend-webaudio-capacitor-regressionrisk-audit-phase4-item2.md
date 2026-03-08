# Phase 4 Audit (Item 2): WebAudio vs Capacitor Regression-Risk Comparison

## Scope
This artifact covers Phase 4 checklist item 2 only:
- Identify regression risks across WebAudio/Capacitor paths.

## Compared Paths
- Web path:
  - `packages/web/src/WebAudioEngine.ts`
  - Browser media session behavior in same engine
- Capacitor path:
  - `packages/ios/src/CapacitorEngine.ts`
  - `packages/ios/native/App/FamiliarAudioPlugin.swift`
  - `packages/ios/native/App/NativeAudioEngine.swift`
- Shared orchestration:
  - `packages/frontend/src/player/useAudioEngine.ts`
  - `packages/frontend/src/player/playerStore.ts`
  - `packages/frontend/src/player/audio/types.ts`

## Risk Matrix

| Area | Shared vs Divergent | WebAudio Behavior | Capacitor Behavior | Regression Risk |
|---|---|---|---|---|
| Queue progression (`ended`, `playNext`) | Shared orchestration | DOM `ended` filtered by active element/crossfade state | Native delegate emits `ended` from scheduled file completion | `P1`: medium risk from event-source differences, but shared hook logic reduces drift |
| Error classification + recovery | Divergent event payload quality | Emits only message from media element errors | Plugin currently emits error message (category optional in TS, mostly absent in plugin delegate) | `P1`: high risk of drift because recovery branch relies on code/message heuristics |
| URL resolution (offline vs stream) | Shared contract, dual implementations | `resolveTrackUrl` uses Dexie blob then stream | `resolveTrackUrl` uses native filesystem URI then stream | `P1`: medium risk; parity generally good, but pending-track sync bypasses resolver |
| Crossfade trigger timing | Shared | Triggered by shared hook `timeUpdate` logic | Same shared trigger logic | `P2`: low risk (single logic source) |
| Crossfade execution state transition | Divergent completion semantics | Web crossfade completes with local A/B element swap | Native crossfade can reject (`success:false`) asynchronously | `P1`: medium/high risk from optimistic store advance before native success |
| Remote next/previous behavior | Divergent command stack | Browser media session handlers emit events only | Native can execute next/previous natively using pending URLs before JS | `P1`: high risk for control-desync bugs unique to native |
| Lock-screen command enablement | Divergent (native-only) | N/A | Native command enablement depends on pending track IDs and currentTime > 3s | `P1`: high risk if pending track sync is stale or wrong-source |
| Time-update cadence | Slightly divergent but convergent in practice | Browser `timeupdate` (~4Hz) | Native timer emits every 0.25s | `P2`: low risk |
| Visualizer feed path | Divergent source, shared consumer | AnalyserNode pull path | Plugin push path with typed-array reuse | `P2`: medium risk for drift/jitter under native bridge pressure |
| Offline queue invariant | Shared store, many callers | Same store behavior | Same store behavior | `P1`: medium risk from non-invariant APIs (`addToQueue`) affecting both, more visible on native/offline |

## Severity-Ranked Findings

### 1) Native remote-control path is materially different from Web and has highest regression surface (`P1`)
Evidence:
- Web media session emits control events only (`WebAudioEngine.updateNowPlaying`).
- Native command handlers can load/play pending next/previous natively before notifying JS (`NativeAudioEngine.swift:1090-1156`).

Why it matters:
- Native path can diverge from store state if pending info is stale, missing, or points to unreachable source.
- Lock-screen regressions can occur even when in-app controls work.

### 2) Pending track sync uses stream URLs instead of resolved offline/local URLs (`P1`)
Evidence:
- Shared hook sends `tracksApi.getStreamUrl(...)` in `syncPendingTracks` payload (`useAudioEngine.ts:450-467`).
- Both engines already expose offline-capable resolvers (`WebAudioEngine.resolveTrackUrl`, `CapacitorEngine.resolveTrackUrl`).

Why it matters:
- In forced offline/no-service scenarios, native preloaded lock-screen transitions may attempt network URLs.
- This disproportionately impacts Capacitor and lock-screen reliability.

### 3) Error-shape parity is weak between native plugin and shared recovery logic (`P1`)
Evidence:
- Engine event type supports structured `code` (`audio/types.ts`).
- Plugin delegate currently emits only `"message"` in `audioEngineDidEncounterError` (`FamiliarAudioPlugin.swift`).
- Shared hook branches recovery by category (`useAudioEngine.ts:264-300`, `:603-625`).

Why it matters:
- Message-based heuristics are brittle and can regress silently with wording changes.

### 4) Crossfade state transition is optimistic relative to native confirmation (`P1`)
Evidence:
- Shared hook advances store immediately in crossfade path (`useAudioEngine.ts:225-227`).
- Native crossfade can reject and return `success: false` (`CapacitorEngine.ts:198-204`).

Why it matters:
- Temporary state mismatch is possible on Capacitor failure edge cases.

### 5) Shared queue/offline core reduces many classes of platform drift (`P2`, positive)
Evidence:
- Queue mechanics are centralized in store (`playerStore.ts`).
- Trigger logic and fallback behavior live in shared hook (`useAudioEngine.ts`).

Why it matters:
- Most baseline playback semantics are already common-path; focused fixes can close remaining divergence quickly.

## Coverage Assessment

### Existing automated coverage (good)
- Integration parity suite includes:
  - auto-advance
  - previous semantics
  - preload fallback
  - pending sync refresh paths
  - offline-unavailable fallback
  (`packages/frontend/src/hooks/__tests__/useAudioEngine.integration.test.tsx`)
- Store-level queue/previous/offline filtering coverage exists:
  - (`packages/frontend/src/player/__tests__/playerStore.test.ts`)

### Key gaps (risk)
1. No direct tests for native command-center dual path (native pre-play vs JS fallback).
2. No test asserting pending sync uses local/offline resolved URLs in offline mode.
3. No connectivity store test coverage for forced-offline/recovery state machine.
4. No test for crossfade reject path keeping store/engine state aligned.

## Decision-Ready Recommendations

### Batch A (immediate)
1. Switch pending track sync to resolver-backed URLs (offline/local when available).
2. Add typed native error category emission in plugin delegate and propagate to `EngineEvent.code`.
3. Add integration test for offline pending-track URL selection.

### Batch B
1. Add native-focused integration tests for remote next/previous fallback contract:
   - pending track exists and native load succeeds
   - pending track exists and native load fails -> JS fallback path
2. Make crossfade store promotion conditional on success-confirmed transition.

### Batch C
1. Add connectivity store unit tests to stabilize no-service/offline recovery behavior.
2. Add diagnostics assertion tests for native command availability state transitions.

## Reproducibility Commands
Run from repo root:

```bash
# Compare engine implementations and shared orchestration references
rg -n "resolveTrackUrl|preloadNext|executeCrossfade|remotePrevious|syncPendingTracks|updateNowPlaying" \
  packages/web/src/WebAudioEngine.ts packages/ios/src/CapacitorEngine.ts \
  packages/ios/native/App/FamiliarAudioPlugin.swift packages/ios/native/App/NativeAudioEngine.swift \
  packages/frontend/src/player/useAudioEngine.ts

# Existing parity tests
rg -n "auto-advances|remotePrevious|pending|offline|preload|crossfade" \
  packages/frontend/src/hooks/__tests__/useAudioEngine.integration.test.tsx \
  packages/frontend/src/player/audio/__tests__/engineContract.test.ts
```
