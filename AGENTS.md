# Familiar

Familiar is a self-hosted music library server with AI-assisted discovery. The server scans and
analyses a local collection; the browser is an administration surface; the Mac and iPhone listening
clients live in the separate `familiar-apple` repository (ADR-0001).

**This file is the one current repository guide** for people and coding tools alike
([ADR-0175](docs/decisions/ADR-0175-contributors-have-one-current-repository-guide.md)). Tool-specific
files (`CLAUDE.md`) include it rather than copy it. Start with
[`docs/START-HERE.md`](docs/START-HERE.md) for orientation and a slice traced through every layer;
[`docs/HEALTH.md`](docs/HEALTH.md) is what is known to be wrong; [`docs/ADR-INDEX.md`](docs/ADR-INDEX.md)
is the decisions by subsystem; [`docs/ADR-HISTORY.md`](docs/ADR-HISTORY.md) is how they were sequenced.

## Architecture

- **Backend**: Python FastAPI + PostgreSQL (pgvector), with Redis optional since ADR-0133 (progress,
  locks and caches fall back to Postgres tables).
- **Analysis**: librosa feature extraction and CLAP embeddings through `clapback-embed` (ONNX), plus
  section and melodic analysis. Versioned per phase in `backend/app/config.py`.
- **Frontend**: React + TypeScript + Vite + Tailwind + Zustand + React Query, in a pnpm workspace. The
  web app is an administration tool (ADR-0058, ADR-0126); it does not play music.
- **API client**: `packages/api-client` is generated from `backend/openapi.json` (ADR-0129); the Apple
  clients generate their Swift client from the same file.
- **LLM surface**: server-side tools behind an MCP endpoint (`/mcp`, ADR-0043); clients bring their own
  assistant. There is no chat provider in the server (ADR-0048).
- **Server forms**: Docker on Linux/NAS, and **Familiar Server**, the Mac menu-bar app under
  `desktop/macos/` (ADR-0131, ADR-0136). Both start through `python -m app.serve`.

**Retired, and not to come back without an ADR:** the Capacitor app (packages/ios, deleted
2026-08-11), the browser player and its audio engine, the PWA and service worker, the Dexie offline
store, and chat inside the server. If you find yourself adding an `isNativeApp`-shaped check, the
native clients live in `familiar-apple` and do not run this bundle.

## Repository Map

```
backend/
├── app/
│   ├── api/               # deps, auth (token gate), errors, route registration
│   │   ├── routes/        # REST endpoints by product surface; compat.py holds every alias (ADR-0079)
│   │   └── schemas/       # shared Pydantic request/response models
│   ├── operations/        # use cases shared by REST, LLM/MCP tools and jobs; no HTTP (ADR-0173)
│   ├── services/          # domain logic: scanner, analysis, background jobs, llm/ tool handlers
│   ├── db/models/         # SQLAlchemy models
│   ├── mcp/               # the MCP endpoint
│   ├── exposure.py        # who a tokenless server answers (ADR-0171)
│   └── serve.py           # `python -m app.serve`: migrate, decide about the token, run
├── migrations/versions/   # Alembic migrations
├── scripts/               # lints (boundaries, migrations, OpenAPI), schema dump, contract lock
└── tests/                 # pytest; needs TEST_DATABASE_URL (ADR-0128)
packages/
├── api-client/            # generated from backend/openapi.json; never edited by hand
├── frontend/src/
│   ├── api/               # feature adapters over the generated client; the only importer of it
│   ├── app/               # shell, routes.ts (the four destinations and their sections)
│   ├── screens/, panels/  # destinations and their sections
│   ├── components/, hooks/, stores/, services/, utils/
│   └── audio/             # the small engine contract the embedded surfaces use
├── web/                   # Vite entry points: main.tsx (admin), embed.tsx, visualizer.tsx; e2e/
├── visualizer-sdk/        # the bridge the first-party visualizers share (ADR-0125)
└── visualizers/           # Beat Tiles and Reactive Terrain, vendored into familiar-apple (ADR-0161)
desktop/macos/             # Familiar Server: Swift package, build and integration scripts
docker/                    # Dockerfile, compose files, start/stop/update scripts
docs/                      # orientation, operator docs, decisions/ (ADRs only)
```

## Key Files

