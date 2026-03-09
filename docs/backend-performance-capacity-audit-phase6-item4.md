# Backend Performance & Capacity Audit (Phase 6, Item 4): Observability Metrics, Dashboards, and Enforceable Thresholds

Date: 2026-03-08

## Scope
This artifact covers Phase 6 checklist item 4 only:
- Define observability metrics/dashboards and enforceable performance thresholds.

This is a governance/specification artifact for operational guardrails. It defines what must be measured, where surfaced, and what is gate-blocking.

## Inputs and Dependencies
- Phase 6 item 1 baseline budgets:
  - `/Users/jeff/Developer/familiar/docs/backend-performance-capacity-audit-phase6-item1.md`
- Phase 6 item 2 hotspot findings:
  - `/Users/jeff/Developer/familiar/docs/backend-performance-capacity-audit-phase6-item2.md`
- Phase 6 item 3 queue/throughput findings:
  - `/Users/jeff/Developer/familiar/docs/backend-performance-capacity-audit-phase6-item3.md`
- Existing diagnostics/health surfaces:
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/health.py`
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/diagnostics.py`
  - `/Users/jeff/Developer/familiar/backend/app/services/background/events.py`
  - `/Users/jeff/Developer/familiar/backend/app/logging_config.py`

## Metrics Specification

### A) API latency/throughput metrics (Tier A/B/C)
Dimensions:
- `route_template`
- `method`
- `status_class` (`2xx/4xx/5xx`)
- `deployment_mode` (`local/docker`)

Required metrics:
1. `api_requests_total` (counter)
2. `api_request_duration_ms` (histogram)
3. `api_inflight_requests` (gauge)
4. `api_errors_total` (counter, `status_class=5xx`)

Tier A routes (required):
- `/tracks` (GET)
- `/tracks/batch` (POST)
- `/tracks/{id}/stream` (GET, TTFB proxy)
- `/library/artists` (GET)

Tier B routes (required):
- `/library/albums` (GET)
- `/favorites` (GET)
- `/playlists` (GET)
- `/library/letter-index` (GET)

Tier C routes (required):
- `/chat/stream` (POST, first-token latency)
- `/library/map` + `/library/map/stream` (GET)

### B) Background throughput/pressure metrics
Dimensions:
- `phase` (`features|embeddings|backfill|melodic|mood_tags`)
- `executor_lane` (`main|ondemand`)

Required metrics:
1. `analysis_queue_depth` (gauge, total + per-phase)
2. `analysis_queue_admissions_total` (counter)
3. `analysis_tasks_completed_total` (counter)
4. `analysis_task_duration_seconds` (histogram)
5. `analysis_drain_rate_tracks_per_min` (gauge, rolling 5m)
6. `sync_phase_requeue_attempts_total` (counter)
7. `sync_phase_stall_recoveries_total` (counter)
8. `sync_phase_forced_exit_total` (counter by reason)
9. `executor_reset_total` (counter by reason)
10. `executor_breaker_disabled_total` (counter)

### C) Query-pressure metrics
Required metrics:
1. `db_query_count_per_request` (histogram)
2. `db_query_duration_ms` (histogram)
3. `db_slow_query_total` (counter; thresholded)

Minimum threshold definitions:
- Slow query candidate: `> 250 ms` for API routes, `> 500 ms` for background jobs.
- Critical slow query: `> 1000 ms`.

## Dashboard Design (Minimum Required)

### Dashboard 1: API Performance Overview
Panels:
1. p50/p95/p99 latency by Tier A route (last 15m, 1h, 24h)
2. req/s by route + status class
3. 5xx error rate by route
4. stream TTFB trend for `/tracks/{id}/stream`
5. first-token latency trend for `/chat/stream`

### Dashboard 2: Background Capacity + Pressure
Panels:
1. analysis queue depth (total + per phase)
2. admissions vs completions rate (tracks/min)
3. drain rate and oldest queued task age
4. executor resets and breaker disable events
5. sync phase requeue/stall/forced-exit counts

### Dashboard 3: Query Health
Panels:
1. request query-count distribution by route
2. slow-query count by route/family
3. top query signatures by p95 duration
4. diagnostics/frontend-log query latency trend

## Enforceable Thresholds (Policy)

### Runtime alert thresholds
P0 alerts:
1. Tier A route p95 exceeds baseline by >40% for 15 minutes.
2. API 5xx rate >2% for 10 minutes on any Tier A route.
3. `analysis_queue_depth` > 2000 for 15 minutes.
4. `analysis_drain_rate_tracks_per_min` near zero with pending > 0 for 10 minutes.
5. `executor_breaker_disabled_total` increments.

P1 alerts:
1. Tier B route p95 exceeds baseline by >50% for 30 minutes.
2. repeated `sync_phase_stall_recoveries_total` increments >5 per hour per phase.
3. forced sync phase exits with timeout/churn reasons.

### CI/Release performance gates
Blocking on release branch:
1. Tier A synthetic perf run produces:
- p95 within baseline +25%
- p99 within baseline +35%
2. No new endpoint with `db_query_count_per_request` regression >30% in touched route family.
3. No new critical slow query (`>1000 ms`) in perf artifact.

Non-blocking (warn-only initially):
1. Tier B route p95 drift >25%.
2. queue/drain imbalance warnings in soak run.

## Rollout Plan

### Stage 1 (instrumentation)
1. Add request-timing middleware and route-template tagging.
2. Add background queue/drain gauges from existing progress/event data.
3. Export metrics to diagnostics endpoint payload and logs.

### Stage 2 (dashboard + alerting)
1. Stand up the 3 dashboards above.
2. Configure P0/P1 alerts.
3. Validate alert noise for one week (tune thresholds once).

### Stage 3 (enforcement)
1. Add CI perf artifact generation (`artifacts/perf/backend-metrics.json`).
2. Enforce release gates for Tier A.
3. Keep Tier B/C as warning until stable over two release cycles.

## Artifact Contract (for CI/ops tooling)
Required JSON fields in `artifacts/perf/backend-metrics.json`:
- `timestamp`
- `environment`
- `routes[].route_template`
- `routes[].p50_ms`
- `routes[].p95_ms`
- `routes[].p99_ms`
- `routes[].throughput_rps`
- `routes[].error_rate`
- `background.queue_depth_total`
- `background.drain_rate_tracks_per_min`
- `background.executor_resets`
- `background.breaker_disabled`
- `db.slow_query_count`
- `db.critical_slow_query_count`

## Acceptance for Phase 6 Item 4
- [x] Core metric catalog defined (API, background, DB).
- [x] Minimum dashboard set and panel requirements defined.
- [x] Runtime alert thresholds and CI/release gates defined.
- [x] Rollout sequence and CI artifact contract documented.

