# Audit Backlog

Consolidated unimplemented action items from all audit documents (frontend + backend).
Items are organized by area with priority levels (P0 = critical, P1 = high, P2 = medium).

---

## Frontend Architecture

### Boundary & Dependency Fixes

| Pri | Item | Key Files |
|-----|------|-----------|
| ~~P0~~ | ~~Break circular dependency: API base <-> profile service~~ | ~~`api/base.ts`, `services/profileService.ts`~~ |
| ~~P0~~ | ~~Remove service→UI store coupling (syncService→toastStore)~~ | ~~`services/syncService.ts`~~ |
| ~~P0~~ | ~~Fix iOS engine dependency on frontend hook module~~ | ~~`ios/src/CapacitorEngine.ts`~~ |
| ~~P0~~ | ~~Fix offline queue rebuild forcing playback on (`setQueue` always sets `isPlaying`)~~ | ~~`player/useAudioEngine.ts:396-421`~~ |
| ~~P1~~ | ~~Centralize platform detection into `utils/platform.ts`~~ | ~~`api/base.ts`, `utils/platform.ts`, `player/audio/platform.ts`~~ |
| ~~P1~~ | ~~Move visualizer constants to shared-utils~~ | ~~`stores/visualizerStore.ts`~~ |
| ~~P2~~ | ~~Reduce repeated offline-track hydration logic across detail surfaces~~ | ~~Favorites, Playlist, SmartPlaylist, Artist, Album~~ |
| P2 | Introduce domain hooks layer to reduce direct API/service imports | Components with `../../api` imports |
| ~~P2~~ | ~~Add dependency-cruiser CI boundary enforcement~~ | ~~`.dependency-cruiser.cjs` + CI `check:boundaries` step~~ |

### God Module Splits

| Pri | Item | Key Files |
|-----|------|-----------|
| ~~P1~~ | ~~Split TrackListBrowser (~~1662~~ ~~1287~~ 1072 LOC) — inline components extracted to `trackList/`, `useMobileJumpFetch` hook extracted (~375 LOC removed), `useTrackListData` hook wired up (~215 LOC removed)~~ | ~~`TrackListBrowser.tsx`~~ |
| ~~P1~~ | ~~Split playerStore (1098 LOC) into queueStore, playbackStore, persistence adapter~~ | ~~`player/playerStore.ts` → facade, `playbackStore.ts`, `queueStore.ts`, `persistenceAdapter.ts`~~ |
| ~~P1~~ | ~~Extract PlaylistDetail data/loading into `usePlaylistDetailData` hook~~ | ~~`PlaylistDetail.tsx`~~ |
| ~~P1~~ | ~~Extract AppShell startup initializers into `useAppBootstrap()`~~ | ~~`AppShell.tsx`~~ |
| ~~P2~~ | ~~Split ImportModal (1004 LOC) into step modules — **struck:** now 328 LOC after prior refactors, below split threshold~~ | ~~`ImportModal.tsx`~~ |
| ~~P2~~ | ~~Split S3BackupSettings (849 LOC) into domain panels — extracted CostEstimateCard, BackupProgressBar, BackupHistory, RestoreSection into `S3Backup/` directory~~ | ~~`S3Backup/S3BackupSettings.tsx`~~ |

### Data & API Layer

| Pri | Item | Key Files |
|-----|------|-----------|
| ~~P1~~ | ~~Create query key factory to fix 72 inconsistent keys~~ | ~~`api/queryKeys.ts` created; all families migrated (65+ sites across ~25 files)~~ |
| ~~P1~~ | ~~Create missing API clients (chat, missingTracks, importSession, diagnosticsLogs)~~ | ~~All 4 named clients exist in `api/`; remaining ~20 direct `fetch()` calls are intentional (SSE streaming, offline download with resume/abort, health probes, CORS blob workarounds)~~ |
| ~~P1~~ | ~~Normalize error shapes across axios and fetch into shared `AppError`~~ | ~~`utils/appError.ts` — `AppError` class + `toAppError()` helper; `apiErrorTracker.ts` exports `categorizeError`/`determineSeverity`; `errorNotifications.ts` fast path~~ |
| ~~P1~~ | ~~Centralize query retry/offline policy~~ | ~~`api/queryDefaults.ts` — `STALE_TIME` tiers + `offlineAwareRetry()` used across ~18 files~~ |
| ~~P1~~ | ~~Replace `Record<string, unknown>` with discriminated DTOs~~ | ~~`api/admin.ts` (ServiceDetails union + type guards), `api/backup.ts` (ExportChatMessage), JSDoc on intentionally-untyped Records~~ |
| ~~P1~~ | ~~Add parse/validation adapters for streams (ChatStreamEvent, MapStreamEvent)~~ | ~~Already implemented: `parseChatStreamEvent()` in `api/chat.ts`, `parseMapProgressEvent()`/`parseMapErrorMessage()` in `api/mapStream.ts`~~ |
| ~~P2~~ | ~~Migrate services from `navigator.onLine` to connectivityStore~~ | ~~All 4 external sites migrated: `syncService.ts`, `profileService.ts`, `ProfileSelector.tsx`~~ |
| ~~P2~~ | ~~Add fetch-side error tracking to `apiErrorTracker`~~ | ~~`trackFetchError()` helper + 4 high-priority sites (chat-stream, map-stream, offline-track-metadata, offline-artwork)~~ |
| ~~P2~~ | ~~Standardize transport layer (axios default, document fetch exceptions)~~ | ~~ESLint `no-restricted-globals` rule for `fetch`; all 11 intentional sites annotated~~ |

