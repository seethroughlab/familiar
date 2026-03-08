# Phase 3 Audit (Item 3): Reusable Feature-Module Extraction Targets

## Scope
This artifact covers Phase 3 checklist item 3 only:
- Propose extraction targets for reusable feature modules.

## Inputs
- Phase 3 item 1 findings: [frontend-ui-component-audit-phase3-item1.md](/Users/jeff/Developer/familiar/docs/frontend-ui-component-audit-phase3-item1.md)
- Phase 3 item 2 findings: [frontend-ui-state-propdrilling-audit-phase3-item2.md](/Users/jeff/Developer/familiar/docs/frontend-ui-state-propdrilling-audit-phase3-item2.md)

## Priority Targets

### Target 1: `playlist-detail-controller` module (`P1`)
Problem:
- Playlist-like detail pages repeat search/filter/play-toggle/queue-start orchestration.

Source files:
- `packages/frontend/src/components/Playlists/FavoritesDetail.tsx`
- `packages/frontend/src/components/Playlists/DownloadsDetail.tsx`
- `packages/frontend/src/components/Playlists/EphemeralPlaylistDetail.tsx`
- `packages/frontend/src/components/Playlists/PlaylistDetail.tsx`
- `packages/frontend/src/components/SmartPlaylists/SmartPlaylistDetail.tsx`

Proposed extraction:
- `packages/frontend/src/features/playlistDetail/controller/usePlaylistDetailController.ts`
- `packages/frontend/src/features/playlistDetail/types.ts`

Suggested contract:
- Inputs: `items`, `toTrack`, `queueSource`, `initialSearch`
- Outputs: `search`, `setSearch`, `filteredItems`, `playAt(index, items?)`

Expected payoff:
- One playback semantics implementation for five surfaces.
- Reduces repeat regression risk for row tap/click behavior.

### Target 2: `offline-track-state` module (`P1`)
Problem:
- Offline ID hydration + derived counters are duplicated and drift-prone.

Source files:
- `packages/frontend/src/components/Playlists/PlaylistDetail.tsx`
- `packages/frontend/src/components/SmartPlaylists/SmartPlaylistDetail.tsx`
- `packages/frontend/src/components/Playlists/FavoritesDetail.tsx`
- `packages/frontend/src/components/Library/ArtistDetail.tsx`
- `packages/frontend/src/components/Library/browsers/AlbumGrid.tsx`

Proposed extraction:
- `packages/frontend/src/features/offline/useOfflineTrackState.ts`

Suggested contract:
- Inputs: `trackIds`, `downloadJobStatus?`
- Outputs: `offlineTrackIds`, `offlineCount`, `allOffline`, `refreshOfflineIds`

Expected payoff:
- Centralizes offline hydration behavior and recovery points.
- Makes offline bugs easier to patch once.

### Target 3: `track-context-actions` module (`P1`)
Problem:
- PlayerBar/FullPlayer/QueueView repeat context menu action wiring.

Source files:
- `packages/frontend/src/components/Player/PlayerBar.tsx`
- `packages/frontend/src/components/FullPlayer/FullPlayer.tsx`
- `packages/frontend/src/components/Queue/QueueView.tsx`

Proposed extraction:
- `packages/frontend/src/features/playerContext/usePlayerTrackContextMenu.tsx`

Suggested contract:
- Inputs: `track`, `beforeNavigate?`, `onPlay?`, `onQueue?`
- Outputs: `openContextMenu(e, track)`, `contextMenuElement`

Expected payoff:
- Keeps track menu behavior consistent across three player surfaces.
- Eliminates repeated action callback wiring blocks.

### Target 4: `library-browser-controller` module (`P1`)
Problem:
- `BrowserProps` is high-arity and `LibraryView` is a callback forwarding hub.

Source files:
- `packages/frontend/src/components/Library/types.ts`
- `packages/frontend/src/components/Library/LibraryView.tsx`
- Browsers under `packages/frontend/src/components/Library/browsers/`

