# ADR-0013: The Mac Is a Management Surface Too

Status: accepted

Date: 2026-08-01

Supersedes [ADR-0002](ADR-0002-web-app-is-the-management-surface.md).

Implementation:
- Accepted 2026-08-01, alongside [ADR-0015](ADR-0015-audio-effects-are-exposed-not-rebuilt.md), which
  is the first piece of work to inherit from it. `ADR-0014` and `ADR-0016` remain `proposed` — they
  are approved separately, when the features they govern are started.
- The album and artist grids shipped before this was accepted and deliberately did not wait on it:
  library browse is in ADR-0001 point 4's v1 scope, so it was never a management surface.

## Context

[ADR-0002](ADR-0002-web-app-is-the-management-surface.md) made the web app the **sole** home for
administration, and [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md) point 5 put the
visualizer, ambient mode, the 23 settings panels, import/cleanup/review queues, embedding maps,
mixtapes and S3 backup out of the native v1 "possibly permanently". ADR-0002 point 4 stated the
principle plainly: *"feature parity between web and native is explicitly not a goal. Divergence is
the intended outcome, not drift to be corrected."*

Both were right for what they were deciding. ADR-0002 was written on 2026-07-26, before a native app
existed, when the risk was a v1 that never shipped because its scope was the whole product. Bounding
native to the listening path is what let it ship — and it did ship: browse, search, playlists,
album and artist detail, the player, the full-screen now-playing, the queue, offline downloads,
favorites and CarPlay all exist and are in daily use.

What changed is not the argument but the vantage point. Using the Mac app daily, the absent
management surfaces read as gaps rather than as scope, and the reason is specific to *that* platform:
a Mac is where this library is actually administered. The phone is not, and never was.

**The premise that has weakened is "web *or* native", not "web is good at this".** The web app
remains an excellent management client; nothing about it has gone wrong. What no longer holds is the
conclusion that management must therefore live in only one place, on a machine where the native app
is already open.

Three things investigation established that bear on the decision, and which the earlier ADRs could
not have known:

1. **The Mac's audio effects already exist.** `NativeAudioEngine` carries `AVAudioUnitEQ`, reverb,
   delay, compressor and the custom `WaveshaperAudioUnit`, with public `setEQ` (line 1042),
   `setReverb` (1062), `setDelay` (1090), `setCompressor` (1119) and `setFilter` (1151). They came
   across intact under ADR-0001 point 2 and have never been called by anything. The cost of exposing
   them is a settings screen, not a DSP project.
2. **Music Map is 690 lines of Canvas 2D in one file**
   (`packages/frontend/src/components/Library/browsers/VibeMap/VibeMap.tsx`), and its data is capped
   at 200 entities, 500 maximum, in `backend/app/api/routes/library_maps.py` (lines 58 and 73).
   ADR-0001 point 5's
   "4,017 lines of three.js" is the **visualizer**, a different feature. The map was grouped with it
   by association rather than by measurement.
3. **Much of the API is already generated for these surfaces.** `smart-playlists` is one of
   ADR-0007's eight tags, so smart playlist CRUD needs no backend or schema work at all; and
   `/library/map`, `/library/map/3d` and `/library/map/ego` carry the `library` tag, which
   `backend/scripts/lint_openapi.py` already notes is generated whole "despite mixing ~18 listening
   operations with ~17 management ones".

**A contradiction this resolves.** ADR-0002 point 5 says new listening-path features go to native
first once the native app exists. [ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md)
point 6 designs radio's client half against `packages/frontend/src/player/ambient/AmbientCoordinator.ts`
— the web player — because it was written when native did not exist. Radio is a listening-path
feature, so those two now disagree. This ADR does not settle it; it records that the disagreement is
real so that whoever builds radio decides deliberately rather than by whichever document they read
first.

## Decision

**macOS becomes a management surface alongside the web app. The web app loses nothing.**

1. **Both clients keep everything.** Nothing is removed from the web app, frozen, or reduced to
   bug-fix-only as `packages/ios` was. A browser on any machine stays fully capable, which is the
   property ADR-0002 valued most and which costs nothing to keep.

2. **iOS stays the listening path.** The phone is not a management client. ADR-0001 point 4's v1
   scope stands for it unchanged, and the mobile web experience remains not a target (ADR-0002
   point 3, carried forward). Managing this library from a phone means the web app in a mobile
   browser, and that is still a second-class experience by design.

