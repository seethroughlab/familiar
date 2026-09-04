# Familiar

Familiar is a self-hosted music library server with AI-assisted discovery. The server scans and
analyzes a local music collection; the browser is now an administration surface; the Mac and iPhone
listening clients live in the separate `familiar-apple` repository.

## Current Architecture

- **Backend**: Python FastAPI + PostgreSQL/pgvector + Redis
- **Frontend**: React + TypeScript + Vite + Tailwind + Zustand in a pnpm workspace
- **Analysis**: librosa feature extraction, CLAP embeddings through `clapback-embed`, and optional
  deeper section/melodic analysis
- **LLM surface**: server-side tools plus an MCP endpoint; clients bring their own assistant/provider
- **Clients**: this repo owns the server, web administration UI, embedded discovery page, and
  visualizer documents. Native Mac/iPhone playback is in `../familiar-apple`

The old Capacitor app, browser player, PWA install path, service worker, Dexie offline store, and
web playback engine were retired in August 2026. Do not reintroduce those shapes without an ADR.

## Key Directories

```
backend/
├── app/
│   ├── api/              # FastAPI dependencies, auth, errors, route registration
│   ├── api/routes/       # REST endpoints, split by product surface/resource
│   ├── api/schemas/      # Shared Pydantic response/request schemas
│   ├── db/models/        # SQLAlchemy models
│   ├── mcp/              # MCP endpoint and playback/tool bridge
│   └── services/         # Domain logic, background jobs, scanners, analysis
├── migrations/versions/  # Alembic migrations
└── tests/                # pytest suite

packages/
├── frontend/             # Shared React code used by web/embed/visualizer entry points
│   └── src/
│       ├── api/          # Axios client modules and query defaults
│       ├── app/          # App shell, top-level routes and navigation definitions
│       ├── audio/        # Small audio contract used by embedded surfaces
│       ├── components/   # Reusable UI and feature components
│       ├── hooks/        # React hooks
│       ├── panels/       # Library, tools and server panels
│       ├── screens/      # Top-level web destinations
│       ├── services/     # Browser-side service modules
│       ├── stores/       # Zustand state stores
│       └── utils/        # Formatting, logging, platform and error helpers
├── web/                  # Vite web app, embed and visualizer HTML entry points
└── visualizers/          # Bundled example/drop-in visualizer documents

docs/
├── decisions/            # ADRs
└── *.md                  # Operator, API, installation and architecture docs
```

## Key Files

| Task | Files |
|------|-------|
| Architecture overview | `docs/ARCHITECTURE.md` |
| Database models | `backend/app/db/models/*.py` |
| Database migrations | `backend/migrations/versions/*.py` |
| API route registration | `backend/app/api/routes/__init__.py` |
| API dependencies/auth | `backend/app/api/deps.py`, `backend/app/api/auth.py` |
| App startup/middleware | `backend/app/main.py` |
| Audio feature versions | `backend/app/config.py`, `VERSIONING.md` |
| Audio analysis | `backend/app/services/analysis.py`, `backend/app/services/track_analysis/` |
| Library scanning | `backend/app/services/scanner.py` |
| Background sync/analysis | `backend/app/services/tasks/`, `backend/app/services/background/` |
| LLM tools | `backend/app/services/llm/tools.py`, `backend/app/services/llm/executor.py`, `backend/app/services/llm/handlers/` |
| Smart playlists | `backend/app/services/smart_playlists.py` |
| Frontend route map | `packages/frontend/src/app/routes.ts` |
| Frontend API client | `packages/frontend/src/api/base.ts`, `packages/frontend/src/api/*.ts` |
| Web entry points | `packages/web/src/main.tsx`, `packages/web/src/embed.tsx`, `packages/web/src/visualizer.tsx` |
| Visualizer host/catalog | `packages/frontend/src/components/Visualizer/`, `packages/frontend/src/services/visualizerCatalog.ts` |

## Development Workflow

### Local Development

```bash
# Terminal 1: database + redis
docker compose -f docker/docker-compose.yml up -d

# Terminal 2: backend
cd backend && make run

# Terminal 3: frontend
cd packages/web && pnpm dev
```

### Testing Against Remote NAS

Use the faster project-specific paths during iteration:

```bash
make dev-remote   # frontend dev server proxies to the NAS backend
make deploy-dev   # build + rsync to NAS + restart
```

Avoid the full Docker build/GitHub Actions path for routine iteration; it is much slower and is
intended as CI/release validation.

## Common Tasks

### Add a new audio feature

1. Add extraction logic in `backend/app/services/analysis.py` for scalar features, or
   `backend/app/services/track_analysis/` for section/melodic analysis.
2. Add a typed column to `TrackAnalysis` in `backend/app/db/models/tracks.py`.
3. Add the column name to `ANALYSIS_FEATURE_COLUMNS`.
4. Write an Alembic migration.
5. Bump only the relevant phase constant in `backend/app/config.py` and update its history comment.
   See `VERSIONING.md`.

Features were promoted from JSONB into typed columns. A computed feature that is not listed in the
model and `ANALYSIS_FEATURE_COLUMNS` will be dropped on persistence.

### Add a new LLM tool

1. Define the schema in `MUSIC_TOOLS` in `backend/app/services/llm/tools.py`.
2. Implement the handler in `ToolExecutor` or an existing handler module under
   `backend/app/services/llm/handlers/`.
3. Add tests for the tool schema and execution path.

### Add a new API endpoint

1. Create or extend a route module in `backend/app/api/routes/`.
2. Register new route modules in `backend/app/api/routes/__init__.py`.
3. Use dependencies from `backend/app/api/deps.py` for database/profile handling.
4. Return shared schemas from `backend/app/api/schemas/` when the shape is reused.
5. Add or update API/client tests and regenerate OpenAPI if the schema changes.

### Add a database migration

1. Create `backend/migrations/versions/YYYYMMDD_slug.py`.
2. Keep the Alembic revision ID at 32 characters or less.
3. Prefer the shared guard helpers in `backend/migrations/helpers.py`.
4. Add the matching SQLAlchemy model field.
5. Run the migration lint and migration tests.

### Add a web surface

1. Add the screen or panel under `packages/frontend/src/screens/` or `packages/frontend/src/panels/`.
2. Update `packages/frontend/src/app/routes.ts` and `packages/frontend/src/app/App.tsx`.
3. Add navigation integrity coverage if a new destination is linked.
4. Keep web responsibilities administrative: library management, tools, server state, embedded
   discovery, and visualizer hosting. Playback UX belongs in `familiar-apple`.

### Regenerate README screenshots

1. Ensure the backend is running.
2. Start the web dev server from `packages/web`.
3. Run the screenshot Playwright spec from `packages/web`.
4. Commit the updated files in `screenshots/`.

## Guardrails

- Do not import `@capacitor` in `@familiar/frontend`.
- Do not add service workers, PWA install prompts, IndexedDB playback caches, or browser playback
  state without an ADR.
- Keep API error envelopes consistent; contract tests exist for this.
- Keep generated OpenAPI current because the Apple clients consume it.
- Avoid route ordering hazards. Dynamic `/{id}` routes must be registered after more specific paths.
- When touching streaming/download routes, release database connections before sending long bodies.
- When fixing a bug, ask whether a focused test could have caught it.

## Quality Checks

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

Backend tests require PostgreSQL and Redis. CI provisions those services; local runs need the Docker
compose stack or equivalent services already running.
