# Backend Background Jobs, Sync Flows & Operational Resilience Audit (Phase 4, Item 1)

Date: 2026-03-08

## Scope
Audit focus:
- Background lifecycle ownership and orchestration boundaries.
- Retry/idempotency/cancellation behavior across sync and analysis pipelines.
- Operational resilience under degraded dependencies (Redis/worker failures/stalls).
- Recoverability and observability readiness for production incidents.

Primary evidence:
- `/Users/jeff/Developer/familiar/backend/app/services/background/**`
- `/Users/jeff/Developer/familiar/backend/app/services/tasks/**`
- `/Users/jeff/Developer/familiar/backend/app/api/routes/library_sync.py`
- `/Users/jeff/Developer/familiar/backend/app/api/routes/library_analysis.py`
- `/Users/jeff/Developer/familiar/backend/app/api/routes/background.py`
- `/Users/jeff/Developer/familiar/backend/app/api/routes/health.py`

## System Inventory (Lifecycle Ownership)
1. In-process orchestration owner: `BackgroundManager` (`manager.py`) composes `SyncMixin`, `AnalysisMixin`, `ExecutorMixin`, `BackupMixin`.
2. Scheduler owner: APScheduler setup in `BackgroundManager.startup()` with periodic sync (2h), worker health checks (5m), log cleanup (daily), update check, and S3 schedule registration.
3. Sync pipeline owner: `run_sync()` -> `_do_sync()` -> `run_library_sync()` (scan subprocess + phased analysis queue loops).
4. Analysis execution owner: `ExecutorMixin` process pools + circuit breaker, invoked by `AnalysisMixin.run_analysis()` task fan-out.
5. API control plane: `/sync`, `/sync/status`, `/sync/cancel`, `/analysis/*`, `/background/jobs`, `/health/system`, `/health/workers`.

