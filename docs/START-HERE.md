# Start here

The first document for a developer. It describes Familiar **as it is now** — not how it got here.
History is in [`docs/decisions/`](decisions/) (the ADRs, indexed in [`docs/ADR-INDEX.md`](ADR-INDEX.md)) and
in [`CHANGELOG.md`](../CHANGELOG.md); this page links into it only where the reason for something
is the thing you need to know. Every path, `make` target and `pnpm` script named here is checked in
CI (`scripts/check_docs.py`), so if it is here, it exists.

## What Familiar is

A self-hosted music library server. It scans a local collection, analyses every track's audio —
energy, valence, tempo, key, a CLAP embedding of how it sounds — and uses that analysis to build
playlists, radio, an ambient mode and recommendations. Listening happens in native Mac and iPhone
apps. The browser is an administration tool.

## What this repository owns

| Piece | Where | Runs as |
|---|---|---|
| The server: REST API, MCP server, scanner, analysis pipeline, background jobs | `backend/` | Python FastAPI, one process, in the Docker image |
| PostgreSQL (with pgvector) and Redis | `docker/docker-compose.yml` | Sidecar containers |
| The web administration app | `packages/frontend/` (all the React), `packages/web/` (the Vite entry points) | Static files the server serves |
| The web transport client, generated from the API schema | `packages/api-client/` | A workspace package; never edited by hand |
| The first-party visualizer documents | `packages/visualizers/` | Sandboxed documents, built here, shipped inside the Mac app |
| The website | `site/` | Cloudflare Pages |

**Not here:** the Mac and iPhone apps are `familiar-apple`, a sibling repository. They consume this
server through a Swift client generated from `backend/openapi.json`, and they ship the visualizer
documents built here. Nothing in this repository runs on a phone.

## How the running pieces connect

```
  Mac / iPhone (familiar-apple)          browser (packages/web, served by the server)
        │ generated Swift client                │ generated TS client + hand-written wrappers
        ▼                                       ▼
  ┌────────────────────────── backend/app ──────────────────────────────┐
  │ api/routes/*  ──depends on──▶ operations/*  ──▶ services/*          │
  │ mcp/server.py (the MCP surface, same tools, same container)         │
  │ services/background/* (APScheduler in-process: sync, analysis, …)   │
  │ container.py: the one place long-lived resources are assembled      │
  └──────┬──────────────────────────┬──────────────────────────┬────────┘
         ▼                          ▼                          ▼
     PostgreSQL + pgvector        Redis (progress, locks)     the library on disk (read-only)
```

Three things about that picture that are decided, not incidental:

- **The server never creates, moves or deletes library files** ([`docs/ZERO-TOUCH.md`](ZERO-TOUCH.md)).
  Everything it learns about a track lives in the database.
- **The API schema is the contract.** `backend/openapi.json` is committed; the Swift client and
  `packages/api-client` are generated from it; CI fails if either is stale. Adding a field is a
  schema change first.
- **The web app opens on an Overview** that answers three questions — is the server healthy, is
  anything running, what needs attention — before it shows a total. Its other destinations are
  Library (the collection), Analysis (the pipeline) and Server (the installation).

## One request, traced

`GET /api/v1/soulseek/status` — the settings panel's "test connection" — through every layer. It is
the smallest complete example of how a feature is put together, and every file below is current.

| Layer | File | What it does |
|---|---|---|
| Panel | `packages/frontend/src/panels/server/SoulseekSettings.tsx` | A React Query `useQuery` whose `queryFn` is `soulseekApi.status` |
| Feature adapter | `packages/frontend/src/api/soulseek.ts` | Names the generated operation in the app's vocabulary; re-exports the wire type as `SoulseekStatus` |
| Generated client | `packages/api-client/src/generated/sdk.gen.ts` | `soulseekGetSoulseekStatus` — path, method, response type, from the schema |
| Transport | `packages/frontend/src/api/base.ts` | `installTransport()`: origin, server token and profile header, installed once on both axios instances |
| Route | `backend/app/api/routes/soulseek.py` | Receives the operation by `Depends`, invokes it, serialises the answer. Knows nothing of slskd |
| Dependency | `backend/app/api/deps.py` | `get_services` reads the container off `app.state`; `probe_soulseek_status` builds the operation |
| Operation | `backend/app/operations/soulseek.py` | `ProbeSoulseekStatus`: the use case, no HTTP |
| Container | `backend/app/container.py` | `Services`, built once in `create_app()`; `build_services()` is the only place a singleton is reached |
| Gateway | `backend/app/services/soulseek.py` | `SoulseekGateway`: reads the configured slskd URL *per call*, opens a client, closes it |
| Background | `backend/app/services/background/soulseek.py` | Every two minutes, asks the same gateway for downloads; a settled folder starts a library sync, remembered in Redis |
| Persistence | the scanner | Finds the downloaded files in the read-only inbox and puts them in pending review — no file moves |

Errors travel one envelope ([`docs/ERROR-CONTRACTS.md`](ERROR-CONTRACTS.md)); the two a client
*acts on* carry a `code` (`backend/app/api/exceptions.py`), and the transport switches on that,
never on the message.

## Five changes, and the whole of each

