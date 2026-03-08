# Capacitor vs WebAudio Parity Signoff Matrix

Generated: 2026-03-07  
Scope: Playback, queue transitions, crossfade, offline playback, lock-screen controls, visualizer analysis parity.  
Out of scope: Effects-node parity (intentional platform difference).

## Release Context

- Latest uploaded iOS build: TestFlight build `45`
- Native playback blocker fix included: `load` token invalidation regression fix in [NativeAudioEngine.swift](/Users/jeff/Developer/familiar/packages/ios/native/App/NativeAudioEngine.swift)

## Status Legend

- `PASS`: Behavior implemented and covered by automated tests and/or validated run evidence.
- `FAIL`: Known broken or missing behavior.

## Signoff Matrix

| Area | WebAudio | Capacitor Swift | Evidence | Status |
|---|---|---|---|---|
| Engine contract (`load/play/pause/seek/ended/timeUpdate`) | Implemented | Implemented | Web: [WebAudioEngine.ts](/Users/jeff/Developer/familiar/packages/web/src/WebAudioEngine.ts), iOS: [CapacitorEngine.ts](/Users/jeff/Developer/familiar/packages/ios/src/CapacitorEngine.ts), [NativeAudioEngine.swift](/Users/jeff/Developer/familiar/packages/ios/native/App/NativeAudioEngine.swift), contract test: [engineContract.test.ts](/Users/jeff/Developer/familiar/packages/frontend/src/player/audio/__tests__/engineContract.test.ts) | PASS |
| Auto-advance behavior | Implemented | Implemented | Hook integration test: [useAudioEngine.integration.test.tsx](/Users/jeff/Developer/familiar/packages/frontend/src/hooks/__tests__/useAudioEngine.integration.test.tsx) (`auto-advances exactly one track on ended event`) | PASS |
| Previous-button semantics (`>3s` restart else history/previous) | Implemented | Implemented | Native logic in [NativeAudioEngine.swift](/Users/jeff/Developer/familiar/packages/ios/native/App/NativeAudioEngine.swift), integration/contract tests in [useAudioEngine.integration.test.tsx](/Users/jeff/Developer/familiar/packages/frontend/src/hooks/__tests__/useAudioEngine.integration.test.tsx) and [engineContract.test.ts](/Users/jeff/Developer/familiar/packages/frontend/src/player/audio/__tests__/engineContract.test.ts) | PASS |
| Pending next/previous sync (lock screen enablement inputs) | N/A (web media session only) | Implemented | Sync flow in [useAudioEngine.ts](/Users/jeff/Developer/familiar/packages/frontend/src/player/useAudioEngine.ts), bridge mapping test in [engineContract.test.ts](/Users/jeff/Developer/familiar/packages/frontend/src/player/audio/__tests__/engineContract.test.ts), refresh tests in [useAudioEngine.integration.test.tsx](/Users/jeff/Developer/familiar/packages/frontend/src/hooks/__tests__/useAudioEngine.integration.test.tsx) | PASS |
| Lock-screen controls visible + enabled correctly on device | N/A | Implemented; device-validated | Command availability logic in [NativeAudioEngine.swift](/Users/jeff/Developer/familiar/packages/ios/native/App/NativeAudioEngine.swift), AppTests scaffold: [NativeAudioEngineRemoteCommandAvailabilityTests.swift](/Users/jeff/Developer/familiar/packages/ios/native/AppTests/NativeAudioEngineRemoteCommandAvailabilityTests.swift) | PASS |
| Preload next track readiness | Implemented | Implemented (`preloadNext` + `preloadNextLocal`) | Web: [WebAudioEngine.ts](/Users/jeff/Developer/familiar/packages/web/src/WebAudioEngine.ts), iOS: [NativeAudioEngine.swift](/Users/jeff/Developer/familiar/packages/ios/native/App/NativeAudioEngine.swift), fallback test in [useAudioEngine.integration.test.tsx](/Users/jeff/Developer/familiar/packages/frontend/src/hooks/__tests__/useAudioEngine.integration.test.tsx) | PASS |
| Crossfade when preloaded | Implemented | Implemented | Crossfade APIs in [WebAudioEngine.ts](/Users/jeff/Developer/familiar/packages/web/src/WebAudioEngine.ts), [CapacitorEngine.ts](/Users/jeff/Developer/familiar/packages/ios/src/CapacitorEngine.ts), [NativeAudioEngine.swift](/Users/jeff/Developer/familiar/packages/ios/native/App/NativeAudioEngine.swift); callback behavior test in [engineContract.test.ts](/Users/jeff/Developer/familiar/packages/frontend/src/player/audio/__tests__/engineContract.test.ts) | PASS |
| Crossfade fallback when preload not ready/timeout | Implemented | Implemented | Timeout + typed failure in [NativeAudioEngine.swift](/Users/jeff/Developer/familiar/packages/ios/native/App/NativeAudioEngine.swift), fallback behavior test in [useAudioEngine.integration.test.tsx](/Users/jeff/Developer/familiar/packages/frontend/src/hooks/__tests__/useAudioEngine.integration.test.tsx) | PASS |
| Offline/downloaded source resolution used for playback | Implemented (Dexie blob URL) | Implemented (Filesystem native URI preference) | Web resolver in [WebAudioEngine.ts](/Users/jeff/Developer/familiar/packages/web/src/WebAudioEngine.ts), iOS resolver in [CapacitorEngine.ts](/Users/jeff/Developer/familiar/packages/ios/src/CapacitorEngine.ts), storage path in [offlineService.ts](/Users/jeff/Developer/familiar/packages/frontend/src/services/offlineService.ts) | PASS |
| Visualizer analysis pipeline active during playback | Implemented | Implemented | Native analysis emit in [NativeAudioEngine.swift](/Users/jeff/Developer/familiar/packages/ios/native/App/NativeAudioEngine.swift), bridge event in [FamiliarAudioPlugin.swift](/Users/jeff/Developer/familiar/packages/ios/native/App/FamiliarAudioPlugin.swift), consumption in [CapacitorEngine.ts](/Users/jeff/Developer/familiar/packages/ios/src/CapacitorEngine.ts), hook in [useAudioAnalyser.ts](/Users/jeff/Developer/familiar/packages/frontend/src/hooks/useAudioAnalyser.ts) | PASS |
| Crash/stability under stress run | Not part of web parity gate | Partially hardened + device-validated | State tokenization + download-task changes in [NativeAudioEngine.swift](/Users/jeff/Developer/familiar/packages/ios/native/App/NativeAudioEngine.swift) | PASS |

