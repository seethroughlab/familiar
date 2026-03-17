# Audit Backlog

Consolidated unimplemented action items from all audit documents (frontend + backend).
Items are organized by area with priority levels (P0 = critical, P1 = high, P2 = medium).

---

## Frontend Architecture

### Boundary & Dependency Fixes

| Pri | Item | Key Files |
|-----|------|-----------|
| P0 | Break circular dependency: API base <-> profile service | `api/base.ts`, `services/profileService.ts` |
| P0 | Remove service→UI store coupling (syncService→toastStore) | `services/syncService.ts` |
| P0 | Fix iOS engine dependency on frontend hook module | `ios/src/CapacitorEngine.ts` |
| P0 | Fix offline queue rebuild forcing playback on (`setQueue` always sets `isPlaying`) | `player/useAudioEngine.ts:396-421` |
| P1 | Centralize platform detection into `platform/runtimeAdapter.ts` | `api/base.ts`, `utils/platform.ts`, `player/audio/platform.ts` |
| P1 | Move visualizer constants to shared-utils | `stores/visualizerStore.ts` |
| P2 | Reduce repeated offline-track hydration logic across detail surfaces | Favorites, Playlist, SmartPlaylist, Artist, Album |
| P2 | Introduce domain hooks layer to reduce direct API/service imports | Components with `../../api` imports |
| P2 | Add dependency-cruiser CI boundary enforcement | `packages/frontend/eslint.config.js` |

### God Module Splits

| Pri | Item | Key Files |
|-----|------|-----------|
| P1 | Split TrackListBrowser (1594 LOC, 27 imports) into data/actions/ui submodules | `TrackListBrowser.tsx` |
| P1 | Split playerStore (1098 LOC) into queueStore, playbackStore, persistence adapter | `stores/playerStore.ts` |
| P1 | Extract PlaylistDetail data/loading into `usePlaylistDetailData` hook | `PlaylistDetail.tsx` |
| P1 | Extract AppShell startup initializers into `useAppBootstrap()` | `AppShell.tsx` |
| P2 | Split ImportModal (1004 LOC) into step modules | `ImportModal.tsx` |
| P2 | Split S3BackupSettings (849 LOC) into domain panels | `S3BackupSettings.tsx` |

### Data & API Layer

| Pri | Item | Key Files |
|-----|------|-----------|
| P1 | Create query key factory to fix 72 inconsistent keys | New: `api/queryKeys.ts` |
| P1 | Create missing API clients (chat, missingTracks, importSession, diagnosticsLogs) | 32 direct `fetch()` calls bypass `api/*` |
| P1 | Normalize error shapes across axios and fetch into shared `AppError` | `errorNotifications.ts` |
| P1 | Centralize query retry/offline policy | `useOfflineQuery.ts` exists but unused |
| P1 | Replace `Record<string, unknown>` with discriminated DTOs | `api/admin.ts`, `api/backup.ts` |
| P1 | Add parse/validation adapters for streams (ChatStreamEvent, MapStreamEvent) | Chat + SSE handlers |
| P2 | Migrate services from `navigator.onLine` to connectivityStore | `syncService.ts`, `profileService.ts` |
| P2 | Add fetch-side error tracking to `apiErrorTracker` | Fetch-heavy services |
| P2 | Standardize transport layer (axios default, document fetch exceptions) | Lint guardrail needed |

### Playback & Offline Critical Path

| Pri | Item | Key Files |
|-----|------|-----------|
| P1 | Enforce offline invariant in incremental queue mutations (addToQueue) | `player/playerStore.ts` |
| P1 | Resolve pending next/previous URLs through offline resolver | `player/useAudioEngine.ts:450-467` |
| P1 | Make crossfade store transition atomic with engine success | `player/useAudioEngine.ts:225-227` |
| P1 | Move circuit-breaker trackers from module globals to store-scoped state | `player/useAudioEngine.ts:20-24` |
| P1 | Add connectivityStore unit test suite (forced-offline, recovery, backoff) | Missing tests |
| P1 | Add bounded fallback + skip-storm circuit breaker | Prevent load-error loops |
| P1 | Add lock-screen availability parity contract (canGoNext/canGoPrevious) | Native command handlers |
| P1 | Add typed native error category emission for error-shape parity | Plugin emits only `"message"` |

### Performance & Bundle

| Pri | Item | Key Files |
|-----|------|-----------|
| P1 | Convert library browser registry to lazy loaders (removes 3D from entry chunk) | `LibraryView` → `./browsers` |
| P1 | Lazy-load visualizer modules (load selected only) | `AudioVisualizer` |
| P1 | Add CI bundle report + size check (entry chunk > 350 kB gzip = fail) | CI pipeline |
| P1 | Add performance budget gates (+30 kB growth = block) | CI pipeline |
| P2 | Remove ineffective dynamic imports (offlineService, toastStore) | Both dynamic and static-imported |
| P2 | Feature-split discovery/proposed-changes into lazy chunks | Route-critical path review |