| Task | Files |
|------|-------|
| Orientation, debt, decisions | `docs/START-HERE.md`, `docs/HEALTH.md`, `docs/ADR-INDEX.md` (generated: `make adr-index`) |
| Architecture and the worked example | `docs/ARCHITECTURE.md` |
| Is this machine set up? | `make doctor` |
| App assembly and middleware order | `backend/app/main.py`, `backend/app/container.py` |
| Route registration, auth, dependencies | `backend/app/api/routes/__init__.py`, `backend/app/api/auth.py`, `backend/app/api/deps.py` |
| Error codes clients act on | `backend/app/api/exceptions.py`, `docs/ERROR-CONTRACTS.md` |
| Database models and migrations | `backend/app/db/models/`, `backend/migrations/versions/` |
| Analysis | `backend/app/services/analysis.py`, `backend/app/services/track_analysis/`, `backend/app/services/analysis_lifecycle.py` |
| Versions per analysis phase | `backend/app/config.py`, `VERSIONING.md` |
| Library scanning and sync | `backend/app/services/scanner.py`, `backend/app/services/tasks/library_sync.py` |
| Background work | `backend/app/services/background/`, `backend/app/services/tasks/` |
| LLM/MCP tools | `backend/app/services/llm/tools.py`, `backend/app/services/llm/executor.py`, `backend/app/services/llm/handlers/` |
| Smart playlists | `backend/app/services/smart_playlists.py` |
| Web routes and navigation | `packages/frontend/src/app/routes.ts`, `packages/frontend/src/app/App.tsx` |
| Web transport (origin, token, profile header) | `packages/frontend/src/api/base.ts` |
| Embedded surfaces | `packages/frontend/src/renderEmbed.tsx`, `packages/frontend/src/components/Embed/`, `packages/frontend/src/services/embedBridge.ts`, `packages/frontend/src/audio/playbackInterceptor.ts` |
| Docker | `docker/Dockerfile`, `docker/docker-compose.prod.yml`, `docker/start.sh` |
| CLAP smoke test | `backend/scripts/smoke_test_clap.py` |

## Architecture Decisions

**Architectural changes are made through ADRs in `docs/decisions/`. Read the relevant ones before
changing anything they govern, and propose a new one before making a decision they don't cover.**

An ADR is warranted when a change sets a direction rather than implements one: a new client or
platform, a data model other work will build on, moving responsibility between server and client, a
new external dependency or protocol, or reversing something an existing ADR decided. Ordinary feature
work, bug fixes and refactors inside an established direction need no ADR, only to respect the ones in
force.

### Convention

- Filename `ADR-NNNN-kebab-case-title.md`; heading `# ADR-NNNN: Title Case`.
- `Status:` (`proposed` → `accepted`; also `superseded by ADR-NNNN` / `rejected`) and `Date:` lines.
- Optional `Implementation:` block, added as phases land, recording what shipped on which branch: an
  accepted ADR stays a living record, not a snapshot.
- Optional `Extends [ADR-NNNN](ADR-NNNN-slug.md)` links after the header.
- Sections in order: `## Context`, `## Decision` (numbered points once non-trivial),
  `## Alternatives Considered`, `## Consequences` (bulleted, tagged **Positive** / **Tradeoff** /
  **Follow-up**).
- The directory holds only ADRs: no README, no template file. `make adr-index` regenerates the index.

### Rules

1. **One decision per ADR**, decomposed so each can be planned, approved and executed on its own.
   Propose the set together; note the execution order, which often differs from the numbering.
2. **New ADRs start `Status: proposed`** and flip to `accepted` only when that specific ADR is
   approved. Never write one straight to `accepted`.
3. **`## Alternatives Considered` must contain real rejected options with real reasons.**
4. **Verify every metric, file path and line number cited** against the repo at write time.
5. **Record contradicted premises in `## Context`** (or the Implementation block, if found while
   building), so nobody re-derives them.
6. **Never edit an accepted ADR's Decision to reflect a change of mind**: supersede it with a new ADR
   and update the old one's `Status:`.

### Before you change these, read the ADR

The traps below each cost real time once. The full story is in the ADR, and in `docs/ADR-HISTORY.md`.

