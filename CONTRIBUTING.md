# Contributing to Familiar

Thanks for helping with Familiar. The project has moved quickly, so the most useful habit is to
preserve the current boundaries while making focused improvements.

## Start Here

1. Read `README.md` for product context.
2. Read `docs/ARCHITECTURE.md` for the current system map.
3. Skim `VERSIONING.md` before changing analysis code.
4. Check `docs/ERROR-CONTRACTS.md` before adding or changing API errors.
5. Look for a relevant ADR in `docs/decisions/` when a choice seems surprising.

## Local Setup

```bash
docker compose -f docker/docker-compose.yml up -d

cd backend
make run

cd ../packages/web
pnpm dev
```

Backend tests need PostgreSQL and Redis. The compose stack above provides them for local work.

## Before Opening a PR

Run the focused checks for the area you touched.

```bash
# Backend
cd backend
uv run ruff check .
uv run mypy app --ignore-missing-imports
uv run pytest tests/ -x -q

# Frontend
pnpm --filter @familiar/frontend run lint
pnpm --filter @familiar/frontend run check:boundaries
pnpm --filter @familiar/frontend test
pnpm --filter @familiar/web run build
```

If a check cannot run locally because an external service is missing, say that in the PR.

## Code Guidelines

- Keep changes scoped to the feature or bug being fixed.
- Prefer existing patterns over new abstractions.
- Add tests for bug fixes when a reasonable focused test can catch the behavior.
- Keep SQLAlchemy models and Alembic migrations in sync.
- Regenerate and commit `backend/openapi.json` when the public API changes.
- Do not import `@capacitor` from `packages/frontend`.
- Do not reintroduce PWA/player/offline-browser behavior without a fresh ADR.

## Backend Notes

- Use `DbSession`, `CurrentProfile` or `RequiredProfile` from `backend/app/api/deps.py`.
- Streaming or download handlers should call `release_connection()` after reading database metadata
  and before sending long response bodies.
- New route modules are registered in `backend/app/api/routes/__init__.py`, not directly in
  `main.py`.
- Migration revision IDs must be 32 characters or shorter.
- New analysis features need a typed `TrackAnalysis` column and an entry in
  `ANALYSIS_FEATURE_COLUMNS`.

## Frontend Notes

- Top-level navigation lives in `packages/frontend/src/app/routes.ts`.
- API calls should use modules under `packages/frontend/src/api/`; raw `fetch` is reserved for
  assets, streams and other cases where axios is a poor fit.
- Keep service modules independent from UI stores unless the dependency-cruiser rule has an explicit
  reason to allow it.
- The browser app is an administration tool. Native listening UX belongs in `familiar-apple`.

## Documentation

Update docs in the same PR when behavior, setup, architecture or public contracts change. Prefer one
current explanation over preserving obsolete guidance in place. Historical context belongs in ADRs.
