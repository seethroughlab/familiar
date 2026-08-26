# Familiar

An LLM-powered local music player that combines library management with AI-powered discovery. Users describe what they want to listen to in natural language, and Claude creates playlists from a deeply-analyzed local music collection.

## Architecture

- **Backend**: Python FastAPI + PostgreSQL (pgvector) + Redis
- **Frontend**: React + TypeScript + Vite + Tailwind + Zustand (pnpm workspace monorepo)
- **Analysis**: Audio embeddings and features extracted via librosa/torch
- **LLM**: Claude API with tool-use
- **Offline**: IndexedDB (Dexie) for track caching, download queue, playlist cache

## Architecture Decisions (ADRs)

**Architectural changes are made through ADRs in `docs/decisions/`. Read the relevant ones before
changing anything they govern, and propose a new one before making a decision they don't cover.**

An ADR is warranted when a change sets a direction rather than implements one: a new client or
platform, a data model that other work will build on, moving responsibility between server and
client, a new external dependency or protocol, or reversing something an existing ADR decided.
Ordinary feature work, bug fixes, and refactors inside an established direction do not need one —
they just need to respect the ADRs already in force.

### Convention

- Filename `ADR-NNNN-kebab-case-title.md`; heading `# ADR-NNNN: Title Case`.
- `Status:` (`proposed` → `accepted`; also `superseded by ADR-NNNN` / `rejected`) and `Date:` lines.
- Optional `Implementation:` block, added as phases land, recording what shipped on which branch —
  an accepted ADR stays a living record, not a snapshot.
- Optional `Extends [ADR-NNNN](ADR-NNNN-slug.md)` links after the header.
- Sections in order: `## Context`, `## Decision` (numbered points once non-trivial),
  `## Alternatives Considered`, `## Consequences` (bulleted, tagged **Positive** / **Tradeoff** /
  **Follow-up**).
- The directory holds only ADRs — no README, no template file.

### Rules

1. **One decision per ADR**, decomposed so each can be planned, approved, and executed on its own.
   Propose the set together; note the execution order, which often differs from the numbering.
2. **New ADRs start `Status: proposed`** and flip to `accepted` only when that specific ADR is
   approved. Never write one straight to `accepted`.
3. **`## Alternatives Considered` must contain real rejected options with real reasons.** Strawmen
   make the record worthless.
4. **Verify every metric, file path, and line number cited** against the repo at write time. ADRs
   are read months later as fact.
5. **Record contradicted premises in `## Context`.** If investigation disproved the original
   rationale, say so, so nobody re-derives it. See `ADR-0001` for an example.
6. **Never edit an accepted ADR's Decision to reflect a change of mind** — supersede it with a new
   ADR and update the old one's `Status:`.

### Current set and execution order

`ADR-0001`–`ADR-0007` cover the move to native macOS/iOS clients, the web app's role as the
management surface, server-owned playback queue, event-sourced listening feedback, the shared
ranking engine, precomputed offline ranking, and OpenAPI-generated clients.

**Numbering is logical order; execution order is different and deliberate:**

| # | ADR | Why here |
|---|---|---|
| 1 | `0001`, `0002` | Framing only. No product code beyond freezing the Capacitor app to bug-fix-only (deleted 2026-08-11). Everything else inherits from these. |
| 2 | `0004` → `0005` | Ships the radio feature to the web app in weeks. `0004` first so skip/completion events accumulate during the months of native work — the recommender is otherwise cold at launch, and that data can only be gathered in wall-clock time. |
| 3 | `0007` | Must land before Swift consumes the API; the schema hardening is a prerequisite, not a cleanup. |
| 4 | `0003` | Behind a flag, in the web app, proven against the existing player test suite before the native client depends on it. Highest-risk change in the set. |
| 5 | `0006` | Depends on `0005`'s weight profiles existing. |
| 6 | native build | Begins under `0001` once `0003`, `0006`, `0007` are stable. |

The ordering principle: **server-side work that every client inherits comes before client work**, and
anything that accumulates data over time starts as early as possible.

