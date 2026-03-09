# Phase 5 Audit (Item 2): Flaky Test Risks + Weak CI Gate Analysis

Date: 2026-03-08

## Scope
This artifact covers Phase 5 checklist item 2 only:
- Identify flaky tests and weak gating in CI workflows.

## Evidence Sources
- `/Users/jeff/Developer/familiar/.github/workflows/ci.yml`
- `/Users/jeff/Developer/familiar/.github/workflows/release.yml`
- `/Users/jeff/Developer/familiar/backend/tests/conftest.py`
- `/Users/jeff/Developer/familiar/backend/tests/test_migrations.py`
- `/Users/jeff/Developer/familiar/backend/tests/test_metadata_writer.py`
- `/Users/jeff/Developer/familiar/backend/tests/test_flac_remux.py`
- `/Users/jeff/Developer/familiar/backend/tests/test_feature_algorithms.py`
- `/Users/jeff/Developer/familiar/backend/tests/test_embedding_map.py`
- `/Users/jeff/Developer/familiar/backend/pyproject.toml`

## Findings (Ranked)
1. P1: Release workflow is not quality-gated by backend test/contract/migration jobs.
- Evidence:
  - `release.yml` builds/pushes image directly, with no dependency on CI test jobs.
- Risk:
  - A tagged release can ship even if backend test quality regressions are unresolved on default branch.

2. P1: Session-scoped `TestClient` with shared app lifecycle amplifies cross-test coupling.
- Evidence:
  - `backend/tests/conftest.py` defines `client` as `scope="session"` with app startup once.
  - Same fixture uses `raise_server_exceptions=False`.
- Risk:
  - Hidden order-dependent state leaks across test modules (background manager/scheduler/singletons).
  - Cascading failures can appear/non-appear depending on collection order and prior fixture mutations.

3. P1: Migration tests shell out multiple subprocess calls and partially ignore intermediate failures.
- Evidence:
  - `test_migrations.py` runs `subprocess.run(... alembic upgrade head ...)` in multiple tests.
  - Some intermediate subprocess return codes are not asserted immediately.
- Risk:
  - Non-deterministic environment failures can produce confusing follow-on errors rather than direct root-cause failure.

4. P1: Backend CI relies on environment-dependent skips for multimedia tests, with no skip budget enforcement.
- Evidence:
  - `test_metadata_writer.py` and `test_flac_remux.py` skip when ffmpeg/ffprobe unavailable or fixture conversions fail.
  - Additional skip gates in `test_feature_algorithms.py` when `librosa` is missing.
- Risk:
  - Critical media-path coverage can silently drop while pipeline still passes green.

5. P2: Randomized numerical test inputs are unseeded in several algorithm tests.
- Evidence:
  - `test_feature_algorithms.py` and `test_embedding_map.py` use `np.random.*` without deterministic seed.
- Risk:
  - Rare statistical edge cases can trigger intermittent failures; failures are harder to reproduce exactly.

6. P2: CI does not split backend tests by risk bucket; one full pytest run is the only backend quality gate.
- Evidence:
  - `ci.yml` backend-test job runs `uv run pytest -v --tb=short` as a single gate.
- Risk:
  - Slow/flaky subsets can destabilize the entire gate; hard to identify whether failures are critical-path regressions vs long-tail flakes.

7. P2: Coverage threshold is low relative to critical-path risk.
- Evidence:
  - `backend/pyproject.toml` enforces `--cov-fail-under=38`.
- Risk:
  - CI can pass with materially weak coverage in high-risk backend paths (sync/resilience/contract surfaces).

## What Is Already Strong
- CI backend-test job enforces DB migrations (`alembic upgrade head`) and migration preflight (`assert_database_at_head()`) before running pytest.
- Backend lint + mypy are explicit CI jobs.
- Contract-focused suite exists (`test_api_contract_error_shapes.py`) and is wired in `Makefile:test-contract`.

## Weak Gate Summary
- Missing release-time quality dependency chain (tests are not mandatory precondition in `release.yml`).
- Missing skip budget / required dependency verification for media-heavy suites.
- Missing deterministic policy for random-input tests.
- Missing risk-bucket job split for faster attribution and less flaky blast radius.

## Decision-Ready Remediation Batches
Batch A (immediate, low risk):
1. Add release gate precondition:
- Require successful `CI` workflow conclusion before `release.yml` build-and-push proceeds.

2. Add deterministic test policy:
- Seed numpy random usage in affected tests (fixed seed per module) and log seed on failure.

3. Add skip observability:
- Collect and fail on excessive skip count in backend CI (global skip budget + required-suite skip budget).

Batch B (medium risk):
1. Split backend pytest in CI into risk buckets:
- `contract+migrations`, `background/sync`, `core API`, `integration/slow`.
- Keep each bucket with explicit timeout and artifacted output.

2. Harden migration test subprocess assertions:
- Assert every subprocess step return code immediately to reduce ambiguous failures.

Batch C (medium/high risk):
1. Reduce shared-lifecycle coupling:
- Migrate high-risk API suites from session-scoped client to function-scoped client where feasible.
- Add a singleton state reset fixture for background manager similar to artwork fetcher reset.

2. Raise quality bar by bucket:
- Replace one global `38%` threshold with minimum per-risk-category thresholds.

## Reproducibility Commands
Run from repo root:

```bash
# Find skip/skipif/xfail usage
rg -n "pytest\.mark\.(skip|skipif|xfail)|pytest\.skip\(" backend/tests

# Find randomized test inputs
rg -n "np\.random|random\." backend/tests

# Inspect backend CI gates
sed -n '1,320p' .github/workflows/ci.yml

# Inspect release workflow dependencies
sed -n '1,260p' .github/workflows/release.yml

# Inspect coverage threshold
sed -n '130,220p' backend/pyproject.toml
```

## Completion Note
Phase 5 item 2 is complete once this artifact is linked in the backend roadmap and used to drive item 3 (minimum quality gates by risk category).
