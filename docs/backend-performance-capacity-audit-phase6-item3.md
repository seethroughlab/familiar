# Backend Performance & Capacity Audit (Phase 6, Item 3): Worker Throughput + Queue Pressure

Date: 2026-03-08

## Scope
This artifact covers Phase 6 checklist item 3 only:
- Evaluate worker/background throughput and queue pressure handling.

Focus areas:
- Analysis executor throughput envelope.
- Queue admission patterns during sync phases.
- Backpressure, churn, and recovery behavior.
- Operability signals available for pressure triage.

## Evidence Sources
- Executor + recovery behavior:
  - `/Users/jeff/Developer/familiar/backend/app/services/background/executors.py`
  - `/Users/jeff/Developer/familiar/backend/app/config.py`
- Sync orchestration + queue churn guardrails:
  - `/Users/jeff/Developer/familiar/backend/app/services/tasks/library_sync.py`
  - `/Users/jeff/Developer/familiar/backend/app/services/background/sync.py`
- Analysis task fan-out:
  - `/Users/jeff/Developer/familiar/backend/app/services/background/analysis.py`
  - `/Users/jeff/Developer/familiar/backend/app/services/tasks/analysis_pipeline.py`
- Operational status surfaces:
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/health.py`
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/library_analysis.py`
  - `/Users/jeff/Developer/familiar/backend/app/services/background/events.py`
- Existing tests:
  - `/Users/jeff/Developer/familiar/backend/tests/test_background.py`
  - `/Users/jeff/Developer/familiar/backend/tests/test_sync_guardrails.py`
  - `/Users/jeff/Developer/familiar/backend/tests/test_sync_integration.py`

## Current Throughput Model (As Implemented)

### Executor concurrency envelope
1. Main analysis executor is single-process:
- `ProcessPoolExecutor(max_workers=1, max_tasks_per_child=1)` in:
  - `/Users/jeff/Developer/familiar/backend/app/services/background/executors.py:71-76`
2. On-demand executor is also single-process:
- `/Users/jeff/Developer/familiar/backend/app/services/background/executors.py:92-97`
3. Health surface reports concurrency `1`:
- `/Users/jeff/Developer/familiar/backend/app/api/routes/health.py:379`

Implication:
- Effective track analysis throughput is strictly serialized per executor lane.
- Peak steady-state throughput (tracks/sec) is bounded by:
  - `1 / avg_task_duration_seconds` (main lane)
  - plus optional on-demand lane when used.

## Ranked Findings

### 1) P0: Queue admission can outpace single-worker consumption by large burst factor
- Evidence:
  - Sync phase queue calls request up to `limit=100` (regular) and `limit=200` (stall recovery):
    - `/Users/jeff/Developer/familiar/backend/app/services/tasks/library_sync.py:628-633`
    - `/Users/jeff/Developer/familiar/backend/app/services/tasks/library_sync.py:648-652`
    - `/Users/jeff/Developer/familiar/backend/app/services/tasks/library_sync.py:751-756`
    - Similar pattern for backfill/melodic.
  - Queue functions iterate all selected IDs and enqueue one-by-one:
    - `/Users/jeff/Developer/familiar/backend/app/services/tasks/analysis_pipeline.py:687-689`
    - `/Users/jeff/Developer/familiar/backend/app/services/tasks/analysis_pipeline.py:738-740`
    - `/Users/jeff/Developer/familiar/backend/app/services/tasks/analysis_pipeline.py:774-776`
- Why this matters:
  - With `max_workers=1`, enqueue bursts of 100-200 create large in-memory pending task sets.
  - Under slow CPU tasks, backlog drains slowly and pressure persists.

### 2) P1: `_analysis_tasks` serves as both dedupe registry and implicit queue, but without explicit queue-depth policy
- Evidence:
  - Tasks stored in dict and counted as active/pending:
    - `/Users/jeff/Developer/familiar/backend/app/services/background/analysis.py:57`
    - `/Users/jeff/Developer/familiar/backend/app/services/background/analysis.py:67-72`
    - `/Users/jeff/Developer/familiar/backend/app/services/background/analysis.py:133`
  - Health endpoint reports pending as `len(bg._analysis_tasks)`:
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/health.py:387`
- Why this matters:
  - No hard cap per phase/total queue depth at admission layer.
  - No separate metric for runnable vs executing vs recently failed.

### 3) P1: Sync lock TTL (2h) is shorter than phase max durations (up to 8h), creating lock semantics mismatch risk
- Evidence:
  - Lock set with TTL `ex=7200`:
    - `/Users/jeff/Developer/familiar/backend/app/services/background/sync.py:103`
  - Multiple phases allow up to 8h timeout:
    - `/Users/jeff/Developer/familiar/backend/app/services/tasks/library_sync.py:582`
    - `/Users/jeff/Developer/familiar/backend/app/services/tasks/library_sync.py:812`
    - `/Users/jeff/Developer/familiar/backend/app/services/tasks/library_sync.py:913`
- Why this matters:
  - Long valid sync runs can outlive lock TTL without explicit lock renewal.
  - Stale lock detection exists, but TTL mismatch still weakens lock-as-authority semantics.

### 4) P1: Worker stuck threshold and recovery are fixed, but throughput SLOs are not enforced
- Evidence:
  - Worker marked unhealthy only if single task > 10 minutes:
    - `/Users/jeff/Developer/familiar/backend/app/services/background/executors.py:230-235`
  - Health check every 5 minutes:
    - `/Users/jeff/Developer/familiar/backend/app/services/background/manager.py:78-83`
  - Circuit breaker disables after 5 consecutive failures:
    - `/Users/jeff/Developer/familiar/backend/app/services/background/executors.py:21`
    - `/Users/jeff/Developer/familiar/backend/app/services/background/executors.py:115-130`
- Why this matters:
  - Recovery mechanisms exist, but there are no throughput budgets (tracks/min) tied to alarms/gates.

### 5) P2: Operational telemetry is useful but incomplete for queue-pressure triage
- Evidence:
  - Background timeline ring buffer exists:
    - `/Users/jeff/Developer/familiar/backend/app/services/background/events.py`
  - Sync progress includes `phase_requeue_attempts` / `phase_stall_recoveries` / forced-exit reasons:
    - `/Users/jeff/Developer/familiar/backend/app/services/tasks/library_sync.py:93-96`
    - `/Users/jeff/Developer/familiar/backend/app/services/tasks/library_sync.py:1019-1021`
  - `health/workers` does not expose phase queue depth, admission rate, drain rate:
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/health.py:321-410`
- Why this matters:
  - Current data helps postmortem but is weak for real-time capacity tuning.

