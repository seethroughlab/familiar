# Web / Mac / iPhone parity

**What this is for.** The web app has been kept partly as a record of what Familiar can do, so that
nothing is lost on the way to native clients. This document is that record, so the code no longer has
to be. Code is a poor inventory: you cannot read it as a list, and it rots without saying so.

Written 2026-08-10, last updated 2026-08-16. Verified against the repos at that date — every "no"
below was checked by looking for the call, not by assuming.

**This is maintained, not a snapshot.** ADR-0050 point 6 makes it the reference the code used to be,
which only holds if it is corrected when a row changes. Update it in the same change that moves a
✅ or a ❌, the way `openapi.json` is regenerated with the schema it describes.

**How to read the verdicts:**

| | |
|---|---|
| ✅ | Native has it |
| ⚠️ | Native has part of it — the gap is named |
| ❌ | Browser only |
| 💀 | Dead — unreachable in any client |

---

## Listening

| Capability | Web | Mac | iPhone | Notes |
|---|---|---|---|---|
| Browse tracks | ✅ | ✅ | ✅ | Mac has a sortable multi-column table (ADR-0021); the phone has a list |
| Browse albums / artists | ✅ | ✅ | ✅ | |
| Album / artist detail | ✅ | ✅ | ✅ | Names containing `/` fall back to a filtered list with a banner |
| Playlists | ✅ | ✅ | ✅ | |
| Smart playlists | ✅ | ✅ | ✅ | Browse and play on all three. **Editing is Mac-only** (ADR-0013 point 3): full CRUD over 25 server-supplied rule fields, and the phone shows no pencil and no `+` |
| Favorites, Downloads | ✅ | ✅ | ✅ | |
| Music Map | ✅ | ✅ | ❌ | **not a blocker:** desktop-only by decision — a dense field of labels navigated by pinch and pan wants a large screen and hover (ADR-0062). Native `Canvas`, 500-artist cap; web uses three.js |
| Discover | ✅ | ✅ | ✅ | **The native ones are a `WKWebView` on `/embed`** (ADR-0016/0017/0019) |
| New Releases detail | ❌ | ❌ | ❌ | **not a blocker:** exists nowhere. The web screen was deleted by ADR-0050 (`35ba672`) and this row went on claiming it; the "See all" link that reached it was dead on all three until 2026-08-18. The *section* still renders, on all three |
| Home | ✅ | ✅ | ✅ | ADR-0032 |
| Queue | ✅ | ✅ | ✅ | See "reorder" below |
| Shuffle | ✅ | ✅ | ✅ | Native adds four server-drawn weighted presets (ADR-0035) |
| Crossfade / gapless | ✅ | ✅ | ✅ | 0s is labelled Gapless |
| Radio | ✅ | ✅ | ✅ | ADR-0040 |
| Audio effects (EQ, reverb, delay…) | ✅ | ✅ | ✅ | Web `EffectsChain`; native its own DSP |
| Visualizer | ✅ | ✅ | ✅ | **A `WKWebView`**, bundled *inside* the app (3.4 MB `VisualizerBundle.html`) |
| Visualizer auto-select | ✅ | ✅ | ✅ | ADR-0064. **The page does the ranking on all three** — it knows the server, the profile and what it registered; the app supplies a menu toggle that travels on the URL |
| Offline downloads | ✅ | ✅ | ✅ | Independent implementations — Dexie vs background `URLSession` |
| Network output (Sonos/UPnP/Chromecast) | ✅ | ✅ | ✅ | ADR-0056 brought casting to the phone. AirPlay stays the OS picker's job (ADR-0031 point 3), reachable from the same merged control |
| CarPlay | — | — | ✅ | |
| Music video | ❌ | ✅ | ❌ | **not a blocker:** the browser copy was *deleted*, not skipped — `MusicVideo.tsx` went in `c00d99f` when visualizers became documents (ADR-0087), so the ❌ here is a removal rather than something the browser cannot do. ADR-0085 rebuilt it on the Mac as a player mode with its own destination and a match-and-download row action; ADR-0013 point 2 keeps all of that off the phone, which loses a picker entry that had already stopped selecting anything |
| Sleep timer, playback speed | ❌ | ❌ | ❌ | **not a blocker:** exists nowhere, including the web app, so it is not a reason to keep it (ADR-0060 point 1) |