Proposed extraction:
- `packages/frontend/src/features/libraryBrowser/useLibraryBrowserController.ts`
- `packages/frontend/src/features/libraryBrowser/contracts.ts`

Suggested contract split:
- `navigation`: artist/album/year/genre/mood handlers
- `selection`: selected IDs + toggles
- `playback`: play/queue/edit handlers
- `filters`: current filters + update method

Expected payoff:
- Reduces prop-drilling churn across 9 registered browsers.
- Makes browser contracts explicit and easier to evolve.

### Target 5: `playlist-search-ui` consolidation (`P2`)
Problem:
- Search UI is duplicated while `TrackSearchInput` exists but unused.

Source files:
- `packages/frontend/src/components/Playlists/TrackSearchInput.tsx`
- Playlist-like detail pages listed above.

Proposed extraction:
- Keep `TrackSearchInput` as shared primitive and migrate all five detail views to it.
- Optionally move to `packages/frontend/src/components/shared/TrackSearchInput.tsx`.

Expected payoff:
- Immediate consistency win with low risk.
- Removes repeated markup + clear-button behavior drift.

### Target 6: `playlist-track-list` composition split (`P2`)
Problem:
- `PlaylistTrackList` blends data shaping, selection, context menu, sorting, and rendering.

Source file:
- `packages/frontend/src/components/shared/PlaylistTrackList.tsx`

Proposed extraction:
- `packages/frontend/src/components/shared/playlistTrackList/PlaylistTrackTable.tsx`
- `packages/frontend/src/components/shared/playlistTrackList/usePlaylistTrackSelection.ts`
- `packages/frontend/src/components/shared/playlistTrackList/usePlaylistTrackMenu.tsx`

Expected payoff:
- Cleaner composition and narrower test surfaces.
- Better reuse for non-playlist list screens.

## Batch Plan

### Batch A (immediate, low/medium risk)
1. Migrate all playlist-like pages to shared `TrackSearchInput`.
2. Add `useOfflineTrackState` and adopt in favorites/playlist/smart-playlist.
3. Add `usePlaylistDetailController` and adopt in favorites/downloads/ephemeral.

### Batch B (medium risk)
1. Add `usePlayerTrackContextMenu` and migrate PlayerBar/FullPlayer/QueueView.
2. Introduce `useLibraryBrowserController` and thin `LibraryView`.

### Batch C (higher churn)
1. Decompose `PlaylistTrackList` into table/controller/menu pieces.
2. Transition browser implementations to narrowed contracts from `contracts.ts`.

## Acceptance Criteria for Extraction Work
- No behavior change in playback/queue/selection semantics for migrated screens.
- Snapshot/manual parity checks pass for:
  - favorites/downloads/playlist/smart-playlist/ephemeral detail screens
  - player bar + full player + queue context menu actions
- `LibraryView` no longer directly forwards placeholder playback callbacks.
- New modules include focused unit tests:
  - `usePlaylistDetailController`
  - `useOfflineTrackState`
  - `usePlayerTrackContextMenu`

## Reproducibility Commands
Run from repo root:

```bash
# PlaylistTrackList consumers
rg -n "<PlaylistTrackList" packages/frontend/src/components -g '*.tsx' | sort

# BrowserProps implementers
rg -n "}: BrowserProps\\)|\\(\\{[^}]*\\}: BrowserProps\\)" \
  packages/frontend/src/components/Library/browsers -g '*.tsx'

# Duplicated search/offline/context menu state patterns
rg -l "const \\[searchFilter, setSearchFilter\\]" packages/frontend/src/components -g '*.tsx' | sort
rg -l "const \\[offlineTrackIds, setOfflineTrackIds\\]" packages/frontend/src/components -g '*.tsx' | sort
rg -l "const \\[contextMenu, setContextMenu\\]" packages/frontend/src/components -g '*.tsx' | sort
```
