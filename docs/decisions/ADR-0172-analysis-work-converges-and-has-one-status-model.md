# ADR-0172: Analysis Work Converges and Has One Status Model

Status: accepted

Date: 2026-11-08

Implementation:

- **Observed 2026-11-09 on the NAS** (Phase 1). Every two-hourly sync spun features and then
  embeddings for about two minutes each, until `queue_churn_limit_exceeded:61/60:300s`: the loop's
  2-second cadence makes 60 attempts in two minutes, and the loop's own "nothing queueable" exit
  waits for a five-minute stall, so the guard always fired first. Two causes, neither a churn of
  real work:
  - the loop counted pending as `count(Track) - current analyses`, but the queue takes only `active`
    tracks. 30 tracks (27 `skipped`, 2 `missing`, 1 `pending_deletion`) were pending for features,
    and 1 `pending_deletion` track for embeddings, for ever;
  - 4 active tracks fail embedding with "could not decode … Unspecified internal error" and were
    retried every 24 hours indefinitely. Feature failures were already terminal: a failure marks
    the features version current.
- **Converged (PR 1, Phases 2–3).** `backend/app/services/analysis_lifecycle.py` defines each
  phase's population (`active`, not missing) and what may be tried now, once. The features and
  embeddings queues, `queue_unanalyzed_tracks` (whose embedding branch had no status filter), and
  the sync loop's exit counts all use it. Embedding failures carry `embedding_failure_reason` and
  `embedding_attempts` (migration `20261109_embed_failure_reason`, which backfills reasons from the
  stored message): `undecodable` and `file_missing` are terminal, anything else after three
  attempts. A changed file is retried because the scanner deletes its analysis row. Failures log
  `phase`, `track`, `reason` and `attempt`. The churn limit is unchanged.
  `tests/test_analysis_converges.py` seeds one track of each NAS shape and runs the real
  `run_library_sync` with only the scan stubbed: it finishes at once without a forced exit. Against
  the previous loop it spins until the test's 60-second timeout.
- **Unified (PR 2, Phase 4).** `analysis_lifecycle.phase_counts` is the one status query: for each
  of features, embeddings, deep backfill, melodic and mood tags, the library's tracks split into
  complete / queued / retrying / failed / waiting (an earlier phase is not done), which partition
  the total. `pending` means `queued + retrying` everywhere. Before it, four places defined pending
  four ways: `/health/system` and `/health/workers` as every track minus current analyses,
  `/library/stats` as active tracks minus active analyses (clamped after reaching -41), and
  `/library/analysis/status` as no current analysis and not failed in 24 hours, any status. All four
  now read `phase_counts`; `/health/workers.phase_queues` gains `queued`, `retrying`, `failed` and
  `waiting`, and `analysis_progress` is typed (`AnalysisProgress`) instead of a free-form object.
  The deep-backfill, melodic and mood-tag queues and loop counts take the same in-library
  conditions, closing the status asymmetry there too. `GET /library/analysis/failures` lists each
  failed track with its phase, reason code, attempts and whether it is final (point 7). The
  Analysis → Status page shows the five states and the failed tracks.
  `tests/test_analysis_status_model.py` seeds every state, requires the states to sum to the
  library, and requires all four endpoints to report the same numbers. Contract stays at v1
  (additive).
- **Exit condition:** met in code and tests. The NAS confirmation (two syncs without a forced exit)
  is tracked in `docs/HEALTH.md` until it runs this.

## Context

A periodic NAS sync that finds no new music can spend most of six minutes in feature and embedding
phases before both exit with `queue_churn_limit_exceeded:61/60:300s`. Some tracks are requeued
instead of reaching a terminal result. Raising the limit would hide the symptom while wasting more
work.

At the same time, `/health/system` and `/library/stats` have reported different pending-analysis
counts. The administration UI cannot say which is authoritative or whether they mean different
things.

## Decision

1. Analysis items have an explicit lifecycle: queued, active, retry-wait, failed, or complete.
   Transitions are owned by one domain service, not independently inferred by routes and workers.
2. Requeue decisions carry a stable reason code, attempt count, and next eligible time. Diagnostic
   logs include track and phase identifiers without prose parsing.
3. Retry is bounded by reason. Permanent input or configuration failures reach `failed` rather
   than circulating until a wall-clock guard stops the phase.
4. The churn guard remains a final brake, not normal completion. Its limit is not raised as the fix.
5. Capture or construct the smallest state reproducing the NAS loop and pin it with a regression
   test. A no-op sync over it reaches idle without the guard.
6. One domain query defines counts by lifecycle and phase. Both endpoints, workers, and the UI use
   it. A genuinely different question receives a different metric name, not another `pending`.
7. Queue diagnostics identify reasons and affected tracks without direct database inspection.

## Phased Delivery

1. **Observe:** add reason codes and capture the looping transitions.
2. **Reproduce:** reduce production state to a deterministic fixture.
3. **Converge:** centralize transitions and bounded retry.
4. **Unify:** move public status and UI surfaces to the domain query.

**Exit condition:** the captured workload terminates without churn timeout, contract tests make
public status agree, and the UI distinguishes queued, active, retrying, failed, and complete work.

## Alternatives Considered

**Increase or remove the guard.** Rejected because it spends more time on the loop and removes the
signal that exposed it.

**Document different endpoint meanings.** Acceptable only if they truly differ. Rejected as the
default while both present an ambiguously named pending count.

**Fix only the current analyzer.** Rejected because another analyzer could recreate the same
unbounded transition; lifecycle ownership is the durable boundary.

## Consequences

- **Positive:** an empty sync finishes promptly and failed work is visible.
- **Positive:** clients share one vocabulary and set of counts.
- **Tradeoff:** explicit retry state may require persisted or Redis schema changes.
- **Tradeoff:** tracks formerly retried forever may require deliberate retry after repair.
