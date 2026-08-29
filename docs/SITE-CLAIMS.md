# Site claims ledger

Every claim `site/` makes, what it was checked against, and when. ADR-0055 point 2 requires this;
it exists because the first audit was ad-hoc greps in a conversation and passed a false claim.

**How a claim is resolved.** In order, first source that answers wins:

1. **`docs/WEB-PARITY.md`** — the per-surface row (Web / Mac / iPhone). Default for anything a user
   does in a client.
2. **The browser-only tag list** in that file — an API tag outside `VENDORED_TAGS`
   (`backend/scripts/lint_openapi.py`) cannot be reached natively, whatever else is true.
3. **The "Retired, and deliberately not coming back" table** — anything there is a claim the site
   may never make again.
4. **Reachability** — route mounted in `main.py` → a wrapper in `api/` → a UI caller that is itself
   reachable. Existence at one layer proves nothing. `LIBRARY_ITEMS` and `BROWSER_ROUTES` in
   `packages/frontend/src/routes.ts` decide whether a web surface is reachable at all.
5. **Backend** — for server-only claims with no UI.

**Verdicts.** `true` · `false` · `misdescribed` (the capability exists, the sentence does not
describe it) · `browser-only` (real, but not on a surface the site promotes) · `unverifiable`
(outside this repository).

Last full sweep: **2026-08-15**, after the page was rebuilt around the install→listen journey.

## Why the previous audit missed things

Recorded so the method is not quietly reverted. The check that passed "Music videos — attach video
files to tracks" was `grep -rl "video"`, which returned `routes/videos.py` and `services/video.py`.
A filename is not a feature. Four other failures compounded it: `WEB-PARITY.md` was never opened;
the wrong surface was audited (the site promises native apps, and `videos` is browser-only by
construction); the topic was matched rather than the assertion; and nothing was written down, so
"broadly sound" was generalised from a handful of positives.

## Feature blocks — `index.html`

| Claim | Verdict | Evidence |
|---|---|---|
| Make a playlist from a track, album, artist or selection, scored from how it sounds | true | `POST /api/v1/playlists/generate`, `routes/playlists/generate.py:84`. Seed is closed to those four forms (ADR-0048 point 2) |
| …no prompt, no model, no API key | true | ADR-0048 point 1: no English sentence is constructed in any client |
| **Surface caveat — deliberately not on the page** | **web-only today** | `playlists_generate` is tagged `playlists`, so it IS in the generated Swift client — and **nothing calls it**. Web callers: `ArtistDetail.tsx:855`, `FullPlayer.tsx:514`, +2. Jeff's call to state the capability without naming a surface; the native work is the agreed next task. **Revisit this row first if that slips.** |
| Real apps: background audio, lock-screen, offline downloads, CarPlay, radio | true | `WEB-PARITY.md:45` offline downloads ✅ all three; `:47` CarPlay iPhone ✅; `:42` Radio ✅ all three (ADR-0040) |
| A map of the library laid out by how things sound | true | Native `MusicMapView.swift`, `MusicMapStore.swift`; `WEB-PARITY.md:35` Mac ✅ |
| MCP, 36 tools, searching the audio not the tags | true | 34 `MUSIC_TOOLS` + `list_players` + `now_playing`; `semantic_search` handler `llm/handlers/search.py:102` |
| The two prompt→filter examples | true | Both map to real feature columns in `ANALYSIS_FEATURE_COLUMNS` |
| Familiar holds no API key, calls no model | true | ADR-0048; ADR-0043 |
| Scans, resolves artists and albums, fetches artwork, analyses | true | ADR-0052 (canonical albums), artist resolver, `services/artwork.py` |
| Fixes stick — a re-scan will not undo them | true | ADR-0051, "edited metadata outranks file tags" |
| Files are never moved or rewritten | true | scanner reads only; writes go to `metadata_overrides`, not to files |
| The browser is for setup, not listening | true | ADR-0050 points 1–3 |

## Also included — `index.html`

| Claim | Verdict | Evidence |
|---|---|---|
| Discover — new releases from artists in your library | true | `WEB-PARITY.md:36` all three ✅; native renders `/embed` in a `WKWebView` |
| Smart playlists — rules over tags, features, history | true | `WEB-PARITY.md:33` Web ✅ Mac ✅ iPhone ❌ |
| Find similar | true | Native `DownloadControls.swift:168` "Play similar"; web `useTrackDiscovery.tsx` |
| Musical features — BPM, key, energy, danceability, acousticness | true | All in `ANALYSIS_FEATURE_COLUMNS`, `db/models/tracks.py` |
| Community cache | true | `routes/settings.py:59`; UI `components/Settings/CommunityCache.tsx` |
| Web app for setup | true | ADR-0050 point 3 |