**`ADR-0013`–`ADR-0016` bring management surfaces to the Mac app** (all four accepted 2026-08-01).
`0013` supersedes `0002`: macOS becomes a management surface alongside the web app, which keeps
everything; iOS stays the listening path. Their own order:

| # | ADR | Why here |
|---|---|---|
| 1 | `0013` | Framing only, and the one that supersedes. Nothing else is coherent without it. |
| 2 | `0014` | Widens the generated surface to eleven tags. Cheap, and unblocks pending review, proposed changes and mixtapes. |
| 3 | `0015`, `0016` | Independent of each other. `0015` exposes six effects the engine already has; `0016` decides embed-vs-native and covers Discover and Music Map. |

Smart playlist CRUD and the album/artist grids need no ADR — ordinary work inside `0013`'s direction,
and both depend on nothing, so they were the fastest visible wins once `0013` was accepted.

**`ADR-0018`–`ADR-0019` bring the Mac's arrangement to the phone, both accepted and shipped.** `0018`
replaces the segmented picker and the Collections screen with one root list of destinations; `0019`
opens that list's Discover row onto the same embedded surface the Mac uses. Neither reverses
`ADR-0013` point 2 — every destination involved is a way of finding something to play, and the
management surfaces stay off the phone. Both shipped — `0018` in `familiar-apple` #44, `0019` in
#53 — and the phone's Chat row followed under `0022`.