## Capacity Risk Matrix

| Risk | Trigger | Current Mitigation | Residual Risk |
|---|---|---|---|
| Queue bloat during sync | enqueue bursts (100-200) with single worker | phase churn guardrails + stall handling | Memory pressure / long drain windows |
| Throughput collapse after executor failures | repeated BrokenProcessPool / OOM | circuit breaker + manual reset + optional auto-recovery | prolonged degraded analysis if manual action delayed |
| Long-running sync lock ambiguity | sync runtime > lock TTL | heartbeat stale detection, lock cleanup | lock ownership semantics can drift |
| Slow but not “stuck” throughput | tasks under 10m each but very slow aggregate | periodic health check | no SLO-based alerts for low tracks/min |

## Recommended Throughput/Pressure Guardrails (Decision-Ready)

### Batch A (immediate, low risk)
1. Add explicit admission cap for `_analysis_tasks` total size and per-phase size.
- Reject/defer new queue admissions when cap reached.
2. Lower default sync queue burst size from `100/200` to adaptive values based on current backlog.
3. Add lock heartbeat renewal/extension while sync is active to align with multi-hour phase windows.

Expected outcome:
- Reduced queue spikes, clearer sync lock ownership, steadier drain behavior.

### Batch B (medium risk)
1. Emit per-phase throughput metrics at fixed interval:
- `queued_per_min`, `completed_per_min`, `queue_depth`, `oldest_task_age`.
2. Extend `/health/workers` payload with:
- phase-specific backlog and drain-rate snapshots.
3. Define pressure alarms:
- queue depth > threshold for N minutes
- drain rate below threshold with non-zero pending
- repeated stall recoveries within window.

Expected outcome:
- Real-time capacity diagnosis without log forensics.

### Batch C (medium/high risk)
1. Introduce bounded worker scaling setting for analysis lane (`max_workers` configurable, default 1).
2. Add resource-aware mode:
- keep `max_workers=1` on low-memory hosts
- allow >1 only when memory headroom and CLAP profile are safe.
3. Add soak test profile in CI/nightly:
- fixed dataset + synthetic queue pressure + pass/fail on drain-rate and breaker behavior.

Expected outcome:
- Controlled path to improved throughput while preserving stability.

## Measurable Validation Plan

### 1) Queue pressure run
- Start sync and sample every 30s:
  - `/api/v1/library/sync/status`
  - `/api/v1/health/workers`
- Capture:
  - `_analysis_tasks` depth proxy
  - `phase_requeue_attempts`
  - `phase_stall_recoveries`
  - forced exit reasons.

### 2) Throughput baseline
- Compute `tracks/min` over each phase from progress deltas:
  - features/embeddings/backfill/melodic.
- Acceptance target (initial):
  - no sustained decline to near-zero drain rate with non-zero pending for >10m without corresponding stall event.

### 3) Recovery behavior
- Simulate executor crash/failure path (test harness) and verify:
  - breaker events emitted
  - manual reset endpoint recovers lane
  - optional auto-recovery (if enabled) obeys backoff/attempt caps.

## Test/CI Coverage Gaps (for item 3)
Existing:
- Guardrail unit tests and executor behavior tests exist:
  - `test_sync_guardrails.py`
  - `test_background.py`
  - `test_sync_integration.py`

Missing:
1. No explicit throughput regression test (tracks/min floor).
2. No queue-depth saturation test asserting bounded admission behavior.
3. No long-run soak test for sync phase churn under large pending sets.

## Acceptance for Phase 6 Item 3
- [x] Current worker throughput envelope documented with concrete evidence.
- [x] Queue-pressure and backpressure failure modes identified/ranked.
- [x] Decision-ready remediation batches defined (A/B/C).
- [x] Measurable validation plan and test gaps documented.

