.PHONY: install dev run reset-db migrate test test-services test-services-down test-contract lint lint-contracts openapi openapi-check contract-lock contract-lock-check format backfill-artists backfill-albums adopt-videos backfill-video-posters match-videos refetch-videos find-stills

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

# ---------------------------------------------------------------------------------------------
# Tests run only against a disposable database (ADR-0128).
#
# The suite deletes rows from eighteen tables before and after each test, so it never reads
# DATABASE_URL: tests/conftest.py takes TEST_DATABASE_URL, refuses any database whose name does
# not end in `_test`, and stops before collection otherwise. `make test` is the short path — it
# starts a throwaway Postgres and Redis on spare ports (the shared dev stack on 5432/6379 is
# never touched), migrates the test database, and runs pytest. Re-running it is idempotent.
#
# Override the ports if they collide: `make test TEST_PG_PORT=5444`.
# ---------------------------------------------------------------------------------------------
TEST_PG_PORT ?= 5434
TEST_REDIS_PORT ?= 6380
TEST_DB_NAME := familiar_test
TEST_DATABASE_URL ?= postgresql+asyncpg://familiar:familiar@localhost:$(TEST_PG_PORT)/$(TEST_DB_NAME)
TEST_REDIS_URL ?= redis://localhost:$(TEST_REDIS_PORT)/0
TEST_ENV := TEST_DATABASE_URL=$(TEST_DATABASE_URL) DATABASE_URL=$(TEST_DATABASE_URL) REDIS_URL=$(TEST_REDIS_URL)

# Start (or resume) the throwaway containers and migrate the test database. Idempotent.
test-services:
	@docker start familiar-test-postgres >/dev/null 2>&1 || docker run -d --name familiar-test-postgres \
		-e POSTGRES_USER=familiar -e POSTGRES_PASSWORD=familiar -e POSTGRES_DB=$(TEST_DB_NAME) \
		-p $(TEST_PG_PORT):5432 pgvector/pgvector:pg16 >/dev/null
	@docker start familiar-test-redis >/dev/null 2>&1 || docker run -d --name familiar-test-redis \
		-p $(TEST_REDIS_PORT):6379 redis:7-alpine >/dev/null
	@until docker exec familiar-test-postgres pg_isready -U familiar -d $(TEST_DB_NAME) >/dev/null 2>&1; do sleep 0.5; done
	@$(TEST_ENV) uv run python -m alembic upgrade head
	@echo "test database ready: $(TEST_DATABASE_URL)"

# Remove the throwaway containers and their data.
test-services-down:
	@docker rm -f familiar-test-postgres familiar-test-redis >/dev/null 2>&1 || true

# Run the suite against the disposable database. ARGS passes through: `make test ARGS="tests/test_health.py -x"`.
test: test-services
	$(TEST_ENV) uv run pytest -v $(ARGS)

# Run backend API contract tests with required migration preflight
test-contract: test-services
	$(TEST_ENV) uv run pytest tests/test_contract_error_shapes.py tests/test_contract_auth_matrix.py tests/test_contract_envelope_parity.py -v --tb=short --no-cov

# Lint code
lint:
	uv run ruff check .
	uv run mypy app

# Run the custom checks CI enforces (schema, migrations, profile contracts)
lint-contracts:
	uv run python scripts/lint_openapi.py
	uv run python scripts/lint_migrations.py
	uv run python scripts/lint_profile_contracts.py

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
