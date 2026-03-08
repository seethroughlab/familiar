# Phase 3 Audit (Item 2): Duplicated UI State Logic and Prop-Drilling Hotspots

## Scope
This artifact covers Phase 3 checklist item 2 only:
- Identify duplicated UI state logic and prop-drilling hotspots.

## Method
- Static scan across `packages/frontend/src/components/**/*.tsx`.
- Focused on repeated local state patterns (`searchFilter`, `offlineTrackIds`, `contextMenu`) and repeated callback wiring.
- Traced high-arity component contracts (`BrowserProps`, `PlaylistTrackListProps`) and parent call sites.

## Snapshot Signals
- Files with duplicated `searchFilter` state pattern: 5
  - `Playlists/DownloadsDetail.tsx`
  - `Playlists/EphemeralPlaylistDetail.tsx`
  - `Playlists/FavoritesDetail.tsx`
  - `Playlists/PlaylistDetail.tsx`
  - `SmartPlaylists/SmartPlaylistDetail.tsx`
- Files with duplicated `offlineTrackIds` hydration pattern: 5
  - `Library/ArtistDetail.tsx`
  - `Library/browsers/AlbumGrid.tsx`
  - `Playlists/FavoritesDetail.tsx`
  - `Playlists/PlaylistDetail.tsx`
  - `SmartPlaylists/SmartPlaylistDetail.tsx`
- Files with duplicated `contextMenu` state + `TrackContextMenu` action wiring: 3
  - `Player/PlayerBar.tsx`
  - `FullPlayer/FullPlayer.tsx`
  - `Queue/QueueView.tsx`

## Findings

### 1) Playlist-style pages duplicate controller logic (`P1`)
Evidence:
- Repeated local search state and client filter blocks:
  - `FavoritesDetail` (`packages/frontend/src/components/Playlists/FavoritesDetail.tsx:33`, `:113-122`)
  - `DownloadsDetail` (`packages/frontend/src/components/Playlists/DownloadsDetail.tsx:30`, `:55-63`)
  - `EphemeralPlaylistDetail` (`packages/frontend/src/components/Playlists/EphemeralPlaylistDetail.tsx:70`, `:73-81`)
  - `PlaylistDetail` (`packages/frontend/src/components/Playlists/PlaylistDetail.tsx:115`, `:246-261`)
  - `SmartPlaylistDetail` (`packages/frontend/src/components/SmartPlaylists/SmartPlaylistDetail.tsx:97`, `:191-205`)
- Repeated play/toggle queue semantics:
  - `PlaylistDetail` (`:269-290`)
  - `SmartPlaylistDetail` (`:289-303`)
  - `DownloadsDetail` (`:65-94`)
  - `EphemeralPlaylistDetail` (`:83-97`)
  - `FavoritesDetail` (`:124-136`)

Impact:
- Behavior drift risk (play-toggle, queue source, search semantics) across near-identical screens.
- Fixes require touching many files for one UX behavior.

### 2) Offline hydration/download state is copied across views (`P1`)
Evidence:
- Same offline ID hydration + refresh-on-download-complete pattern repeated:
  - `PlaylistDetail` (`packages/frontend/src/components/Playlists/PlaylistDetail.tsx:204-210`, `:222-228`)
  - `SmartPlaylistDetail` (`packages/frontend/src/components/SmartPlaylists/SmartPlaylistDetail.tsx:225-231`, `:234-241`)
  - `FavoritesDetail` (`packages/frontend/src/components/Playlists/FavoritesDetail.tsx:76-82`, `:85-91`)
- Same derived UI state repeated (`allTracksOffline`, `offlineCount`):
  - `FavoritesDetail` (`:94-95`)
  - `PlaylistDetail` (`:233-234`)
  - `SmartPlaylistDetail` (`:286-287`)

Impact:
- Offline fixes/regressions are likely to land inconsistently across detail surfaces.

### 3) Track context-menu orchestration duplicated in three player surfaces (`P1`)
Evidence:
- Repeated local `contextMenu` state and open/close handlers:
  - `PlayerBar` (`packages/frontend/src/components/Player/PlayerBar.tsx:92-107`)
  - `FullPlayer` (`packages/frontend/src/components/FullPlayer/FullPlayer.tsx:52`, `:87-100`)
  - `QueueView` (`packages/frontend/src/components/Queue/QueueView.tsx:43`)
