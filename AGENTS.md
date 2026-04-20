# Familiar

An LLM-powered local music player that combines library management with AI-powered discovery. Users describe what they want to listen to in natural language, and Codex creates playlists from a deeply-analyzed local music collection.

## Architecture

- **Backend**: Python FastAPI + PostgreSQL (pgvector) + Redis
- **Frontend**: React + TypeScript + Vite + Tailwind + Zustand (pnpm workspace monorepo)
- **Analysis**: Audio embeddings and features extracted via librosa/torch
- **LLM**: Codex API with tool-use
- **Offline**: IndexedDB (Dexie) for track caching, download queue, playlist cache

## Key Directories

```
packages/
├── frontend/              # Shared React code (components, hooks, stores, types)
│   └── src/
│       ├── components/    # React components
│       ├── hooks/         # Custom hooks (useFavorites, useAutoDownload, etc.)
│       ├── stores/        # Zustand state stores (playerStore, downloadStore)
│       ├── player/        # Audio engine abstraction, playback hooks
│       ├── services/      # offlineService, playlistCache, syncService, profileService
│       └── db/            # IndexedDB/Dexie storage
├── web/                   # Web entry point + Web Audio engine + PWA
│   ├── src/
│   │   ├── main.tsx       # Registers WebAudioEngine, sets up SW
│   │   └── WebAudioEngine.ts
│   ├── e2e/               # Playwright E2E tests
│   └── vite.config.ts     # PWA plugin, dev proxy, manual chunks
└── ios/                   # Capacitor + native Swift + iOS deploy
    ├── src/
    │   ├── main.tsx       # Registers CapacitorEngine
    │   ├── CapacitorEngine.ts
    │   └── plugins/familiarAudio.ts
    ├── native/            # Xcode project + Swift code
    ├── capacitor.config.ts
    └── scripts/           # deploy-device.sh, release-testflight.sh
backend/
├── app/
│   ├── api/routes/        # FastAPI endpoints (~29 route files)
│   ├── db/models.py       # SQLAlchemy models
│   └── services/          # Business logic
│       └── llm/           # LLM module (service.py, executor.py, tools.py, providers.py)
├── migrations/versions/   # Alembic database migrations
└── tests/                 # pytest tests
```

## Key Files

| Task | Files |
|------|-------|
| Database models | `backend/app/db/models.py` |
| Database migrations | `backend/migrations/versions/*.py` |
| API routes | `backend/app/api/routes/*.py` |
| Audio analysis | `backend/app/services/analysis.py` |
| LLM tools | `backend/app/services/llm/tools.py`, `llm/executor.py` |
| Library scanning | `backend/app/services/scanner.py` |
| Smart playlists | `backend/app/services/smart_playlists.py` |
| Background tasks | `backend/app/services/background.py`, `services/tasks.py` |
| Audio engine abstraction | `packages/frontend/src/player/audio/types.ts`, `createEngine.ts` |
| Audio playback | `packages/frontend/src/player/useAudioEngine.ts` |
| Web Audio engine | `packages/web/src/WebAudioEngine.ts` |
| iOS Audio engine | `packages/ios/src/CapacitorEngine.ts` |
| Player state | `packages/frontend/src/stores/playerStore.ts` |
| Download queue | `packages/frontend/src/stores/downloadStore.ts` |
| Offline storage | `packages/frontend/src/services/offlineService.ts` |
| Playlist caching | `packages/frontend/src/services/playlistCache.ts` |
| Favorites | `packages/frontend/src/hooks/useFavorites.ts` |
| IndexedDB schema | `packages/frontend/src/db/index.ts` |
| Full player | `packages/frontend/src/components/FullPlayer/` |
| Discovery | `packages/frontend/src/components/Discovery/` |
| Smart playlists UI | `packages/frontend/src/components/SmartPlaylists/` |
| Settings | `packages/frontend/src/components/Settings/` |

## Frontend Architecture

The frontend uses a **registration pattern** for platform-specific code. The shared `@familiar/frontend` package has zero `@capacitor` dependencies:

- **`createEngine.ts`** — `registerEngineFactory(fn)` sets the audio engine constructor
- **`api/base.ts`** — `registerPreferencesProvider(p)` for Capacitor Preferences

Each platform entry point (`packages/web/src/main.tsx`, `packages/ios/src/main.tsx`) registers its implementations before calling `renderApp()`.

## Common Tasks

### Add a new audio feature
1. Add extraction logic to `analysis.py` in `extract_features()`
2. No schema change needed (features stored as JSONB)
3. Bump `ANALYSIS_VERSION` in `config.py` to re-analyze existing tracks

### Add a new LLM tool
1. Define tool schema in `MUSIC_TOOLS` list in `services/llm/tools.py`
2. Implement handler in `ToolExecutor` class in `services/llm/executor.py`
3. Tools can query JSONB with PostgreSQL `->` operator

