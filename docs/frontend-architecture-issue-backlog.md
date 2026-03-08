# Frontend Architecture Issue Backlog (Phase 1)

Severity rubric:
- `P0`: boundary/security/platform-break risk
- `P1`: high coupling/regression amplifier
- `P2`: maintainability debt
- `P3`: cleanup opportunity

Effort scale: `S` (<=1 day), `M` (2-4 days), `L` (1+ week).

## Top 10 Structural Issues

| Rank | Severity | Issue | Evidence | Violated Rule | Effort | Blast Radius | Refactor Entrypoint |
|---|---|---|---|---|---|---|---|
| 1 | P1 | Track list browser is a god module and cross-concern hub | `packages/frontend/src/components/Library/browsers/TrackListBrowser.tsx` (1594 LOC, 27 imports) | God module threshold | L | Library browsing + queue behavior | Extract `trackList/data`, `trackList/actions`, `trackList/ui` modules |
| 2 | P1 | Player store owns too many responsibilities (queue logic, persistence, hydration, lazy loading) | `packages/frontend/src/player/playerStore.ts` (1098 LOC) | Single-responsibility boundary for store/state | L | Core playback + persistence | Split into `queueStore`, `playbackStore`, and persistence adapter |
| 3 | P0 | Circular dependency between API base and profile service | `packages/frontend/src/api/base.ts` <-> `packages/frontend/src/services/profileService.ts` | No cycles across service/api | M | All API requests, profile boot | Move profile-header injector out of `api/base.ts` into dedicated interceptor module |
| 4 | P0 | Service layer imports UI store via toast API | `packages/frontend/src/services/syncService.ts` -> `stores/toastStore.ts` | `service/api` must not depend on `store/state` | S | Offline sync and retries | Emit typed errors/events; let feature hooks map to toasts |
| 5 | P1 | iOS engine depends on frontend hook module | `packages/ios/src/CapacitorEngine.ts` -> `packages/frontend/src/hooks/useAudioAnalyser.ts` | `player/engine` must not depend on `feature` | M | Capacitor playback path | Move native analysis bridge into `player/audio` adapter module |
| 6 | P1 | Store depends on feature type module | `packages/frontend/src/stores/visualizerStore.ts` -> `components/Visualizer/types.ts` | `store/state` must not depend on `feature` | S | Visualizer preference state | Move visualizer constants/types to `shared-utils` |
| 7 | P1 | Platform detection/calls are scattered in shared package | `api/base.ts`, `utils/platform.ts`, `player/audio/platform.ts`, `services/offlineService.ts`, `stores/connectivityStore.ts` | Centralized platform adapter boundary | M | Web + iOS runtime behavior | Create `platform/runtimeAdapter.ts` and migrate all capability checks |
| 8 | P2 | Repeated offline-track hydration logic across playlist/library surfaces | e.g. `FavoritesDetail.tsx`, `PlaylistDetail.tsx`, `SmartPlaylistDetail.tsx`, `ArtistDetail.tsx`, `AlbumGrid.tsx` (`getOfflineTrackIds` + local `Set` patterns) | Feature duplication guardrail | M | Offline UX consistency | Create shared `useOfflineTrackSet` + `DownloadedFilter` utilities |
| 9 | P2 | Feature components call API/services directly at high volume, reducing domain encapsulation | Many direct imports in `components/**` (`../../api`, `../../services/*`) | Feature-domain boundary (prefer domain hooks) | L | Broad; most screens | Introduce domain hooks layer (`hooks/domain/*`) and migrate incrementally |
| 10 | P2 | CI has no dependency-boundary enforcement | Current lint in `packages/frontend/eslint.config.js` has no dependency rules | Governance gap | S | Whole frontend | Add dependency-cruiser/ESLint boundary checks in CI |

## Additional Flagged God Modules (Non-Top-10)
- `packages/frontend/src/components/Import/ImportModal.tsx` (1156 LOC)
- `packages/frontend/src/components/Library/ArtistDetail.tsx` (865 LOC, 23 imports)
- `packages/frontend/src/components/Playlists/PlaylistDetail.tsx` (788 LOC, 20 imports)
- `packages/frontend/src/services/offlineService.ts` (677 LOC, 22 exports)
- `packages/frontend/src/api/backup.ts` (619 LOC, 34 exports)

## Batch Plan

### Batch A (Low-to-Medium risk, start immediately)
- Break cycle `api/base` <-> `profileService`.
- Remove `syncService` -> `toastStore` import.
- Move visualizer constants out of component layer.
- Add CI boundary checks in warning mode, then fail mode.

### Batch B (Medium risk)
- Isolate native analysis bridge from `CapacitorEngine` into engine-layer adapter.
- Consolidate platform runtime checks into one adapter module.
- Introduce shared offline track-set hook and replace duplicated offline ID logic.

### Batch C (Higher risk / larger refactors)
- Split `TrackListBrowser` by concerns.
- Split `playerStore` by domain responsibilities.
- Introduce domain hooks façade to reduce direct API calls in components.
