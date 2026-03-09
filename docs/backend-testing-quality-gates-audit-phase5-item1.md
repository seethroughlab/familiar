# Phase 5 Audit (Item 1): Backend Risk Categories vs Existing Test Coverage

Date: 2026-03-08

## Scope
This artifact covers Phase 5 checklist item 1 only:
- Map backend risk categories to existing unit/integration/contract tests.

## Evidence Sources
- Test inventory: `/Users/jeff/Developer/familiar/backend/tests/**`
- CI workflow: `/Users/jeff/Developer/familiar/.github/workflows/ci.yml`
- Backend test config/gates:
  - `/Users/jeff/Developer/familiar/backend/pyproject.toml`
  - `/Users/jeff/Developer/familiar/backend/Makefile`
- Prior backend risk artifacts:
  - `/Users/jeff/Developer/familiar/docs/backend-api-error-contract-audit-phase2-item1.md`
  - `/Users/jeff/Developer/familiar/docs/backend-error-status-consistency-audit-phase2-item2.md`
  - `/Users/jeff/Developer/familiar/docs/backend-data-migrations-query-audit-phase3-item1.md`
  - `/Users/jeff/Developer/familiar/docs/backend-background-resilience-audit-phase4-item1.md`

## Coverage Snapshot
- Backend test files: 44 (`backend/tests/test_*.py`).
- Integration-focused files: 7 (`*_integration.py`).
- API route-focused files: 15 (`test_api_*.py`).
- Dedicated migration + contract + background resilience suites exist:
  - `test_migrations.py`
  - `test_api_contract_error_shapes.py`
  - `test_background.py`, `test_sync_integration.py`, `test_sync_guardrails.py`, `test_background_events.py`
- CI currently executes backend lint + mypy + full backend pytest and enforces migration preflight (`alembic upgrade head` + `assert_database_at_head()`).
- Coverage gate currently enforced at `--cov-fail-under=38`.

## Risk-to-Coverage Map

| Risk Category | Existing Coverage | Notable Gaps | Gap Severity | Needed Layer |
|---|---|---|---|---|
| API contract + error-shape stability | `test_api_contract_error_shapes.py`, broad `test_api_*.py` coverage | Limited positive/negative schema contract assertions for some non-player route families | P1 | Contract + API tests |
| Profile/auth boundary correctness | `test_api_profiles.py`, profile-required checks in API suites | Missing cross-route matrix test ensuring all protected endpoints enforce profile headers consistently | P2 | API contract |
| Migration safety + schema drift | `test_migrations.py` (`upgrade`, `current`, `alembic check`) + CI preflight | No downgrade cycle safety suite for reversible migrations | P1 | Migration integration |
| Background sync/analysis resilience | `test_background.py`, `test_sync_integration.py`, `test_sync_guardrails.py`, `test_background_events.py` | Limited multi-failure dependency fault injection (Redis/DB transient outages mid-sync) | P1 | Integration/chaos-style |
| Queue/churn guardrails + breaker behavior | `test_sync_guardrails.py`, executor tests in `test_background.py` | No long-run end-to-end guardrail validation under realistic queue pressure | P2 | Soak/integration |
| Health/operability endpoints | `test_health.py`, worker/diagnostic surfaces exercised indirectly | Sparse assertions for deep diagnostics payload semantics over time (timeline chronology, event density limits) | P2 | API/integration |
| Scanner/file-system edge cases | `test_scanner.py`, `test_sync_integration.py` | Limited network filesystem/permission-flap scenario coverage | P2 | Integration |
| Recommendation/discovery correctness | `test_recommendations*.py`, `test_smart_playlists*.py`, `test_embedding_map.py` | Few deterministic regression fixtures for ranking drift across model/version changes | P2 | Integration + snapshot |
| External service adapters (Last.fm/Bandcamp/MusicBrainz) | `test_lastfm.py`, `test_bandcamp.py`, service tests with mocks | No CI-isolated contract stubs verifying response-shape compatibility over provider changes | P2 | Contract/mock integration |
| Streaming/playback backend endpoints | `test_api_tracks.py`, contract tests for invalid stream id | Limited performance/concurrency validation for stream endpoint behavior under parallel clients | P2 | Load/integration |

## CI Coverage Posture (Item 1 Evidence)
- Strong:
  - Backend tests are gated in CI (`uv run pytest -v --tb=short`).
  - Migration head enforcement is explicit in CI and E2E jobs.
  - Backend lint + mypy are required jobs before docker build.
- Baseline risk:
  - Coverage quality bar is still low (`38%`), so critical-path holes can hide behind aggregate pass.
  - No dedicated backend-only risk-bucket test selection (all-or-nothing full pytest run).

## Priority Gaps To Carry Into Item 2/3
1. Add reversible-migration downgrade/upgrade cycle tests for migrations that claim downgrade support.
2. Add background fault-injection tests for Redis unavailable / DB transient failure during sync phases.
3. Add protected-endpoint auth/profile contract matrix test.
4. Add targeted stream endpoint concurrency test (parallel range/stream requests).
5. Raise coverage gate by risk bucket rather than one global aggregate threshold.

## Reproducibility Commands
Run from repo root:

```bash
# Count backend tests by type
rg --files backend/tests | rg '^backend/tests/test_.*\.py$' | wc -l
rg --files backend/tests | rg '_integration\.py$' | wc -l
rg --files backend/tests | rg 'test_api_.*\.py$' | wc -l

# Inspect CI backend gates
sed -n '1,320p' .github/workflows/ci.yml

# Inspect backend coverage/test thresholds
sed -n '120,240p' backend/pyproject.toml
sed -n '1,120p' backend/Makefile
```

## Completion Note
Phase 5 item 1 is complete once this risk map is linked in the backend roadmap and used as the source list for item 2 (flaky/weak CI gate audit) and item 3 (minimum quality gates by risk category).
