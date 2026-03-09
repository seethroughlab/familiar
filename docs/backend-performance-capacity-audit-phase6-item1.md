# Backend Performance & Capacity Audit (Phase 6, Item 1): Latency/Throughput Baselines

Date: 2026-03-08

## Scope
This artifact covers Phase 6 checklist item 1 only:
- Establish latency and throughput budget baselines for high-traffic backend endpoints.

It does not yet include:
- Deep slow-query/N+1 profiling (Phase 6 item 2).
- Worker queue throughput/capacity analysis (Phase 6 item 3).
- Dashboard/alert enforcement rollout (Phase 6 item 4).

## Evidence Sources
- Route surfaces:
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/tracks/listing.py`
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/tracks/streaming.py`
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/library_artists.py`
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/library_albums.py`
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/playlists.py`
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/favorites.py`
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/chat.py`
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/library_maps.py`
- App middleware/observability:
  - `/Users/jeff/Developer/familiar/backend/app/main.py`
  - `/Users/jeff/Developer/familiar/backend/app/logging_config.py`
  - `/Users/jeff/Developer/familiar/backend/app/api/routes/diagnostics.py`
- Frontend call surfaces:
  - `/Users/jeff/Developer/familiar/packages/frontend/src/api/tracks.ts`
  - `/Users/jeff/Developer/familiar/packages/frontend/src/api/library.ts`
  - `/Users/jeff/Developer/familiar/packages/frontend/src/api/playlists.ts`
  - `/Users/jeff/Developer/familiar/packages/frontend/src/api/profiles.ts`
  - `/Users/jeff/Developer/familiar/packages/frontend/src/api/chat.ts`

## High-Traffic Endpoint Set (Baseline Tiering)
Tier assignment criteria:
- Tier A: invoked repeatedly during normal browsing/playback flows.
- Tier B: frequent but less bursty.
- Tier C: heavy/expensive or bursty specialty paths.

| Tier | Endpoint | Why It Is Hot |
|---|---|---|
| A | `GET /api/v1/tracks` | Primary library track browsing path; paginated list requests throughout app usage. |
| A | `POST /api/v1/tracks/batch` | Used to hydrate visible queue/list slices repeatedly. |
| A | `GET /api/v1/tracks/{id}/stream` | Core playback path; sustained during active listening sessions. |
| A | `GET /api/v1/library/artists` | Default library landing path and frequent navigation target. |
| B | `GET /api/v1/library/albums` | High-use browsing path, typically paginated and searchable. |
| B | `GET /api/v1/favorites` | Common daily path for mobile/desktop users. |
| B | `GET /api/v1/playlists` | Sidebar/playlist management refresh path. |
| B | `GET /api/v1/library/letter-index` | Drives alphabet jump UX for long lists. |
| C | `POST /api/v1/chat/stream` | SSE and external LLM dependency; high latency variance risk. |
| C | `GET /api/v1/library/map` and `GET /api/v1/library/map/stream` | Embedding/UMAP-heavy compute path with bounded `limit` but high compute cost. |

## Baseline Budgets (Initial)
These are the initial acceptance baselines for this phase and are intentionally conservative enough to gate regressions before full tuning.

| Endpoint | Budget p50 | Budget p95 | Budget p99 | Minimum Throughput Target |
|---|---:|---:|---:|---:|
| `GET /tracks` (`page_size<=100`) | 120 ms | 300 ms | 600 ms | 80 req/s |
| `POST /tracks/batch` (`<=50 ids`) | 80 ms | 220 ms | 450 ms | 120 req/s |
| `GET /tracks/{id}/stream` (TTFB, local file) | 90 ms | 250 ms | 500 ms | 40 starts/s |
| `GET /library/artists` (`page_size<=100`) | 150 ms | 400 ms | 800 ms | 50 req/s |
| `GET /library/albums` (`page_size<=100`) | 170 ms | 450 ms | 900 ms | 40 req/s |
| `GET /favorites` | 120 ms | 320 ms | 700 ms | 60 req/s |
| `GET /playlists` | 90 ms | 250 ms | 550 ms | 70 req/s |
| `GET /library/letter-index` | 100 ms | 260 ms | 550 ms | 80 req/s |
| `POST /chat/stream` (first SSE token) | 1500 ms | 3500 ms | 7000 ms | 5 concurrent streams |
| `GET /library/map` (`limit=200`) | 1200 ms | 3500 ms | 7000 ms | 2 req/s |

