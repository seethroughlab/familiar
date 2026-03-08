# Phase 6 Audit (Item 1): Bundle Composition and Code-Splitting Strategy

## Scope
This artifact covers Phase 6 checklist item 1 only:
- Audit bundle composition and code-splitting strategy.

## Evidence Sources
- Build config:
  - [packages/web/vite.config.ts](/Users/jeff/Developer/familiar/packages/web/vite.config.ts)
  - [packages/ios/vite.config.ts](/Users/jeff/Developer/familiar/packages/ios/vite.config.ts)
- App entry/routing:
  - [packages/frontend/src/App.tsx](/Users/jeff/Developer/familiar/packages/frontend/src/App.tsx)
  - [packages/frontend/src/components/AppShell.tsx](/Users/jeff/Developer/familiar/packages/frontend/src/components/AppShell.tsx)
  - [packages/frontend/src/components/Library/LibraryView.tsx](/Users/jeff/Developer/familiar/packages/frontend/src/components/Library/LibraryView.tsx)
  - [packages/frontend/src/components/Library/browsers/index.ts](/Users/jeff/Developer/familiar/packages/frontend/src/components/Library/browsers/index.ts)
  - [packages/frontend/src/components/Visualizer/AudioVisualizer.tsx](/Users/jeff/Developer/familiar/packages/frontend/src/components/Visualizer/AudioVisualizer.tsx)
  - [packages/frontend/src/components/Visualizer/visualizers/index.ts](/Users/jeff/Developer/familiar/packages/frontend/src/components/Visualizer/visualizers/index.ts)
- Measured production build output:
  - `pnpm --filter @familiar/web run build`
  - `npx vite build --manifest --sourcemap`

## Measured Bundle Snapshot (Web Build)

Largest JS chunks from `packages/web/dist/assets`:

| Chunk | Size (minified) | Gzip |
|---|---:|---:|
| `index-CLFDuKsM.js` (entry) | 1,657.34 kB | 457.06 kB |
| `index-DZXS52qL.js` (FullPlayer dynamic) | 223.11 kB | 73.21 kB |
| `index-BzsA8nQl.js` (Settings dynamic) | 140.22 kB | 28.90 kB |
| `vendor-audio-CXPx7eTM.js` | 95.01 kB | 32.02 kB |

Build warning is active:
- chunks exceed `chunkSizeWarningLimit: 600` with explicit Vite warning on oversized entry chunk.

## Composition Findings

### P1: Initial entry chunk is oversized
- Entry chunk remains ~1.66 MB minified despite manual vendor chunks.
- This is the primary startup/download parse risk.

### P1: Library browser registration eagerly imports heavy browser implementations
- `LibraryView.tsx` imports `./browsers`.
- `browsers/index.ts` statically imports all browsers, including 3D-capable explorers.
- Sourcemap evidence shows the entry chunk includes:
  - `components/Library/browsers/UMAPExplorer/UMAPExplorer.tsx`
  - `components/Library/browsers/EgoMusicMap/EgoMusicMap.tsx`
  - `@react-three/fiber` / `@react-three/drei` modules
- Result: users loading normal library routes still pay for advanced map/explorer code up front.

### P2: Some dynamic imports are neutralized by static imports
- Vite reports dynamic-import ineffectiveness for:
  - `offlineService.ts`
  - `toastStore.ts`
- Those modules are both dynamic and broadly static-imported, so they stay in base chunks.

### P2: FullPlayer split is working, but visualizers are bundled together
- FullPlayer is lazy-loaded (good).
- Its chunk contains all visualizers/effects (`AudioVisualizer` imports `./visualizers` registry eagerly).
- This creates one large deferred chunk instead of per-visualizer granularity.

### P3: Manual chunk strategy is mostly vendor-based, not feature-based
- Current chunking separates libs (`react`, query, dexie, icons) but not large feature domains.
- Feature boundaries (library maps, discovery, proposed-changes, visualizer families) are not used for split policy.

## Decision-Complete Split Strategy

### Batch A (Immediate, low risk)
1. Convert library browser registry to lazy browser loaders by route/browser ID.
2. Keep current UX, but ensure 3D browsers (`umap-explorer`, `ego-music-map`) are not in initial entry.
3. Add a CI bundle report step that records top 10 chunks and fails if entry chunk grows above agreed threshold.

### Batch B (Near term)
1. Move `AudioVisualizer` registration to per-visualizer lazy loading:
   - load selected visualizer module only.
2. Feature-split discovery/proposed-changes browser modules if they are not default route-critical.
3. Remove ineffective dynamic imports where static import is already required (or invert to truly lazy usage).

### Batch C (Higher effort)
1. Adopt explicit feature manual chunks in Vite (maps/explorer/visualizers/settings/admin) once lazy boundaries are stable.
2. Add performance budget checks:
   - max initial JS (gzip)
   - max entry parse-size growth per PR.
3. Extend same budget policy to Capacitor build artifacts for parity.

## Recommended Minimum Budgets (Initial Proposal)
- `P0` startup critical: entry chunk gzip <= `300 kB` target, hard ceiling `350 kB`.
- `P1` lazy feature chunk gzip <= `120 kB` target, hard ceiling `180 kB`.
- Reject PRs that increase entry chunk gzip by > `30 kB` without explicit perf waiver.

## Reproducibility Commands
Run from repo root:

```bash
# Build and print chunk table
pnpm --filter @familiar/web run build

# Build with manifest/sourcemaps for composition tracing
cd packages/web && npx vite build --manifest --sourcemap

# List largest generated JS assets
cd dist/assets && ls -l *.js | awk '{print $5, $9}' | sort -nr | head -n 20

# Verify eager browser registration
sed -n '1,220p' packages/frontend/src/components/Library/LibraryView.tsx
sed -n '1,220p' packages/frontend/src/components/Library/browsers/index.ts
```

## Completion Note
Phase 6 item 1 is complete when this artifact is linked in the roadmap and the Phase 6 checklist item 1 is checked.
