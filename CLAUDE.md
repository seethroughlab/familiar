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
(name the five JSON operations instead, per ADR-0031); and **`visualizerID` is stored as a bare
`String`**, so deleting `VisualizerChoice.musicVideo` leaves profiles holding `"music-video"`
selecting nothing unless they are reset.

**`ADR-0087`–`ADR-0089` make a visualizer a document, and the app bundle seed it.** A visualizer is
now a folder with an `index.html`, sandboxed at an opaque origin and driven by `postMessage` — not a
component the host supplies React to. `App/Shared/Visualizers.bundle/` ships five of them and
`VisualizerPlugins.seed` copies them into the drop-in folder once. `ADR-0091`/`0092` moved the
visualizers and plugin folders out of this repo entirely; the server no longer serves them.
`ADR-0065`, which proposed seeding two examples the old way, is **superseded by `0089`** — its point
2's "once, ever" reasoning survives and is cited in `VisualizerPlugins.swift`, but its examples were
the `"main": "dist/index.js"` shape `0087` replaced.

**`ADR-0072`–`ADR-0077` and `ADR-0079` restructure the API** (all accepted, merged 2026-08-30 as a
nine-PR stack). Tags mean one thing, paths follow function rather than history, and endpoints
nothing called were deleted. **Existing clients keep working**: the five `/queue/*` paths that moved
are aliased, and `ADR-0079` point 5 requires that *every* alias in the API live in one module —
`backend/app/api/routes/compat.py`. They are `include_in_schema=False`, delegate to the same function
object rather than a copy, and answer with `Deprecation: true` and a `Sunset` date. The removal
trigger is written down in that file: when no App Store build calling `/queue/*` is still offered.

**`ADR-0093`–`ADR-0094` are shipped.** `0093` suggests tracks you already own for Favourites and any
playlist, each explaining itself with a real pair of tracks rather than a generated label — three
attempts at naming a cluster failed first. `0094` toggles the artists grid to a sortable table;
**sorting is server-side**, because paging at 50 and sorting the loaded page repeats the
library-shuffle defect on a surface where a wrong order looks like an order.