## Automated Evidence Completed

- `vitest` parity suites passing:
  - [useAudioEngine.integration.test.tsx](/Users/jeff/Developer/familiar/packages/frontend/src/hooks/__tests__/useAudioEngine.integration.test.tsx)
  - [engineContract.test.ts](/Users/jeff/Developer/familiar/packages/frontend/src/player/audio/__tests__/engineContract.test.ts)
- Native project build succeeded:
  - `xcodebuild -project packages/ios/native/App.xcodeproj -scheme App -destination 'generic/platform=iOS' build`
- Native AppTests target/scheme wiring validated on simulator:
  - `xcodebuild -project packages/ios/native/App.xcodeproj -scheme App -destination 'platform=iOS Simulator,OS=18.5,name=iPhone 16' -only-testing:AppTests test`
- TestFlight upload succeeded:
  - build `45`

## Device Validation Completed

1. Lock-screen controls validated on device (build 45): visible with correct next/previous availability transitions.
2. Visualizer validated on device: non-zero changing bands during playback with no sustained dropouts reported.
3. Offline validated on device: downloaded tracks play with network disabled, including queue advance and crossfade behavior.
4. Native stress run validated: no crash or stuck loading reported for test interval.

## Current Signoff Decision

`FINAL` parity signoff achieved for the scoped parity criteria on build `45`, based on automated evidence plus completed device validation.
