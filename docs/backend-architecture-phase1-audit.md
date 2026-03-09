# Backend Architecture & Boundaries Audit (Phase 1)

Date: 2026-03-08

## Scope and Method
This audit covers structural boundaries across:
- `backend/app/api` (route handlers, request/response contracts, DI)
- `backend/app/services` (domain logic, integrations, background orchestration)
- `backend/app/db` (models, sessions, migration preflight)
- background/task subsystems (`services/background`, `services/tasks`)

Evidence was collected via static repo inspection (`rg`, `find`, `wc`, targeted file reads), with no runtime behavior changes.

## Ownership Map (Current)
- `platform-entry`: `backend/app/main.py` (app wiring, middleware, router registration, lifespan hooks)
- `api surface`: `backend/app/api/routes/**` + `backend/app/api/deps.py` + `backend/app/api/exceptions.py`
- `domain/service`: `backend/app/services/**` (library, playlists, metadata, analysis, LLM, integrations)
- `job orchestration`: `backend/app/services/background/**` and `backend/app/services/tasks/**`
- `data access`: `backend/app/db/models/**` and `backend/app/db/session.py`
- `cross-cutting utils`: `backend/app/config.py`, `backend/app/logging_config.py`, `backend/app/utils/**`

## Allowed vs Actual Dependency Directions
Intended dependency ruleset:
- `main -> api|services|config|logging|db(preflight only)` allowed.
- `api/routes -> api/deps|api/exceptions|services|db/models` allowed.
- `services -> db|utils|config|other services` allowed.
- `db -> utils|config` allowed.
- `services !-> api/routes` disallowed.
- `api/routes !-> api/routes` (except router aggregation modules) discouraged.

Observed:
- `services -> api/routes`: not found (good boundary adherence).
- `api/routes -> services` and `api/routes -> db/models`: common and expected.
- `api/routes -> api/routes`: present in several non-aggregator cases (coupling risk).

## Key Findings (Top 10)
Severity rubric: P0 (breakage risk), P1 (regression amplifier), P2 (maintainability debt), P3 (cleanup).

1. P1: Route-to-route contract coupling via shared response models.
   - Evidence: `favorites.py` and `smart_playlists.py` import `TrackResponse` from tracks routes instead of a neutral schema module.
   - Files: `/Users/jeff/Developer/familiar/backend/app/api/routes/favorites.py`, `/Users/jeff/Developer/familiar/backend/app/api/routes/smart_playlists.py`

2. P1: Route-to-route utility coupling in diagnostics.
   - Evidence: diagnostics imports `is_running_in_docker` and `system_health_check` from health route module.
   - File: `/Users/jeff/Developer/familiar/backend/app/api/routes/diagnostics.py`

3. P1: Route-to-route schema coupling in library analysis.
   - Evidence: `library_analysis.py` imports `CancelResponse` from `library_sync.py`.
   - File: `/Users/jeff/Developer/familiar/backend/app/api/routes/library_analysis.py`

4. P1: Oversized API modules above 600 LOC threshold.
   - Evidence: `export_import.py` (785), `library_artists.py` (712), `playlists.py` (689), `library_import.py` (632).
   - Directory: `/Users/jeff/Developer/familiar/backend/app/api/routes`

5. P1: Oversized service modules above 600 LOC threshold (15 files).
   - Evidence includes `track_analysis/analyzers.py` (1563), `s3_backup.py` (1156), `tasks/analysis_pipeline.py` (1035), `analysis.py` (943).
   - Directory: `/Users/jeff/Developer/familiar/backend/app/services`

6. P1: Route handlers contain deep business/process logic (not just orchestration).
   - Evidence: tracks streaming route handles remux/transcode/repair flow directly.
   - File: `/Users/jeff/Developer/familiar/backend/app/api/routes/tracks/streaming.py`

7. P2: Shared DTO ownership is fragmented across route modules.
   - Evidence: multiple route-local Pydantic models reused indirectly via route imports.
   - Impact: schema churn propagates through unrelated route files.

8. P2: Background orchestration spans several modules without an explicit public interface boundary.
   - Evidence: manager/mixins/tasks interact via internal attributes and direct imports.
   - Files: `/Users/jeff/Developer/familiar/backend/app/services/background/manager.py`, `/Users/jeff/Developer/familiar/backend/app/services/tasks/analysis_pipeline.py`

9. P2: Domain packages with very high internal surface area lack submodule boundary guardrails.
   - Evidence: `services/track_analysis` and `services/export_import` have large files and broad re-export patterns.
   - Directories: `/Users/jeff/Developer/familiar/backend/app/services/track_analysis`, `/Users/jeff/Developer/familiar/backend/app/services/export_import`

10. P2: Main app module centralizes broad startup concerns.
    - Evidence: `main.py` owns migration preflight, capability checks, background startup, middleware, error handling, and router registration.
    - File: `/Users/jeff/Developer/familiar/backend/app/main.py`

## Batch Plan (Decision-Ready)
Batch A (low/medium risk, immediate):
- Move shared route DTOs (`TrackResponse`, `CancelResponse`, common diagnostics schemas) into `app/api/schemas/`.
- Replace non-aggregator route-to-route imports with schema/service imports.
- Add boundary lint check in CI: fail on `app/api/routes/**` importing sibling route modules except known aggregators (`library.py`, `tracks/__init__.py`).

Batch B (medium risk):
- Split large route modules by concern (`playlists`, `library_import`, `export_import`) into per-use-case submodules.
- Convert route handlers to orchestration-only wrappers where business logic currently resides inline.

Batch C (higher risk, staged):
- Carve high-LOC service files into pipeline-oriented modules with explicit contracts (inputs/outputs, side effects).
- Introduce background task facade interfaces to decouple manager/mixins/tasks internals.

## Reproducibility Commands
- File inventory: `rg --files backend/app | sort`
- Directory map: `find backend/app -maxdepth 3 -type d | sort`
- Boundary scan: `rg "^from app\\.api\\.routes" backend/app -n`
- Layer import checks:
  - `rg "^from app\\.db|^import app\\.db|from app\\.services|from app\\.api" backend/app/api/routes -n`
  - `rg "^from app\\.api|^import app\\.api|from app\\.db|from app\\.services" backend/app/services -n`
- LOC hotspots:
  - `python3` static LOC scan (used in this audit)
  - `wc -l backend/app/services/*.py backend/app/api/routes/*.py`