| If you touch… | Read | Because |
|---|---|---|
| The embedded Discover/visualizer pages | ADR-0017, ADR-0020 | an embedded page must never construct a second audio engine; the bridge stays at two messages |
| Streaming or video routes | ADR-0086 | do not write a range parser (`app/api/streaming.py`'s `stream_file` exists); do not add `videos` to the generator's tags |
| Moving or renaming an endpoint | ADR-0079 | every alias lives in `backend/app/api/routes/compat.py`, delegating to the same function |
| The server token or who a server answers | ADR-0141, ADR-0171 | a tokenless server answers only its own machine unless opened on purpose; media is exempt (ADR-0045, ADR-0176) |
| Acquisition, Soulseek, an inbox | ADR-0154 | Familiar does not acquire; it ends at Bandcamp |
| Familiar Server's sandboxing | ADR-0140 | it is not App-Sandboxed; zero-touch is a Seatbelt profile |
| The library watcher | ADR-0142 | a watch scan never marks anything missing |
| Analysis queues or status counts | ADR-0172 | one definition in `analysis_lifecycle.py` drives the queues, the sync loop and every count |
| Calling a route from a service | ADR-0173 | services and tools call `app/operations/`, never a route; `lint_boundaries.py` has no exceptions |
| Web API response types | ADR-0173 | use the generated type; `check:contracts` fails a new handwritten one |
| E2E tests | ADR-0174 | no conditional `test.skip`; seed what the test needs |
| Lyrics or visualizers | ADR-0160, ADR-0161 | lyrics are a native player mode, never 3D; two first-party documents |
| Anything a client decodes | ADR-0113 | additive changes keep contract v1; `make contract-lock` decides |

## Frontend Architecture

The web app has three entry points in `packages/web/src`: `main.tsx` (the administration app, which
deliberately registers no audio engine), `embed.tsx` (embedded Discover, registering the null engine
of ADR-0017) and `visualizer.tsx` (the visualizer host). They differ in what they register through
`packages/frontend/src/audio/createEngine.ts`'s `registerEngineFactory`, which is why that pattern
stays although there is no second platform.

`packages/frontend/src/api/` holds thin feature adapters over `@familiar/api-client`. Nothing under
`components/`, `panels/`, `screens/` or `app/` imports the generated client (`check:boundaries`), and
response types are the generated ones (`check:contracts`, ADR-0173). The four destinations (Overview,
Library, Analysis, Server) and their sections are defined once in `app/routes.ts`.

## Common Tasks

### Add an audio feature

1. Extraction in `backend/app/services/analysis.py` (`derive_features()` for librosa scalars) or the
   section analyzers in `backend/app/services/track_analysis/analyzers.py`, mapped through
   `extract_feature_scalars()` in `track_analysis/pipeline.py`.
2. **A typed column** on `TrackAnalysis` in `backend/app/db/models/tracks.py`, listed in
   `ANALYSIS_FEATURE_COLUMNS`, with an Alembic migration. A feature that skips this is computed and
   then silently dropped.
3. Bump the phase's constant in `backend/app/config.py` (`FEATURES_VERSION` and so on; there is no
   `ANALYSIS_VERSION`) with a line in its history comment.
4. Re-analysis happens during a library sync, which also starts on its own every two hours
   (ADR-0138); a large library takes several. Budget for it (`VERSIONING.md`).

### Add an LLM tool

1. Schema in `MUSIC_TOOLS` in `backend/app/services/llm/tools.py`.
2. Handler in `ToolExecutor` or a module under `backend/app/services/llm/handlers/`. If REST does the
   same thing, both call an operation in `backend/app/operations/` (ADR-0173).
3. Tests for the schema and the execution path; `test_llm_library_tools.py` checks the dispatch map.

### Add an API endpoint

1. A route in `backend/app/api/routes/`, registered in `routes/__init__.py`, using `deps.py`.
2. Behaviour shared with another transport goes in `backend/app/operations/`.
3. `cd backend && make openapi && make contract-lock`, then `pnpm generate:api` from the root. CI fails
   if either is stale. After a schema change, `familiar-apple` needs `scripts/vendor-schema.sh --fetch`.
4. A feature adapter in `packages/frontend/src/api/` using the generated types.
5. If a client must *act* on a new error, give it an `ErrorCode` (`backend/app/api/exceptions.py`) and
   document it in `docs/ERROR-CONTRACTS.md`. Clients switch on `code`, never on `message`.

### Add a database migration

1. `backend/migrations/versions/YYYYMMDD_slug.py`; **revision ID at most 32 characters**.
2. Idempotent, with the shared guards:

   ```python
   from migrations.helpers import column_exists, table_exists, index_exists

   def upgrade():
       if not column_exists("tracks", "my_new_col"):
           op.add_column("tracks", sa.Column("my_new_col", sa.Text()))
   ```

3. The matching field on the model in `backend/app/db/models/`.
4. `scripts/lint_migrations.py` runs in CI; `make deploy-dev` runs `alembic upgrade head`.

### Add a section to a destination (ADR-0126)

1. Decide its unit: the collection → Library, the pipeline → Analysis, the installation → Server. A
   provider is one card under Server → Providers, never a new section.
2. Add it to `SECTIONS` in `packages/frontend/src/app/routes.ts`; its path is its route.
3. Mount it in `app/App.tsx` under that destination's `<SectionLayout>`, with an **absolute** path
   (`src/__tests__/navigationIntegrity.test.ts` checks every rail link).
