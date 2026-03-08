# Phase 6 Audit (Item 2): Rerender Hotspots and Virtualization Consistency

## Scope
This artifact covers Phase 6 checklist item 2 only:
- Identify rerender hotspots and list virtualization inconsistencies.

## Evidence Sources
- Virtualized browsers:
  - [TrackListBrowser.tsx](/Users/jeff/Developer/familiar/packages/frontend/src/components/Library/browsers/TrackListBrowser.tsx)
  - [ArtistList.tsx](/Users/jeff/Developer/familiar/packages/frontend/src/components/Library/browsers/ArtistList.tsx)
  - [AlbumGrid.tsx](/Users/jeff/Developer/familiar/packages/frontend/src/components/Library/browsers/AlbumGrid.tsx)
- Non-virtualized large lists:
  - [PlaylistTrackList.tsx](/Users/jeff/Developer/familiar/packages/frontend/src/components/shared/PlaylistTrackList.tsx)
  - [QueueView.tsx](/Users/jeff/Developer/familiar/packages/frontend/src/components/Queue/QueueView.tsx)
  - [ArtistDetail.tsx](/Users/jeff/Developer/familiar/packages/frontend/src/components/Library/ArtistDetail.tsx)
  - [AlbumDetail.tsx](/Users/jeff/Developer/familiar/packages/frontend/src/components/Library/AlbumDetail.tsx)
- Shell/remount behavior:
  - [AppShell.tsx](/Users/jeff/Developer/familiar/packages/frontend/src/components/AppShell.tsx)

## Surface Matrix (Virtualization Consistency)

| Surface | Desktop strategy | Mobile strategy | Consistency risk |
|---|---|---|---|
| Library Tracks | Virtualized (`useVirtualizer`) | Infinite append list (non-virtualized) | P1 |
| Library Artists | Virtualized row grid | Infinite append grid (non-virtualized) | P1 |
| Library Albums | Virtualized row grid | Infinite append grid (non-virtualized) | P1 |
| Playlist/Favorites/Downloads/Smart/Ephemeral details | Non-virtualized full map render | Non-virtualized full map render | P1 |
| Queue panel | Non-virtualized full map render | Non-virtualized full map render | P1 |
| Artist detail tracks | Non-virtualized map render | Non-virtualized map render | P2 |
| Album detail tracks | Non-virtualized map render | Non-virtualized map render | P2 |

## Rerender Hotspots

### P1: Full-store subscription in `AlbumDetail` causes broad rerenders
- `usePlayerStore()` is consumed without selector, so any player store mutation can rerender the entire detail page.
- Evidence: [AlbumDetail.tsx:180](/Users/jeff/Developer/familiar/packages/frontend/src/components/Library/AlbumDetail.tsx:180).

### P1: Playlist/shared detail rows render entire lists without virtualization
- `PlaylistTrackList` maps every sorted item for both mobile and desktop row trees.
- This component is reused by Favorites/Downloads/Playlist/Ephemeral/Smart playlists.
- Evidence: [PlaylistTrackList.tsx:327](/Users/jeff/Developer/familiar/packages/frontend/src/components/shared/PlaylistTrackList.tsx:327), usage in [PlaylistDetail.tsx:756](/Users/jeff/Developer/familiar/packages/frontend/src/components/Playlists/PlaylistDetail.tsx:756), [FavoritesDetail.tsx:291](/Users/jeff/Developer/familiar/packages/frontend/src/components/Playlists/FavoritesDetail.tsx:291), [DownloadsDetail.tsx:240](/Users/jeff/Developer/familiar/packages/frontend/src/components/Playlists/DownloadsDetail.tsx:240), [SmartPlaylistDetail.tsx:518](/Users/jeff/Developer/familiar/packages/frontend/src/components/SmartPlaylists/SmartPlaylistDetail.tsx:518).

