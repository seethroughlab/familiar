# Removing the web player — scope

The countdown in `docs/WEB-PARITY.md` is empty, so ADR-0058 point 4's condition is met and the
fallback player can go. This is the scope, written before cutting anything, because the removal is
**not** a delete of `player/` — the embedded surfaces pin part of it.

## The thing that makes this delicate

ADR-0050 kept the player partly to keep `WebAudioEngine` and the effects chain "exercised rather
than rotting untested", and flagged that `/embed` and `/visualizer` pin much of `player/`. **That
flag was right, and it is more than "much".**

`/embed` is not a passive page. Discover plays music (ADR-0017), so:

- `packages/web/src/embed.tsx:31` registers a **`NullAudioEngine`** through
  `player/audio/createEngine` — the null engine is what makes a missed play intent inert rather than
  a second audio engine.
- `components/Discovery/DiscoveryList.tsx`, `DiscoverTrackList.tsx` and `DiscoveryGrid.tsx` all
  import `usePlayerStore`.
- `stores/playerStore.ts` is a two-line re-export of `player/playerStore.ts` (65 lines), which
  imports `playbackStore`, `queueStore` and `playerStore.types`.

So the embed transitively depends on the queue and playback stores. Deleting `player/` wholesale
breaks the Mac and iPhone Discover tab, which is the opposite of the point.

## What goes

Confident, and self-contained:

- `/library/tracks` route, `TrackListBrowser`, and its registration in `routes.ts`
- `components/FullPlayer/` (679 lines), `components/Player/` (822)
- `packages/web/src/WebAudioEngine.ts` and the effects chain
- `db/` — the Dexie track cache (707) — and `stores/downloadStore.ts`
- `services/offlineService.ts`, `playlistCache.ts`, `offlineManifestService.ts`,
  `queueSyncService.ts` + `stores/queueSyncStore.ts`
- `Settings/PlaybackSettings.tsx` and `OfflineSettings.tsx`, per ADR-0058 point 5's second wave
- The Tools page's "Track list" link (affordance and capability leave together — ADR-0057 point 5)

## What stays, and why

- `player/audio/createEngine.ts` — the registration seam both embed entry points use
- `packages/web/src/NullAudioEngine.ts` — ADR-0017's whole mechanism
- `player/playerStore.ts`, `playbackStore`, `queueStore`, `playerStore.types` — pinned by the
  Discovery components the embed renders
- Everything under `components/Visualizer/`, `services/visualizerPluginHost.ts`, `visualizerSink.ts`
- `/listen/:code` and `components/Guest/` — web-only by decision (ADR-0037 rejected)

## The real question to answer first — measured

**How much of `player/` is reachable from `/embed` and `/visualizer`?** Measured on 2026-08-18 by
building `embed.html` + `visualizer.html` with `index.html` dropped from `rollupOptions.input`, and
dumping every module id rollup emitted (`generateBundle`, 2,529 modules transformed). The source
graph was then walked separately, because type-only imports never reach the bundle and still have to
compile.

Of `player/`'s 28 non-test files — 5,229 lines, with a further 4,181 in 15 test files:

| | files | lines | |
|---|---|---|---|
| **In the embed/visualizer bundle** | 11 | 2,471 | `audio/{analysisDiagnostics,analysisMetrics,createEngine,engineInstance,nativeAnalysisBuffers}`, `persistence`, `persistenceAdapter`, `playbackInterceptor`, `playbackStore`, `playerStore`, `queueStore` |
| **Type-only — compiles, never bundles** | 3 | 224 | `audio/types`, `playerStore.types`, `ambient/types` |
| **Unreachable from either entry** | 14 | 2,534 | all of `ambient/`, `radio/radioController`, `useAudioEngine` (970), `useAudioControls`, `audioSettingsStore`, `audio/eventHandlers`, `audio/platform`, `index.ts` |

So **just under half of `player/` goes**, and `useAudioEngine.ts` — the file the whole subsystem is
named for — is on the removable side. The two pins that matter:

- The **visualizer** pins `playerStore` → `queueStore` → `persistenceAdapter` → `persistence`, via
  `MusicVideo.tsx` → `stores/playerStore`. `queueStore` alone is 1,193 lines.
