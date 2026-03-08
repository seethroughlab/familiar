# Phase 6 Audit (Item 3): Measurable Performance Budgets and Tracking

## Scope
This artifact covers Phase 6 checklist item 3 only:
- Propose measurable performance budgets and tracking.

## Inputs
- Bundle audit: [frontend-performance-bundle-audit-phase6-item1.md](/Users/jeff/Developer/familiar/docs/frontend-performance-bundle-audit-phase6-item1.md)
- Rerender/virtualization audit: [frontend-rerender-virtualization-audit-phase6-item2.md](/Users/jeff/Developer/familiar/docs/frontend-rerender-virtualization-audit-phase6-item2.md)
- Current CI workflow: [ci.yml](/Users/jeff/Developer/familiar/.github/workflows/ci.yml)

## Current Baseline Signals
- Entry chunk gzip currently ~`457 kB` (from item 1).
- No explicit frontend performance budget gates in CI.
- No standardized app-level perf telemetry for render/scroll/mount churn in diagnostics.

## Budget Matrix (Decision-Complete)

| Category | Metric | Target | Hard Fail Threshold | Scope |
|---|---|---:|---:|---|
| Bundle startup | Entry JS gzip | <= 300 kB | > 350 kB | Web build |
| Bundle growth | Entry gzip delta per PR | <= +15 kB | > +30 kB | PR vs baseline |
| Lazy feature | Largest lazy chunk gzip | <= 120 kB | > 180 kB | Web build |
| CSS | Main CSS gzip | <= 18 kB | > 25 kB | Web build |
| Render cost | `PlaylistTrackList` commit (1000 rows test fixture) | <= 120 ms | > 220 ms | Perf test |
| Render cost | `QueueView` commit (1000 rows fixture) | <= 80 ms | > 160 ms | Perf test |
| Scroll smoothness | Library track-list scroll dropped frame ratio | <= 5% | > 10% | Browser perf run |
| DOM pressure | Mobile list rendered rows (steady state) | <= 250 | > 500 | Runtime metric |
| Route churn | Route subtree remounts per navigation | <= 1 expected remount | > 1 unexpected remount | Runtime metric |

## Tracking Specification

### 1) Build-Time Artifact Metrics
1. Produce `packages/web/dist/.vite/manifest.json` and parse:
   - entry chunk size/gzip
   - top 10 chunks
   - largest lazy chunk
2. Emit machine-readable report:
   - `artifacts/perf/bundle-metrics.json`
   - `artifacts/perf/bundle-metrics.md`

### 2) Runtime App Metrics (Diagnostics Integration)
Add counters in the existing diagnostics surface:
1. `ui_render_playlist_rows`
2. `ui_render_queue_rows`
3. `ui_route_subtree_remounts`
4. `ui_mobile_list_dom_nodes`
5. `ui_scroll_frame_drop_ratio_tracks`

Sampling policy:
1. Collect at 1 Hz while relevant surface is visible.
2. Keep ring buffer of last 5 minutes.
3. Include max/p95/latest in diagnostics export.

### 3) Test-Time Performance Benchmarks
1. Add focused perf test harness (non-blocking initially):
   - `PlaylistTrackList` large fixture render/interaction time.
   - `QueueView` large fixture render + reorder action.
2. Output benchmark JSON:
   - `artifacts/perf/component-benchmarks.json`

## CI Gate Policy

### Gate A (Immediate, blocking)
1. Add bundle metric extraction step after web build.
2. Fail CI on hard thresholds:
   - entry gzip > 350 kB
   - largest lazy chunk > 180 kB
3. Warn (non-blocking) on target threshold misses.

### Gate B (Near term, mixed)
1. Add PR delta comparison against `master` baseline artifact.
2. Fail CI if entry gzip delta > +30 kB without explicit waiver label.
3. Publish bundle trend chart as build artifact.

### Gate C (Later, blocking for critical paths)
1. Promote component perf benchmarks to blocking for touched surfaces:
   - playlist/queue/library-list files.
2. Add browser scroll perf check for track-list route with synthetic data.

## Ownership and Review Cadence
1. Owner: Frontend playback/library maintainers.
2. Weekly budget review in release checklist:
   - entry chunk trend
   - lazy chunk outliers
   - diagnostics p95 render/scroll counters.
3. Any threshold override requires:
   - linked issue
   - rollback or follow-up reduction plan
   - expiration date.

## Reproducibility Commands
Run from repo root:

```bash
# Build with manifest
cd packages/web && npx vite build --manifest --sourcemap

# Print largest bundles
cd dist/assets && ls -l *.js | awk '{print $5, $9}' | sort -nr | head -n 20

# Inspect current CI gates
sed -n '1,420p' .github/workflows/ci.yml
```

## Completion Note
Phase 6 is complete when this artifact is linked in roadmap, Phase 6 item 3 is checked, and Gate A is scheduled as the next implementation batch.