## Playlist editing

Was "the biggest gap". Mostly closed on the Mac, 2026-08-11, and closed for regular playlists on
iPhone by `familiar-apple` #118.

| Capability | Web | Mac | iPhone | Notes |
|---|---|---|---|---|
| Create a playlist | ✅ | ✅ | ✅ | ADR-0049; the phone uses the same editor sheet with a phone toolbar (#119) |
| Create a smart playlist | ✅ | ✅ | ❌ | |
| Add a track to a playlist | ✅ | ✅ | ✅ | |
| Remove a track from a playlist | ✅ | ✅ | ✅ | Row menu, playlist screens only. Removes *every* occurrence, so the view reloads rather than guessing which rows went |
| Rename / delete a playlist | ✅ | ✅ | ✅ | Sidebar or playlist actions menu. Delete is confirmed; removing a track is not |
| Reorder playlist tracks | ✅ | ✅ | ✅ | `BrowseStores.reorder`, from Move Up / Move Down row menu items rather than drag — reachable by keyboard and VoiceOver, which a `Table` drag is not. Uses per-occurrence playlist-track ids |
| Delete a smart playlist | ✅ | ✅ | ❌ | |
| Reorder the queue / remove from it | ✅ | ✅ | ✅ | `FamiliarPlayer.moveQueuedTrack` / `removeQueuedTrack`, from `QueueView`'s row menu (#103) |
| Save the queue as a playlist | ✅ | ❌ | ❌ | |

**`/playlists/:id` no longer has a native-parity reason to stay mounted.** Regular playlist editing is
now covered by the Apple clients: the Mac has sidebar/list/detail affordances, and iPhone has create,
rename/delete, remove and move up/down controls. Smart playlists stay Mac-only by design.

## Library management

| Capability | Web | Mac | iPhone | Notes |
|---|---|---|---|---|
| Pending Review | ✅ | ✅ | ❌ | Mac works at folder-group level |
| Proposed Changes | ✅ | ✅ | ❌ | |
| Mixtapes | ✅ | ✅ | ❌ | |
| Edit track metadata | ✅ | ✅ | ❌ | `RowActions.saveMetadata` (#105). Mac only — the phone stays on the listening path (ADR-0013 point 2). Sends only changed fields; a cleared text field travels as `""` |
| **Artist cleanup / merge duplicates** | ✅ | ❌ | ❌ | `/library/artist-cleanup` |
| Trigger a library scan / re-index | ✅ | ✅ | ❌ | `LibrarySyncStore` → `libraryStartSync` (#106). The `library` tag was vendored all along |
| **Analysis settings and runs** | ✅ | ❌ | ❌ | |
| **Backup / restore** | ✅ | ❌ | ❌ | Export with options, restore with preview and merge modes |
| Create a profile | ✅ | ✅ | ✅ | `SetupView.createProfile` (#104), on the setup screen where a server with no profiles is discovered |
| **Last.fm OAuth link** | ✅ | ❌ | ❌ | |
| **Community cache, update channel, diagnostics** | ✅ | ❌ | ❌ | |
| **Listening history / stats** | ✅ | ❌ | ❌ | The clients *write* play events and never read any back |

## Configuration

API keys and library paths are **not** configurable from any client — they are environment variables.
`ApiKeyStatus` only reports whether they are set.

Native settings are three tabs (Playback, Effects, Downloads) plus Server on the phone. Everything
under System, Library, Integrations, Data and Developer is browser-only.

Roughly a third of the web's settings files configure *the web player itself* — `OfflineSettings`,
`OfflineTracksPanel`, `StorageQuotaDisplay`, `PlaybackSettings`, `ThemeSettings`. Those retire with
the player they configure; they are not part of the management surface. `ThemeSettings` is the
exception that outlives it, because it styles the administration interface (ADR-0058 point 5).

**Four are already gone.** `ShuffleWeightSettings`, `RadioSettings`, `AudioEffectsSettings` and
`QueueSyncSettings` were **deleted** — not unmounted — by ADR-0058 point 5, so unlike everything in
`PARKED_BROWSERS` their code no longer exists. The capabilities they configured are unaffected: the
native clients own them per-device (ADR-0029), and in the browser they remain reachable from the
player's own chrome — `ShuffleWeightPopover` and `EffectsQuickAccess` — which retires with the
player. Queue sync keeps its store and service; only its switch went, and the persisted flag is
forced back off so no device is left syncing with nothing to turn it off.

## What the native clients load *from* the web bundle

Not features — dependencies. **These cannot be removed while the Apple apps exist.**

| Document | Entry | Consumer |
|---|---|---|
| `embed.html` | `packages/web/src/embed.tsx` → `renderEmbed.tsx` | `EmbeddedDiscoverView.swift`, both platforms |
| `visualizer.html` | `packages/web/src/visualizer.tsx` → `renderVisualizer.tsx` | `EmbeddedVisualizerView.swift`, and folded into the app bundle by `scripts/inline-visualizer.mjs` |

Both are verified natively by a `<meta name="familiar-surface">` marker, so the marker is part of the
contract. Measured closures: `embed` pins 121 files / 20,046 lines; `visualizer` pins 97 / 18,670.
Against a full app of 313 files / 60,682 lines, the genuinely app-only remainder is **169 files /
35,911 lines**.

## API surface the native clients cannot reach

Eleven tags are generated into the Swift client, plus **nine named `outputs` operations** — the
filter lives in `Sources/FamiliarAPI/openapi-generator-config.yaml` in `familiar-apple`, and
`backend/scripts/lint_openapi.py` reads it so the two cannot drift.

**`openapi.json` itself is not filtered.** It is the whole artifact, copied verbatim, so all 32 tags
appear in that file. Counting tags in the vendored schema therefore proves nothing about what the
apps can reach — a check that was run during this re-verification and briefly suggested the whole
list was wrong.

These are the tags with nothing generated, so anything they serve is browser-only by construction —
with the one exception noted:

```
admin  settings  s3-backup  export-import  analysis  background  artwork
deduplicate  "Library Organization"  diagnostics  download  updates  videos
lastfm  new-releases  bandcamp  external-albums  ambient  outputs  playback
auth  health
```

**`outputs` is the exception and is listed above only because it has no tag entry.** Nine of its
twenty-four operations *are* generated, by name — list, discover-all, get, play, pause, resume,
stop, seek, set-volume (ADR-0031). The nine zone operations and the AirPlay discovery are excluded
deliberately, which is why the filter names operations rather than the tag: adding `outputs` to
`tags:` would re-admit all twenty-four, and the config says so in a comment.

## Retired, and deliberately not coming back

| | |
|---|---|
| Chat / AI assistant | ADR-0043 → ADR-0048. Familiar calls no model; an MCP host brings its own |
| Spotify favorites import | Retired 2026-08-10; the UI had been unreachable |
| Server-synced playback queue | ADR-0028 |
| Capacitor iOS app (`packages/ios`) | **Deleted 2026-08-11** (ADR-0001 point 6). It had been the largest consumer of `frontend/src` |
| Listen-together (guest sessions) | **Deleted 2026-08-18** (ADR-0070), both halves. ADR-0036 built the server side for ADR-0037, which was rejected the same day; with the fallback player gone, `/listen/:code` would have been the only route in the app that plays music |
| The fallback player | **Deleted 2026-08-18.** ADR-0058 point 4's trigger was met. `WebAudioEngine`, the effects chain, the queue and the Dexie offline store went with it (ADR-0071) |

## Removed from the browser 2026-08-16 (ADR-0057)

| Capability | Where it went |
|---|---|
| Playlist detail (`/playlists/:id`) | Native, both platforms. Point 3 of ADR-0050 kept it "until the Apple clients can edit a playlist"; they can |
| Artist detail (`/library/artists/:name`) | Native. ADR-0057 point 3 makes the fallback player a flat list, so "Go to artist" now filters `/library/tracks` instead |
| Album detail (`/library/albums/:artist/:album`) | Native. Same — the track context menu's album entry filters the list |
| Seeded playlists in the browser | Native as of `familiar-apple` #120. Five affordances and `useGeneratePlaylist` went with the route they navigated to |
| Sidebar playlist and smart-playlist sections | Their only destinations were the routes above and `/smart-playlists/:id`, which was never mounted |

`LegacyRedirect` went too — 82 lines migrating a hash/query-param URL scheme to `/home`,
`/favorites`, `/downloads`, `/library/music-map`, `/library/discover` and
`/library/proposed-changes`, **none of which has been a mounted route for some time**.

## Re-verified 2026-08-16

Checked row by row against the code, after a claim in this file turned out to be eight rows stale
and produced a wrong statement in a source comment two repositories away.

**Eight rows moved, all in the same direction: native had more than this said.** Playlist reorder,
queue reorder and removal, track metadata editing, library scan, profile creation, playlist
creation on the phone, removing a track from a playlist, and smart playlists. Each shipped in a
numbered PR — #103, #104, #105, #106, #119, #123 — and none of them updated this file.

**That means ADR-0050 point 6's condition is met.** It said "settings only" is not reachable until
the Apple clients can edit playlists, edit track metadata, trigger a scan, and create a profile.
All four are done. The remaining browser-only capabilities are the ones in genuinely ungenerated
tags — artist cleanup, analysis, backup and restore, Last.fm OAuth, community cache, diagnostics,
listening history. Listen-together used to be on that list, web-only by decision since ADR-0037 was
rejected; ADR-0070 deleted it instead, so nothing is browser-only by decision any more.

**How to check a row, so the next re-verification is cheaper.** Grep for the capability's *generated
operation* in `familiar-apple`, not for a word: a filename or a comment matching "restore" or
"diagnostics" proves nothing, and three false positives were produced that way during this pass.
Then confirm a caller that is itself reachable — `LIBRARY_ITEMS` and `BROWSER_ROUTES` in
`packages/frontend/src/routes.ts` for the web, `LibraryRootList.swift` for the phone. A capability
with no affordance is what `.smartPlaylists` was: routable, stored, rendered, and unreachable.

## Changes since first written

- **2026-08-11** — `packages/ios` deleted. It was the last thing outside this repo's own surfaces
  holding the shared frontend to full breadth, and the only path to App Store Connect until
  `familiar-apple` shipped version 1.2 build 14.

- **2026-08-11** — the Mac gained remove-a-track, rename and delete for playlists
  (`familiar-apple` #100). At that point reorder and iPhone editing still kept `/playlists/:id`
  mounted.
- **2026-08-14** — the iPhone gained regular playlist create, rename/delete, remove and move up/down
  reorder controls (`familiar-apple` #118). The playlist-editing row is no longer part of the
  "settings only" gate in ADR-0050 point 6.
- **2026-08-11** — the web app was reduced to management (`familiar` #151, ADR-0050): it opens on
  Settings and twelve listening-path routes are unmounted. **The Web column below still describes
  what the code can do, not what is currently routed** — `PARKED_BROWSERS` in
  `packages/frontend/src/routes.ts` is the list of what is unmounted, and points 4 of ADR-0050 makes
  deleting it a consequence of accepting that ADR.
- **2026-08-16** — `/library/stats` was corrected (`familiar` #168). It had disagreed with
  `/library/albums`, `/library/artists` and `/tracks` on all three totals for as long as nothing
  called it: no active-status filter, a string distinct for albums, raw tag strings for artists.
  Nothing in the matrix changes; noted because "the web app can show library stats" was true of the
  screen and false of the numbers.
- **2026-08-18** — **New Releases detail was never a native gap: it exists nowhere.** The web
  screen (`NewReleasesDetail.tsx`) was deleted by ADR-0050 in `35ba672`, and the Web column went on
  saying ✅ for eight days. The "See all" link that reached it was therefore dead on every platform —
  redirecting home in a browser, and inside the embedded Discover WebView changing the URL while
  leaving the same page on screen, because a react-router `Link` is a `pushState` the native side
  never sees. The link is now removed; the section, the count, dismiss and the purchase links all
  stay and all work.

  **This empties the player's removal countdown.** Under ADR-0060 point 1's second rule a row that
  is ❌ in the Web column too cannot be a reason to keep the browser, and no rule was bent to get
  here — the ✅ was simply false. `docs/WEB-PARITY.md`'s Listening table now shows no ❌ in the Mac
  or iPhone columns that is not excluded, which is the condition ADR-0058 point 4 set for removing
  the web player.
- **2026-08-18** — the Music Map became **desktop-only by decision** (ADR-0062) rather than an
  unfinished row. No ADR had ever said the phone should have one — ADR-0016 is Mac-scoped — so the
  ❌ recorded "nobody decided" and the countdown read it as "not yet done". **One row now remains**:
  New Releases detail, which needs a decision about the embed bridge before it needs code.
- **2026-08-18** — casting reached the phone (`familiar-apple` #125 and #127, ADR-0056), so
  **Network output goes native-✅ and leaves the player's removal countdown**. Two rows remain in the
  Listening table under ADR-0060's rule: Music Map on iPhone, and New Releases detail on Mac and
  iPhone. Both are `familiar-apple` work; nothing in the web app blocks its own player now.

  The ADR is worth reading for what the measurement did to it: it argued the discarded *stream* was
  the cost, and the server log said otherwise — a downloaded track is never fetched, and casting
  only works on the home LAN where bandwidth is not the constraint. What it actually removes is the
  full decode ADR-0031 point 7 named in the first place.
- **2026-08-17** — the PWA was retired (ADR-0059). No manifest, no service worker, no install
  prompt, and `vite-plugin-pwa` is gone. `/sw.js` still exists and must: it serves a **tombstone**
  worker that unregisters the Workbox worker earlier versions installed, because deleting a service
  worker does not remove it — a browser that registered one keeps serving the old shell cache-first
  forever, and the unregistration code in `main.tsx` would never run. Verified by seeding a
  Workbox-style cache, registering the worker, and watching both the cache and the registration
  disappear. **The browser-only listener loses offline access to already-downloaded tracks**: the
  tracks are untouched in IndexedDB, but the shell no longer loads without a server.
- **2026-08-16** — duplicates, the organiser and artwork coverage reached the browser (`familiar`
  #170, ADR-0058 phases 4–5). All browser-only and all infrastructural under ADR-0057 point 2.
  The first two are preview-only because the server has no apply route for either; the third needed
  a new endpoint, `GET /artwork/coverage`. `organizerApi` had existed uncalled — the fourth such
  wrapper this ADR turned up.
- **2026-08-16** — the web app became an administration tool with three destinations (`familiar`
  #169, ADR-0058): Library, Tools, Server. Settings keeps only theme, playback and offline. Four
  settings panels were **deleted** rather than unmounted — see the Settings section above.
  Rewriting the sidebar turned up three more affordances that led nowhere: `/favorites` and
  `/downloads` had been linked with no route mounted since the ADR-0057 strip, and the mixtape
  export modal's only setter was its own `onClose`. `navigationIntegrity.test.ts` now reads
  `App.tsx` and fails on a link to an unmounted path, which is what the registry-only guard missed.

## Dead at the time of writing

💀 Ephemeral ("Unsaved") playlists — `addPlaylist` had zero callers and nothing dispatched
`show-ephemeral-playlist`, so the sidebar section, the `/ephemeral/:id` route and "Save to Library"
could never be reached. Removed in the same change as this document, along with ~2,150 further lines
whose only importers were themselves: three superseded Settings panels, `useOfflineQuery`,
`urlParams`, `useToast`, `MixedValueInput`, `StoreSearchLinks`, `useRetryableOperation`,
`useProfileInit`, `useFocusTrap`, `TrackSearchInput`, `uuid`, and the `playerPersistence` shim.

They are listed here because a "record of what we had" that includes things that never worked is
worse than no record.
