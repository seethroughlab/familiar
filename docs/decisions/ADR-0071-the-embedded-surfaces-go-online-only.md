# ADR-0071: The Embedded Surfaces Go Online-Only

Status: proposed

Date: 2026-08-18

Extends [ADR-0017](ADR-0017-the-embedded-surface-gets-a-null-audio-engine.md), which established
that the embedded page is a separate entry point rather than the app with its chrome hidden. This
applies the same reasoning to storage.

## Context

`ADR-0050` point 5 said `/embed` and `/visualizer` "pin most of `api/`, `player/`, `db/` and
`services/` regardless of what the app's own routes do", and flagged it as the reason the web bundle
is not going anywhere. That flag was right, and `docs/REMOVING-THE-WEB-PLAYER.md` measured how right
on 2026-08-18 by building both documents with `index.html` dropped from `rollupOptions.input` and
dumping the module ids rollup emitted.

**The measurement found three independent chains from the embedded Discover surface into the Dexie
track cache**, none of them obvious from reading any single file:

```
renderEmbed → EmbedDiscover → DiscoverBrowser → useOfflineStatus → connectivityStore
            → offlineService → db/index

renderEmbed → EmbedDiscover → DiscoverBrowser → Discovery → DiscoverTrackList
            → PlaylistTrackList → useTrackContextMenu → useFavorites
            → {playlistCache, offlineService, syncService} → db/index

renderVisualizer → visualizers → MusicVideo → playerStore → queueStore
            → persistenceAdapter → persistence → db/index
```

So the page a `WKWebView` loads inside the Mac and iPhone apps carries a 430-line IndexedDB schema,
a 627-line offline download service, a 529-line playlist cache and a 405-line offline action queue —
**3,329 lines including their consumers** — none of which it can usefully do anything with.

**Why it cannot.** The embedded surface registers a null audio engine (`ADR-0017` point 2) and never
plays a note; the native app owns the queue, the playback and the reporting (`ADR-0016` point 5). A
track cached by the embedded page would be cached for a player that does not exist in that document.
Offline downloads on the Apple clients are background `URLSession` transfers under `ADR-0009` —
a separate implementation, as `docs/WEB-PARITY.md` records — so the Dexie copy is not even the same
feature.

**One of the three chains is actively wrong rather than merely useless.**
`connectivityStore.startMonitoring()` polls the server for reachability, and `useOfflineStatus` calls
it from `DiscoverBrowser` on mount. Inside a native application that already knows its own network
state and shows a native "unavailable" screen when the server is unreachable (`ADR-0016` point 7),
the embedded page is running a second, slower, contradictory reachability check whose answer nothing
native reads.

## Decision

1. **The embedded surfaces store nothing.** No IndexedDB, no Dexie, no cached track bytes, no
   offline action queue. What the page needs, it fetches; what it cannot fetch, it says it cannot.

2. **`useFavorites` becomes online-only.** It keeps its optimistic update and its React Query cache,
   and loses `playlistCache`, `offlineService` and `syncService`. A favourite toggled with no server
   is an error shown to the user, not an action queued for a sync that the native app would never
   run.

3. **`connectivityStore` loses its offline half, and `useOfflineStatus` with it.** What the embedded
   page needs is whether a request failed, which React Query already reports per query. Its
   diagnostic counters are governed by no ADR and have no reader outside the store; keeping them
   without the Dexie dependency or dropping them is an implementation call, not a decision.

4. **The following are deleted:** `db/` (430), `services/offlineService.ts` (627),
   `services/playlistCache.ts` (529), `services/syncService.ts` (405),
   `services/offlineManifestService.ts` (178), `stores/downloadStore.ts` (475),
   `hooks/useOfflineTrack.ts` (109) and `hooks/useOfflineStatus.ts` (29), along with the `dexie`
   dependency.

5. **A dependency-cruiser rule keeps them out.** `embed.tsx` and `visualizer.tsx` must not reach
   `dexie` or any storage service. `ADR-0017` point 2's guarantee is enforced by the null engine's
   *omission* of members rather than by a flag; the same shape applies here — the guard is what makes
   a future import a build failure rather than a silent 3,000-line regression inside a web view.

## Alternatives Considered

**Keep the stack and delete only what is provably unreachable.** The conservative option, and the
one the removal scope originally assumed. Rejected because "unreachable" was measured and these are
*reachable* — they are pinned by exactly the components the Mac and phone render. Keeping them means
keeping the whole chain, and the goal is that a newcomer meets no code whose purpose has to be
explained by history.

**Keep the offline stack for the admin app only, and strip it from the embed via a separate build.**
Rejected because the admin app does not use it either: after the fallback player goes, the only
consumers left are the three chains above, all of which are the embed. Splitting the build to
preserve something neither surface wants is cost without a beneficiary.

**Leave `connectivityStore` intact and remove only the Dexie import.** Tempting, since the store also
holds `ADR-0028`'s counters. Rejected as an incomplete answer: `offlineModeActive`, the forced-offline
state machine and the skip-storm circuit breaker are all reasoning about a player that will not exist
in either surface. The counters can survive without the state machine.

**Give the embedded page a smaller cache — metadata only, no audio.** Rejected because it recreates
the failure this cache has already produced once: "metadata present, audio absent" is
indistinguishable from a working cache until playback is attempted, and on this surface playback is
handed to the native app, so the page would never be the thing that discovers the gap.

## Consequences

- **Positive** — the embedded documents get materially smaller, and what they contain is what they
  do. `web/scripts/check-bundle-budgets.mjs` should show it.
- **Positive** — the reachability poll running inside a web view whose host already knows the answer
  stops.
- **Positive** — one of `db/`'s three pins is removed here; the third (`persistence` via `queueStore`)
  is cut separately, which means `db/` can actually be deleted rather than merely orphaned.
- **Tradeoff** — this edits code the Mac and iPhone Discover tabs run, and **nothing automated covers
  those surfaces**. Favourites toggling and the offline-status header must be exercised by hand on
  both, as `docs/REMOVING-THE-WEB-PLAYER.md` says of every change to this surface.
- **Tradeoff** — the web app permanently loses offline browsing. `ADR-0059` already accepted that the
  administration tool no longer opens offline; this extends that from the app shell to its data.
- **Follow-up** — the *native* client's caching is proposed in `familiar` PR #53 (played bytes are
  cached; the library is cached whole and refreshed by delta), which has been open since 2026-08-05
  and is not merged, so those ADRs do not exist in this repository yet. Nothing here constrains
  them, and this ADR should not be read as a finding that caching is a bad idea — only that the
  browser is the wrong place for it.
