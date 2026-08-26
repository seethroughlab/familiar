# ADR-0067: The Plugin API Exposes What a First-Party Visualizer Uses

Status: rejected — superseded before acceptance by
[ADR-0087](ADR-0087-a-visualizer-is-a-document-not-a-component.md)

**Rejected because its subject no longer exists.** This ADR decided *what* the host should expose on
`window.Familiar` — React, THREE, `@react-three/fiber`, drei and a set of hooks — having concluded
that the list should be what a first-party visualizer actually uses. `ADR-0087` removes the global
entirely: a visualizer is a document that brings its own libraries, so there is nothing left to
choose the contents of.

Its reasoning was sound for the contract it was written against, and one observation outlived it:
the note that Music Video was the only built-in needing `playerStore` and an API client, and that its
absence is what kept this surface small. That was evidence the component contract was wrong, and
`ADR-0087` cites it as such.

Date: 2026-08-18

Extends [ADR-0034](ADR-0034-visualizers-are-drop-in-bundles.md) point 3, which decided what the host
hands a plugin. That list grows here. Depends on
[ADR-0066](ADR-0066-music-video-is-a-player-mode-not-a-visualizer.md), which removes the one
built-in that would have forced playback state into this surface.

## Context

`ADR-0034` point 3 gave plugins React, three.js, `@react-three/fiber` and `@react-three/drei` on
`window.Familiar`, plus nine hooks — `useAudioAnalyser`, `getAudioData`, `useArtworkPalette`,
`useBeatSync`, `getBeatPhase`, `getBeatSine`, `useLyricTiming`, `getUpcomingLyrics` and
`getWordTiming`. That is enough to draw something. It is **not** enough to write any of the
visualizers this project ships.

Audited on 2026-08-18, the four remaining built-ins import, beyond that surface:

| Module | Used by | What it is |
|---|---|---|
| `components/Visualizer/effects/AudioReactiveEffects` | `ReactiveTerrain`, `BeatTiles` | The shared post-processing chain the Glow slider drives |
| `components/Visualizer/effects/FrameScheduler` | `ReactiveTerrain`, `BeatTiles` | Frame pacing |
| `components/Visualizer/visualizers/LyricWordField` | `ScrollingLyrics`, `LyricStorm` | A drifting field of the song's words, shared by both |
| `player/audio/analysisMetrics` | `ScrollingLyrics` | Nine exports over the analysis buffers |
| `utils/platform` | `ReactiveTerrain`, `BeatTiles` | Three exports |

**So the documented plugin API cannot express the visualizers that document it.** An author who
reads `docs/VISUALIZER_API.md`, copies a built-in, and tries to build it as a drop-in bundle finds
that half its imports do not exist. That gap has been there since the format was adopted and has
never been stated, because until now nothing tried to build a built-in as a plugin.

**`GPUParticles` is in the same directory and used by none of the four.** It is a capability the
effects folder offers that nothing currently takes up — worth listing here so the decision about it
is deliberate rather than inherited.

**The cost of widening is the point of the argument, and it has a measured precedent.**
`ADR-0034`'s own Consequences record that handing plugins `@react-three/drei` cost **1.59 MB**,
because `import * as Drei` cannot be tree-shaken — the inlined visualizer document went 1,782 kB to
3,375 kB. Everything added here is first-party code already in the bundle, so the byte cost is
different in kind; the cost that matters is that these modules stop being internal.

**Music Video is not in the table above**, and that is the whole reason this ADR is modest.
`ADR-0066` moves it out of the visualizer set; while it was in, this surface would have had to
include `stores/playerStore`, the API client and `@tanstack/react-query` — that is, playback state
and network access — for one entry that draws nothing.

## Decision

1. **`window.Familiar` gains exactly what the built-ins use**: the effects chain and frame
   scheduler, `LyricWordField`, the analysis metrics, and the platform helpers. Nothing is added
   speculatively. The test for inclusion is that a shipped visualizer imports it, which is a
   question with an answer rather than a judgement about what someone might want.

2. **`GPUParticles` is included, and it is the one exception to point 1.** No built-in uses it, but
   it sits in the same directory, is written to the same shape, and omitting it would mean an author
   reading the effects folder finds one of its members unavailable for no reason they can see. This
   is recorded as an exception so it is not read as precedent.