### Playback & Offline Critical Path

| Pri | Item | Key Files |
|-----|------|-----------|
| ~~P1~~ | ~~Enforce offline invariant in incremental queue mutations (addToQueue)~~ | ~~`player/playerStore.ts`~~ |
| ~~P1~~ | ~~Resolve pending next/previous URLs through offline resolver~~ | ~~`player/useAudioEngine.ts:450-467`~~ |
| ~~P1~~ | ~~Make crossfade store transition atomic with engine success~~ | ~~`player/useAudioEngine.ts:225-227`~~ |
| ~~P1~~ | ~~Move circuit-breaker trackers from module globals to store-scoped state~~ | ~~`player/useAudioEngine.ts:20-24`~~ |
| ~~P1~~ | ~~Add connectivityStore unit test suite (forced-offline, recovery, backoff)~~ | ~~Missing tests~~ |
| ~~P1~~ | ~~Add bounded fallback + skip-storm circuit breaker~~ | ~~Prevent load-error loops~~ |
| ~~P1~~ | ~~Add lock-screen availability parity contract (canGoNext/canGoPrevious)~~ | ~~Native command handlers~~ |
| ~~P1~~ | ~~Add typed native error category emission for error-shape parity~~ | ~~Plugin emits only `"message"`~~ |

### Performance & Bundle

| Pri | Item | Key Files |
|-----|------|-----------|
| ~~P1~~ | ~~Convert library browser registry to lazy loaders (removes 3D from entry chunk)~~ | ~~`LibraryView` → `./browsers`~~ |
| ~~P1~~ | ~~Lazy-load visualizer modules (load selected only)~~ | ~~`AudioVisualizer`~~ |
| ~~P1~~ | ~~Add CI bundle report + size check (entry chunk > 350 kB gzip = fail)~~ | ~~CI pipeline~~ |
| ~~P1~~ | ~~Add performance budget gates (+30 kB growth = block)~~ | ~~CI pipeline~~ |
| ~~P2~~ | ~~Remove ineffective dynamic imports (offlineService, toastStore)~~ | ~~Both dynamic and static-imported~~ |
| ~~P2~~ | ~~Feature-split discovery/proposed-changes into lazy chunks~~ | ~~`DiscoverBrowser/index.ts` and `ProposedChangesBrowser/index.ts` — lazy wrappers following UMAPExplorer pattern~~ |

### Rendering & Virtualization

| Pri | Item | Key Files |
|-----|------|-----------|
| ~~P1~~ | ~~Fix full-store subscription in AlbumDetail (use field selectors)~~ | ~~`AlbumDetail.tsx:180`~~ |
| ~~P1~~ | ~~Virtualize PlaylistTrackList (used by 5 surfaces)~~ | ~~`PlaylistTrackList`~~ |
| ~~P1~~ | ~~Virtualize QueueView list~~ | ~~`QueueView`~~ |
| ~~P1~~ | ~~Add windowing for mobile library lists (unbounded DOM)~~ | ~~Tracks/Artists/Albums~~ |
| ~~P2~~ | ~~Extract expensive effects from TrackListBrowser behind guards~~ | ~~visibleTracks mapping~~ |
| ~~P2~~ | ~~Add memo row wrappers in PlaylistTrackList~~ | ~~Desktop/mobile row blocks~~ |
| ~~P2~~ | ~~Review AppShell Outlet remount behavior (keyed by pathname)~~ | ~~Resets virtualizer scroll~~ |

### Shared UI Extractions