Notes:
- Stream budget is TTFB for a valid local file, not full-track transfer completion.
- Chat/map budgets are set as guardrails for user-perceived responsiveness, not strict hard real-time guarantees.
- Final thresholds should be tightened after Phase 6 item 2 query profiling.

## Measurement Method (Reproducible)
Environment:
- Run against the same deployment mode each time (local or NAS), record mode in results.
- Use representative dataset size for comparisons.

Required request headers:
- Include `X-Profile-ID` for protected endpoints.

### 1) Single-endpoint latency sweep
Use repeated curl timing captures (no external tools required):

```bash
URL="http://localhost:4400/api/v1/tracks?page=1&page_size=50"
PROFILE_ID="<profile-id>"
for i in $(seq 1 100); do
  curl -sS -o /dev/null -w "%{time_total}\n" \
    -H "X-Profile-ID: ${PROFILE_ID}" \
    "${URL}"
done | sort -n > /tmp/tracks_times.txt
```

Then compute quantiles from sorted values:
- p50: line 50
- p95: line 95
- p99: line 99

### 2) Concurrency throughput sweep
If `hey` is available:

```bash
hey -n 2000 -c 40 -H "X-Profile-ID: <profile-id>" \
  "http://localhost:4400/api/v1/tracks?page=1&page_size=50"
```

Fallback without `hey`:

```bash
seq 1 400 | xargs -n1 -P20 -I{} \
  curl -sS -o /dev/null -H "X-Profile-ID: <profile-id>" \
  "http://localhost:4400/api/v1/tracks?page=1&page_size=50"
```

### 3) Stream TTFB baseline

```bash
TRACK_ID="<known-track-id>"
curl -sS -o /dev/null -w "%{time_starttransfer}\n" \
  -H "X-Profile-ID: <profile-id>" \
  "http://localhost:4400/api/v1/tracks/${TRACK_ID}/stream"
```

### 4) Chat first-token baseline

```bash
curl -N -sS \
  -H "Content-Type: application/json" \
  -H "X-Profile-ID: <profile-id>" \
  -d '{"message":"play calm ambient music","history":[]}' \
  "http://localhost:4400/api/v1/chat/stream"
```

Measure time from request start to first `data:` frame.

## Current Gaps Blocking Stronger Baselines
1. No universal request-timing middleware.
- `RequestIDMiddleware` exists, but per-request `duration_ms` is not automatically emitted for all routes.
2. No endpoint-level latency histogram in diagnostics export.
- Diagnostics currently exports recent logs/failures/system health, not percentile latency per endpoint.
3. No CI perf gate for high-traffic backend endpoints.
- Current CI enforces correctness/lint/migrations, but not regression thresholds for response-time/throughput.

## Immediate Follow-Ups (feeds Phase 6 items 2-4)
1. Add HTTP timing middleware that logs:
- `route_template`, `method`, `status_code`, `duration_ms`, `request_id`.
2. Add a small perf baseline artifact in CI output for Tier A endpoints:
- JSON file with p50/p95/p99 + req/s from controlled run.
3. Add diagnostics summary endpoint fields:
- last 15-minute rolling p95 for Tier A endpoints.

## Acceptance for Phase 6 Item 1
- [x] High-traffic endpoint shortlist identified and tiered.
- [x] Initial latency and throughput baseline budgets defined.
- [x] Reproducible measurement method documented.
- [x] Gaps preventing stronger enforcement explicitly listed.

