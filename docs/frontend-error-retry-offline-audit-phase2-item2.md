# Phase 2 Audit: Error Shape Handling + Retry/Offline Consistency

## Scope
This document covers Phase 2 checklist item 2:
- Verify error-shape handling and retry/offline behavior consistency.

## Findings

### 1) Error-shape handling is fragmented across axios and fetch paths (`P1`)
Evidence:
- Axios interceptor + tracker path exists in `packages/frontend/src/api/base.ts` (response interceptor).
- UI-level message extraction assumes axios-like shapes in `packages/frontend/src/utils/errorNotifications.ts`.
- Multiple fetch-based services throw plain `Error(statusText)` and bypass typed API error handling:
  - `packages/frontend/src/services/profileService.ts`
  - `packages/frontend/src/services/syncService.ts`
  - `packages/frontend/src/services/libraryCache.ts`
- Component-level manual parsing duplicates shape logic (`axiosError.response?.data?.detail`) in `packages/frontend/src/components/Library/browsers/EgoMusicMap/EgoMusicMap.tsx`.

Impact:
- Same backend failure can render different user messages depending on call path.
- Error-category attribution (network/auth/server/validation) is inconsistent.
- Retry behavior cannot be policy-driven if errors are not normalized first.

Recommendation:
- Introduce a shared `AppError` normalizer (`category`, `status`, `message`, `isRetryable`, `isOfflineRelated`, `source`).
- Normalize both axios and fetch failures in one place before they reach UI/hooks.
- Remove per-component ad hoc parsing of `error.response`.

### 2) Retry policy is inconsistent by surface (`P1`)
Evidence:
- Global QueryClient default retry is `1` in `packages/frontend/src/App.tsx`.
- Many domain queries override to `retry: isOffline ? false : 3` (examples: `useFavorites`, `Sidebar`, `MobileMoreSheet`, `PlaylistDetail`, `SmartPlaylistDetail`, `SmartPlaylistList`).
- Some queries still use fixed `retry: 1` even when other domain queries for same screen use `3` (`PlaylistDetail` recommendations query).
- `useOfflineQuery` defines an offline-aware retry policy but is currently not consumed by app code (`packages/frontend/src/hooks/useOfflineQuery.ts`, only self-reference found).

Impact:
- Different views have materially different resilience and latency under the same network conditions.
- Tuning retries is hard because behavior is scattered across components.

Recommendation:
- Centralize query retry/offline policy in one utility (e.g. `createQueryOptions({ domain, offlineModeActive })`).
- Keep per-query overrides explicit and rare (documented exceptions only).
- Either adopt `useOfflineQuery` in priority offline screens or remove it to avoid dead policy code.

### 3) Offline source-of-truth is mixed (`connectivityStore` vs `navigator.onLine`) (`P1`)
Evidence:
- Authoritative offline state now comes from reachability-aware store in `packages/frontend/src/stores/connectivityStore.ts` and `packages/frontend/src/hooks/useOfflineStatus.ts`.
- `packages/frontend/src/services/syncService.ts` still relies on `window` `online` events and `navigator.onLine` startup check.
- `packages/frontend/src/services/profileService.ts` background validation also gates on `navigator.onLine`.

Impact:
- No-service scenarios can be misclassified as online in services that bypass connectivity store.
- Recovery behavior diverges: player path uses forced offline/reachability probes, while profile/sync paths use browser online signals.

Recommendation:
- Migrate service listeners to consume `connectivityStore` state transitions (`offlineModeActive`, `reachabilityState`, `lastRecoveryAt`).
- Treat `navigator.onLine` as a low-signal input only, never as policy authority.

### 4) API error observability does not cover fetch traffic (`P2`)
Evidence:
- `apiErrorTracker` integration is wired through axios interceptor (`packages/frontend/src/api/base.ts`).
- Fetch-heavy services/components do not report to tracker (`profileService`, `syncService`, `libraryCache`, several settings/chat/import components).

Impact:
- Diagnostics underrepresent failures from high-impact offline/sync/profile operations.
- Production triage can miss no-service and non-axios failure patterns.

Recommendation:
- Add `trackFetchError(...)` helper that feeds `apiErrorTracker` with normalized shape.
- Enforce tracker usage in shared service-layer fetch wrappers.

### 5) Test coverage misses the new offline/retry decision path (`P1`)
Evidence:
- Good coverage exists for axios client and tracker (`packages/frontend/src/api/__tests__/client.test.ts`, `packages/frontend/src/utils/__tests__/apiErrorTracker.test.ts`).
- No dedicated tests found for:
  - `packages/frontend/src/stores/connectivityStore.ts` reachability + forced-offline transitions.
  - `packages/frontend/src/hooks/useOfflineQuery.ts` behavior matrix.
  - cross-service consistency between connectivity state and retry behavior.

Impact:
- Regressions in no-service handling and recovery can pass CI.
- Retry/offline policy drift is likely to recur.

Recommendation:
- Add integration tests for three core flows:
  1. `navigator.onLine=true` + failed reachability probe => forced offline + retries disabled.
  2. Recovery probe success => retries re-enabled without app restart.
  3. Mixed axios/fetch failures normalize to one `AppError` category model.

## Decision-Ready Next Actions
1. Implement a shared `AppError` normalizer and migrate `errorNotifications` + key fetch services first.
2. Introduce a single query retry/offline policy helper and migrate high-traffic screens (`Favorites`, `Sidebar`, `Playlists`, `SmartPlaylists`).
3. Migrate `syncService` and `profileService` from `navigator.onLine` gating to `connectivityStore` transitions.
4. Add fetch-side error tracking wrapper and ban raw `fetch(getApiUrl(...))` in components via lint rule (allowlist exceptions).
5. Add connectivity/retry integration tests before Phase 2 close.

## Reproducibility Commands
Run from repo root:

```bash
# Find explicit retry settings
rg -n "retry\s*:" packages/frontend/src --glob '!**/__tests__/**'

# Find fetch usage outside API client
rg -n "fetch\(" packages/frontend/src/components packages/frontend/src/services --glob '*.{ts,tsx}'

# Find navigator.onLine usage (policy drift risk)
rg -n "navigator\\.onLine|addEventListener\\('online'|addEventListener\\(\"online\"" packages/frontend/src/services packages/frontend/src/stores

# Check useOfflineQuery adoption
rg -n "useOfflineQuery\(" packages/frontend/src --glob '!**/__tests__/**'
```