Each names the contract, test and documentation work, not just the first file to edit.

### 1. Add an endpoint
1. Route in `backend/app/api/routes/`; register it in `backend/app/api/routes/__init__.py`. Take
   the database and profile from `backend/app/api/deps.py`; if it needs a long-lived resource,
   take the container (`get_services`) and put the use case in `backend/app/operations/`.
2. `cd backend && make openapi && make contract-lock` — the schema is the contract, and the lock
   records whether the change was compatible.
3. `pnpm generate:api` from the root; wrap the operation in an adapter under
   `packages/frontend/src/api/`. Nothing under `components/`, `panels/`, `screens/` or `app/` may
   import `@familiar/api-client` (`pnpm --filter @familiar/frontend run check:boundaries`).
4. A contract test in `backend/tests/` (the `test_contract_*.py` files show the shape); an error a
   client must *act on* gets an `ErrorCode` and a row in `docs/ERROR-CONTRACTS.md`.
5. The Swift client regenerates from the same schema in `familiar-apple`.

### 2. Add a persisted field
1. The column on the model in `backend/app/db/models/`, and a migration in
   `backend/migrations/versions/` named `YYYYMMDD_slug.py` with a revision id of 32 characters or
   fewer, guarded with the helpers in `backend/migrations/helpers.py` so it is idempotent.
2. If it is an audio feature: list it in `ANALYSIS_FEATURE_COLUMNS` and bump `FEATURES_VERSION` in
   `backend/app/config.py` — a feature that skips the typed column is computed and dropped.
3. `backend/tests/test_migrations.py` proves the chain; `make migrate` applies it locally.
4. Then it is an endpoint change: step 2 of the path above.

### 3. Add background work
1. A mixin in `backend/app/services/background/` (`soulseek.py` is the small worked example),
   scheduled from `BackgroundManager.startup()` in `backend/app/services/background/manager.py`.
   Resolve dependencies from `self.services`, the container the manager is handed — never from a
   singleton inside the job.
2. Progress and "already triggered" state go in Redis with a TTL; the Overview and Server → Jobs
   read `GET /background/jobs`.
3. Test the mixin with a fake manager, the way `backend/tests/test_soulseek_poll.py` does: the
   test decides when the job fires and what the gateway answers.

### 4. Add an admin section
1. Decide the unit: the collection → Library, the pipeline → Analysis, the installation → Server. A
   provider is one card under Server → Providers, never a new section.
2. Add it to `SECTIONS` in `packages/frontend/src/app/routes.ts`; its path is its route.
3. Mount it in `packages/frontend/src/app/App.tsx` under that destination's `SectionLayout`, with
   an **absolute** path — `navigationIntegrity.test.ts` reads `path="/…"` from that file and checks
   every rail link.
4. The component uses `SectionPage` from `packages/frontend/src/screens/AdminPage.tsx`; the layout
   owns the `<h2>`. If the Overview should flag something about it, the rule goes in
   `packages/frontend/src/screens/overview/attention.ts`, which is pure and tested.

### 5. Add a visualizer
1. Read [`docs/VISUALIZER_API.md`](VISUALIZER_API.md) first: a visualizer is a document in a folder
   with a manifest, driven by four `postMessage` events. The two in `packages/visualizers/examples/`
   need no build at all.
2. A React + three.js one lives under `packages/visualizers/`, builds an IIFE into a dist folder of its own,
   and is shipped by `familiar-apple`, which vendors that folder into its bundle. Nothing here serves
   it at runtime. The bridge, the shared effects and the event fixtures come from
   `packages/visualizer-sdk` (ADR-0125) — import `@familiar/visualizer-sdk` rather than copying
   `familiar.ts` from a sibling, which is how four visualizers came to carry six identical files.
3. Its manifest's `affinity` is what lets the server pick it for a track.

## Two commands

- `make doctor` — what this machine can do with this checkout: runtimes, whether the database and
  Redis answer, which database that is and whether tests would accept it, migration state, and
  whether the committed schema, its lock and the generated web client agree. Read-only.
- `make check` — the safe local equivalents of the required CI checks: lints, type checks, the
  frontend and SDK unit tests, the contract and boundary checks, this document's own check. The
  backend suite needs a disposable database and is its own command: `cd backend && make test`.

## Security posture, stated plainly

**Familiar has no login.** A server token exists ([ADR-0045](decisions/ADR-0045-familiar-authenticates-inbound-requests.md)):
when one is configured, every REST and MCP request must present it. **It is not on by default**, and
media — streams, artwork — cannot carry it, because an `<audio>` element and a Mac's casting target
send no headers. So a Familiar port that is reachable from the internet is a public server. Keep it
on your own network or a tailnet; the website's remote-access section says why, and never says how
to port-forward.

## Where to read next

- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) — the backend and frontend shape in more detail, and the
  modules to treat with care.
- [`docs/HEALTH.md`](HEALTH.md) — the current debt register: what is known to be wrong or unfinished,
  with the evidence and what closes it.
- [`docs/ADR-INDEX.md`](ADR-INDEX.md) — the decisions, by subsystem.
- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — setup and the checks to run before a pull request.
- [`docs/INSTALLATION.md`](INSTALLATION.md) — running it as an operator rather than developing it.