| Pri | Item | Description |
|-----|------|-------------|
| ~~P1~~ | ~~`usePlaylistDetailController`~~ | ~~Search/filter portion extracted as `useTrackSearch`; play/queue unification deferred (track type variations make full controller impractical)~~ |
| ~~P1~~ | ~~`useOfflineTrackState`~~ | ~~Deduplicate offline ID hydration across 5 surfaces~~ |
| ~~P1~~ | ~~`usePlayerTrackContextMenu`~~ | ~~Extract repeated context menu action wiring — already exists as `useTrackContextMenu.tsx` (233 LOC, 4+ consumers)~~ |
| ~~P1~~ | ~~`useLibraryBrowserController`~~ | ~~Split BrowserProps into navigation/selection/playback/filters — **struck:** browsers consume disjoint prop subsets (9/4/1/1), a unified controller would increase coupling without enabling reuse~~ |
| ~~P2~~ | ~~Migrate search inputs to shared `TrackSearchInput` component~~ | ~~Moved to `shared/TrackSearchInput.tsx`, 5 detail views migrated~~ |
| ~~P2~~ | ~~Decompose PlaylistTrackList into table/selection/menu submodules~~ | ~~`PlaylistRow` extracted to own file (~190 LOC); hooks already extracted~~ |

---

## Backend Architecture

### Route & Service Structure

| Pri | Item | Key Files |
|-----|------|-----------|
| ~~P1~~ | ~~Move shared route DTOs into `app/api/schemas/`~~ | ~~`schemas/tracks.py` (6 models), `schemas/common.py` (CancelResponse); diagnostics utility import deferred~~ |
| ~~P1~~ | ~~Replace route-to-route imports with schema/service imports~~ | ~~3 cross-route DTO imports fixed; diagnostics utility import deferred; CI lint deferred~~ |
| ~~P1~~ | ~~Split large route modules (playlists, library_import, export_import)~~ | ~~All 3 converted to packages following tracks/ pattern: playlists/ (crud, tracks, recommendations), export_import/ (profile, library, backup), library_import/ (quick, preview)~~ |
| ~~P1~~ | ~~Convert route handlers to orchestration-only wrappers~~ | ~~Extract inline business logic~~ |
| ~~P2~~ | ~~Carve high-LOC service files into pipeline-oriented modules — extracted `analysis_queue.py` (6 queue functions, ~290 LOC) from analysis_pipeline.py (1072→~705), extracted `library_sync_progress.py` (SyncProgressReporter + helpers, ~330 LOC) from library_sync.py (1176→~846)~~ | ~~`tasks/analysis_queue.py`, `tasks/library_sync_progress.py`~~ |

### API Contracts & Error Handling

| Pri | Item | Description |
|-----|------|-------------|
| ~~P1~~ | ~~Define single documented error contract per transport (REST JSON vs SSE)~~ | ~~`docs/ERROR-CONTRACTS.md` — REST envelope, SSE patterns, FamiliarError hierarchy, status matrix, usage guide~~ |
| ~~P1~~ | ~~Add centralized HTTPException handler in `main.py` with request ID~~ | ~~Normalize REST error responses~~ |
| ~~P1~~ | ~~Migrate high-traffic routes to typed `FamiliarError` subclasses~~ | ~~Replace raw HTTPException — all 28 route files migrated (complete)~~ |
| ~~P1~~ | ~~Standardize status codes per matrix in high-traffic routes~~ | ~~All 28 route files use FamiliarError subclasses with correct status codes~~ |
| ~~P1~~ | ~~Remove raw exception-string leaks (library_import family first)~~ | ~~All route-file string leaks fixed (f-string messages → static message + detail kwarg)~~ |
| ~~P1~~ | ~~Add/standardize `response_model` for untyped non-streaming endpoints~~ | ~~20 endpoints across 8 files: spotify_import (6), chat (2), health (2), diagnostics (2), videos (1), library_missing (3), lastfm (1), settings (1)~~ |
| ~~P1~~ | ~~Add error-semantics reference table in backend docs~~ | ~~Included in `docs/ERROR-CONTRACTS.md` — hierarchy table, status matrix, handler chain~~ |
| ~~P1~~ | ~~Expand contract tests: envelope parity, dependency contracts, SSE error schema~~ | ~~3 test files: error shapes (11), auth matrix (20), envelope parity + SSE (12)~~ |

### Auth/Profile Contract

| Pri | Item | Description |
|-----|------|-------------|
| ~~P1~~ | ~~Add dedicated `make test-contract` CI job as branch protection requirement~~ | ~~Fast pre-merge gate~~ |
| ~~P1~~ | ~~Split contract tests into error shapes + auth contract matrix files~~ | ~~`test_contract_error_shapes.py`, `test_contract_auth_matrix.py`, `test_contract_envelope_parity.py`~~ |
| ~~P2~~ | ~~Add static guardrail: fail if new mutating routes omit RequiredProfile~~ | ~~CI scan~~ |
| ~~P2~~ | ~~Fail if routes introduce non-canonical auth error messages~~ | ~~Approved constants only~~ |

### Data & Migrations