### Rendering & Virtualization

| Pri | Item | Key Files |
|-----|------|-----------|
| P1 | Fix full-store subscription in AlbumDetail (use field selectors) | `AlbumDetail.tsx:180` |
| P1 | Virtualize PlaylistTrackList (used by 5 surfaces) | `PlaylistTrackList` |
| P1 | Virtualize QueueView list | `QueueView` |
| P1 | Add windowing for mobile library lists (unbounded DOM) | Tracks/Artists/Albums |
| P2 | Extract expensive effects from TrackListBrowser behind guards | visibleTracks mapping |
| P2 | Add memo row wrappers in PlaylistTrackList | Desktop/mobile row blocks |
| P2 | Review AppShell Outlet remount behavior (keyed by pathname) | Resets virtualizer scroll |

### Shared UI Extractions

| Pri | Item | Description |
|-----|------|-------------|
| P1 | `usePlaylistDetailController` | Unify search/filter/play-toggle/queue across 5 detail pages |
| P1 | `useOfflineTrackState` | Deduplicate offline ID hydration across 5 surfaces |
| P1 | `usePlayerTrackContextMenu` | Extract repeated context menu action wiring |
| P1 | `useLibraryBrowserController` | Split BrowserProps into navigation/selection/playback/filters |
| P2 | Migrate search inputs to shared `TrackSearchInput` component | Exists but unused |
| P2 | Decompose PlaylistTrackList into table/selection/menu submodules | Data + rendering split |

---

## Backend Architecture

### Route & Service Structure

| Pri | Item | Key Files |
|-----|------|-----------|
| P1 | Move shared route DTOs into `app/api/schemas/` | TrackResponse, CancelResponse, diagnostics schemas |
| P1 | Replace route-to-route imports with schema/service imports | Add CI boundary lint |
| P1 | Split large route modules (playlists, library_import, export_import) | Per-use-case submodules |
| P1 | Convert route handlers to orchestration-only wrappers | Extract inline business logic |
| P2 | Carve high-LOC service files into pipeline-oriented modules | Background task facades |

### API Contracts & Error Handling

| Pri | Item | Description |
|-----|------|-------------|
| P1 | Define single documented error contract per transport (REST JSON vs SSE) | Error envelope normalization |
| P1 | Add centralized HTTPException handler in `main.py` with request ID | Normalize REST error responses |
| P1 | Migrate high-traffic routes to typed `FamiliarError` subclasses | Replace raw HTTPException |
| P1 | Standardize status codes per matrix in high-traffic routes | download, artwork, library_import, export_import, lastfm, chat |
| P1 | Remove raw exception-string leaks (library_import family first) | Security + consistency |
| P1 | Add/standardize `response_model` for untyped non-streaming endpoints | Type safety |
| P1 | Add error-semantics reference table in backend docs | Developer reference |
| P1 | Expand contract tests: envelope parity, dependency contracts, SSE error schema | Test coverage |

### Auth/Profile Contract

| Pri | Item | Description |
|-----|------|-------------|
| P1 | Add dedicated `make test-contract` CI job as branch protection requirement | Fast pre-merge gate |
| P1 | Split contract tests into error shapes + auth contract matrix files | Separate concerns |
| P2 | Add static guardrail: fail if new mutating routes omit RequiredProfile | CI scan |
| P2 | Fail if routes introduce non-canonical auth error messages | Approved constants only |

### Data & Migrations

| Pri | Item | Description |
|-----|------|-------------|
| P1 | Publish explicit migration policy (one-way vs reversible) in file headers | Consistency |
| P1 | Add guard helpers for destructive downgrade ops | Safety |
| P1 | Add CI lint for migration doc consistency (revision/down_revision validity) | Automation |
| P1 | Add trigram GIN indexes on tracks.title, tracks.artist, tracks.album | Wildcard search perf |
| P1 | Add index on `track_analysis.features_version` | Query perf |
| P1 | Add index on `frontend_logs.client_ts` | Query perf |
| P1 | Add migration regression tests (downgrade/upgrade cycles) | Test coverage |
| P2 | Normalize downgrade behavior to single policy across all migrations | Consistency |

### Performance & Capacity

| Pri | Item | Key Files |
|-----|------|-----------|
| P0 | Fix 2N+1 in bulk analysis report (batch queries + in-memory join) | Analysis routes |
| P0 | Fix playlist-create per-track loads (batch fetch by UUIDs) | Playlist routes |
| P0 | Fix discover looped library checks (single grouped query) | Discovery service |
| P0 | Add explicit admission cap for analysis task queue | Background tasks |
| P1 | Lower default sync queue burst size to adaptive values | Background sync |
| P1 | Add lock heartbeat renewal during long sync phases | Lock management |
| P1 | Add cache TTL for expensive stable aggregation endpoints | Letter-index variants |
| P2 | Add query-level instrumentation (route template + query count + duration) | Request scope logging |
| P2 | Introduce bounded worker scaling setting for analysis lane | `max_workers` configurable |
| P2 | Add soak test profile in CI/nightly | Synthetic queue pressure validation |

