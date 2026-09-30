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

The web app is an administration tool with no install prompt, no browser playback engine and no
offline track cache; the Mac and iPhone apps own listening. `packages/web/public/sw.js` still exists
and must keep answering: it is a tombstone that unregisters the service worker browsers installed
before the PWA was retired, and a 404 there would leave those browsers on a cached app forever.

## Backend Shape

The backend is a FastAPI app backed by PostgreSQL, pgvector and Redis.

- `backend/app/main.py` holds `create_app(settings, services)`: middleware in the one order that
  works, static files, OpenAPI customization and error handlers. `backend/app/container.py` is the
  container it is given and the only place a long-lived resource or singleton is reached for.
- `backend/app/operations/` holds use cases a route invokes by dependency; they contain no HTTP.
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

The frontend workspace has four kinds of package:

- `packages/frontend`: the React — API adapters, Zustand stores, hooks, panels and screens.
- `packages/web`: Vite entry points for the administration app, embedded discovery document and
  visualizer document host.
- `packages/api-client`: the transport client generated from `backend/openapi.json`. Only
  `packages/frontend/src/api/` may import it; screens consume the adapters there.
- `packages/visualizers/*`: the first-party visualizer documents, each building to its own folder,
  shipped by `familiar-apple`.

Important boundaries:

- `packages/frontend/src/app/routes.ts` is the source of truth for the four destinations and every
  section under them; a section's path is its route, and one `isUnder()` decides what is lit.
- `packages/frontend/src/api/base.ts` owns API origin, server token and profile headers, installed
  once on both the hand-written wrappers' axios instance and the generated client's.
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
