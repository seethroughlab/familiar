# ADR-0002: The Web App Is the Management Surface

Status: superseded by [ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md)

Date: 2026-07-26

Implementation:
- Accepted 2026-07-26 alongside [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md).
  Mobile-web polish, install-prompt work, and iOS-Safari-specific layout work stop as of this date;
  existing code stays in place until it is actively in the way.
- The deletion-or-dormancy call on `MobileNav/`, `PWA/InstallPrompt.tsx`, and the iOS Safari layout
  workarounds is deferred until the native client ships, per the follow-up below.

Extends [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md).

## Context

[ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md) commits to native macOS and iOS
clients scoped to the listening path. That leaves an unanswered question that has to be settled
deliberately: **what is the web app for now?**

The question is not rhetorical. `packages/frontend/src/components/` is 202 files and 40,654 lines,
and most of it is not listening — it is administration:

| Area | Scale |
|---|---|
| `Settings/` | 23 panels, 7,014 lines — server URL, playback, audio effects, analysis, AI, Last.fm, offline, storage quota, library organizer/sync, missing tracks, proposed changes, remote logs, debug, theme, profiles, community cache, system status, data management |
| `Library/` sub-browsers | `VibeMap` (3D embedding map), `PendingReviewBrowser`, `ProposedChangesBrowser`, `ArtistCleanupBrowser`, `DiscoverBrowser` |
| `Visualizer/` | 22 files, 3,985 lines of three.js/R3F |
| `TrackEdit/` | 12 files, 2,299 lines — metadata editing, MusicBrainz lookup, bulk auto-populate |
| `MixTape/`, S3 backup, import | Mixtape rendering, `S3Backup/`, Spotify import |

Rebuilding that natively — once for Apple, later again for Windows — is not work anyone wants to do,
and none of it benefits from being native. It is desk-bound, mouse-and-keyboard, occasional-use
tooling.

Meanwhile the web app has been carrying a second identity as a would-be native mobile app: install
prompts (`components/PWA/InstallPrompt.tsx` branches across `ios-safari` / `macos-safari` /
`beforeinstallprompt`), iOS Safari flexbox workarounds, mobile navigation (`MobileNav/`), and PWA
docking behaviour. That identity is what [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md)
retires.

## Decision

The web app keeps full desktop playback and becomes the **sole home for administration**. It stops
being a mobile-native pretender.

1. **Retained, and the web app is the only place they live:** all 23 Settings panels; library import,
   cleanup, pending review, and proposed changes; embedding maps; the visualizer; mixtapes; S3
   backup; track metadata editing.

2. **Retained: full playback on desktop.** `WebAudioEngine.ts` and the `audioEffects/` chain stay.
   The web app remains a complete player at a computer — it is not reduced to an admin console.

3. **No longer a target: the mobile web experience.** No further work on install-prompt positioning,
   iOS Safari-specific layout, PWA docking, or mobile navigation polish. Existing code stays until
   it is in the way; it simply stops receiving investment.

4. **Feature parity between web and native is explicitly not a goal.** The two clients have
   different jobs. Divergence is the intended outcome, not drift to be corrected.

5. **New listening-path features go to native first** once the native app exists, and reach the web
   app only if they are cheap there. New management features go to web only.

## Alternatives Considered

- **Retire the web app entirely.** Rejected. It would require rebuilding 40,654 lines of component
  code natively, twice, for tooling that gains nothing from being native.
- **Keep full parity on both clients.** Rejected. This is precisely the status quo that produced the
  maintenance fatigue behind [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md);
  formalising it would guarantee the same outcome.
- **Reduce the web app to admin only, removing playback.** Rejected. Desktop browser playback is
  genuinely useful and already works; removing it would delete `WebAudioEngine.ts` and the effects
  chain for no benefit before the macOS native client exists.
- **Move administration into the native app instead.** Rejected. It is the largest surface and the
  least suited to native.

## Consequences

- **Positive:** The native app's v1 scope shrinks to something achievable, because administration is
  explicitly someone else's job.
- **Positive:** A clear answer to "what is the PWA for" — it is the management surface and the
  desktop player, not a degraded phone app.
- **Positive:** Zero-install access from any machine is retained for free.
- **Tradeoff:** Managing the library from a phone means using the web app in a mobile browser, which
  will be a second-class experience by design.
- **Tradeoff:** Two clients to keep working against one backend. Mitigated by
  [ADR-0007](ADR-0007-clients-are-generated-from-openapi.md), which makes the contract generated
  rather than hand-maintained.
- **Follow-up:** Decide whether mobile-web code (`MobileNav/`, `PWA/InstallPrompt.tsx`, iOS Safari
  layout workarounds) is deleted or left dormant, once the native app ships.
