# ADR-0001: Native Apple Clients Supersede the Capacitor App

Status: proposed

Date: 2026-07-26

## Context

Familiar's mobile client is a Capacitor app (`packages/ios`) wrapping the shared React frontend
(`packages/frontend`, ~62.5k lines of product code). Daily use has drifted toward Spotify, with three
reported symptoms: offline/sync is unreliable, playback glitches, and the app "feels like a website."

The opening hypothesis was that the PWA architecture causes the bug volume, and that fully native
apps for macOS, Windows, and iOS in separate repos would fix it. **That hypothesis does not survive
the evidence, and this ADR records why — so the reasoning is not re-derived later.**

Of the last 300 commits' 112 fix commits:

| Category | Share |
|---|---|
| CI / lint / test plumbing (not user-facing) | ~48% |
| Backend / Python | ~21% |
| Ordinary app logic and UI | ~13% |
| PWA / browser platform | ~9% |
| iOS / Capacitor native | ~8% |

A native rewrite addresses the ~9%. It *inherits* the ~8%, because those are defects in Swift that
already exists — `dbcc3496 Fix NativeAudioEngine graph reconfiguration crash`, `e6b0369 fix: resolve
iOS lock screen greyed-out buttons`, `58ca2d9 fix: CarPlay/lock screen metadata desync`. Supporting
signals point the same way: exactly one `HACK`/`FIXME` comment across 449 source files; the service
worker has been touched for a bug once in 922 commits and is compiled out of the iOS build entirely
(`packages/web/vite.config.ts` gates `VitePWA` on `!isCapacitorBuild`); the issue tracker holds three
open items; `docs/AUDIT-BACKLOG.md` is almost entirely struck through. This codebase is not losing a
fight with its platform.

**The symptoms are nonetheless real, and they do justify native work — on different grounds:**

1. **Offline downloads are structurally compromised on iOS.** `packages/frontend/src/services/offlineService.ts`
   base64-encodes audio across the Capacitor bridge into the filesystem. Cf. `edd96c5 fix: fail loudly
   instead of silently blob-storing on native iOS download`. `URLSession` background download tasks
   continue while the app is suspended; a WebView cannot. No amount of PWA work closes this gap.
2. **macOS plays audio through the browser media element.** `HTMLAudioElement` `ended`/`waiting`/`canplay`
   semantics are where most PWA playback fixes landed (`ea34fd5`, `039ace3`, `680db03`). iOS already
   bypasses this — `packages/frontend/src/player/audio/platform.ts` routes Capacitor builds to native
   audio. macOS has no such escape today.
3. **Native feel** is not achievable by a WebView on either platform.

Notably, the hybrid boundary is *already* drawn correctly on iOS: `NativeAudioEngine.swift` is 1,860
lines of AVAudioEngine doing playback, crossfade, EQ/reverb/delay, FFT for the visualizer, lock
screen, and CarPlay. The WebView does zero audio work. What remains hybrid is the UI.

## Decision

Build **one native application targeting macOS and iOS** from a single new repository,
`familiar-apple`, sharing a `FamiliarKit` SwiftPM package between the two targets.

1. **One repo, two targets.** macOS and iOS share `FamiliarKit` and the large majority of SwiftUI.
   They are not split.

2. **`NativeAudioEngine.swift` moves intact.** All 1,860 lines — the AVAudioEngine graph, the
   `WaveshaperAudioUnit`, token-guarded load/preload/seek/crossfade, the FFT analysis processor,
   `AVAudioSession` interruption handling, `MPNowPlayingInfoCenter`/`MPRemoteCommandCenter` — become
   the core of `FamiliarKit`. The four XCTest suites in `packages/ios/native/AppTests/` come with it.

3. **The Capacitor bridge is deleted, not ported.** `FamiliarAudioPlugin.swift` (536 lines) exists
   solely to marshal 35 methods across the JS boundary. In a native app it has no purpose.
   `packages/ios/src/` (1,623 lines of TypeScript, including `CarPlayCoordinator.ts` at 792) is
   likewise not ported; CarPlay is rewritten against native state.

4. **v1 scope is the listening path.** Library browse, search, playlists, album/artist detail,
   player, full-screen now-playing, queue, offline, CarPlay, and AI chat/discovery. The bar is
   fundamental playback and navigation quality, not feature breadth.

5. **Explicitly out of v1**, remaining web-only and possibly permanently: the visualizer (4,017 lines
   of three.js/React-Three-Fiber across 23 files), ambient/generative mode, the 23 settings panels,
   library import/cleanup/review queues, embedding maps, mixtapes, S3 backup.

6. **`packages/ios` freezes to bug-fix-only immediately** and is retired once the native app reaches
   parity on the v1 scope.

7. **Windows is deliberately not built now.** It is prepared for by keeping logic server-side
   (see [ADR-0003](ADR-0003-server-owns-the-playback-queue.md),
   [ADR-0006](ADR-0006-offline-ranking-is-precomputed-server-side.md),
   [ADR-0007](ADR-0007-clients-are-generated-from-openapi.md)) so that a future Windows client is
   UI plus audio engine and little else.

## Alternatives Considered

- **Three separate repos for macOS, Windows, and iOS.** Rejected. macOS and iOS share the audio
  engine and most of the view layer; splitting them duplicates `FamiliarKit` on day one. Windows is
  not being built, so its repo would sit empty.
- **Renovate the PWA instead.** Rejected. It cannot deliver background downloads on iOS, which is
  the strongest of the three reported symptoms.
- **Keep Capacitor, rewrite only the UI in native views.** Rejected. Capacitor's value is the shared
  web UI; once the UI is native the bridge is pure overhead.
- **Do nothing.** Rejected — but it deserves recording that this was defensible on bug data alone.
  The case for acting rests on the three structural symptoms, not on defect counts.

## Consequences

- **Positive:** Background downloads become reliable on iOS; macOS gains AVAudioEngine; both
  platforms gain native feel. The most valuable existing native asset is preserved rather than
  rewritten.
- **Positive:** Deleting the Capacitor bridge removes ~2,150 lines of pure marshalling code
  (`FamiliarAudioPlugin.swift` plus `packages/ios/src/`).
- **Tradeoff:** 3–6 months part-time to reach v1 scope. This is the dominant cost of the decision.
- **Tradeoff:** iOS stagnates for that duration. Mitigated by shipping backend work first
  ([ADR-0004](ADR-0004-listening-feedback-is-event-sourced.md),
  [ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md)), which reaches the existing
  app without native work.
- **Tradeoff:** Feature surface splits across two clients. [ADR-0002](ADR-0002-web-app-is-the-management-surface.md)
  defines the split so it is intentional rather than accidental.
- **Follow-up:** The ~8% iOS-native defect bucket is not fixed by this decision and carries forward
  into `FamiliarKit`. Those bugs need addressing on their own merits.
