.PHONY: install dev run reset-db migrate test test-contract lint lint-contracts openapi openapi-check format backfill-artists backfill-albums

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

# Run tests
test:
	uv run pytest -v

# Run backend API contract tests with required migration preflight
test-contract:
	uv run python -m alembic upgrade head
	uv run pytest tests/test_contract_error_shapes.py tests/test_contract_auth_matrix.py tests/test_contract_envelope_parity.py -v --tb=short --no-cov

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

# Format code
format:
	uv run ruff format .
	uv run ruff check --fix .

# One-shot backfill: give already-downloaded video files a `track_videos` row.
# ADR-0086 says the file on disk wins for existence; this is the half it did not build.
adopt-videos:
	uv run python -m app.cli.adopt_orphan_videos $(ARGS)

# One-shot backfill: populate canonical artists/aliases from existing tracks.
# Pass ARGS="--dry-run" or ARGS="--no-mb --limit 50" for variants.
backfill-artists:
	uv run python -m app.cli.backfill_artists $(ARGS)

# One-shot backfill: populate canonical albums/aliases from existing tracks (ADR-0052).
# Pass ARGS="--dry-run" first — it reports what it would create and writes nothing.
backfill-albums:
	uv run python -m app.cli.backfill_albums $(ARGS)
