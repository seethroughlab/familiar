# Familiar Architecture

Familiar is split around ownership of responsibility rather than around every UI that can display
music.

## System Boundaries

| Layer | Owned here | Not owned here |
|------|------------|----------------|
| Server | Scanning, metadata, analysis, discovery, playlists, profiles, REST API, MCP API | Native playback UI |
| Web | Library administration, tools, server settings/status, embedded discovery, visualizer hosting | General-purpose player, offline listening, mobile playback |
| Apple clients | The REST/OpenAPI contract they consume | Native playback implementation, library listening UX |
| Visualizers | Document contract, catalog, bundled examples, sandboxed iframe host | Arbitrary in-page plugin execution |

The browser used to be a PWA/player. That path was retired: the current web app intentionally has no
service worker, no install prompt, no browser playback engine, and no offline track cache. The Mac
and iPhone apps own listening.

## Backend Shape

The backend is a FastAPI app backed by PostgreSQL, pgvector and Redis.

- `backend/app/main.py` wires startup, middleware, static files, OpenAPI customization and error
  handlers.
- `backend/app/api/routes/__init__.py` aggregates the REST surface once, preserving route order where
  dynamic paths could otherwise swallow specific routes.
- `backend/app/api/deps.py` owns database/profile dependencies and the streaming connection-release
  helper.
- `backend/app/api/auth.py` owns the server token gate for REST and MCP paths.
- `backend/app/db/models/` contains SQLAlchemy models. Fresh database shape must be represented here,
  not only in migrations.
- `backend/app/services/` contains domain services. Larger domains have been split into packages such
  as `background/`, `export_import/`, `llm/`, `metadata/`, `tasks/` and `track_analysis/`.

## Analysis Pipeline

Analysis is versioned by phase in `backend/app/config.py`:

- `FEATURES_VERSION` for scalar feature extraction
- `EMBEDDING_VERSION` for CLAP embedding pipeline changes
- `MELODIC_VERSION` for melodic analysis
- `GENERATIVE_ART_VERSION` for generated artwork
- `MOOD_TAGS_VERSION` for mood tag generation

Only bump the phase that changed. Re-analysis is triggered by library sync, not by a scheduler.

## Frontend Shape

The frontend workspace has two main packages:

- `packages/frontend`: shared React modules, API clients, Zustand stores, hooks, panels and screens.
- `packages/web`: Vite entry points for the administration app, embedded discovery document and
  visualizer document host.

Important boundaries:

- `packages/frontend/src/app/routes.ts` is the source of truth for top-level web destinations.
- `packages/frontend/src/api/base.ts` owns API origin, server token and profile headers.
- `packages/frontend/.dependency-cruiser.cjs` enforces cross-module import rules.
- `packages/web/src/main.tsx` deliberately does not register an audio engine.
- `packages/web/src/embed.tsx` and `packages/web/src/visualizer.tsx` register the small null/audio
  contracts needed by embedded surfaces.

## Contracts

- The REST schema in `backend/openapi.json` is committed because external clients generate from it.
- Error responses use a standard envelope. See `docs/ERROR-CONTRACTS.md`.
- Visualizers are sandboxed documents, not React components injected into the host page.
- Profile IDs select a listener. The server token, when configured, authorizes access to the server.

## Known Large Surfaces

These modules are important and large enough to treat with extra care:

- `backend/app/services/track_analysis/analyzers.py`
- `backend/app/services/outputs.py`
- `backend/app/services/s3_backup.py`
- `backend/app/services/llm/tools.py`
- `backend/app/services/scanner.py`
- `backend/app/main.py`

Prefer small, tested extractions when touching these files. Avoid opportunistic rewrites.
