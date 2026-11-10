# ADR History

How the decisions in `docs/decisions/` were sequenced, what each set shipped, and the traps building
them surfaced. **This is history, kept verbatim** from the repository guide where it grew, moved here
by [ADR-0175](decisions/ADR-0175-contributors-have-one-current-repository-guide.md) so the current
guide ([`AGENTS.md`](../AGENTS.md)) stays current. Read the ADR itself, and its Implementation block,
before relying on anything here; where they disagree, the ADR wins.

The ADRs by subsystem are in [`ADR-INDEX.md`](ADR-INDEX.md).

## Current set and execution order

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

**`ADR-0154` takes acquisition out of Familiar** (accepted and built 2026-10-25). It supersedes
`ADR-0116`/`0117`, and `0142` point 5: the four Soulseek tools, the slskd settings, the two-minute
poll, `GET /soulseek/status` and the `/music/Inbox` mount are gone. A recommendation of something
the library lacks ends at **Bandcamp**, which Familiar means to send listeners to. Soulseek lives in
a separate repository, `soulseek-mcp`, which took the slskd client and its measured facts, and can
also move a settled download into the music folder. That move is the listener's own tool doing it,
never Familiar, so zero-touch is unaffected. Familiar's watcher then finds the folder, and its files
reach Pending Review by the ordinary rule. **Do not bring back an acquisition tool, an inbox
special case or a `withheld_tools()`-style seam for one** without reading 0154's Context. A
`settings.json` holding the old `soulseek_*` keys still loads, because unknown keys are ignored.
That is pinned, because a `ValidationError` there silently resets every setting.

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
the same day; **points 1–4 superseded by `ADR-0159`**, which removed the community cache with
the Clapback commons on 2026-11-02, so the paragraph below is history). clapback's `ADR-0019` measured the corpus key as a function of the fingerprinting
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

**`ADR-0122`–`ADR-0130` are all accepted (2026-09-17), and every one has at least a first slice built (the table says which).** They are about
structure rather than features: how the Apple client, the backend, the web client and the docs are put
together. Two of them exist because a routine command was dangerous — until `0128` shipped, `uv run pytest`
deleted every row from eighteen tables in whatever database `DATABASE_URL` named, and CI's
disposable database was itself called `familiar`, so the name proved nothing. Execution order, which
again differs from the numbering:

| # | ADR | Why here |
|---|---|---|
| 1 | `0128` | **Built 2026-09-17.** `TEST_DATABASE_URL`, a `_test` suffix with no second marker, CI renamed to `familiar_test`. Its guard runs in the rootdir `conftest.py` until `0130` gives it a factory. |
| 2 | `0130` | **Soulseek slice built 2026-09-18, removed with the feature by `0154`.** `create_app(settings, services)` exists; `app/container.py` is **empty** until the next domain moves in, and that domain's first test restores the two-containers proof. The pattern is the ADR's Implementation block. Library sync and analysis go last; `scanner.py:126` still reads env at import. |
| 3 | `0129` | **First slice built 2026-09-18.** `packages/api-client` is generated from `backend/openapi.json` by `@hey-api/openapi-ts` 0.99.0 and checked in CI; `base.ts` installs one transport on both the wrappers' and the generated client's instances; the interceptor switches on the envelope's `code` — the prose match it replaced had never fired for a dead profile, because the sentence was in `message`, not `detail`. Soulseek status was the first feature on the generated path (gone with `0154`); library-watch status is the one the transport test drives now. Remaining features migrate one at a time. |
| 4 | `0126` | **Built 2026-09-19.** Overview / Library / Analysis / Server, section rails with routes, ancestor matching in one `isUnder`, `/tools/*` redirects. A provider is one card (`ProviderCards.tsx`); the pipeline is one destination; the Overview's rules are pure (`screens/overview/attention.ts`) and read the backlog from the worker phase queues. Its gate was a mock; the built page was then checked against the NAS and the demo. Not done: pending review (no screen), a persisted duplicates count. |
| 5 | `0125` | **Built 2026-09-19.** `packages/visualizer-sdk`; the four visualizers are workspace members at last (they never were — `packages/*` does not recurse) building to their own `dist/`, vendored into `familiar-apple` by `scripts/build-visualizers.sh`. Bridge tests on recorded events; `packages/visualizers/e2e` runs every built document in a sandboxed frame. |
| 6 | `0127` | **Built 2026-09-19.** `docs/START-HERE.md` (map, a slice traced through every layer — the library-watch status since `0154`, five golden paths, the security posture), `make doctor`, `make check`, `docs/ADR-INDEX.md` (generated), `docs/HEALTH.md` (the debt register that replaced the archived backlog), and `scripts/check_docs.py` in CI — which found six wrong claims in START-HERE's own first draft. Follow-up: one shared source for this file and `AGENTS.md`. |
| — | `0122` → `0123` → `0124` | **Built 2026-09-19** (`familiar-apple` #195, #196, #197). `FamiliarAppCore` is the one target that knows both `FamiliarKit` and `FamiliarAPI`; `FamiliarApplication` there is the process — `start()` and `bindConfiguration()`, both idempotent and measured; `RepositoryError` is the one vocabulary a server-backed capability fails with, mapped once in `GeneratedResponses.swift`, casting the first slice. Each ADR's Implementation block has what moved and what it found. After a `familiar` schema change, every `familiar-apple` branch fails CI until `scripts/vendor-schema.sh --fetch` is run there. |

Two things the numbers in those records settle that the text would have let you assume otherwise: the
four first-party visualizers really are byte-identical in six files (one md5 each, 613 lines per package),
and the fifteen Apple tests that read Swift as text do so through two helpers, `AppSource.swift` and
`EngineSource.swift`, so they are found by searching for those rather than for the file paths.

**`ADR-0131`–`ADR-0138` make the server its own app** (`0131`–`0136` and `0138` accepted and built — `0134` in #345 and familiar-apple #198, `0136`/`0138` in #346–#350, `0135`'s notarized `.dmg` on 2026-09-30 — `0137` accepted 2026-10-04 and built in `familiar-apple` #210–#221, with its point 5 superseded
by `0150`, 8 GB per server and profile). `0131` frames it:
Familiar is a server and the clients that play from it, installed and paired separately. The server
comes as **Familiar Server** (a Developer ID menu-bar Mac app, source at `desktop/macos/` in this repo)
or as Docker on Linux/NAS, and both are first-class. The Mac player stays in the App Store and carries
no server. **Windows is shelved until the Mac ecosystem is done** (0131 point 4 makes that checkable).
Two earlier drafts, a server inside the player, were reversed; 0131's Context says why, so do not
rebuild them. **`ADR-0140` (accepted 2026-10-01) supersedes 0136 points 2–4: Familiar Server is not
App-Sandboxed.** macOS refuses to let a sandboxed app register an unsandboxed agent, and Postgres
cannot run sandboxed, so the first real install failed at "Operation not permitted". Zero-touch is
enforced instead by a Seatbelt profile (`sandbox-exec`) on the Python server that denies writing the
music folder, which also makes `os.access` report it unwritable. Do not re-add the App Sandbox
without reading 0140. **`ADR-0141`**: a new server (no token, no tracks) mints a token at first start
and prints a sign-in link to its log (`python -m app.token` reprints it); an existing tokenless
server keeps serving and warns; `FAMILIAR_OPEN_SERVER` (the demo) is open on purpose. Both images
start through `python -m app.serve`, so a start-up rule cannot again apply to only one form.
**`ADR-0142`**: the server watches its own library (`watchfiles`), scans only folders
quiet for three minutes, never marks anything missing from such a scan, and (since `0154`) treats `Inbox/` like any
other folder; Familiar Server's own FSEvents watch is gone. Execution order differs from the numbering:

| # | ADR | Why here |
|---|---|---|
| 1 | `0131` | Framing only. |
| 2 | `0132` → `0133` | One ordinary process (`FAMILIAR_DATA_DIR`, `python -m app.serve`) against one database: Postgres stays (SQLite was counted and rejected), and Redis gets a Postgres implementation behind `ResilientRedisClient`'s twelve operations. |
| 3 | `0134` | Pairing: the Apple client finally sends `X-Familiar-Token`, `_familiar._tcp` over zeroconf, one `familiar://pair` link as a QR code or opened on the same Mac. Nothing listens beyond loopback until a phone is paired. Clears ADR-0045 point 5's larger blocker. |
| 4 | `0136` spike | Does Postgres run inside Familiar Server's sandbox? The answer shapes 0136 point 4. |
| 5 | `0135` | Familiar Server's notarized `.dmg` and Sparkle appcast, built by `release.yml` from the image's tag. |
| 6 | `0136` with `0138` | The menu-bar login-item app (read-only folder, zero-touch enforced by macOS — by the App Sandbox as built, by a Seatbelt profile since `0140`), and the etiquette it keeps: pause on battery/heat, background QoS, never hold the Mac awake. |
| 7 | `0137` | The phone keeps a copy of its library: favourites kept by default, kept playlists, a storage budget, a defined "away" state. |

**`ADR-0160`–`ADR-0164` get lyrics and the visualizers ready for wide release** (accepted 2026-11-07, for app 1.7). The lyrics
defect was not matching: **nothing ever requested them**, in any app build, and a blocked origin and a
missing token stood behind that. `0160` makes lyrics a native player mode, `0161` cuts the documents to
Beat Tiles and Reactive Terrain, `0162` makes an unmodified seeded copy follow the app, `0163` resolves
lyrics local-first and reports a `status`, and `0164` makes the embedded page a paired client. Execution
order: `0163`, `0164`, `0160`, then `0161` and `0162` together. **Hit rate is a property of the library,
so there is no target for it**: 400 tracks gave 26% synced, 17% plain and 56% miss, and many of those
misses are instrumentals on a heavily electronic collection. `TrackAnalysis.instrumentalness` cannot
separate them, since its 10th, 50th and 90th percentiles are all 1.0.

**`0138` found that a library sync starts every two hours** (`CronTrigger(hour="*/2")`), so "nothing is
scheduled" below and in `VERSIONING.md` is true of analysis only narrowly.