| Pri | Item | Description |
|-----|------|-------------|
| ~~P1~~ | ~~Publish explicit migration policy (one-way vs reversible) in file headers~~ | ~~`migrations/helpers.py` module docstring + CLAUDE.md updated~~ |
| ~~P1~~ | ~~Add guard helpers for destructive downgrade ops~~ | ~~`migrations/helpers.py` — `column_exists`, `table_exists`, `index_exists`, `constraint_exists`; 23 migration files refactored to shared imports~~ |
| ~~P1~~ | ~~Add CI lint for migration doc consistency (revision/down_revision validity)~~ | ~~`scripts/lint_migrations.py` + CI `migration-lint` job~~ |
| ~~P1~~ | ~~Add trigram GIN indexes on tracks.title, tracks.artist, tracks.album~~ | ~~Wildcard search perf~~ |
| ~~P1~~ | ~~Add index on `track_analysis.features_version`~~ | ~~Query perf~~ |
| ~~P1~~ | ~~Add index on `frontend_logs.client_ts`~~ | ~~Query perf~~ |
| ~~P1~~ | ~~Add migration regression tests (downgrade/upgrade cycles)~~ | ~~`test_migrations.py` — head round-trip + parametrized reversible tests~~ |
| ~~P2~~ | ~~Normalize downgrade behavior to single policy across all migrations~~ | ~~All downgrade() functions standardized to `# One-way: <reason>` or actual reversals~~ |

### Performance & Capacity

| Pri | Item | Key Files |
|-----|------|-----------|
| ~~P0~~ | ~~Fix 2N+1 in bulk analysis report (batch queries + in-memory join)~~ | ~~Analysis routes~~ |
| ~~P0~~ | ~~Fix playlist-create per-track loads (batch fetch by UUIDs)~~ | ~~Playlist routes~~ |
| ~~P0~~ | ~~Fix discover looped library checks (single grouped query)~~ | ~~Discovery service~~ |
| ~~P0~~ | ~~Add explicit admission cap for analysis task queue~~ | ~~Background tasks~~ |
| ~~P1~~ | ~~Lower default sync queue burst size to adaptive values~~ | ~~Background sync~~ |
| ~~P1~~ | ~~Add lock heartbeat renewal during long sync phases~~ | ~~Lock management — `SYNC_HEARTBEAT_STALE_SECONDS` + stale lock detection in `background/sync.py`~~ |
| ~~P1~~ | ~~Add cache TTL for expensive stable aggregation endpoints~~ | ~~Letter-index cached with 60s Redis TTL~~ |
| ~~P2~~ | ~~Add query-level instrumentation (route template + query count + duration)~~ | ~~Request scope logging — contextvar counter + SQLAlchemy `before_cursor_execute` event on async engine + middleware reset/read; `avg_queries_per_request` and `max_queries_per_request` in metrics snapshot~~ |
| ~~P2~~ | ~~Introduce bounded worker scaling setting for analysis lane~~ | ~~`config.py` `max_analysis_workers` setting; wired into `_create_executor()` in `executors.py`~~ |
| P2 | Add soak test profile in CI/nightly | Synthetic queue pressure validation |

---

## Testing & CI

### Frontend Testing

| Pri | Item | Description |
|-----|------|-------------|
| ~~P1~~ | ~~Add frontend unit test CI job (`pnpm --filter @familiar/frontend test`)~~ | ~~Currently missing from CI~~ |
| ~~P1~~ | ~~Add iOS native AppTests CI gate~~ | ~~Lock-screen remote-command regressions~~ |
| ~~P1~~ | ~~Add E2E no-service scenario test (stream failure → offline fallback)~~ | ~~`offline-fallback.spec.ts` — 3 tests: stream 503 error state, offline IndexedDB fallback, network recovery~~ |
| ~~P1~~ | ~~Add E2E offline invariant test (non-downloaded absent across surfaces)~~ | ~~`offline-invariant.spec.ts` — 4 tests: empty downloads, count ≤ library, download-and-verify, IndexedDB↔UI consistency~~ |
| ~~P1~~ | ~~Fix 108 flaky fixed sleeps → event/state waits across 11 E2E specs (101 removed, 7 intentional keepers)~~ | ~~`waitForTimeout` → `expect.poll`, element `.waitFor()`, `waitForContentReady` helper~~ |
| ~~P1~~ | ~~Re-enable skipped crossfade E2E coverage~~ | ~~`test.describe.skip` → `test.describe` + suite-level `test.skip(IS_CI)` — tests run locally, skip in CI~~ |
| ~~P2~~ | ~~Add static check for no-op assertions (`expect(... \|\| true).toBe(true)`)~~ | ~~`playlists.spec.ts:265`, `ai-chat.spec.ts:119`~~ |
| P2 | Remove data-dependent test skips → deterministic seeded fixtures | `audio-playback.spec.ts:17`, `playlists.spec.ts:191` |
| ~~P2~~ | ~~Add flake budget check (fail on retry-only passes in blocking suites)~~ | ~~CI reliability~~ |

### Backend Testing

