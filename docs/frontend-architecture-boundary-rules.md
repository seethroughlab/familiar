# Frontend Boundary Rules (Phase 1)

## Layer Model
- `platform-entry`: platform bootstrap files (`packages/web/src/main.tsx`, `packages/ios/src/main.tsx`).
- `app-shell`: app composition and top-level lifecycle (`App.tsx`, `renderApp.tsx`).
- `feature`: components and hooks implementing user-facing behavior.
- `store/state`: Zustand stores and domain state orchestration.
- `service/api`: API clients, service modules, persistence adapters.
- `player/engine`: audio engine abstraction and implementations.
- `shared-utils`: pure utility/types modules.

## Allowed Import Directions
- `platform-entry` -> `app-shell`, `player/engine`, `store/state` (registration only), `shared-utils`.
- `app-shell` -> `feature`, `player/engine`, `store/state`, `service/api`, `shared-utils`.
- `feature` -> `feature`, `store/state`, `service/api`, `player/engine`, `shared-utils`.
- `store/state` -> `store/state`, `service/api`, `shared-utils`.
- `service/api` -> `service/api`, `shared-utils`.
- `player/engine` -> `player/engine`, `shared-utils`, `service/api`.
- `shared-utils` -> `shared-utils` only.

## Forbidden Directions (Explicit)
- `service/api` -> `store/state`.
- `store/state` -> `feature`.
- `shared-utils` -> `store/state`.
- `player/engine` -> `feature`.
- `platform-entry` -> `service/api` (except through registration interfaces).
- Any direct `@capacitor/*` import in `packages/frontend`.

## Evidence: Current Violations
1. `service/api -> store/state`
- `packages/frontend/src/services/syncService.ts`
- imports `packages/frontend/src/stores/toastStore.ts`

2. `store/state -> feature`
- `packages/frontend/src/stores/visualizerStore.ts`
- imports `packages/frontend/src/components/Visualizer/types.ts`

3. `shared-utils -> store/state`
- `packages/frontend/src/utils/errorNotifications.ts`
- imports `packages/frontend/src/stores/toastStore.ts`

4. `player/engine -> feature`
- `packages/ios/src/CapacitorEngine.ts`
- imports `packages/frontend/src/hooks/useAudioAnalyser.ts`

5. `platform-entry -> service/api`
- `packages/ios/src/main.tsx`
- imports `packages/frontend/src/api/base.ts`

## Registration Seam Rules
- Only platform entrypoints may register platform implementations:
  - `registerEngineFactory`
  - `registerNativeEffectsSync`
  - `registerPreferencesProvider`
- Shared package must consume these seams, not platform plugins directly.

## God Module Thresholds
A module is flagged when any threshold is met:
- LOC > 600
- imports > 20
- exports > 15
- 5+ distinct responsibility categories (qualitative review)
