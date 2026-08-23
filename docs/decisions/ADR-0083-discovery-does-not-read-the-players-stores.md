# ADR-0083: Discovery Does Not Read the Player's Stores

Status: accepted

Date: 2026-08-18

Extends [ADR-0017](ADR-0017-the-embedded-surface-gets-a-null-audio-engine.md). Depends on
[ADR-0066](ADR-0066-music-video-is-a-player-mode-not-a-visualizer.md), which removes the same
dependency from the other embedded surface.

## Context

`ADR-0016` point 5 made the embedded page's relationship to playback one-way: the page posts an
intent, and *"the web view is never told what is playing"*. Three components on the embedded Discover
surface reach past that and read the player's state directly.

`components/Discovery/DiscoverTrackList.tsx`, `DiscoveryGrid.tsx` and `DiscoveryList.tsx` each import
`usePlayerStore`, using four selectors between them:

| selector | used for |
|---|---|
| `currentTrack` | which row shows as playing |
| `isPlaying` | the play/pause glyph on that row |
| `setIsPlaying` | toggling it |
| `setQueueByTrackId` | starting playback (`DiscoverTrackList` only) |

On the embedded surface none of these are connected to anything. The engine is null (`ADR-0017`
point 2), so `isPlaying` never becomes true from this page; the native app owns the queue and never
tells the page what it is playing. `setQueueByTrackId` is the path `ADR-0017`'s Implementation
already had to intercept — `registerPlaybackInterceptor` exists in `embed.tsx` precisely because
`DiscoverTrackList` calls the store instead of its `onPlayTrack` prop, and pressing a row otherwise
set a local queue, made no sound, and left the row spinning forever.

**So the store is doing nothing here except holding the surface hostage.** It is the last thing
pinning `player/` into the embedded bundle:

```
Discovery/* → stores/playerStore → player/playerStore → queueStore (1,193 lines)
            → persistenceAdapter → persistence → db/index
```

`ADR-0066` cuts the identical dependency on the *visualizer* surface, where `MusicVideo` reads
`currentTime` from a store that is never mounted — a defect it documents as having broken music-video
sync on the Mac and phone since `ADR-0033`. This ADR is the Discover half of the same finding, and
the two together are what allow `queueStore`, `playbackStore`, `persistence` and `persistenceAdapter`
to be deleted rather than merely orphaned.

**What remains after both is the engine seam** — `audio/createEngine`, `engineInstance`,
`analysisMetrics`, `analysisDiagnostics`, `nativeAnalysisBuffers`, `types` and `playbackInterceptor`,
roughly 900 lines rather than the 2,695 the removal scope originally measured as unavoidable.

## Decision

1. **The three Discovery components take playing state as props, not from a store.** `currentTrackId`
   and `isPlaying` come from the parent; the parent on the embedded surface supplies what it knows,
   which is nothing, and the components render no playing indicator there.

2. **Starting playback goes through the callback the components already receive.**
   `DiscoverTrackList` calls `onPlayTrack` rather than `setQueueByTrackId`. The interceptor in
   `embed.tsx` stays regardless — `ADR-0017` point 5 makes it a floor rather than a mechanism to be
   removed once the paths look clean.

3. **`stores/playerStore.ts` is deleted**, along with `player/playerStore.ts`, `queueStore.ts`,
   `playbackStore.ts`, `persistence.ts`, `persistenceAdapter.ts` and `playerStore.types.ts`, once
   `ADR-0066` has removed the visualizer's dependency.

4. **`player/` is renamed `audio/`.** What survives is an audio-engine seam, not a player, and the
   directory name is the last place in the tree that says otherwise.

5. **A dependency-cruiser rule holds the line**: `embed.tsx` and `visualizer.tsx` must not reach any
   store outside the surfaces' own. This replaces `frontend/scripts/check-audio-guardrails.mjs`,
   which reads `player/useAudioEngine.ts` and `player/queueStore.ts` by path and **will crash** when
   they are deleted.

6. **This lands after `ADR-0066`, not beside it.** Both touch the same dependency for the same
   reason, in adjacent files, and `ADR-0066` also removes `music-video` from the visualizer registry.
   Sequencing them avoids two changes editing one import graph from opposite ends.

## Alternatives Considered

**Feed the store from the bridge instead**, so the embedded page knows what is playing and the
components work unchanged. This is the option that makes the indicators *correct* rather than absent,
and it is a real product improvement — seeing which track is playing while browsing Discover is
useful. Rejected here because it is a bridge change: `ADR-0033` opened an app-to-page channel for the
visualizer only and said so explicitly, and widening it to Discover is a decision that deserves its
own ADR rather than arriving as a refactor. **This is the most likely thing to revisit.**

**Keep `usePlayerStore` and leave the pin.** Rejected because it keeps 1,193 lines of `queueStore`,
the persistence layer and the Dexie schema in a document that cannot play anything — and because
`ADR-0071` deletes `db/`, which the persistence layer imports, so the pin has to be cut regardless.

**Give the embedded surface a stub store** with the same shape and no behaviour. Rejected as the
pattern `ADR-0017` point 1 already refused for the app itself: the embedded surface is a separate
entry point rather than the app with pieces neutralised, because a stub is a thing that looks
connected and is not.

**Do it in the same change as `ADR-0066`.** Tempting, since it is one dependency. Rejected under
point 6, and because `ADR-0066` is another author's proposed decision with its own scope.

## Consequences

- **Positive** — the embedded Discover surface stops depending on the player entirely, which is what
  `ADR-0016` point 5 said it did.
- **Positive** — with `ADR-0066`, roughly 1,900 further lines are deleted, and `player/` becomes a
  900-line `audio/` seam. Nothing in the tree is named for a player afterwards.
- **Positive** — the guardrail script that would crash on the deletions is replaced by a rule that
  checks the property rather than the filenames.
- **Tradeoff** — **the Discover rows lose their playing indicator on every surface**, including the
  admin app if anything still renders them. On the embedded surface it never worked; elsewhere this
  is a small regression traded for the dependency, and the Alternatives note how to get it back
  properly.
- **Tradeoff** — this is the highest-risk change in the restructure. It edits the components the Mac
  and iPhone Discover tabs render, and no automated check covers them. Pressing a row must still
  start playback in the *native* player on both devices.
- **Follow-up** — if the playing indicator turns out to matter, the answer is a bridge message under
  `ADR-0020` point 3's bar, not a restored store import.
