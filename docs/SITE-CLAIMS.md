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

Last full sweep: **2026-08-14**.

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
| Ask for music by how it sounds — CLAP, via an MCP host | **true**, after rewrite | `semantic_search` in `services/llm/tools.py:46`, handler `llm/handlers/search.py:102`. **No REST endpoint and no UI on any client** — it is reachable only through MCP. The block previously read as an in-app search box; it now names the host. |
| 36 tools | true | 34 in `MUSIC_TOOLS` + `list_players` + `now_playing` (`app/mcp/server.py:exposed_tools`) |
| Familiar holds no API key, calls no model | true | ADR-0048; no provider call outside `llm/` tool handlers, which run for an MCP host |
| Music Map | true | Native: `familiar-apple/App/Shared/MusicMapView.swift`, `MusicMapStore.swift`. `WEB-PARITY.md:35` Web ✅ Mac ✅ iPhone ❌. Screenshot is the Mac |
| Smart playlists are rules, not snapshots | true | `WEB-PARITY.md:33` Web ✅ Mac ✅ iPhone ❌. Mac has CRUD over 25 rule fields |
| Discover — new releases from your artists | true | `WEB-PARITY.md:36` all three ✅; native is a `WKWebView` on `/embed` |
| Native apps: background audio, lock-screen, offline downloads | true | `WEB-PARITY.md:45` offline downloads ✅ on all three, background `URLSession` natively |
| The browser is for setup, not listening | true | ADR-0050 points 1–3 |

## Also included — `index.html`

| Claim | Verdict | Evidence |
|---|---|---|
| Find similar | true | Native `App/Shared/DownloadControls.swift:168` "Play similar"; web `Discovery/hooks/useTrackDiscovery.tsx` |
| Musical features — BPM, key, energy, danceability, acousticness | true | All present in `ANALYSIS_FEATURE_COLUMNS`, `db/models/tracks.py` |
| Community cache | true | `routes/settings.py:59`; UI `components/Settings/CommunityCache.tsx` |
| Web app for setup | true | ADR-0050 point 3 |
| ~~Mood Grid~~ | **false — removed** | No component anywhere. `/library/mood-grid` survives only as an icon in `Sidebar.tsx:42`; absent from `LIBRARY_ITEMS` and `BROWSER_ROUTES`; nothing in `familiar-apple`. An affordance whose destination is not mounted |
| ~~3D Explorer~~ | **false — removed** | Same shape: `Sidebar.tsx:44` icon only |
| ~~Music videos — "attach video files to tracks"~~ | **misdescribed + browser-only — removed** | Real feature is a *visualizer* that searches YouTube (`Visualizer/visualizers/index.ts:23`). `videos` is not in `VENDORED_TAGS`, so it is browser-only by construction |
| ~~Listening sessions~~ | **browser-only — removed** | `WEB-PARITY.md:48` Web ✅ Mac ❌ iPhone ❌; web-only *by decision* since ADR-0037 was rejected |

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