**`ADR-0095`–`ADR-0097` are about the website, and two of them exist because the record was wrong.**
`0095` makes the install section platform-first — five panels, one per machine you might install on —
and supersedes `ADR-0055` point 1's reader, who was defined as "comfortable enough to run `docker
compose up`". `0096` gives remote access its own section leading with the reason: **Familiar has no
login**, because `ADR-0045` is accepted and unimplemented, so "don't port-forward 4400" is the
difference between a private server and a public one.

`0097` exists because **the live site served an April build for four months**. Cloudflare's
`production_branch` was `master` against a repository on `main`, so every green deploy landed as a
preview and the production alias never moved — while `check-claims.py` passed, because it audits the
working tree. It now fetches the deployed site as well. **Both are fixed**, and the shape is the one
this project keeps finding: a check whose subject is not the thing anyone uses.

Three things established by running them rather than reading them, all of which had been asserted
wrongly for months: **Docker Desktop on Windows genuinely rejects the `journald` driver** (exit 125),
so `docker-compose.desktop.yml` — renamed from `.macos.yml`, since the content is "this host is not
Linux" — is required there; **the first pull is ~7 GB**, not the 4 GB three docs claimed; and
**disabling CLAP costs far more than "semantic search"**, since `TrackAnalysis.embedding` is read by
eighteen modules including Find Similar and suggested tracks.

**`ADR-0116` lets a host acquire what the discovery tools recommend** (accepted 2026-09-15).
Familiar talks HTTP to a **slskd** the operator already runs — never the Soulseek protocol — and
only once `soulseek_url` is set. On a server with none configured the four tools are **withheld
from `tools/list`** by `app/mcp/server.py`'s `withheld_tools()`, which is ADR-0022 point 3 applied
to tools: absent, not present and failing. Two slskd facts the schema does not tell you, both
pinned in `tests/test_soulseek.py`: responses read as `[]` until the search `isComplete` (~15–25 s),
and `extension` is blank on most files. `find_missing_on_soulseek` checks the library **before** the
network; `download_from_soulseek` lists the folder before enqueueing, so a one-track match downloads
the album.

**`ADR-0117` closes the loop without a file move** (accepted 2026-09-15, built with 0116). The
follow-up 0116 first asked for — "move-and-sync" — would have broken **zero-touch**
(`docs/ZERO-TOUCH.md`, commit `5fe90d7a`: Familiar never creates, moves or deletes library files).
Instead slskd's completed folder is bind-mounted **inside** the library at `/music/Inbox:ro`
(`SOULSEEK_INBOX_PATH`), the ordinary scanner finds new files and puts them in `PENDING_REVIEW`,
and `background/soulseek.py` polls slskd every two minutes to start a sync when a folder has
*settled* — every file terminal, at least one success — once per success count. Not per file
(slskd moves files to `complete` one at a time) and not a watcher (inotify across bind mounts).
Without an inbox, the tools return a **handoff** — the folder's path as slskd sees it, the
library path, and "move it, then call `start_library_sync`" — for the listener or a host with
its own shell to act on; the move never goes through Familiar. The dead `/imports-incoming`
mount and `GET /import/scan-path` are gone. If you find yourself adding a `shutil.move` for
downloads, read 0117's Alternatives first.

**`ADR-0118` makes a phone download AAC when the source is lossless** (accepted 2026-09-15,
both halves shipped). `GET /tracks/{id}/stream?format=aac` encodes a lossless file once — 256 kbps, ffmpeg's
native `aac` (the image has no `libfdk_aac`), cached beside the AIFF remux in `data/transcode_cache`
— and serves a **lossy source untouched**, with its own MIME type: the parameter means "no larger
than AAC", never "re-encode". Playback never sends it; only `familiar-apple`'s `DownloadManager`
does, from a device-local preference (ADR-0029) that defaults to AAC on the phone and to originals
on the Mac. A query parameter rather than a header, the inverse of ADR-0112's reasoning: the bytes
differ, so the URL must. One number decides the risk — **12.4 s per 4:32 FLAC on the NAS, one
core** — so encodes run under their own semaphore of four, separate from the file-response
ceiling, and the first sync after it ships is the thing to watch. Plan in
`familiar-apple/PLAN-lossy-downloads.md`.

**`ADR-0119` asks the corpus by recording before it asks by hash** (accepted 2026-09-16, built
the same day). clapback's `ADR-0019` measured the corpus key as a function of the fingerprinting
path — `fpcalc` and pyacoustid agree on 24 of 56 FLACs — so a miss by hash does not mean the
corpus lacks the recording. `CommunityCacheService.lookup(…, recording_mbid=)` asks
`GET /v1/recordings/{mbid}` first and the hash only on a 404; **an unanswered recording request
does not fall through** (the `ADR-0008` duplicate-agreement trap, point 4). `contribute` sends
`recording_mbid` when held, a claim in the same request. The pipeline passes
`track.musicbrainz_track_id` — present for ~90% at re-analysis, almost never at first analysis —
and writes `embedding_source` as `community_cache:recording` or `community_cache:hash`, so the
next re-analysis reports the split. Batch calls, the AcoustID track id and adopting
`clapback-client` are named and left. `docker/Dockerfile` no longer installs `git`: the
`git+` dependency it was for has been on PyPI since 2026-09-04.

**`ADR-0120` makes a weighted shuffle apply to the queue that is playing** (accepted 2026-09-16,
both halves built the same day). ADR-0035 point 4 applied a preset only where a queue was drawn
from the whole library; the listener's everyday queue is Favorites, and the preset acted on a
button they never pressed. `GET /tracks/ids?favorites=true` scopes every path — weighted, random,
sorted, `start_with` — to the profile's favourites by joining `ProfileFavorite` on the base query
(400 without a profile: a whole-library answer would look like the feature working). Additive;
contract re-locked at v1. On the Apple side `FamiliarPlayer.queueScope` (`.library` / `.favorites`)
replaces the boolean, a preset chosen over a scoped queue re-draws it, and turning shuffle on over
one with a preset set draws weighted after the local permutation. Nothing else is weightable.

**`ADR-0121` makes a batch of downloads a Live Activity** (accepted 2026-09-17, client only).
From the lock screen a favourites sync that is working and one that is wedged looked identical.
`familiar-apple` gains a `DownloadActivityWidget` extension: one card per batch — "Downloading
104 of 1478", the moving track, "Transcode · AAC" or "Direct · original files" (ADR-0118's
preference, not each file's fate), failures, a ring with a stop button. Driven from `Downloads`'
coalesced phase stream, never the raw 34/s one; counts are the card's own (what was seen in
flight), not `DownloadManager.states`. A drained queue ends it "Finished" for five minutes, or
"Stopped at 62 of 98 — open Familiar to continue" when the process that held the queue is gone.
The stop button is a `LiveActivityIntent` reaching `DownloadManager.cancelAll()` through a hook
`AppDelegate` installs on every launch — the first control that discards a whole queue.

**`ADR-0122`–`ADR-0130` are all accepted (2026-09-17); only `0128` is built, the same day.** They are about
structure rather than features: how the Apple client, the backend, the web client and the docs are put
together. Two of them exist because a routine command was dangerous — until `0128` shipped, `uv run pytest`
deleted every row from eighteen tables in whatever database `DATABASE_URL` named, and CI's
disposable database was itself called `familiar`, so the name proved nothing. Execution order, which
again differs from the numbering:

| # | ADR | Why here |
|---|---|---|
| 1 | `0128` | **Built 2026-09-17.** `TEST_DATABASE_URL`, a `_test` suffix with no second marker, CI renamed to `familiar_test`. Its guard runs in the rootdir `conftest.py` until `0130` gives it a factory. |
| 2 | `0130` | **Soulseek slice built 2026-09-18.** `create_app(settings, services)` exists; `app/container.py` holds one gateway; the route, MCP executor and background poll are handed it. The pattern for the next domain is the ADR's Implementation block. Library sync and analysis go last; `scanner.py:126` still reads env at import. |
| 3 | `0129` | `@hey-api/openapi-ts`, pinned; the first slice is the one whose interceptor greps English (`base.ts:197`). Before `0126` so the new screens consume feature adapters, not `api/*.ts`. |
| 4 | `0126` | Overview / Library / Analysis / Server — four, after a panel-level audit found the first draft's three split providers, the analysis pipeline and backup across groups, and placed two screens that don't exist (pending review; editable library paths). Its gate — a mocked Overview reviewed against the idle NAS and a failing server, desktop and 400px — was cleared the same day. Old router paths redirect — not an `0079` alias. |
| 5 | `0125` | `@familiar/visualizer-sdk`, build-time only. Independent of everything above; the dependency-free path is already proven by `packages/visualizers/examples/`. |
| 6 | `0127` | `docs/START-HERE.md`, `make doctor`, `make check`, and a CI check that cited paths exist. Last so the traced slice goes through the generated web client and the factory. Its follow-up reconciles this file with `AGENTS.md`. |
| — | `0122` → `0123` → `0124` | The Apple track, in `familiar-apple`, in parallel with all of the above. `FamiliarAppCore` is the first boundary, because `0123`'s `FamiliarApplication` and `0124`'s repositories both live there. |

Two things the numbers in those records settle that the text would have let you assume otherwise: the
four first-party visualizers really are byte-identical in six files (one md5 each, 613 lines per package),
and the fifteen Apple tests that read Swift as text do so through two helpers, `AppSource.swift` and
`EngineSource.swift`, so they are found by searching for those rather than for the file paths.

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
make test                    # creates + migrates familiar_test, then pytest (ADR-0128)
make test-db                 # just the database; then `uv run pytest -x -q` works, TEST_DATABASE_URL exported
make test-services test      # no compose stack? throwaway Postgres+Redis on 5434/6380 instead; ARGS="-x" passes through
make test-services-down      # remove those containers
# A bare `uv run pytest` without TEST_DATABASE_URL refuses to run — it would empty DATABASE_URL's database.

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
