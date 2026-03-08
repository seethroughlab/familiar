# Phase 3 Audit (Item 1): UI Component Size, Complexity, and Cohesion

## Scope
This artifact covers Phase 3 checklist item 1 only:
- Audit component size, complexity, and cohesion.

## Method
Static scan over `packages/frontend/src/components/**/*.tsx` (excluding `__tests__`) with these heuristics:
- Size: lines of code (LOC)
- Coupling: import count
- Local complexity proxy: hook call count (`useXxx(`)
- Cohesion proxy: multiple local component declarations in one file

## Snapshot Metrics
- Component TSX files scanned: 174
- Files over 600 LOC: 13
- Files over 400 LOC: 32
- Files over 300 LOC: 45
- Files with >20 imports: 4

Top largest files:
1. `packages/frontend/src/components/Library/browsers/TrackListBrowser.tsx` (1594 LOC, 27 imports, 65 hook calls)
2. `packages/frontend/src/components/Import/ImportModal.tsx` (1004 LOC)
3. `packages/frontend/src/components/Library/ArtistDetail.tsx` (864 LOC, 23 imports)
4. `packages/frontend/src/components/Settings/S3BackupSettings.tsx` (849 LOC)
5. `packages/frontend/src/components/Settings/AudioEffectsSettings.tsx` (836 LOC)
6. `packages/frontend/src/components/Library/browsers/EgoMusicMap/EgoMusicMap.tsx` (820 LOC)
7. `packages/frontend/src/components/Settings/DataManagement.tsx` (813 LOC)
8. `packages/frontend/src/components/Playlists/PlaylistDetail.tsx` (787 LOC, 42 hook calls)

## Findings

### 1) `TrackListBrowser.tsx` is a high-risk god module (`P1`)
Evidence:
- File registers browser and also defines row/card/local action components in the same module (`packages/frontend/src/components/Library/browsers/TrackListBrowser.tsx:47`, `:72`, `:139`, `:222`).
- Imports span API, multiple stores, hooks, browser registration, offline cache/services, and interaction policy (`:18-41`).
- Desktop virtualization and mobile card behavior are co-located in one file (`:4-11`, `:138-220`).

Impact:
- High regression amplifier for playback/selection/mobile behavior changes.
- Hard to test row intent semantics independently from virtualized list infrastructure.

### 2) `PlaylistDetail.tsx` mixes too many responsibilities (`P1`)
Evidence:
- Combines route wiring, queue control, offline cache fallback, download orchestration, discovery rendering, filtering, and drag/reorder (`packages/frontend/src/components/Playlists/PlaylistDetail.tsx:1-19`, `:153-243`, `:245-260`).
- Directly coordinates many stores/services in one render module (`:7-15`).

Impact:
- Large blast radius for offline/playback and playlist UX changes.
- Hard to isolate defects in queue behavior vs data loading vs UI rendering.

### 3) `AppShell.tsx` acts as global side-effect hub (`P1`)
Evidence:
- Initializes audio engine, scrobbling, play tracking, sync listeners, remote logging, player hydration, keyboard shortcuts, and global event listeners in one component (`packages/frontend/src/components/AppShell.tsx:80-150`).
- Also owns layout rendering and modal/panel orchestration (`:180-260`).

Impact:
- App startup behavior is tightly coupled to layout concerns.
- Increases risk of unintended side effects when editing shell UI.

### 4) Import and settings flows are monolithic and state-heavy (`P2`)
Evidence:
- `ImportModal.tsx` contains full upload/preview/edit/import lifecycle plus bulk-edit state (`packages/frontend/src/components/Import/ImportModal.tsx:34-57`, `:58-220`).
- `S3BackupSettings.tsx` combines validation, schedule config, status polling, history, restore, and notifications (`packages/frontend/src/components/Settings/S3BackupSettings.tsx:78-107`, `:137-240`).

Impact:
- Elevated maintainability risk and higher bug surface for edge cases.

### 5) Sidebar navigation concerns are consolidated in one large module (`P2`)
Evidence:
- `Sidebar.tsx` couples navigation rendering, counts queries, context menu orchestration, playlist editing modal, and smart playlist builder toggles (`packages/frontend/src/components/Sidebar/Sidebar.tsx:50-99`, `:126-240`).

Impact:
- Changes to one section (e.g., collections) can unintentionally affect unrelated sidebar capabilities.

## Decision-Ready Extraction Targets

### Batch A (low/medium risk, start now)
1. Extract `TrackListBrowser` row/card rendering into `trackList/` subcomponents with an explicit row interaction adapter boundary.
2. Extract `PlaylistDetail` data/loading/offline composition into `usePlaylistDetailData` hook; keep presentational rendering in component.
3. Extract `AppShell` startup initializers into a `useAppBootstrap()` hook.

### Batch B (medium risk)
1. Split `ImportModal` into step modules (`UploadStep`, `PreviewStep`, `ImportProgressStep`) plus reducer-driven state model.
2. Split `S3BackupSettings` into domain panels (`Credentials`, `Schedule`, `RunStatus`, `Restore`).
3. Split `Sidebar` sections into focused components with shared query/count hooks.

### Batch C (optional/higher churn)
1. Standardize complexity guardrails in CI for component size/coupling budgets.
2. Migrate visualizer files with many local component declarations to per-visualizer submodules.

## Proposed Guardrails (for Phase 5 integration)
- Warn at >450 LOC per component file.
- Warn at >20 imports in component files.
- Warn at >30 hook invocations in one file.
- Require explicit justification comment for files exceeding hard caps (>700 LOC) until refactor.

## Reproducibility Commands
Run from repo root:

```bash
# Size distribution
rg --files packages/frontend/src/components -g '*.tsx' | rg -v '__tests__' | xargs wc -l | sort -nr

# Top files by LOC/imports/hooks
for f in $(rg --files packages/frontend/src/components -g '*.tsx' | rg -v '__tests__'); do
  loc=$(wc -l < "$f" | tr -d ' ')
  imports=$(grep -E '^import ' "$f" | wc -l | tr -d ' ')
  hooks=$(grep -Eo 'use[A-Z][A-Za-z0-9_]*\\(' "$f" | wc -l | tr -d ' ')
  printf '%s\t%s\t%s\t%s\n' "$loc" "$imports" "$hooks" "$f"
done | sort -nr | head -n 25

# Files above key thresholds
for f in $(rg --files packages/frontend/src/components -g '*.tsx' | rg -v '__tests__'); do
  i=$(grep -E '^import ' "$f" | wc -l | tr -d ' ')
  [ "$i" -gt 20 ] && echo "$i $f"
done | sort -nr
```