4. Use `SectionPage` from `screens/AdminPage.tsx`; the layout owns the `<h2>`.
5. The accessibility spec (`packages/web/e2e/accessibility.spec.ts`) covers each destination.

### Regenerate README screenshots

The web screenshots are of the administration tool; the listening ones (`mac-*.png`) are taken from
the Mac app by hand.

1. A backend with a library: a local one, or `familiar-demo.fly.dev` **only while it is on** (during
   App Store review, ADR-0158). Against a server you do not own, use a Playwright config without
   `globalSetup`, which POSTs a library sync.
2. `cd packages/web && VITE_API_TARGET=<backend> pnpm dev`
3. `cd packages/web && BASE_URL=http://localhost:3000 npx playwright test --grep="screenshot"`

New screenshot tests have `screenshot` in the title (CI excludes them by that word), navigate with
`navigateToDestination()` and `navigateToSection()`, and use the file's `takeScreenshot()`.

## Configuration

Most settings live in settings.json in the server's data directory, and are edited in the web
admin. Only infrastructure needs
environment variables (`docs/CONFIGURATION.md` has them all):

```bash
DATABASE_URL=postgresql+asyncpg://familiar:familiar@localhost:5432/familiar   # required
REDIS_URL=redis://localhost:6379/0     # optional (ADR-0133): unset, Postgres holds the same state
MUSIC_LIBRARY_PATH=/data/music         # Docker volume mounting
FAMILIAR_DATA_DIR=/path/to/state       # where settings.json, caches and profiles live (ADR-0132)
```

## Running Locally

First setup, from a clone: the prerequisites and versions are in `CONTRIBUTING.md` (Python 3.11+
with headers, uv, Node 22, pnpm 10), then `make doctor`, `pnpm install` and
`cd backend && uv sync --extra dev`. After that:

```bash
docker compose -f docker/docker-compose.yml up -d   # Postgres + Redis
cd backend && make run                               # API with reload on :4400
cd packages/web && pnpm dev                          # web admin
```

Or as a server outside Docker runs: `DATABASE_URL=… FAMILIAR_DATA_DIR=… uv run python -m app.serve`
(migrates, then serves on 127.0.0.1).

### Against the NAS

`make dev-remote` runs the web dev server against the NAS backend; `make deploy-dev` builds, rsyncs
and restarts in about 30 seconds and verifies the container has the code it sent. Do not use the full
Docker build and release workflow for iteration; it takes about an hour.

## Quality Checks

Two tiers, and they are not the same thing:

```bash
make check                   # database-free: lints, types, contracts, boundaries, unit tests, docs
cd backend && make test      # the backend suite: creates and migrates familiar_test, then pytest
```

`make check` does **not** run the backend suite. That suite needs PostgreSQL: `make test` uses the
compose stack's, `make test-services test` starts a throwaway Postgres and Redis on 5434/6380 instead,
and a bare `uv run pytest` without `TEST_DATABASE_URL` refuses to run, because it would empty the
database `DATABASE_URL` names (ADR-0128).

Focused checks: `pnpm run typecheck` (every workspace package; Vite does not check types),
`pnpm --filter @familiar/frontend test`, and `cd packages/web && npx playwright test` with a backend
and web build running. The browser suite includes the accessibility gate; before a release, also make
the manual pass in `docs/RELEASE-CHECKLIST.md`. `make smoke-test-docker` runs the CLAP smoke test in
Docker (about 1.5 GB of model on first run).

## Apple Clients

Not in this repo. The phone and Mac apps are built from `../familiar-apple`; `make release-testflight`
and `make deploy-device` here only print that and exit non-zero.

## Guardrails and Conventions

- No `@capacitor` imports, service workers, PWA prompts, IndexedDB playback caches or browser playback
  state without an ADR.
- Keep error envelopes consistent; contract tests cover them.
- Keep `backend/openapi.json` current: the Apple clients consume it.
- Register specific routes before dynamic `/{id}` ones.
- Streaming and download routes release their database connection before sending a long body.
- Backend uses async SQLAlchemy with the `DbSession` dependency; Zustand for global UI state, React
  Query for server state.
- Profiles are selectors, not authentication: the profile ID travels in a header; the server token
  authorises (ADR-0045).
- Audio features are typed columns on `TrackAnalysis`; embeddings are pgvector columns.
- iOS Safari flexbox: a nested `flex-1` inside `flex-col` needs `min-h-0` at every level for
  `overflow-y-auto` to work.
- When fixing a bug, ask whether a test could have caught it, and add it.