- The **embed** pins `audio/{createEngine,engineInstance}` through `renderEmbed` and
  `hooks/useAudioAnalyser`.

`player/index.ts` is itself unreachable: every surviving import names the module directly, and
`stores/playerStore.ts` re-exports `../player/playerStore`, not the barrel. Deleting the barrel is
what makes the 14 unreachable files stay unreachable rather than being dragged back by a re-export.

### The list above was wrong about three files

`db/index.ts`, `services/offlineService.ts` and `services/playlistCache.ts` are under "What goes",
and **all three are in the embed bundle.** So is `services/syncService.ts`, which the list does not
mention at all. The chains are short and real:

```
renderEmbed → EmbedDiscover → DiscoverBrowser → useOfflineStatus → connectivityStore → offlineService → db/index
renderEmbed → EmbedDiscover → DiscoverBrowser → Discovery → DiscoverTrackList → PlaylistTrackList
                            → useTrackContextMenu → useFavorites → {playlistCache, offlineService, syncService} → db/index
renderVisualizer → visualizers → MusicVideo → stores/playerStore → playerStore → queueStore → persistenceAdapter → persistence → db/index
```

Three independent pins on Dexie: offline status on the Discover header, favorites-with-offline-cache
in the track context menu, and queue persistence. `PlaylistTrackList` also pulls `useOfflineTrack`.

That is a decision, not a measurement, so it is recorded here rather than settled: **either keep
`db/` and the offline stack, or give `useFavorites` and `connectivityStore` an online-only path
first.** The second is the honest version — an embedded page inside a native app has no use for a
Dexie track cache, and `connectivityStore.startMonitoring()` is running reachability polling inside
a web view whose host already knows whether it is online — but it is its own change, and it edits
code the Mac and iPhone Discover tab runs.

Everything else on the "What goes" list is confirmed unreachable from both entry points:
`FullPlayer/`, `Player/`, `WebAudioEngine.ts`, `audioEffects/` (14 files), `downloadStore`,
`offlineManifestService`, `queueSyncService`, `queueSyncStore`, `PlaybackSettings`,
`OfflineSettings`, `TrackListBrowser`.

Remaining sequence:

1. ~~Measure.~~ Done, above.
2. Delete what is genuinely unreachable.
3. Leave the rest, and record *why* each survivor survives — otherwise the next person meets the
   same ambiguity with less context than we have now.

Do **not** start by deleting `player/` and fixing the errors. The dependency runs through
`playerStore`, so the errors will appear in Discovery components that must keep working, and the
temptation will be to stub them.

**Reproducing the measurement:** add a `generateBundle` plugin that writes `Object.keys(chunk.modules)`
for every chunk, and build with `input` reduced to `embed.html` + `visualizer.html`. Walk the source
graph separately for the type-only edges — and strip comments before regexing for imports, or
`stores/playerStore.ts`'s `// DEPRECATED: import from '../player' instead` fabricates an edge to the
barrel and makes all 14 dead files look pinned.

## Verification, once cut

```bash
cd packages/frontend && npx tsc -p tsconfig.json --noEmit   # 7 errors, all pre-existing
pnpm test                                                    # 41 files / 532 tests
node ./scripts/check-embed-guardrails.mjs                    # replaces check-audio-guardrails.mjs
cd ../web && pnpm run build                                  # must still emit embed + visualizer
```

**The counts moved, and both directions are expected.** The baseline was 14 tsc errors and
63 files / 955 tests when this was written; it was 14 and 67 / 1,012 by the time the cut ran. Seven
of those errors lived in `useKeyboardShortcuts.test.ts` and went with it, leaving 7 — three in
`engineContract.test.ts`, three in `serverToken.test.ts`, one in `useScrobbling.test.ts`, none of
them touched by this work. The test files that vanished are the player's, the sessions' and the
offline stack's own.

Then, and this is the part that actually matters: **open Discover on the Mac and on the phone.**
Both render the embedded page, both can start playback from it, and a regression there is invisible
to every check above. `navigationIntegrity.test.ts` guards the routes; nothing guards the embed.