---

## Testing & CI

### Frontend Testing

| Pri | Item | Description |
|-----|------|-------------|
| P1 | Add frontend unit test CI job (`pnpm --filter @familiar/frontend test`) | Currently missing from CI |
| P1 | Add iOS native AppTests CI gate | Lock-screen remote-command regressions |
| P1 | Add E2E no-service scenario test (stream failure → offline fallback) | Missing browser-level simulation |
| P1 | Add E2E offline invariant test (non-downloaded absent across surfaces) | Cross-surface coverage |
| P1 | Fix 96 flaky fixed sleeps → event/state waits across 10 E2E specs | `waitForTimeout` → `expect.poll` |
| P1 | Re-enable skipped crossfade E2E coverage | `crossfade-playback.spec.ts:75` |
| P2 | Add static check for no-op assertions (`expect(... \|\| true).toBe(true)`) | `playlists.spec.ts:265`, `ai-chat.spec.ts:119` |
| P2 | Remove data-dependent test skips → deterministic seeded fixtures | `audio-playback.spec.ts:17`, `playlists.spec.ts:191` |
| P2 | Add flake budget check (fail on retry-only passes in blocking suites) | CI reliability |

### Backend Testing

| Pri | Item | Description |
|-----|------|-------------|
| P0 | Split monolithic backend pytest CI into risk buckets with timeouts | Contract+migrations, background, core API, integration |
| P0 | Add retry-only-pass detector for blocking buckets | CI reliability |
| P0 | Add skip-budget checker in CI output parsing | Prevent skip accumulation |
| P0 | Require release blocked unless latest CI on target commit succeeded | Release safety |
| P1 | Add reversible-migration downgrade/upgrade cycle tests | Migration safety |
| P1 | Add background fault-injection tests (Redis/DB transient failures) | Resilience |
| P1 | Add protected-endpoint auth/profile contract matrix test | Auth coverage |
| P1 | Add stream endpoint concurrency test (parallel range/stream requests) | Concurrency safety |
| P1 | Migrate high-risk suites from session-scoped to function-scoped client | Test isolation |
| P1 | Add deterministic seed policy for `np.random` usage | Reproducibility |
| P1 | Enforce backend-lint + backend-test split in branch protection | CI gates |
| P2 | Raise coverage gate per risk bucket (not one global threshold) | Targeted coverage |
| P2 | Enable merge queue once flake budget is stable | CI maturity |

---

## Observability

| Pri | Item | Description |
|-----|------|-------------|
| P0 | Add HTTP request-timing middleware with route template tagging | `route_template`, `method`, `status_code`, `duration_ms`, `request_id` |
| P0 | Add background queue/drain gauges from progress/event data | Capacity visibility |
| P0 | Export metrics to diagnostics endpoint + logs | Unified observability |
| P1 | Stand up dashboards: API Performance, Background Capacity, Query Health | Operational visibility |
| P1 | Configure P0/P1 alerts and tune thresholds | Alerting |
| P1 | Add CI perf artifact generation (`artifacts/perf/backend-metrics.json`) | Regression detection |
| P1 | Emit per-phase throughput metrics (queued/completed per min, queue depth) | Background monitoring |
| P1 | Extend `/health/workers` with phase-specific backlog and drain-rate | Health endpoint |
| P1 | Define pressure alarms (queue depth, drain rate, stall recoveries) | Operational safety |
| P2 | Keep Tier B/C endpoints as warning-only until stable over 2 release cycles | Gradual enforcement |

---

## Summary

| Area | P0 | P1 | P2 | Total |
|------|----|----|-----|-------|
| Frontend Architecture | 4 | 4 | 5 | 13 |
| Frontend God Module Splits | 0 | 4 | 2 | 6 |
| Frontend Data & API Layer | 0 | 6 | 3 | 9 |
| Frontend Playback & Offline | 0 | 8 | 0 | 8 |
| Frontend Performance & Bundle | 0 | 4 | 2 | 6 |
| Frontend Rendering & Virtualization | 0 | 4 | 3 | 7 |
| Frontend Shared UI Extractions | 0 | 4 | 2 | 6 |
| Backend Route & Service Structure | 0 | 4 | 1 | 5 |
| Backend API Contracts | 0 | 8 | 0 | 8 |
| Backend Auth/Profile Contract | 0 | 2 | 2 | 4 |
| Backend Data & Migrations | 0 | 7 | 1 | 8 |
| Backend Performance & Capacity | 4 | 3 | 3 | 10 |
| Frontend Testing & CI | 0 | 6 | 3 | 9 |
| Backend Testing & CI | 4 | 7 | 2 | 13 |
| Observability | 3 | 5 | 1 | 9 |
| **Total** | **15** | **80** | **30** | **125** |

*Note: Phase 4 Background Resilience (Batch A-C) was fully implemented 2026-03-08 and is not included above.*
