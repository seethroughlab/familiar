.PHONY: install dev run reset-db migrate test test-contract lint format

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
	uv run pytest tests/test_api_contract_error_shapes.py -v --tb=short --no-cov

# Lint code
lint:
	uv run ruff check .
	uv run mypy app

# Format code
format:
	uv run ruff format .
	uv run ruff check --fix .