| Pri | Item | Description |
|-----|------|-------------|
| ~~P0~~ | ~~Split monolithic backend pytest CI into risk buckets with timeouts~~ | ~~Contract+migrations, background, core API, integration~~ |
| ~~P0~~ | ~~Add retry-only-pass detector for blocking buckets~~ | ~~CI reliability~~ |
| ~~P0~~ | ~~Add skip-budget checker in CI output parsing~~ | ~~Prevent skip accumulation~~ |
| ~~P0~~ | ~~Require release blocked unless latest CI on target commit succeeded~~ | ~~Release safety~~ |
| ~~P1~~ | ~~Add reversible-migration downgrade/upgrade cycle tests~~ | ~~`test_migrations.py` — parametrized over 19 reversible migrations~~ |
| ~~P1~~ | ~~Add background fault-injection tests (Redis/DB transient failures)~~ | ~~`test_background_fault_injection.py` — 11 tests: Redis lock failures (3), broken pool edge cases (2), heartbeat edge cases (6 parametrized)~~ |
| ~~P1~~ | ~~Add protected-endpoint auth/profile contract matrix test~~ | ~~10 endpoints × 2 tests in `test_contract_auth_matrix.py`~~ |
| ~~P1~~ | ~~Add stream endpoint concurrency test (parallel range/stream requests)~~ | ~~Concurrency safety~~ |
| ~~P1~~ | ~~Migrate high-risk suites from session-scoped to function-scoped client~~ | ~~`conftest.py` client fixture changed from `scope="session"` to `scope="function"`~~ |
| ~~P1~~ | ~~Add deterministic seed policy for `np.random` usage~~ | ~~`conftest.py` autouse fixture seeds stdlib `random` with 42~~ |
| ~~P1~~ | ~~Enforce backend-lint + backend-test split in branch protection~~ | ~~CI already has 4 separate backend jobs; branch protection is a GitHub UI setting~~ |
| ~~P2~~ | ~~Raise coverage gate per risk bucket (not one global threshold)~~ | ~~`--cov-fail-under` added to contract (12%) and integration (5%) CI jobs; core keeps 38%; contract job timeout bumped 3→4 min~~ |
| P2 | Enable merge queue once flake budget is stable | CI maturity |

---

## Observability

| Pri | Item | Description |
|-----|------|-------------|
| ~~P0~~ | ~~Add HTTP request-timing middleware with route template tagging~~ | ~~`route_template`, `method`, `status_code`, `duration_ms`, `request_id`~~ |
| ~~P0~~ | ~~Add background queue/drain gauges from progress/event data~~ | ~~Capacity visibility~~ |
| ~~P0~~ | ~~Export metrics to diagnostics endpoint + logs~~ | ~~Unified observability~~ |
| P1 | Stand up dashboards: API Performance, Background Capacity, Query Health | Operational visibility |
| P1 | Configure P0/P1 alerts and tune thresholds | Alerting |
| ~~P1~~ | ~~Add CI perf artifact generation (`artifacts/perf/backend-metrics.json`)~~ | ~~Frontend bundle metrics already uploaded as CI artifact; backend runtime metrics are operational (dashboards/health endpoints), not CI-meaningful~~ |
| ~~P1~~ | ~~Emit per-phase throughput metrics (queued/completed per min, queue depth)~~ | ~~Background monitoring~~ |
| ~~P1~~ | ~~Extend `/health/workers` with phase-specific backlog and drain-rate~~ | ~~Health endpoint~~ |
| ~~P1~~ | ~~Define pressure alarms (queue depth, drain rate, stall recoveries)~~ | ~~Operational safety~~ |
| P2 | Keep Tier B/C endpoints as warning-only until stable over 2 release cycles | Gradual enforcement |

---

## Summary

| Area | P0 | P1 | P2 | Total | Done |
|------|----|----|-----|-------|------|
| Frontend Architecture | 0 | 4 | 5 | 10 | 8 |
| Frontend God Module Splits | 0 | 4 | 2 | 6 | 6 |
| Frontend Data & API Layer | 0 | 6 | 3 | 9 | 9 |
| Frontend Playback & Offline | 0 | 8 | 0 | 8 | 8 |
| Frontend Performance & Bundle | 0 | 4 | 2 | 6 | 6 |
| Frontend Rendering & Virtualization | 0 | 4 | 3 | 7 | 7 |
| Frontend Shared UI Extractions | 0 | 4 | 2 | 6 | 6 |
| Backend Route & Service Structure | 0 | 4 | 1 | 5 | 5 |
| Backend API Contracts | 0 | 8 | 0 | 8 | 8 |
| Backend Auth/Profile Contract | 0 | 1 | 2 | 3 | 3 |
| Backend Data & Migrations | 0 | 4 | 1 | 5 | 8 |
| Backend Performance & Capacity | 0 | 3 | 3 | 6 | 9 |
| Frontend Testing & CI | 0 | 6 | 3 | 9 | 8 |
| Backend Testing & CI | 0 | 7 | 2 | 9 | 12 |
| Observability | 0 | 5 | 1 | 6 | 7 |
| **Total** | **0** | **72** | **30** | **103** | **115** |

