# Backend Performance & Capacity Audit (Phase 6, Item 2): Slow Query + N+1 Hotspots

Date: 2026-03-08

## Scope
This artifact covers Phase 6 checklist item 2 only:
- Audit slow query and N+1 risk hotspots with measurable evidence.

This pass is code-and-query-shape based. It includes reproducible `EXPLAIN (ANALYZE, BUFFERS)` commands for runtime verification on NAS/local datasets.

## Evidence Sources
- Query-heavy routes:
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/tracks/listing.py`
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/library_discover.py`
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/analysis.py`
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/playlists.py`
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/library_aggregations.py`
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/diagnostics.py`
- Model/index definitions:
  - `/Users/jeff/Developer/familiar/backend/app/db/models/tracks.py`
  - `/Users/jeff/Developer/familiar/backend/app/db/models/frontend_log.py`
- Prior index audit context:
  - `/Users/jeff/Developer/familiar/docs/backend-data-migrations-query-audit-phase3-item1.md`

## Ranked Findings

### 1) P0: `GET /tracks/analysis/bulk/{task_id}/report` has explicit `2N+1` DB pattern
- Evidence:
  - Per track ID, one query for `TrackAnalysis` and one for `Track` inside loop:
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/analysis.py:78`
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/analysis.py:86`
- Measurable impact model:
  - DB round trips = `1 + 2N` where `N = len(progress["track_ids"])`.
  - Example: `N=100` => `201` DB queries before report assembly.
- Risk:
  - Latency grows linearly with track count and can spike under larger bulk analysis reports.

### 2) P1: `GET /library/discover` performs DB query inside similar-artist loop (N+1)
- Evidence:
  - For each similar artist candidate, route runs `select(count(Track.id))`:
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/library_discover.py:118`
  - Outer loops over top artists and up to 3 similars each:
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/library_discover.py:81`
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/library_discover.py:108`
- Measurable impact model:
  - DB round trips ~= `2 + S` where `S` is number of processed similar artists.
  - Current bound is moderate, but still scales linearly and adds avoidable latency.

### 3) P1: `POST /playlists` create path does per-track existence load (N+1)
- Evidence:
  - Track verification uses `await db.get(...)` inside loop:
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/playlists.py:162`
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/playlists.py:169`
- Measurable impact model:
  - DB round trips ~= `1 + N` for create with `N` track IDs (plus commit/flush overhead).
  - With large imported playlists this increases request time and DB load.

### 4) P1: `/tracks` and `/tracks/ids` use dual-query pagination + wildcard ILIKE filters
- Evidence:
  - Separate count subquery and data query:
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/tracks/listing.py:115`
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/tracks/listing.py:142`
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/tracks/listing.py:291`
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/tracks/listing.py:322`
  - Search path uses `%term%` across title/artist/album:
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/tracks/listing.py:73-78`
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/tracks/listing.py:244-249`
- Measurable impact model:
  - Minimum 2 queries/request (+1 play-history query in `/tracks` when profile + results present).
  - Wildcard predicates are prone to sequential scans without trigram indexes.

### 5) P2: `GET /library/letter-index` uses windowed row-number subqueries
- Evidence:
  - Tracks/artists/albums branches each build row-number subquery + aggregate pass:
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/library_aggregations.py:288`
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/library_aggregations.py:354`
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/library_aggregations.py:435`
- Measurable impact model:
  - Cost grows with cardinality of filtered set; can become expensive under broad searches.
  - Still preferable to per-letter scans, but should be measured and cached where possible.

### 6) P2: Frontend log query path is index-misaligned for common filters
- Evidence:
  - Query orders by/filters on `client_ts` and supports `message ILIKE`:
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/diagnostics.py:263`
    - `/Users/jeff/Developer/familiar/backend/app/api/routes/diagnostics.py:289`
  - `frontend_logs` indexes are only `server_ts`, `level`, `namespace`:
    - `/Users/jeff/Developer/familiar/backend/app/db/models/frontend_log.py:19-21`
- Measurable impact model:
  - Query can degrade to scans/sorts for time-window searches on `client_ts`.
  - `message ILIKE` can become costly without trigram support.

## Hotspot Measurement Plan (Executable)
Run against representative dataset/profile.

### A) Bulk analysis report (`2N+1`) proof
1. Trigger/locate a task with at least 50 track IDs.
2. Observe query count and total time while requesting:
   - `GET /api/v1/tracks/analysis/bulk/{task_id}/report`
3. Verify linear growth by repeating with larger `N`.

SQL shape to benchmark in DB:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM track_analysis WHERE track_id = ANY(:track_ids);

EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM tracks WHERE id = ANY(:track_ids);
```

### B) Library discover N+1 proof
Endpoint:
- `GET /api/v1/library/discover?recommendations_limit=8`

Query to replace looped count checks:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT lower(trim(artist)) AS artist_normalized, count(id) AS track_count
FROM tracks
WHERE lower(trim(artist)) = ANY(:similar_normalized)
  AND status = 'active'
GROUP BY lower(trim(artist));
```

### C) Tracks listing + wildcard search
Endpoint:
- `GET /api/v1/tracks?page=1&page_size=50&search=<term>`

Representative plan checks:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT id
FROM tracks
WHERE lower(title) LIKE :q OR lower(artist) LIKE :q OR lower(album) LIKE :q
ORDER BY artist, album, track_number
LIMIT 50 OFFSET 0;
```

### D) Diagnostics frontend logs
Endpoint:
- `GET /api/v1/diagnostics/frontend-logs?since=...&search=...&limit=100`

Representative plan checks:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT *
FROM frontend_logs
WHERE client_ts >= :since
  AND message ILIKE :q
ORDER BY client_ts DESC
LIMIT 100;
```

## Decision-Ready Remediation Batches

### Batch A (immediate, low risk)
1. Fix `2N+1` in bulk analysis report:
- Replace per-track loop queries with two batched queries (`IN (...)`) and in-memory map join.
2. Fix playlist-create per-track loads:
- Batch fetch `Track` rows by all UUIDs once, then validate/order in-memory.
3. Fix discover looped library checks:
- Single grouped query for all candidate similar artists.

Expected impact:
- Large latency drops on report generation and playlist create paths.
- Lower DB connection churn.

### Batch B (medium risk)
1. Optimize tracks/listing search predicates:
- Add trigram indexes for `title/artist/album` (already identified in Phase 3 artifact).
2. Review whether `count(*)` should be skipped/approximated for some hot list endpoints under specific UI contexts.
3. Add cache TTL for expensive but stable aggregation endpoints (`letter-index` variants).

Expected impact:
- Better p95 under broad search and large library cardinality.

### Batch C (medium risk)
1. Diagnostics query index alignment:
- Add index on `frontend_logs.client_ts`.
- Optional trigram index on `frontend_logs.message` if text-search is operationally common.
2. Add query-level instrumentation:
- Log route template + query count + duration at request scope for top endpoints.

Expected impact:
- Stronger production triage and faster regression detection.

## Suggested Acceptance Checks for Item 2 Completion
- [x] At least 5 concrete slow/N+1 hotspots identified with file/line evidence.
- [x] Each P0/P1 hotspot has explicit query-count growth model.
- [x] Reproducible `EXPLAIN (ANALYZE, BUFFERS)` commands provided for validation.
- [x] Remediation batches defined with risk ordering.