### Add a new API endpoint
1. Create route in `backend/app/api/routes/`
2. Register router in `main.py`
3. Use dependency injection from `deps.py` for DB/auth

### Add a database migration
1. Create file in `backend/migrations/versions/` named `YYYYMMDD_slug.py`
2. **Revision ID must be ≤32 characters** (alembic_version column limit)
3. Always use the `_column_exists()` guard pattern for idempotent migrations:
```python
def _column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = :table AND column_name = :column"
    ), {"table": table_name, "column": column_name})
    return result.fetchone() is not None
```
4. Add corresponding field to the SQLAlchemy model in `models.py`
5. `deploy-dev.sh` auto-runs `alembic upgrade head` on deploy

### Add a new settings section
1. Add component in `packages/frontend/src/components/Settings/`
2. Export from `Settings/index.tsx`
3. Add to settings tabs in main Settings component

### Regenerate README screenshots
Screenshots for the README are auto-generated using Playwright:

1. Ensure backend is running: `cd backend && make run`
2. Start frontend dev server: `cd packages/web && pnpm dev`
3. Run screenshot script: `cd packages/web && BASE_URL=http://localhost:3000 npx playwright test --grep="screenshot"`

Screenshots are saved to `screenshots/` directory. The script is in `packages/web/e2e/screenshots.spec.ts`.

To add new screenshots:
1. Add a new test case to `screenshots.spec.ts`
2. Use the `selectBrowser()` helper to switch library views
3. Use `navigateToTab()` helper to switch between Library/Playlists/Settings
4. Update README.md to include the new screenshot

## Configuration

Most settings are configured via the admin UI (Settings panel):
- **Music library paths** - Settings > Library Management
- **API keys** - Admin page (Anthropic, Spotify, Last.fm, AcoustID)
- **LLM provider** - Settings > AI Assistant

Settings are stored in `data/settings.json` and persist across restarts.

## Environment Variables

Only infrastructure settings require environment variables:

```bash
# Required (from docker-compose or shell)
DATABASE_URL=postgresql+asyncpg://familiar:familiar@localhost:5432/familiar
REDIS_URL=redis://localhost:6379/0

# Optional (for Docker volume mounting only - actual paths configured in UI)
MUSIC_LIBRARY_PATH=/data/music
```

## Running Locally

```bash
# Backend (from backend/)
DATABASE_URL="..." REDIS_URL="..." uv run uvicorn app.main:app --reload --port 4400

# Frontend (from packages/web/)
pnpm dev
```

## Development Workflow

### Local Development (Default)
Backend and frontend run locally with hot-reload:
```bash
# Terminal 1: Start database + redis
docker compose -f docker/docker-compose.yml up -d

# Terminal 2: Backend with hot-reload
cd backend && make run

# Terminal 3: Frontend dev server
cd packages/web && pnpm dev
```

### Testing Against Remote NAS (openmediavault)
For testing with the real 23K track library via Tailscale:

**Frontend-only changes (fastest):**
```bash
make dev-remote  # Vite dev server proxies to NAS backend
```

**Full-stack changes:**
```bash
make deploy-dev  # Build + rsync to NAS + restart (~16-30s)
```

**IMPORTANT:** Do NOT use the full Docker build + GitHub Actions workflow for iterative development - that takes ~1 hour per change. Use `make deploy-dev` instead.

### Running Tests

```bash
# Backend (from backend/)
make test                    # pytest with coverage
uv run pytest tests/ -x -q   # quick run, stop on first failure

# Frontend unit tests (from packages/frontend/)
pnpm test                   # vitest run
pnpm test:watch             # vitest watch mode

# Frontend E2E tests (requires backend + frontend running)
cd packages/web && npx playwright test                # Playwright headless
cd packages/web && npx playwright test --ui           # Playwright UI mode
```

### iOS Development

```bash
make deploy-device            # Build + install to connected iPhone (~2 min)
make release-testflight       # Build + upload to TestFlight
```

## Code Conventions

- Backend uses async SQLAlchemy with `DbSession` dependency
- Frontend uses Zustand for global state, React Query for server state
- Profile-based multi-user (no traditional auth) - profile ID in header
- Audio features stored as JSONB for flexibility
- Embeddings stored in pgvector for similarity search
- SmartPlaylistService uses `**kwargs` with `setattr()` for flexible updates - new model fields work automatically
- Offline-first: `offlineService.ts` manages IndexedDB track storage, `playlistCache.ts` caches playlists, `downloadStore.ts` manages download queue with persistence and resume
- iOS Safari flexbox: nested `flex-1` inside `flex-col` needs explicit `min-h-0` for `overflow-y-auto` to work - add at every level of the flex chain
- Platform-specific code uses registration pattern — never import `@capacitor` packages in `@familiar/frontend`

- When fixing a bug, ask yourself: can we add a test that could have caught this?