### P1: Queue list renders full queue and updates row-by-row on queue mutations
- Queue view maps full `displayTracks` and rerenders list container on queue, shuffle, index changes.
- Evidence: [QueueView.tsx:359](/Users/jeff/Developer/familiar/packages/frontend/src/components/Queue/QueueView.tsx:359).

### P1: Mobile library views accumulate unbounded DOM nodes during infinite loading
- Mobile tracks/artists/albums paths use append-based rendering rather than windowing.
- Evidence: [TrackListBrowser.tsx:1360](/Users/jeff/Developer/familiar/packages/frontend/src/components/Library/browsers/TrackListBrowser.tsx:1360), [ArtistList.tsx:326](/Users/jeff/Developer/familiar/packages/frontend/src/components/Library/browsers/ArtistList.tsx:326), [AlbumGrid.tsx:358](/Users/jeff/Developer/familiar/packages/frontend/src/components/Library/browsers/AlbumGrid.tsx:358).

### P2: Expensive derived arrays recomputed in hot path of track browser
- Track browser maps loaded tracks to visible-track context and artwork prefetch payload on change.
- Both operations scale with loaded item count and run in effects.
- Evidence: [TrackListBrowser.tsx:1042](/Users/jeff/Developer/familiar/packages/frontend/src/components/Library/browsers/TrackListBrowser.tsx:1042), [TrackListBrowser.tsx:1066](/Users/jeff/Developer/familiar/packages/frontend/src/components/Library/browsers/TrackListBrowser.tsx:1066).

### P2: Route outlet remount by pathname invalidates route-local UI state/scroll on navigation
- `Outlet` keyed by pathname forces route subtree remount on path changes.
- This can reset virtualizer scroll caches and local state when switching between library surfaces.
- Evidence: [AppShell.tsx:194](/Users/jeff/Developer/familiar/packages/frontend/src/components/AppShell.tsx:194).

### P2: Artist/Album detail track sections are fully mapped lists
- `artist.tracks.map` and `album.tracks.map` are rendered directly.
- Evidence: [ArtistDetail.tsx:639](/Users/jeff/Developer/familiar/packages/frontend/src/components/Library/ArtistDetail.tsx:639), [AlbumDetail.tsx:480](/Users/jeff/Developer/familiar/packages/frontend/src/components/Library/AlbumDetail.tsx:480).

## Prioritized Remediation Batches

### Batch A (Fast, low risk)
1. Replace full-store selector in `AlbumDetail` with field selectors (`currentTrack`, `isPlaying`, `setQueue`, `setIsPlaying`).
2. Introduce `React.memo` row wrappers for `PlaylistTrackList` desktop/mobile row blocks.
3. Gate expensive track-browser effect work (visibleTracks/artwork prefetch) behind changed-length/hash guards.

### Batch B (Medium)
1. Add virtualization to `PlaylistTrackList` desktop path (react-virtual row list).
2. Add virtualization to `QueueView` list with fixed row estimate and drag integration.
3. Add windowing for mobile library lists once item count exceeds threshold.

### Batch C (Higher effort)
1. Unify list virtualization policy across all large track surfaces (library + playlist + queue + detail).
2. Add perf canary counters for rendered row count and mount churn per route.
3. Revisit `Outlet key={location.pathname}` behavior and preserve route-local scroll where expected.

## Reproducibility Commands
Run from repo root:

```bash
# Find virtualization usage
rg -n "useVirtualizer|IntersectionObserver|data-list-index" packages/frontend/src/components

# Find non-selector store subscriptions
rg -n "usePlayerStore\\(\\)" packages/frontend/src -g "*.tsx" -g "*.ts"

# Find large map-rendered list surfaces
rg -n "\\.map\\(" packages/frontend/src/components/shared/PlaylistTrackList.tsx \
  packages/frontend/src/components/Queue/QueueView.tsx \
  packages/frontend/src/components/Library/ArtistDetail.tsx \
  packages/frontend/src/components/Library/AlbumDetail.tsx
```

## Completion Note
Phase 6 item 2 is complete when this artifact is linked in the roadmap and the checklist item is checked.