## Install and remote access — `index.html`

Added 2026-08-29 with ADR-0095 and ADR-0096. ADR-0095 point 8 draws the line these rows sit on:
**the platform support table is a claim; the instructions are not.** A procedure is checked by
running it, which this ledger does not model — what it carries is the assertion that Familiar
installs on a given platform.

| Claim | Verdict | Evidence |
|---|---|---|
| Installs on macOS | true | `docker/start.sh:86` detects `Darwin` and adds `docker-compose.desktop.yml`; `docs/MACOS_BEGINNER.md` is a 299-line walkthrough of exactly the steps the panel gives |
| Installs on Linux, and on OpenMediaVault | true | `docker-compose.prod.yml` needs only `./init-pgvector.sql` locally, and every other variable has a default — `MUSIC_LIBRARY_PATH` falls back to `/data/music`. OMV walkthrough at `INSTALLATION.md:72` |
| Installs on Synology via Container Manager | true | `INSTALLATION.md:241`, DSM 7.2+, with the compose file to paste and a supported-model list. **Not run by anyone here**; the claim rests on the guide, which is specific enough to be checkable |
| Installs on Windows | **unverifiable** | `docs/WINDOWS.md` is a compatibility *audit*, not a guide: 21 issues, four critical, **all of them about running the backend natively**. Under Docker the container is Linux and the host "only needs Docker installed" (`WINDOWS.md:15`). So this should work and **nobody has run it**. The panel says so on the page — this is the verdict the site itself displays |
| `./start.sh` builds the image locally | **false — corrected on the page** | It does not build. `start.sh:84` runs `docker compose -f docker-compose.prod.yml`, which pulls `ghcr.io/seethroughlab/familiar:latest`, and there is no `--build` anywhere in the script. The "Build from source" block now shows an explicit `compose build` and says what `start.sh` actually does |
| Windows needs `docker-compose.desktop.yml` | true | That file only swaps `journald` for `json-file`, and journald is Linux-only. Docker Desktop runs a Linux VM on macOS and Windows alike, so the override applies to both. It was `docker-compose.macos.yml` until 2026-08-29; the rename is why the Windows panel no longer has to explain itself |
| Familiar has no login | true | ADR-0045 is **accepted and unimplemented**: no token in `backend/app/api/deps.py`, `app/config.py` or `app/main.py`, and no auth middleware. Its own Implementation block explains why — point 2, closing the 158 allowlisted operations, is the real project |
| A reverse proxy without authentication does not protect it | true | Follows from the row above: there is nothing behind the proxy to authenticate against |
| Tailscale gives a private network, HTTPS and no router configuration | **unverifiable** | Tailscale's own documented behaviour, not checkable here. ADR-0096 point 5 is why the page says nothing about their pricing, plans or limits — `ADR-0055` point 2 was burned once already by claims about somebody else's product |

**Expiry (ADR-0096 point 6).** The last three rows depend on Familiar having no authentication. When
ADR-0045 ships, the "Listening away from home" section and these rows are revisited — a scheduled
edit, not a later discovery.

## Removed, with the reason

Kept so nothing is quietly restored later.

