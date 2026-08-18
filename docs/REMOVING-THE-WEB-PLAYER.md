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

## The real question to answer first

**How much of `player/` (9,439 lines) is reachable from `/embed` and `/visualizer`?** Nobody has
measured it. The honest sequence is:

1. Build `/embed` and `/visualizer` with the app entry point removed, and see what the bundler
   demands. That is a mechanical answer, not a judgement call.
2. Delete what is genuinely unreachable.
3. Leave the rest, and record *why* each survivor survives — otherwise the next person meets the
   same ambiguity with less context than we have now.

Do **not** start by deleting `player/` and fixing the errors. The dependency runs through
`playerStore`, so the errors will appear in Discovery components that must keep working, and the
temptation will be to stub them.

## Verification, once cut

```bash
cd packages/frontend && npx tsc -p tsconfig.json --noEmit   # baseline 14 errors
pnpm test                                                    # 63 files / 955 tests
cd ../web && pnpm run build                                  # must still emit embed + visualizer
```

Then, and this is the part that actually matters: **open Discover on the Mac and on the phone.**
Both render the embedded page, both can start playback from it, and a regression there is invisible
to every check above. `navigationIntegrity.test.ts` guards the routes; nothing guards the embed.