- Near-identical `TrackContextMenu` action wiring:
  - `PlayerBar` (`packages/frontend/src/components/Player/PlayerBar.tsx:418-468`)
  - `FullPlayer` (`packages/frontend/src/components/FullPlayer/FullPlayer.tsx:440-493`)
  - `QueueView` (`packages/frontend/src/components/Queue/QueueView.tsx:448-493`)

Impact:
- Frequent regression vector for “player controls/context menu actions differ by surface.”

### 4) Library browser contract is a prop-drilling hotspot (`P1`)
Evidence:
- `BrowserProps` is a broad contract bundling data, selection, navigation, playback, editing, filters, and offline flags (`packages/frontend/src/components/Library/types.ts:73-108`).
- `LibraryView` forwards many callbacks/props at once, including placeholder handlers (`packages/frontend/src/components/Library/LibraryView.tsx:181-191`, `:288-311`).

Impact:
- Browser implementations couple to a large shared API surface.
- Changes in one domain (e.g. playback callbacks) force churn in unrelated browsers.

### 5) `PlaylistTrackList` contract has high arity and mixed concerns (`P2`)
Evidence:
- `PlaylistTrackListProps` includes sorting, selection, context menu hooks, drag-reorder, render props, empty states, and queue context in one interface (`packages/frontend/src/components/shared/PlaylistTrackList.tsx:38-99`).
- Parent views pass many customization callbacks to shape behavior and UI (`FavoritesDetail` `:291-304`, `DownloadsDetail` `:240-263`).

Impact:
- Powerful but hard to reason about; behavior changes can create hidden cross-view regressions.

### 6) Search input UI is duplicated despite existing reusable component (`P2`)
Evidence:
- Shared component exists: `packages/frontend/src/components/Playlists/TrackSearchInput.tsx:1-30`.
- It is currently unused (only declaration file has references).
- Manual search input markup is duplicated in detail pages:
  - `FavoritesDetail` (`:270-288`)
  - `DownloadsDetail` (`:219-237`)
  - `EphemeralPlaylistDetail` (`:182-200`)
  - `PlaylistDetail` (`:736-753`)
  - `SmartPlaylistDetail` (`:498-515`)

Impact:
- Styling/behavior consistency bugs (clear button, placeholder, spacing) likely over time.

## Decision-Ready Remediation Batches

### Batch A (low/medium risk, immediate)
1. Create `usePlaylistLikeController` hook for shared `searchFilter` + play/toggle + queue-start semantics used by favorites/downloads/ephemeral/playlist/smart-playlist detail views.
2. Create `useOfflineTrackHydration` hook for `offlineTrackIds` load/refresh and derived counters.
3. Replace duplicated search markup with `TrackSearchInput` in all playlist-like detail pages.

### Batch B (medium risk)
1. Extract `useTrackContextMenuActions` for shared action handlers used by `PlayerBar`, `FullPlayer`, and `QueueView`.
2. Split `BrowserProps` into narrower grouped contracts (`navigation`, `selection`, `playback`, `filters`) and pass a single controller object.

### Batch C (higher churn)
1. Split `PlaylistTrackList` into composable primitives:
   - `PlaylistTrackTable`
   - `PlaylistSelectionController`
   - `PlaylistTrackContextMenuBridge`
2. Move offline filtering outside list primitive so parent controllers own data invariants.

## Reproducibility Commands
Run from repo root:

```bash
# Duplicated local state patterns
rg -l "const \\[searchFilter, setSearchFilter\\]" packages/frontend/src/components -g '*.tsx' | sort
rg -l "const \\[offlineTrackIds, setOfflineTrackIds\\]" packages/frontend/src/components -g '*.tsx' | sort
rg -l "const \\[contextMenu, setContextMenu\\]" packages/frontend/src/components -g '*.tsx' | sort

# Repeated play/toggle queue behavior
rg -n "currentTrack\\?\\.id === clickedTrack\\.id|setQueueByTrackId\\(|setIsPlaying\\(!isPlaying\\)" \
  packages/frontend/src/components/Playlists packages/frontend/src/components/SmartPlaylists -g '*.tsx'

# TrackSearchInput usage check
rg -n "TrackSearchInput" packages/frontend/src/components -g '*.tsx'
```