| Claim | Why it went |
|---|---|
| ~~Try the live demo~~ | **2026-08-15.** ADR-0038 built that instance because *"Apple App Store review requires a working backend server with test data"*. It is a compliance fixture; presenting it as a product tour implied you can try Familiar without your own server. Reverses `0039` point 8 — recorded in ADR-0055 point 10 |
| ~~faq: "First launch connects to a public demo backend"~~ | **2026-08-15, false** — as written. The app does not *connect*; it asks. **Evidence corrected 2026-08-16:** the removal was justified with "`familiar-demo` appears nowhere in the Swift", which was true when checked and stopped being true the same day — `familiar-apple` `e78a44b` now sets `@State private var address = "https://familiar-demo.fly.dev"` on **macOS only** (iOS still starts empty). That is a prefilled field for an App Store reviewer, not a connection and not a product tour, so the removal stands on ADR-0038's own reasoning rather than on the absence of the string. Recorded because a one-day-old citation going stale is the failure mode this ledger exists to catch |
| ~~Mood Grid~~ | **2026-08-14, false.** No component anywhere. `/library/mood-grid` survives only as an icon in `Sidebar.tsx:42`; absent from `LIBRARY_ITEMS` and `BROWSER_ROUTES`; nothing native |
| ~~3D Explorer~~ | **2026-08-14, false.** Same shape, `Sidebar.tsx:44` |
| ~~Music videos — "attach video files to tracks"~~ | **2026-08-14, misdescribed and browser-only.** Real feature is a visualizer that searches YouTube (`Visualizer/visualizers/index.ts:23`); `videos` is not in `VENDORED_TAGS` |
| ~~Listening sessions~~ | **2026-08-14, browser-only.** `WEB-PARITY.md:48` Web ✅ Mac ❌ iPhone ❌, web-only by decision since ADR-0037 was rejected |
| ~~Offline PWA~~ | **2026-08-13, positioning.** Still real (`vite-plugin-pwa`, `public/manifest.json`, `/sw.js`), but ADR-0050 makes the browser a management surface, so it is not promoted as a way to listen |

## Comparison table — `index.html`

Familiar's own column is checked. The competitor cells were filed as **unverifiable** on
2026-08-14, on the grounds that nothing in this repository settles what Plex does. That was a
mistake — true about the repository, and irrelevant, because these products publish documentation.
Checked against it on **2026-08-16**, and two cells were wrong **in Familiar's favour**:

| Cell | Was | Now | Source |
|---|---|---|---|
| Plex, audio feature analysis | "Basic" | "Sonic analysis (Plex Pass)" | Plex runs a neural network placing tracks in an N-dimensional space for sonic similarity, track radio and mixes. Calling that basic understated the nearest competitor on the axis Familiar claims as its own |
| Spotify, plays your own files | "—" | "Local Files — MP3 only, same Wi-Fi" | Local Files plays MP3/MP4/M4P and syncs to mobile over the same network. No FLAC and not remotely, which is the honest distinction — and the site's own FAQ already said so while the table contradicted it |
| Jellyfin, smart playlists | "—" | "Community plugin" | Not built in; several maintained plugins provide it |
| Row label "Semantic audio search" | — | "Search by describing the sound" | Plex's sonic similarity is track-to-track and real. What Familiar does differently is text-to-audio, so the row now says that rather than implying nobody analyses audio |

The table now carries the date it was checked and an invitation to correct it.

| Row | Familiar's cell | Verdict |
|---|---|---|
| Plays your existing MP3 / FLAC files | Yes | true |
| MCP server | Yes | true |
| Semantic audio search | Yes (CLAP) | true — via MCP; the row above establishes the mechanism |
| Audio feature analysis | BPM, key, energy, mood | true |
| Community analysis cache | Yes | true |
| Self-hosted / no cloud | Yes | true |
| Smart playlists | Rules-based | true |
| ~~Music video playback~~ | — | **removed**, browser-only |

**Re-check when a competitor ships something.** Plex Pass features and Spotify's Local Files both
move. The date on the table is the promise being made — it does not claim to be current, it claims
to have been true on a stated day, which is a promise that can actually be kept.

## `faq.html`

| Claim | Verdict | Evidence |
|---|---|---|
| No API key needed | true | ADR-0048 |
| Analysis ≈1s/track, 20k library ≈6h | **unverified** | No benchmark in the repository. Plausible and unchecked — needs a measured run |
| Community cache shares only SHA-256 hashes | true | `services/` cache client sends hashes and features, no titles |
| Nothing leaves the network without opt-in | true | consistent with `privacy.html` after correction |
| Listening away from home via Tailscale | true | `docs/CONFIGURATION.md#tailscale-https` |
| iOS app on the App Store | true | link resolves 200; native, not Capacitor |

## `privacy.html`

| Claim | Verdict | Evidence |
|---|---|---|
| Your own assistant, if you connect one | true | corrected 2026-08-13; previously claimed a chat feature that no longer exists |
| Last.fm, LRCLIB, MusicBrainz, Cover Art Archive, AcoustID, community cache | **unswept** | integrations exist; the exact fields each sends have not been traced |
| No analytics SDKs, no ad identifiers | true | no analytics dependency in `packages/web/package.json` |

## Open

- Analysis timing claim — needs a measured run.
- `privacy.html` third-party bullets — the field lists each integration sends are unverified.