Within `0016`, Music Map shipped before embedded Discover (`familiar-apple` #41, then #43): the two
halves were independent, and the map was one self-contained screen against endpoints that already
generate, while the embedding half carried point 4's rule that an embedded page must never construct
a second audio engine. **The map's interaction was half-wired and is now finished** — the footer had
advertised a scroll-to-zoom nothing implemented, so `zoomed(by:toward:)` was reachable only through
`stepped()`, and a 1pt drag threshold ate click-to-focus. Worth keeping from that: **the footer of a
canvas is documentation, and nothing checked it against the gestures that existed.**

**`ADR-0017` (`accepted`, shipped both sides) governs how embedded Discover boots.** It extends `0016`. It began
by recording that point 4's conclusion — forbid playback, and no second engine is constructed — did
not hold, because seven capability helpers constructed one without playing anything. That cause has
since been fixed, and the ADR records both that and why it still stands: **Discover itself plays
music** (`DiscoverTrackList` drives `playerStore`), so an embedded copy has real construction paths,
and the bridge has to catch every one. The **null audio engine** on its own entry point is what makes
a missed intent inert rather than a second engine. Both halves are built: `/embed` serves its own
document registering the null engine, and `familiar-apple` #43 added the `WKWebView`, the
`WKScriptMessageHandler` and the native "unavailable" state.

**Three defects have come out of that surface since, all the same shape** — an affordance whose
destination is not mounted, failing silently: zero-height virtualised lists (`familiar` #70), a play
that posted no intent and spun forever (#74), and "Listening Ideas" with no chat to open (#76).
Worth knowing before adding anything to the embedded page: check what the affordance reaches, not
just that it renders. The ADR's own record carries the detail.

**`ADR-0020`–`ADR-0021` are accepted and shipped (2026-08-02).** `0020` widens the embed bridge by one message so
Discover's links open the app's own artist and album screens, and states the bar for a third. `0021`
turns the Mac's track lists into sortable tables with a column chooser, bumps the **macOS floor to
14** for `TableColumnCustomization` (iOS stays at 15), and adds `playCount`/`dateAdded` to the
server's sort allowlist. `0021`'s load-bearing point is that the Tracks list sorts **server-side** —
it pages at 50, and sorting the loaded page would repeat the library-shuffle defect on a surface
where a wrong order looks like an order.

**`ADR-0022` builds chat natively** (accepted 2026-08-02; the Mac surface shipped in
`familiar-apple` #54, with the phone in #55 and the web-app gate in `familiar` #78, both open at the
time of writing). It extends `0016` by applying that ADR's point 1 test to a
third surface: chat is 965 lines against Discover's 2,828 and has had 6 commits in
six months against 15, so it lands on the **native** side rather than being embedded. The bridge
settles it independently — a chat response carries `queued_tracks` and `playback_action`, so an
embedded chat would need both, against `0020` point 2's cap of two. Its load-bearing point is point
3: **the destination is absent when the active provider is not configured**, read from
`GET /chat/status`, which already existed for that purpose and which nothing had ever called.
Not a disabled row and not an error after the user has typed — that is the "Listening Ideas" defect
(`#76`) moved one step later. `familiar` #78 applies the same rule to the web app, where
`chatApi.getStatus` had never been called at all.

**"Listening Ideas" came back without growing the bridge.** The obvious route was a third message
under `0020` point 3, whose bar a chat prompt clears once a native chat exists — but it was not
needed: `/library/discover/prompts` carries the `library` tag and was already generated, so the
native surface asks for the prompts itself and shows them in the chat's empty state, above the field
that acts on them. **The bridge stays at two messages.** Do not add a third for this.

**`ADR-0023` moves the phone to iOS 17** (accepted 2026-08-03). It extends `0021`, whose point 2 had
said "iOS is untouched at 15". The prompt was three unavailable APIs while building chat on the
phone; the finding was that the floor is why **the phone has no swipe-back at all** —
`NavigationStack(path:)` is iOS 16, so `LibraryView` hand-rolls a `[BrowseRoute]` stack across ten
push sites behind a custom back bar. 17 rather than 16 because 16 would leave the `onChange`
compatibility branch alive for one API. **Adopting `NavigationStack` is deliberately not part of it**
— that is the payoff, recorded as a follow-up, and a navigation rewrite should not ride along with a
deployment-target bump.

**`ADR-0085`–`ADR-0086` make music videos a Mac function** (both accepted, proposed 2026-08-18).
**Execution order is `0086` then `0085`** — server work every client inherits first. `0086` makes the
existing feature a real resource: `track_videos` is read and written by nothing and, on any database
stamped at baseline before the model landed, **does not exist**; the stream advertises
`Accept-Ranges` and never honours a `Range`; and no generated client can reach the endpoints. `0085`
then says what the PWA got wrong: **a music video is a way of playing a track, not a visualizer.**

**Read both ADRs' own record of what drifted under them before working from their line numbers.**
They were drafted while the web app still had a player. Since then `MusicVideo.tsx`,
`packages/frontend/src/player/` and `FullPlayer.tsx` have all been deleted (#190, #192, #194), so the
web visualizer went by collateral rather than by decision, `0085` point 9's "removes a `queueStore`
pin" argument is vacuous, and its point 10's parity reasoning is moot because the player's removal
countdown already emptied. What survives is sharper, not weaker: the feature is now reachable from
**nothing**, while five endpoints and a yt-dlp service run in production with zero callers in either
repo.

Three traps the two ADRs name explicitly, all of which the compiler is silent about:
**do not write a range parser** — `app/api/streaming.py`'s `stream_file` exists and its docstring
records the incident the hand-rolled one caused; **do not add `videos` to the generator's `tags:`** —
the filter keys are a union, so the tag re-admits the stream the ADR deliberately leaves hand-written
(name the four JSON operations instead, per ADR-0031); and **`visualizerID` is stored as a bare
`String`**, so deleting `VisualizerChoice.musicVideo` leaves profiles holding `"music-video"`
selecting nothing unless they are reset.

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
└── web/                   # Web entry point + Web Audio engine + PWA
    ├── src/
    │   ├── main.tsx       # Registers WebAudioEngine, sets up SW
    │   └── WebAudioEngine.ts
    ├── e2e/               # Playwright E2E tests
    └── vite.config.ts     # PWA plugin, dev proxy, manual chunks
                           # The Apple clients live in the familiar-apple repo (ADR-0001);
                           # packages/ios, the Capacitor app, was deleted 2026-08-11.
backend/
├── app/
│   ├── api/routes/        # FastAPI endpoints (~29 route files)
│   ├── db/models/         # SQLAlchemy models (tracks, profiles, playlists, artists, ...)
│   └── services/          # Business logic
│       └── llm/           # Tool definitions and execution (tools.py, executor.py, handlers/).
│                          # No provider layer: ADR-0048 removed service.py, providers.py and
│                          # both SDKs when chat was replaced by the MCP server (ADR-0043).
├── migrations/versions/   # Alembic database migrations
└── tests/                 # pytest tests
docs/
└── decisions/             # ADRs — read before changing what they govern
```

## Key Files

| Task | Files |
|------|-------|
| Database models | `backend/app/db/models/` (package: `tracks.py`, `profiles.py`, `playlists.py`, `artists.py`, …) |
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
| Player state | `packages/frontend/src/stores/playerStore.ts` |
| Download queue | `packages/frontend/src/stores/downloadStore.ts` |
| Offline storage | `packages/frontend/src/services/offlineService.ts` |
| Playlist caching | `packages/frontend/src/services/playlistCache.ts` |
| Favorites | `packages/frontend/src/hooks/useFavorites.ts` |
| IndexedDB schema | `packages/frontend/src/db/index.ts` |
| Full player | `packages/frontend/src/components/FullPlayer/` |
| Discovery | `packages/frontend/src/components/Discovery/` |
| Chat (web) | `packages/frontend/src/components/Chat/`, `api/chat.ts` |
| Embedded surface | `packages/frontend/src/renderEmbed.tsx`, `components/Embed/`, `services/embedBridge.ts`, `player/playbackInterceptor.ts` |
| Smart playlists UI | `packages/frontend/src/components/SmartPlaylists/` |
| Settings | `packages/frontend/src/components/Settings/` |
| Docker setup | `docker/Dockerfile`, `docker/docker-compose.prod.yml`, `docker/start.sh` |
| CLAP smoke test | `backend/scripts/smoke_test_clap.py` |

## Frontend Architecture

The frontend uses a **registration pattern** for platform-specific code:

- **`createEngine.ts`** — `registerEngineFactory(fn)` sets the audio engine constructor

`packages/web/src/main.tsx` registers its implementation before calling `renderApp()`, and is now
the only registrar. The pattern stays because `/embed` and `/visualizer` are separate entry points
that need different engines — not because a second platform exists.

**There is no Capacitor anything.** That app was deleted on 2026-08-11 (ADR-0001 point 6), and the
detection that outlived it — `isNativeApp()`, which tested `window.Capacitor` — was permanently
false while still gating real code. It was removed along with `registerPreferencesProvider`, a
filesystem provider nothing registered, an AirPlay bridge with no registrar, and the
Connect-to-Server screen. If you find yourself adding a `isNativeApp`-shaped check, the answer is
that the native clients live in `familiar-apple` and do not run this bundle.

## Common Tasks

### Add a new audio feature
1. Add extraction logic in `analysis.py` — `derive_features()` for librosa scalars (`extract_features()`
   is a thin wrapper), or `services/track_analysis/analyzers.py` for the section analyzers, mapped
   through `extract_feature_scalars()` in `track_analysis/pipeline.py`
2. **Add a typed column** to `TrackAnalysis` in `backend/app/db/models/tracks.py`, list it in
   `ANALYSIS_FEATURE_COLUMNS`, and write an Alembic migration. Features were promoted out of JSONB
   into typed columns — a new feature that skips this is computed and then silently dropped
3. Bump `FEATURES_VERSION` in `config.py` and add a line to the history comment beside it. There is
   **no `ANALYSIS_VERSION`**; the constants are per phase, so bumping features leaves embeddings and
   melodic data alone
4. Re-analysis only happens during a **library sync** — nothing is scheduled. Budget for it: one
   worker, a fresh interpreter per track, and an 8-hour cap on the features phase, so a large
   library takes several consecutive syncs. See `VERSIONING.md`

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
3. Always use the shared guard helpers from `migrations.helpers` for idempotent migrations:
```python
from migrations.helpers import column_exists, table_exists, index_exists

def upgrade():
    if not column_exists("tracks", "my_new_col"):
        op.add_column("tracks", sa.Column("my_new_col", sa.Text()))
```
4. Add corresponding field to the SQLAlchemy model in the matching `backend/app/db/models/*.py`
5. `deploy-dev.sh` auto-runs `alembic upgrade head` on deploy

### Add a new settings section
1. Add component in `packages/frontend/src/components/Settings/`
2. Export from `Settings/index.tsx`
3. Add to settings tabs in main Settings component

### Regenerate README screenshots

**The web app's screenshots are of an administration tool** — the three destinations and Settings
(ADR-0058 point 2). The listening screenshots are `mac-*.png`, taken from the Mac app by hand;
there is no script for those, because the browser cannot render them.

1. Backend with a library. Against the demo server: `familiar-demo.fly.dev` (~32 tracks).
2. Frontend pointed at it: `cd packages/web && VITE_API_TARGET=https://familiar-demo.fly.dev pnpm dev`
3. `cd packages/web && BASE_URL=http://localhost:3000 npx playwright test --grep="screenshot"`

**Against a server you do not own, run with a config that has no `globalSetup`.** The repo config's
`e2e/global-setup.ts` POSTs `/api/v1/library/sync` — fine against CI fixtures, a write against
anyone else's server.

Output goes to `screenshots/` (README) and `screenshots/mobile/` (a responsive sweep across five
device widths, linked from nowhere and used for spotting layout breakage).

To add one:
1. Add a test to `screenshots.spec.ts` whose title contains `screenshot` — the CI exclusion and the
   run command both match on that word.
2. Navigate with `navigateToDestination()` (Library/Tools/Server) or `navigateToTab()`
   (Library/Playlists/Settings). There is no `selectBrowser()`; the library browsers were unmounted
   by ADR-0050 and ADR-0057.
3. Use the file's `takeScreenshot()`, which waits for spinners and "Loading…" to clear. **Do not use
   `waitForContentReady({ images: true })`** — it does not honour the timeout it is given while a
   page is re-rendering (asked for 8s, measured at 27s).
4. Update README.md to include it.

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

### Docker / Smoke Tests

```bash
# macOS Docker stack (from docker/)
./start.sh                   # Start with platform detection + health check
./stop.sh                    # Stop

# CLAP smoke test in Docker (downloads ~1.5GB model on first run)
make smoke-test-docker

# Heavy analysis tests with real CLAP (not run in normal CI)
cd backend && FAMILIAR_HEAVY_TESTS=1 uv run pytest tests/test_analysis_heavy.py -v
```

### iOS Development

**Not in this repo.** The phone and Mac apps are built from `familiar-apple` (ADR-0001); the
Capacitor app that used to live in `packages/ios` was deleted on 2026-08-11, once the native client
had shipped a TestFlight build of its own.

```bash
cd ../familiar-apple && ./scripts/release-testflight.sh   # archive, sign, upload
```

Same App Store Connect record (`com.familiar.player`), so it replaces rather than migrates. `make
release-testflight` and `make deploy-device` still exist here and print this, then exit non-zero.

## Code Conventions

- Backend uses async SQLAlchemy with `DbSession` dependency
- Frontend uses Zustand for global state, React Query for server state
- Profile-based multi-user (no traditional auth) - profile ID in header
- Audio features stored as JSONB for flexibility
- Embeddings stored in pgvector for similarity search
- SmartPlaylistService uses `**kwargs` with `setattr()` for flexible updates - new model fields work automatically
- Offline-first: `offlineService.ts` manages IndexedDB track storage, `playlistCache.ts` caches playlists, `downloadStore.ts` manages download queue with persistence and resume
- iOS Safari flexbox: nested `flex-1` inside `flex-col` needs explicit `min-h-0` for `overflow-y-auto` to work - add at every level of the flex chain
- Platform-specific code uses the registration pattern; `@capacitor` packages are gone entirely and must not come back (ADR-0001 point 6)

- When fixing a bug, ask yourself: can we add a test that could have caught this?
