# ADR-0172: Analysis Work Converges and Has One Status Model

Status: proposed

Date: 2026-11-08

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