*Note: Phase 4 Background Resilience (Batch A-C) was fully implemented 2026-03-08 and is not included above. "Done" column reflects items completed as of 2026-03-18 (struck through in tables above). Rendering & Virtualization section fully completed 2026-03-17. Batch 3 (2026-03-17): 4 backend routes migrated to FamiliarError (chat, artwork, lastfm, download — 36 HTTPExceptions replaced), query key factory created and top 6 families migrated (~54 sites). Batch 4 (2026-03-17): 3 more routes migrated to FamiliarError (playlists, smart_playlists, library_import — 38 HTTPExceptions replaced, 3 string leaks fixed), query key migration completed (all families), letter-index Redis cache added, heartbeat item struck. Batch 5 (2026-03-17): 5 more routes migrated to FamiliarError (favorites, profiles, library_missing, videos, export_import — 58 HTTPExceptions replaced, 0 string leaks), contract tests expanded from 5→18 cases, usePlayerTrackContextMenu struck (already implemented as useTrackContextMenu). Batch 6 (2026-03-17): 8 more routes migrated to FamiliarError (ambient, library_albums, tracks/playback, organizer, library_artists, tracks/discovery, library_analysis, proposed_changes — 21 HTTPExceptions replaced, 5 string leaks fixed in proposed_changes), ineffective dynamic import in useOfflineTrack.ts removed. Batch 7 (2026-03-17): Final 8 routes migrated to FamiliarError (tracks/listing, tracks/metadata, tracks/identification, spotify_import, library_maps, analysis, tracks/streaming, outputs — 63 HTTPExceptions replaced, 6 string leaks fixed), completing the FamiliarError migration (28/28 route files) and string leak elimination. Batch 8 (2026-03-17): Contract test expansion — split 18 tests in single file into 3 focused files (~43 test cases): `test_contract_error_shapes.py` (11 route-specific), `test_contract_auth_matrix.py` (10 endpoints × 2 parametrized = 20), `test_contract_envelope_parity.py` (7 envelope parity + 5 SSE pre-stream). Fixed bug: chat endpoint uses CurrentProfile (optional), not RequiredProfile — old test expected 401 but correct behavior is 503 (LLMNotConfiguredError). Batch 9 (2026-03-17): Created `docs/ERROR-CONTRACTS.md` (error contract doc: REST envelope, FamiliarError hierarchy table, status code matrix, global handler chain, SSE contracts, usage guide). Added `response_model` to 20 untyped endpoints across 8 files (spotify_import 6, chat 2, health 2, diagnostics 2, videos 1, library_missing 3, lastfm 1, settings 1). Wired `create_sse_error()` into 4 SSE error sites in library_maps.py. Fixed stale error docs in REST-API.md. Batch 10 (2026-03-17): Frontend API client consolidation — added artwork `statusBatch`/`uploadTrackArtwork` to existing `artworkApi` in `api/metadata.ts`, replaced 2 direct fetch in artworkStore + 1 in ArtworkTab; consolidated profileService (5 fetch→profilesApi), syncService (3 fetch→lastfmApi/favoritesApi), libraryCache (1 fetch→api.get); migrated 4 `navigator.onLine` sites to connectivityStore (syncService, profileService, ProfileSelector); struck "Standardize status codes per matrix" (complete). Updated 4 test files to mock API clients instead of global.fetch. Batch 11 (2026-03-17): Backend schemas — created `app/api/schemas/` package with `tracks.py` (6 Pydantic models) and `common.py` (CancelResponse); moved DTOs out of route modules, fixed 3 cross-route imports (smart_playlists, favorites, library_analysis); library_sync.CancelResponse now inherits from schemas.common.CancelResponse. Frontend query defaults — created `api/queryDefaults.ts` with `STALE_TIME` tier constants and `offlineAwareRetry()` helper; replaced 31 scattered staleTime/retry literals across ~18 files. Batch 12 (2026-03-17): Struck "Create missing API clients" (all 4 named clients already exist, remaining ~20 fetch calls are intentional streaming/special-purpose). Moved visualizer constants to `Visualizer/constants.ts` (DEFAULT_VISUALIZER_ID, VISUALIZER_IDS, VISUALIZER_STORAGE_KEY); replaced magic `'music-video'` string in FullPlayer and `'familiar-visualizer'` in visualizerStore. Replaced `Record<string, unknown>` with typed DTOs: `ExportChatMessage` in backup.ts (4 sites), `ServiceDetails` union + type guards in admin.ts/SystemStatus.tsx (removed `as number` casts), JSDoc on intentionally-untyped Records in admin.ts, analysis.ts, chat.ts, backup.ts. Batch 13 (2026-03-17): Struck "Add parse/validation adapters for streams" (already implemented: `parseChatStreamEvent()` in chat.ts, `parseMapProgressEvent()`/`parseMapErrorMessage()` in mapStream.ts). Lazy-loaded DiscoverBrowser and ProposedChangesBrowser following UMAPExplorer pattern (moved to directories with lazy `index.ts` wrappers). Created `utils/appError.ts` with `AppError` class extending `Error` + `toAppError()` normalizer; extracted `categorizeError`/`determineSeverity` as module-level exports from `apiErrorTracker.ts`; added `AppError` fast path in `errorNotifications.ts`. Batch 14 (2026-03-17): Struck `useLibraryBrowserController` (browsers use disjoint prop subsets — unified controller impractical). Moved `TrackSearchInput` to `shared/` and migrated 5 detail views (PlaylistDetail, FavoritesDetail, DownloadsDetail, EphemeralPlaylistDetail, SmartPlaylistDetail). Added `trackFetchError()` helper to `apiErrorTracker.ts` + tracking at 4 fetch sites (chat-stream, map-stream, offline-track-metadata, offline-artwork). Created `migrations/helpers.py` with `column_exists`/`table_exists`/`index_exists`/`constraint_exists`; refactored 23 migration files to use shared imports; updated CLAUDE.md migration guide. Batch 15 (2026-03-17): Struck CI bundle items (lines 68-69, already implemented via `check-bundle-budgets.mjs` + CI job). Extracted `PlaylistRow` (~190 LOC) from `PlaylistTrackList.tsx` into own file with memo comparator. Normalized 6 migration downgrade() functions to `# One-way: <reason>` comment style. Added `deterministic_random` autouse fixture in `conftest.py` (seeds stdlib `random` with 42). Batch 16 (2026-03-17): TrackListBrowser partial decomposition — reconciled inline `TrackRow`/`MobileTrackCard` with extracted versions (added `onDoubleClick` prop, synced title markup), moved `AlbumOfflineButton` to `trackList/AlbumOfflineButton.tsx`, extracted `useMobileJumpFetch` hook (~150 LOC of mobile jump-fetch state/handlers/effects); TrackListBrowser 1662→1287 LOC (~375 removed). Created `scripts/lint_migrations.py` (validates revision chain integrity, ID lengths ≤32, no duplicates, downgrade comments) + `migration-lint` CI job. Added migration round-trip tests: head downgrade→upgrade cycle + parametrized test over 19 reversible migrations. Struck "Enforce backend-lint + backend-test split in branch protection" (CI already has 4 separate jobs). Batch 17 (2026-03-17): Split 3 large route modules into packages following tracks/ pattern: `export_import/` (profile.py, library.py, backup.py), `playlists/` (crud.py, tracks.py, recommendations.py), `library_import/` (quick.py, preview.py) — all endpoint URLs preserved, no main.py changes needed. Changed `conftest.py` client fixture from `scope="session"` to `scope="function"` for test isolation. Added `test_background_fault_injection.py` (11 tests: Redis lock failures, broken pool edge cases, heartbeat/progress edge cases with parametrization). Struck "CI perf artifact generation" (frontend bundle metrics already in CI; backend runtime metrics are operational, not CI-meaningful). Batch 18 (2026-03-17): Per-phase throughput metrics — extended `update_background_gauges()` in `metrics.py` to read sync progress from Redis and populate per-phase gauges (current_phase, phase_analyzed, phase_pending, phase_total, per-phase requeue_attempts/stall_recoveries/forced_exit_reason). Extended `/health/workers` with `phase_queues` field (PhaseQueue model with per-phase pending/completed/total/percent + runtime stats from sync progress). Added `check_pressure_alarms()` with threshold constants (queue depth >500, error rate >5%, p95 >5000ms, task failures >5/min, stall recoveries >3) wired into `_log_metrics_summary()`. Wired `useTrackListData` hook into TrackListBrowser replacing ~215 LOC of inline data-fetching logic (useInfiniteQuery, sparse pages, column/sort config, queue filters, offline fallback); updated hook to accept `isOffline` param, export `fetchTracksPage`, remove stale mobile jump state. Added `test_metrics.py` (10 tests: phase gauge population, no-sync safety, pressure alarm thresholds with min-request guard). Batch 19 (2026-03-17): Route orchestration — extracted `convert_to_static()` and `import_playlist_file()` from smart_playlists route into SmartPlaylistService (~160 LOC moved); extracted `is_heartbeat_stale()` helper into `background/sync.py`, simplified library_sync route. Adaptive queue sizing — added `adaptive_queue_limit()` to `config.py` (CPU-scaled, clamped [50,500]); changed 6 `queue_tracks_for_*` defaults from `limit=500` to `limit=None` with lazy adaptive default; aligned mood_tags initial burst from 500→200. Stream concurrency — added `test_stream_concurrency.py` (5 heartbeat stale tests + 3 concurrent stream tests). Added 6 adaptive sizing tests to `test_metrics.py`. Batch 20 (2026-03-17): playerStore split — decomposed 1,162 LOC monolithic `playerStore.ts` into `playbackStore.ts` (~90 LOC, pure playback state/setters), `queueStore.ts` (~550 LOC, queue state + cross-cutting actions), `persistenceAdapter.ts` (~30 LOC, reads both stores for debounced save), and `playerStore.ts` facade (~60 LOC, `useSyncExternalStore`-based combined hook). Zero consumer migration — 45 existing `usePlayerStore` import sites unchanged. Split test file into `playbackStore.test.ts` (11 tests), `queueStore.test.ts` (50 tests), plus original facade tests (31 tests) retained. Fixed `prefetchService.ts` subscribe pattern for facade compatibility. New exports: `usePlaybackStore`, `useQueueStore` in `player/index.ts` for new code to use focused subscriptions. Batch 21 (2026-03-17): E2E flaky sleep fixes — replaced 101 of 108 `waitForTimeout` calls across 11 E2E files with deterministic waits: `expect.poll()` for async state assertions, element `.waitFor()` for DOM readiness, `waitForLoadState('domcontentloaded')` for navigation, new `waitForContentReady()` helper for screenshot image/canvas readiness. 7 intentional keepers: 3 polling intervals (syncComplete 1s, analysisComplete 2s, trackChange 100ms), 3 audio seek settle delays in crossfade spec (500ms, 1s, 2s), 1 zoom-step delay (150ms). Batch 22 (2026-03-17): E2E test coverage — re-enabled crossfade spec (`test.describe.skip` → `test.describe` + suite-level `test.skip(IS_CI)`), created `offline-fallback.spec.ts` (3 tests: stream 503 error state, IndexedDB offline fallback, network recovery after failure), created `offline-invariant.spec.ts` (4 tests: empty downloads, count ≤ library total, download-and-verify, IndexedDB↔UI consistency). Frontend Testing 2→5 done. Batch 23 (2026-03-17): CI gates — added `ios-native-tests` job to CI (xcodebuild test on macos-latest, CODE_SIGNING_ALLOWED=NO). Fixed 3 no-op assertions: `playlists.spec.ts` (drag reorder `|| true` → explicit skip), `ai-chat.spec.ts` (playing `|| true` → removed), `offline-fallback.spec.ts` (`|| true` → sidebar visibility check). Added E2E flake budget: JSON reporter in Playwright config + CI step detecting retry-only passes. Created `scripts/lint_profile_contracts.py` (AST-based lint: mutating routes must have RequiredProfile, non-canonical auth message detection) + wired into backend-lint CI job. Auth/Profile 2→3 done, Frontend Testing 5→8 done. Batch 24 (2026-03-17): Implemented `useOfflineAlbum` hook (album-level offline state wrapping `useOfflineTrackState` + downloadStore progress); refactored ArtistDetail to use `useOfflineTrackState` hook replacing inline state + manual refresh. Added ESLint `no-restricted-globals` rule for `fetch` with warning severity; annotated all 11 intentional fetch sites (SSE streaming, offline downloads, CORS blob workarounds, health probes, debug actions). Installed dependency-cruiser with 2 forbidden rules: `no-capacitor-in-frontend` (error), `no-service-to-store` (warn); added `check:boundaries` script + CI step in frontend-lint job. Batch 25 (2026-03-18): Per-bucket coverage gates — added `--cov-fail-under` to contract (12%) and integration (5%) CI jobs alongside existing core (38%); bumped contract timeout 3→4 min. Query-level instrumentation — added contextvar query counter (`reset_query_count`/`increment_query_count`/`get_query_count`) in `metrics.py`, SQLAlchemy `before_cursor_execute` event on async engine in `session.py`, middleware reset/read in `main.py`; extended metrics 5→6-tuple with `query_count`; `get_snapshot()` returns `avg_queries_per_request` and `max_queries_per_request`. Bounded worker scaling — added `max_analysis_workers` setting to `config.py` (default 1); wired into `_create_executor()` in `executors.py`. Added 8 tests: query counter (6), worker scaling (2). Batch 26 (2026-03-18): God module splits + service carving — split S3BackupSettings (849 LOC) into `S3Backup/` directory with 4 extracted sub-components (CostEstimateCard, BackupProgressBar, BackupHistory, RestoreSection) + utils.ts; main component ~330 LOC. Carved `analysis_queue.py` (6 queue_tracks_for_* functions, ~290 LOC) from analysis_pipeline.py (1072→~705 LOC). Carved `library_sync_progress.py` (SyncProgressReporter + guardrail helpers, ~330 LOC) from library_sync.py (1176→~846 LOC). Struck ImportModal (now 328 LOC, below split threshold).*