3. **`apiVersion` stays 1.** Every addition is additive: no existing bundle reads a global that
   changes meaning, so nothing that loads today stops loading. `ADR-0034` point 7 refuses a manifest
   declaring a version the host does not implement, so a bump would refuse both shipped examples and
   every third-party bundle to add capability none of them uses.

4. **What is exposed becomes a contract, and the ADR says so rather than discovering it later.**
   Once `FrameScheduler` is on the global, its signature is public: changing it breaks bundles this
   project did not build and cannot test. These five modules are frozen in the sense that
   `VisualizerProps` is frozen — changeable, but only the way a public interface is changeable.

5. **`stores/playerStore`, the API client and react-query are deliberately not exposed.** No
   remaining built-in needs them once `ADR-0066` lands, and each is a much larger claim than
   drawing: the store is playback control, and the API client is credentialed network access from
   code the app did not ship. A plugin that needs the playhead has `VisualizerProps.currentTime`,
   which is correct on every surface — including the embedded one, where the store is not mounted at
   all.

6. **`docs/VISUALIZER_API.md` documents the additions with the same weight as the originals.** An
   API surface that exists but is undocumented is the gap this ADR was written to close, and adding
   to it silently would reproduce that gap one level down.

## Alternatives Considered

- **Leave the surface as it is, and rewrite the built-ins to use only what plugins get.** Genuinely
  attractive: it keeps the API narrow, and it would prove the contract is sufficient by construction
  rather than by assertion. Rejected because the shared modules exist for good reasons — `BeatTiles`
  and `ReactiveTerrain` share an effects chain so the Glow slider drives both, and `LyricWordField`
  is shared so `ScrollingLyrics` and `LyricStorm` cannot drift apart. Duplicating them into each
  visualizer to satisfy a boundary would make the code worse to make the rule true.

- **Expose the whole frontend module graph** — hand plugins everything and let them import what they
  like. Simple to implement and never wrong about what is needed. Rejected because it makes every
  internal a public contract at once, which is the cost point 4 accepts deliberately for five
  modules and refuses to accept for hundreds.

- **Version the added surface separately from `apiVersion`** — a `familiar.effectsVersion`, say, so
  the wider API can move without touching the core. Rejected as machinery ahead of need: there is
  one version number and no evidence yet that these two things want to move at different rates.
  Point 4's contract is a promise, and a second version number would be a way of making a weaker
  promise without saying so.

- **Expose the modules but mark them unstable** — a `window.Familiar.unstable` namespace. Attractive
  because it is honest about the risk in point 4. Rejected because it does not change what happens:
  a plugin that uses an unstable module still breaks when it changes, and the label mostly moves the
  blame. If these modules cannot be kept stable, they should not be exposed.

## Consequences

- **Positive:** The documented API becomes sufficient to write the visualizers that document it —
  which is what an author copying a built-in has always assumed was true.
- **Positive:** [ADR-0068](ADR-0068-built-in-visualizers-ship-as-drop-in-bundles.md) becomes
  possible. It is the reason this is being done now, and it is not the only reason to do it.
- **Tradeoff:** Five internal modules become public. Refactoring `FrameScheduler` or
  `analysisMetrics` now has a cost outside this repository, and nothing in CI can tell you when you
  have broken a stranger's visualizer.
- **Tradeoff:** The exposed surface can only grow. Removing something from `window.Familiar` is an
  `apiVersion` bump under `ADR-0034` point 7, which refuses every existing bundle — so a module
  added here in error is expensive to take back.
- **Tradeoff:** Point 2 admits one thing nothing uses. That is a small, deliberate breach of point
  1's own rule, and it is the kind of exception that becomes a precedent if it is not labelled.
- **Follow-up:** Nothing tests that a bundle built against the published globals actually loads.
  `familiar-plugin-non-places` is the only artefact exercising the shared three.js globals today,
  and after this there will be five more globals with no such artefact.
- **Follow-up:** `ADR-0034` point 3 says a plugin "must not carry its own" copy of what the host
  provides, and nothing enforces it. That contract now covers five more modules, and duplicating
  `LyricWordField` in particular would produce two three.js scenes that look identical and diverge.