3. **In scope for the Mac**, each as its own piece of work: smart playlist CRUD, audio effects,
   pending review, proposed changes, Music Map, mixtapes, and Discover.

4. **Still web-only, and now for stated reasons rather than by inclusion in a list:**
   - the **visualizer** — 4,017 lines of three.js across 23 files per ADR-0001's audit, with no
     native analogue and no management purpose;
   - **ambient/generative mode** — out of v1 per ADR-0001 point 5, and `ambient` is deliberately
     absent from the generated surface per ADR-0007;
   - the **23 settings panels** — they configure the *server*, and a server has one configuration
     whichever client edits it; there is no per-client value in a second editor;
   - **S3 backup**, **library import** and **Spotify import** — long-running operations tied to
     server-side filesystem state, where a second client is a second thing to keep correct for no
     gain.

5. **Full web playback is retained**, unchanged from ADR-0002 point 2. `WebAudioEngine.ts` and the
   `audioEffects/` chain stay; the web app is a complete player at a computer, not an admin console.

6. **Parity, restated precisely.** Parity between web and **iOS** remains explicitly not a goal —
   ADR-0002 point 4 holds there in full. Parity between web and **macOS**, on the management
   surfaces named in point 3, is now the direction. Divergence between the two desktop clients is no
   longer the intended outcome for those features.

7. **New management features go to whichever client is asked for, and are not required in both.**
   Point 6 names a target for a specific list, not a standing obligation to build twice. A new
   management feature is not blocked on having a Mac implementation.

## Alternatives Considered

**Leave ADR-0002 as it is and use the web app for management.** This is the status quo and it works
— the web app is genuinely good, and this ADR is the more expensive path. Rejected because the friction
is real and repeated: administering the library means leaving the app that is already open and in
which the library is already being browsed. Over months that is a large number of small costs, and
the specific features wanted are ones where the Mac has an advantage the browser cannot match
(effects belong to the audio engine; a map wants real trackpad gestures).

**Move management to the Mac and remove it from the web app.** Cleaner as a story — one home per
concern, no duplication, no drift. Rejected on sequencing rather than principle: every removal is a
capability lost before its replacement is proven, and management from a non-Mac machine disappears
entirely. If the Mac versions prove better in use, removal can be its own decision later, made
against evidence.

**Keep the web versions but freeze them, as `packages/ios` was frozen.** Attractive because it caps
the two-client cost while removing nothing. Rejected because the freeze on `packages/ios` worked as a
countdown to deletion — it had a stated end. These have none, and a frozen management surface that
nobody may fix is worse than either keeping it alive or removing it honestly.

**Bring these to iOS as well.** Rejected as a scope trap. The features are wanted because a Mac is
where administration happens; a review queue on a phone is a screen nobody would open. ADR-0001 point
4's bar — "fundamental playback and navigation quality, not feature breadth" — is still exactly right
for the phone.

## Consequences

- **Positive:** The Mac app becomes a complete client for how this library is actually used, rather
  than a listening front-end onto it.
- **Positive:** Several of these are far cheaper than ADR-0001 point 5's grouping implied — audio
  effects are already built and unexposed; smart playlists need no API work; the map is a tenth the
  size the "4,017 lines of three.js" figure suggested.
- **Positive:** Zero-install management from any machine is retained, unchanged.
- **Tradeoff:** Two implementations of each named surface, and they will drift. Accepted knowingly:
  the alternative is removing a working capability before its replacement has earned it.
- **Tradeoff:** The Mac app's scope grows well beyond ADR-0001's v1, which was deliberately small so
  that it shipped. It has shipped; this is what comes after, not a widening of it.
- **Tradeoff:** ADR-0001 point 5 is now half-right. Its exclusions hold for iOS and for the
  visualizer, ambient mode, settings and backup; they no longer hold for the Mac on the rest. It is
  not superseded, because its other six points stand.
- **Follow-up:** Radio's client half is unowned — ADR-0002 point 5 says native first, ADR-0005 point
  6 designs for web. Decide it when radio is built, not before.
- **Follow-up:** If the Mac versions of these surfaces prove better in use, revisit whether the web
  originals should be removed. That is a decision for evidence, and deliberately not taken here.
