# Phase 2 Audit: API Client Boundaries & Query-Layer Consistency

## Scope
This audit covers the first Phase 2 checklist item:
- Audit API client boundaries and query-layer consistency.

## Findings

### 1) API boundary is partially bypassed by direct `fetch` in UI components (`P1`)
Evidence:
- 21 direct `fetch(...)` call sites in `packages/frontend/src/components/**`.
- Examples:
  - `packages/frontend/src/components/Settings/MissingTracksPanel.tsx`
  - `packages/frontend/src/components/Import/ImportModal.tsx`
  - `packages/frontend/src/components/Chat/ChatPanel.tsx`
  - `packages/frontend/src/components/Settings/MissingTracksPanel.tsx` mixes endpoint paths and response handling inline.

Impact:
- Response/error handling diverges by component.
- Harder to enforce consistent auth/profile-header/retry semantics.
- Increases coupling between UI and transport details.

Recommendation:
- Move component-level endpoint calls behind `packages/frontend/src/api/*` modules.
- Keep components/higher-level hooks consuming typed API functions only.

### 2) Query keys are string-literal and distributed (no shared key factory) (`P1`)
Evidence:
- 72 React Query call sites (`useQuery`, `useInfiniteQuery`, `useMutation`) across components/hooks.
- No shared query-key factory module detected.
- Inconsistent key variants for same domain:
  - `playlists` (`['playlists']`, `['playlists', 'ai']`)
  - `tracks` (multiple variants including base + filtered/object forms)
  - `album` / `playlist` / `track-metadata` variants

Impact:
- Higher risk of partial invalidation bugs and accidental over-invalidation.
- Harder to refactor cache behavior safely.

Recommendation:
- Introduce `queryKeys` factory (e.g. `queryKeys.playlists.all()`, `queryKeys.playlists.ai()`, `queryKeys.playlist.detail(id)`).
- Replace literal arrays incrementally, starting with playlist/track domains.

### 3) Invalidation strategy is broad and repeated (`P2`)
Evidence:
- Many invalidations target broad keys (`['playlists']`, `['tracks']`, `['proposed-changes']`) from many modules.
- Examples:
  - `packages/frontend/src/components/Sidebar/PlaylistContextMenu.tsx`
  - `packages/frontend/src/components/TrackEdit/TrackEditModal.tsx`
  - `packages/frontend/src/components/Settings/ProposedChangesPanel.tsx`

Impact:
- Excess refetching and cache churn.
- Mutation side effects are difficult to reason about globally.

Recommendation:
- Pair query-key factory with domain mutation helpers that invalidate precise keys.
- Standardize invalidation pattern per domain.

### 4) Service-layer transport is split between axios and fetch (`P2`)
Evidence:
- Shared axios client in `packages/frontend/src/api/base.ts`.
- Parallel direct `fetch` usage in services:
  - `packages/frontend/src/services/profileService.ts`
  - `packages/frontend/src/services/offlineService.ts`
  - `packages/frontend/src/services/syncService.ts`
  - `packages/frontend/src/services/libraryCache.ts`

Impact:
- Inconsistent interceptor/error/profile-header behavior.
- Different timeout/retry semantics by caller.

Recommendation:
- Define explicit policy:
  - Use axios client for authenticated app API calls by default.
  - Allow direct `fetch` only for documented exceptions (streaming, binary, service-worker/offline cases).
- Document exceptions in API boundary rules.

## Decision-Ready Next Actions
1. Create `packages/frontend/src/api/queryKeys.ts` and migrate playlist + track domains first.
2. Add API wrappers for missing-tracks/import/chat status endpoints currently called directly from components.
3. Create lint/check rule: no direct `fetch(getApiUrl(...))` in `components/**` (allowlist approved exceptions).
4. Add mutation helper utilities per domain to centralize invalidate/refetch behavior.

## Reproducibility Commands
Run from repo root:

```bash
# Direct fetch in components/services
rg -n "fetch\\(" packages/frontend/src/components packages/frontend/src/services -g"*.ts" -g"*.tsx"

# React Query usage footprint
rg -n "useQuery\\(|useInfiniteQuery\\(|useMutation\\(" packages/frontend/src/components packages/frontend/src/hooks -g"*.ts" -g"*.tsx"

# Query invalidation hotspots
rg -n "invalidateQueries\\(" packages/frontend/src -g"*.ts" -g"*.tsx"
```
