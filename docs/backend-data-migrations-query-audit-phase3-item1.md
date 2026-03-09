# Backend Data Model, Migrations & Query Audit (Phase 3, Item 1)

Date: 2026-03-08

## Scope
Audit focus:
- Model-to-migration parity and schema drift risk.
- Migration safety/idempotency and downgrade policy consistency.
- High-risk query/index alignment for core API paths.

Primary evidence:
- `/Users/jeff/Developer/familiar/backend/app/db/models/**`
- `/Users/jeff/Developer/familiar/backend/migrations/versions/**`
- `/Users/jeff/Developer/familiar/backend/tests/test_migrations.py`
- `/Users/jeff/Developer/familiar/backend/app/api/routes/**`

## Findings (Ranked)
1. P1: Parity protection exists but is split across runtime/test gates.
- Strengths:
  - baseline migration builds from current `Base.metadata.create_all(...)`.
  - CI backend test and e2e jobs run `alembic upgrade head` + migration preflight.
  - `test_migrations.py` includes `alembic check` drift detection.
- Risk:
  - Drift still surfaces late as runtime failures when environments skip upgrade/preflight (already seen in prior contract runs).

2. P1: Migration idempotency pattern is mostly good but inconsistent.
- Many migrations correctly use `_column_exists` / `_table_exists` guards.
- Some downgrades perform unconditional destructive ops (for example older migrations dropping columns without guard checks), while newer ones are guarded.
- Result: downgrade/idempotent behavior is not uniform across the chain.

3. P1: Downgrade policy is inconsistent (reversible vs one-way/no-op).
- Several migrations explicitly use one-way `downgrade: pass` for removed features (`drop_*` migrations).
- Others attempt full reversibility.
- Result: rollback expectations are ambiguous unless policy is documented/enforced.

4. P1: Core listing/search queries rely on patterns with weak index support.
- `tracks/listing.py` and related paths use multiple `ILIKE` filters on `title/artist/album`.
- There are B-tree indexes on `artist/album/title`-adjacent fields, but no trigram indexes for wildcard search patterns.
- Risk: poor selectivity and scan-heavy behavior as library size grows.

5. P2: Frontend log query path is index-misaligned.
- `diagnostics.py` filters/orders by `client_ts` and `message ILIKE`, but `frontend_logs` indexes are on `server_ts/level/namespace`.
- Risk: expensive scans for time-filtered/search-heavy diagnostics queries.

6. P2: Feature-version filtering has no dedicated index.
- Core analysis status paths use `TrackAnalysis.features_version` thresholds.
- No explicit index on `features_version` currently.
- Risk: avoidable full/large scans on `track_analysis` for status and queueing logic.

7. P2: Migration metadata is structurally valid but naming/comments drift exists.
- Revision/down_revision graph resolves cleanly (25 revisions, no unresolved refs).
- Some docstring `Revises:` labels differ from canonical revision IDs used in code.
- Risk: operator confusion during manual triage.

## What Is Already Strong
- Revision IDs are within 32-char constraint and unique.
- Head merge exists (`20260306_merge_heads`) and graph resolves cleanly.
- Advanced index work already present for known hotspots:
  - HNSW embedding index migration.
  - functional `lower(trim(...))` indexes for artist/album normalization paths.
  - GIN index for `track_analysis.mood_tags`.

## Decision-Ready Remediation Batches
Batch A (immediate, low risk):
- Publish explicit migration policy:
  - “one-way” vs “reversible” migrations must be declared in file header.
  - require guard helpers for destructive downgrade ops when downgrade is supported.
- Add CI lint-style check for migration doc consistency:
  - revision/down_revision parse validity,
  - optional check that docstring `Revision/Revises` matches code identifiers.
- Keep `alembic upgrade head` + preflight as mandatory before contract tests (already in CI; enforce in local runbook too).

Batch B (medium risk):
- Add targeted indexes for current query load:
  - trigram GIN indexes on `tracks.title`, `tracks.artist`, `tracks.album` for wildcard search.
  - index on `track_analysis.features_version`.
  - index on `frontend_logs.client_ts` (and optionally trigram index on `message` if diagnostics search is frequent).
- Add `EXPLAIN ANALYZE` validation notes for listing/search/diagnostics endpoints.

Batch C (medium/high risk):
- Normalize downgrade behavior:
  - choose a single policy (strictly reversible vs explicitly one-way),
  - apply consistently and document in migration template.
- Add migration regression tests:
  - representative downgrade/upgrade cycle for reversible migrations,
  - explicit assertion that one-way migrations are tagged and excluded from downgrade cycle tests.

## Acceptance Checks for This Audit Item
- [x] Model-to-migration parity posture evaluated with current safeguards and gaps.
- [x] Migration safety/idempotency and downgrade consistency reviewed with concrete examples.
- [x] High-risk query/index mismatches identified on core route paths.
- [x] Refactor/remediation batches defined with risk ordering.

## Reproducibility Commands
- Migration inventory:
  - `ls -1 backend/migrations/versions | sort`
- Migration ops scan:
  - `rg "op\\.add_column|op\\.drop_column|op\\.create_index|op\\.drop_index|op\\.drop_table|op\\.alter_column" backend/migrations/versions -n`
- Query/filter scan:
  - `rg "ilike|order_by\\(|features_version|mood_tags|embedding" backend/app/api/routes backend/app/services -n`
- Migration guard checks:
  - `sed -n '1,220p' backend/tests/test_migrations.py`
