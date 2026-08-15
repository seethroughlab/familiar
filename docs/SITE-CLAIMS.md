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

## Removed, with the reason

Kept so nothing is quietly restored later.

| Claim | Why it went |
|---|---|
| ~~Try the live demo~~ | **2026-08-15.** ADR-0038 built that instance because *"Apple App Store review requires a working backend server with test data"*. It is a compliance fixture; presenting it as a product tour implied you can try Familiar without your own server. `SetupView.swift` asks for an address on first launch and `familiar-demo` appears nowhere in the Swift. Reverses `0039` point 8 — recorded in ADR-0055 point 10 |
| ~~faq: "First launch connects to a public demo backend"~~ | **2026-08-15, false.** Same evidence: the app has no demo default |
| ~~Mood Grid~~ | **2026-08-14, false.** No component anywhere. `/library/mood-grid` survives only as an icon in `Sidebar.tsx:42`; absent from `LIBRARY_ITEMS` and `BROWSER_ROUTES`; nothing native |
| ~~3D Explorer~~ | **2026-08-14, false.** Same shape, `Sidebar.tsx:44` |
| ~~Music videos — "attach video files to tracks"~~ | **2026-08-14, misdescribed and browser-only.** Real feature is a visualizer that searches YouTube (`Visualizer/visualizers/index.ts:23`); `videos` is not in `VENDORED_TAGS` |
| ~~Listening sessions~~ | **2026-08-14, browser-only.** `WEB-PARITY.md:48` Web ✅ Mac ❌ iPhone ❌, web-only by decision since ADR-0037 was rejected |
| ~~Offline PWA~~ | **2026-08-13, positioning.** Still real (`vite-plugin-pwa`, `public/manifest.json`, `/sw.js`), but ADR-0050 makes the browser a management surface, so it is not promoted as a way to listen |

## Comparison table — `index.html`

Familiar's own column is checked. **Every competitor cell is `unverifiable`** — nothing in this
repository can settle what Jellyfin, Plex, Apple Music or Spotify do, and ADR-0055 point 2 forbids
passing them as checked. 7 rows × 4 competitors = **28 assertions awaiting review**.

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

**What would settle the competitor cells:** a dated check against each product's own documentation,
recorded here with the date. Until then the table ships as-is and this ledger is the worklist.

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

- 28 competitor assertions in the comparison table — Jeff to confirm or correct.
- Analysis timing claim — needs a measured run.
- `privacy.html` third-party bullets — the field lists each integration sends are unverified.