## Findings (Ranked)
1. P0: Cancellation/control-plane uses private internals and does not guarantee hard stop semantics.
- Evidence:
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/library_sync.py:192` calls `bg._cancel_sync()` directly.
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/library_analysis.py:78` iterates `bg._analysis_tasks` directly and cancels tasks.
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/library_analysis.py:69-70` explicitly notes subprocess work may continue after cancel.
- Risk:
  - API routes tightly couple to implementation internals and can drift from manager invariants.
  - Operator expectation mismatch: “cancelled” response can be returned while CPU-bound subprocess work continues.

2. P1: Single-node in-memory task state + Redis lock/progress split creates recovery ambiguity.
- Evidence:
  - In-memory owners: `BackgroundManager._current_sync_task` / `_analysis_tasks` in `analysis.py` and `sync.py`.
  - Redis lock/progress: `familiar:sync:lock` + `familiar:sync:progress` in `sync.py` and `library_sync.py`.
  - Stale logic mismatch: `is_sync_running()` uses ~60s heartbeat staleness while `/sync/status` treats stale at 5 minutes.
- Risk:
  - Divergent staleness thresholds can produce conflicting user/ops interpretation of whether sync is active.
  - Multi-process or restarted-node behavior depends on best-effort cleanup instead of a single authoritative lifecycle state.

3. P1: Queue loops are resilient but not fully bounded by global orchestration guardrails.
- Evidence:
  - Phase loops in `run_library_sync()` have per-phase timeout/stall checks and requeue behavior (features/embeddings/backfill/melodic).
  - Queue functions enqueue by DB selection and rely on `run_analysis()` dedupe for active task keys.
- Risk:
  - Repeated queue scans plus per-track enqueue can still generate high churn under persistent failure patterns.
  - No global “consecutive queue stall breaker” per sync run across all phases.

4. P1: Executor resilience is solid, but recovery remains partly manual after breaker trips.
- Evidence:
  - Circuit breaker in `ExecutorMixin` with cooldown + max consecutive failures (5) and disable path.
  - Manual reset endpoint exists: `/analysis/executor/reset`.
  - Worker health check can recreate stuck executor every 5 minutes.
- Risk:
  - Once disabled, analysis progress halts until manual reset/operator action.
  - Good for safety, but operationally noisy for unattended deployments.

5. P2: Health/diagnostic surfaces are useful but incomplete for root-cause timelines.
- Evidence:
  - `health/workers` exposes active tasks + recent failures (Redis list).
  - `background/jobs` only returns active jobs and omits historical transition/cancel/recovery events.
- Risk:
  - Incident triage lacks an event timeline (start, stall detected, reset, cancel, recover).
  - Hard to distinguish transient flake vs systemic job pathology without digging through logs.

6. P2: Retry policies are distributed and partially inconsistent by task family.
- Evidence:
  - Feature retry window keyed by `Track.analysis_failed_at` (24h).
  - Embedding retry window keyed by `TrackAnalysis.embedding_failed_at` (24h).
  - Scan worker path has no circuit breaker equivalent (explicitly documented as separate failure mode).
- Risk:
  - Different retry stores/fields increase policy drift risk and make system-wide retry behavior harder to reason about.

## What Is Already Strong
- Background manager startup includes stale Redis cleanup to avoid permanent stuck lock after crash.
- Sync lock acquisition uses NX+TTL (`ex=7200`) with stale heartbeat eviction before lock acquisition.
- Analysis executor uses spawn context + `max_tasks_per_child=1` to reduce memory accumulation and worker poisoning.
- Sync analysis phases include explicit timeout and stall detection to avoid infinite wait loops.
- Embedding failures are persisted into DB and counted as “done” for sync progress, preventing deadlock on permanent failures.

## Decision-Ready Remediation Batches
Batch A (immediate, low-medium risk): Control-plane hardening
- Introduce public manager APIs:
  - `cancel_sync()` and `cancel_analysis()` methods on `BackgroundManager`.
  - stop exposing `_cancel_sync`/`_analysis_tasks` to route layer.
- Normalize staleness policy constants in one place (single threshold used by `is_sync_running()` and `/sync/status`).
- Return explicit cancellation semantics in API response:
  - `requested`, `in_process_tasks_cancelled`, `subprocess_may_continue` boolean.
  - Status: Implemented on 2026-03-08 in:
    - `/Users/jeff/Developer/familiar/backend/app/services/background/sync.py`
    - `/Users/jeff/Developer/familiar/backend/app/services/background/analysis.py`
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/library_sync.py`
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/library_analysis.py`
    - `/Users/jeff/Developer/familiar/backend/tests/test_background.py`
    - `/Users/jeff/Developer/familiar/backend/tests/test_api_library.py`

Batch B (medium risk): Retry and queue guardrails
- Add per-sync-run circuit breaker counters:
  - `phase_requeue_attempts`, `stall_recoveries`, `forced_phase_exit_reason`.
- Add global cap on queue churn per phase window to prevent pathological requeue storms.
- Standardize retry state ownership (track-level vs analysis-row-level) with one policy table in docs/code constants.
- Status: Implemented on 2026-03-08 in:
  - `/Users/jeff/Developer/familiar/backend/app/services/tasks/library_sync.py`
  - `/Users/jeff/Developer/familiar/backend/app/services/tasks/analysis_pipeline.py`
  - `/Users/jeff/Developer/familiar/backend/tests/test_sync_guardrails.py`

Batch C (medium-high risk): Operational observability + auto-recovery
- Add background event timeline ring buffer in Redis:
  - events: sync_start, phase_transition, queue_stall, executor_reset, breaker_disabled, cancel_requested, sync_complete/error.
- Expose timeline via new diagnostics endpoint or extend `/health/workers` payload.
- Add optional auto-recovery policy for disabled executor (bounded backoff + cap), default disabled behind setting/flag.
- Status: Implemented on 2026-03-08 in:
  - `/Users/jeff/Developer/familiar/backend/app/services/background/events.py`
  - `/Users/jeff/Developer/familiar/backend/app/services/background/executors.py`
  - `/Users/jeff/Developer/familiar/backend/app/services/background/sync.py`
  - `/Users/jeff/Developer/familiar/backend/app/services/background/analysis.py`
  - `/Users/jeff/Developer/familiar/backend/app/services/tasks/library_sync.py`
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/health.py`
  - `/Users/jeff/Developer/familiar/backend/tests/test_background_events.py`
  - `/Users/jeff/Developer/familiar/backend/tests/test_background.py`

## Acceptance Checks for This Audit Item
- [x] Background jobs and sync lifecycle ownership mapped with concrete modules.
- [x] Retry/idempotency/cancel behavior audited with concrete evidence.
- [x] Degraded/recovery paths and resilience gaps identified and ranked.
- [x] Remediation batches (A/B/C) defined with risk ordering.

## Reproducibility Commands
- Background orchestration map:
  - `rg -n "class BackgroundManager|class .*Mixin|run_sync|run_analysis|_check_and_recover_worker|reset_executor" backend/app/services/background`
- Queue/retry policy scan:
  - `rg -n "failure_cutoff|analysis_failed_at|embedding_failed_at|stalled|timeout|queue_tracks_for_" backend/app/services/tasks`
- API control-plane scan:
  - `rg -n "sync/cancel|analysis/cancel|_analysis_tasks|_cancel_sync|already_running|status" backend/app/api/routes/library_sync.py backend/app/api/routes/library_analysis.py`
- Health/diagnostics scan:
  - `rg -n "health/workers|recent_failures|background_processing|get_sync_progress" backend/app/api/routes/health.py backend/app/api/routes/background.py`
