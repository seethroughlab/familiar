.PHONY: install dev run reset-db migrate test-db test-services test-services-down test test-contract lint lint-contracts openapi openapi-check contract-lock contract-lock-check format backfill-artists backfill-albums adopt-videos backfill-video-posters match-videos refetch-videos find-stills

# Install dependencies
install:
	uv sync

# Install with dev dependencies
dev:
	uv sync --all-extras

# Run the API server (background tasks run in-process)
run:
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 4400

# Reset database (drop and recreate all tables)
reset-db:
	uv run python -m app.db.init_db

# Apply migrations to latest revision
migrate:
	uv run python -m alembic upgrade head

# The database the suite is allowed to empty (ADR-0128). Beside the development one on the
# compose stack's PostgreSQL; the `_test` suffix is what the suite checks for, and there is no
# opt-out. Override to point at another server, not to point at a real database.
TEST_DATABASE_URL ?= postgresql+asyncpg://familiar:familiar@localhost:5432/familiar_test
export TEST_DATABASE_URL

# Create the test database if it is missing, and migrate it. Idempotent; `test` runs it first.
test-db:
	uv run python scripts/ensure_test_database.py

# No compose stack running? `make test-services` starts a throwaway Postgres and Redis on spare
# ports instead — the dev stack on 5432/6379 is never touched — and points TEST_DATABASE_URL at
# them for the targets that follow in the same invocation:
#
#     make test-services test            # containers up, migrate, run the suite
#     make test-services test ARGS="-x"  # ARGS passes through to pytest
#     make test-services-down            # remove the containers and their data
#
# Re-running is idempotent (`docker start` on an existing container). Override the ports if they
# collide: `make test-services TEST_PG_PORT=5444`.
TEST_PG_PORT ?= 5434
TEST_REDIS_PORT ?= 6380
ifneq ($(filter test-services,$(MAKECMDGOALS)),)
TEST_DATABASE_URL := postgresql+asyncpg://familiar:familiar@localhost:$(TEST_PG_PORT)/familiar_test
REDIS_URL := redis://localhost:$(TEST_REDIS_PORT)/0
export REDIS_URL
endif

test-services:
	@docker start familiar-test-postgres >/dev/null 2>&1 || docker run -d --name familiar-test-postgres \
		-e POSTGRES_USER=familiar -e POSTGRES_PASSWORD=familiar -e POSTGRES_DB=familiar_test \
		-p $(TEST_PG_PORT):5432 pgvector/pgvector:pg16 >/dev/null
	@docker start familiar-test-redis >/dev/null 2>&1 || docker run -d --name familiar-test-redis \
		-p $(TEST_REDIS_PORT):6379 redis:7-alpine >/dev/null
	@until docker exec familiar-test-postgres pg_isready -U familiar -d familiar_test >/dev/null 2>&1; do sleep 0.5; done
	@echo "test services ready: $(TEST_DATABASE_URL)"

test-services-down:
	@docker rm -f familiar-test-postgres familiar-test-redis >/dev/null 2>&1 || true

# Run tests — against the test database only. `uv run pytest` on its own refuses to run
# without TEST_DATABASE_URL, with the same instructions, rather than emptying whatever
# DATABASE_URL names; that is the whole of ADR-0128. ARGS passes through to pytest.
test: test-db
	uv run pytest -v $(ARGS)

# Run backend API contract tests with required migration preflight
test-contract: test-db
	uv run pytest tests/test_contract_error_shapes.py tests/test_contract_auth_matrix.py tests/test_contract_envelope_parity.py -v --tb=short --no-cov $(ARGS)

# Lint code
lint:
	uv run ruff check .
	uv run mypy app

# Run the custom checks CI enforces (schema, migrations, profile contracts, import boundaries)
lint-contracts:
	uv run python scripts/lint_openapi.py
	uv run python scripts/lint_migrations.py
	uv run python scripts/lint_profile_contracts.py
	uv run python scripts/lint_boundaries.py

# Write backend/openapi.json — the artifact familiar-apple generates its Swift client from.
# Regenerate and commit whenever the API changes; CI fails if it is stale.
openapi:
	uv run python scripts/dump_openapi.py

# Fail if the committed schema no longer matches the app (CI gate).
openapi-check:
	uv run python scripts/dump_openapi.py --check

# Record the current API shape against API_CONTRACT_VERSION (ADR-0113). Run after any schema
# change: either the change is compatible and this just re-locks, or it is not and you bump
# API_CONTRACT_VERSION in app/config.py first.
# `SATISFIED_BY` is required only when raising MIN_CLIENT_CONTRACT — the one change that can
# refuse an app already on a device (ADR-0113 point 10):
#   make contract-lock SATISFIED_BY="iOS/macOS build 41"
contract-lock:
	uv run python scripts/check_contract_bump.py $(if $(SATISFIED_BY),--satisfied-by "$(SATISFIED_BY)")

# Fails when the shape moved but nobody decided what it means for shipped clients.
contract-lock-check:
	uv run python scripts/check_contract_bump.py --check

# Format code
format:
	uv run ruff format .
	uv run ruff check --fix .

# One-shot backfill: give already-downloaded video files a `track_videos` row.
# ADR-0086 says the file on disk wins for existence; this is the half it did not build.
adopt-videos:
	uv run python -m app.cli.adopt_orphan_videos $(ARGS)

backfill-video-posters:
	uv run python -m app.cli.backfill_video_posters $(ARGS)

match-videos:
	uv run python -m app.cli.match_music_videos $(ARGS)

refetch-videos:
	uv run python -m app.cli.refetch_unplayable_videos $(ARGS)

find-stills:
	uv run python -m app.cli.find_still_videos $(ARGS)

# One-shot backfill: populate canonical artists/aliases from existing tracks.
# Pass ARGS="--dry-run" or ARGS="--no-mb --limit 50" for variants.
backfill-artists:
	uv run python -m app.cli.backfill_artists $(ARGS)

# One-shot backfill: populate canonical albums/aliases from existing tracks (ADR-0052).
# Pass ARGS="--dry-run" first — it reports what it would create and writes nothing.
backfill-albums:
	uv run python -m app.cli.backfill_albums $(ARGS)
