# Web / Mac / iPhone parity

**What this is for.** The web app has been kept partly as a record of what Familiar can do, so that
nothing is lost on the way to native clients. This document is that record, so the code no longer has
to be. Code is a poor inventory: you cannot read it as a list, and it rots without saying so.

Written 2026-08-10. Verified against the repos at that date — every "no" below was checked by looking
for the call, not by assuming.

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
| Smart playlists | ✅ | ✅ | ❌ | Mac has full CRUD over 25 server-supplied rule fields |
| Favorites, Downloads | ✅ | ✅ | ✅ | |
| Music Map | ✅ | ✅ | ❌ | Native `Canvas`, 500-artist cap. Web uses three.js |
| Discover | ✅ | ✅ | ✅ | **The native ones are a `WKWebView` on `/embed`** (ADR-0016/0017/0019) |
| New Releases detail | ✅ | ❌ | ❌ | The embed bridge only understands `openArtist` / `openAlbum` |
| Home | ✅ | ✅ | ✅ | ADR-0032 |
| Queue | ✅ | ✅ | ✅ | See "reorder" below |
| Shuffle | ✅ | ✅ | ✅ | Native adds four server-drawn weighted presets (ADR-0035) |
| Crossfade / gapless | ✅ | ✅ | ✅ | 0s is labelled Gapless |
| Radio | ✅ | ✅ | ✅ | ADR-0040 |
| Audio effects (EQ, reverb, delay…) | ✅ | ✅ | ✅ | Web `EffectsChain`; native its own DSP |
| Visualizer | ✅ | ✅ | ✅ | **A `WKWebView`**, bundled *inside* the app (3.4 MB `VisualizerBundle.html`) |
| Offline downloads | ✅ | ✅ | ✅ | Independent implementations — Dexie vs background `URLSession` |
| Network output (Sonos/UPnP/Chromecast) | ✅ | ✅ | ❌ | AirPlay deliberately left to the OS picker |
| CarPlay | — | — | ✅ | |
| Listen-together (guest sessions) | ✅ | ❌ | ❌ | ADR-0036 built the server half; **ADR-0037 was rejected**, so this is web-only by decision |
| Sleep timer, playback speed | ❌ | ❌ | ❌ | Exists nowhere |

## Playlist editing — the biggest gap

| Capability | Web | Mac | iPhone | Notes |
|---|---|---|---|---|
| Create a playlist | ✅ | ✅ | ❌ | ADR-0049; both editors are `#if os(macOS)` |
| Create a smart playlist | ✅ | ✅ | ❌ | |
| Add a track to a playlist | ✅ | ✅ | ✅ | |
| **Remove a track from a playlist** | ✅ | ❌ | ❌ | `playlists/tracks.py` has the endpoint; nothing native calls it |
| **Rename / delete a playlist** | ✅ | ❌ | ❌ | `playlistsUpdatePlaylist` / `playlistsDeletePlaylist` are **generated and uncalled** |
| **Reorder playlist tracks** | ✅ | ❌ | ❌ | |
| Delete a smart playlist | ✅ | ✅ | ❌ | |
| **Reorder the queue / remove from it** | ✅ | ❌ | ❌ | `QueueView` has no `onMove`/`onDelete`; the only removal is rejecting a radio suggestion |
| Save the queue as a playlist | ✅ | ❌ | ❌ | |

**This is why `/playlists/:id` stays mounted in the browser.** The Mac's playlist detail looks
equivalent and is nearly read-only.

## Library management

| Capability | Web | Mac | iPhone | Notes |
|---|---|---|---|---|
| Pending Review | ✅ | ✅ | ❌ | Mac works at folder-group level |
| Proposed Changes | ✅ | ✅ | ❌ | |
| Mixtapes | ✅ | ✅ | ❌ | |
| **Edit track metadata** | ✅ | ❌ | ❌ | No write path exists natively at all |
| **Artist cleanup / merge duplicates** | ✅ | ❌ | ❌ | `/library/artist-cleanup` |
| **Trigger a library scan / re-index** | ✅ | ❌ | ❌ | No endpoint is generated; Pending Review only shows what a scan already found |
| **Analysis settings and runs** | ✅ | ❌ | ❌ | |
| **Backup / restore** | ✅ | ❌ | ❌ | Export with options, restore with preview and merge modes |
| **Create or edit a profile** | ✅ | ❌ | ❌ | `SetupView` says outright: *"Create one in the web app first"* |
| **Last.fm OAuth link** | ✅ | ❌ | ❌ | |
| **Community cache, update channel, diagnostics** | ✅ | ❌ | ❌ | |
| **Listening history / stats** | ✅ | ❌ | ❌ | The clients *write* play events and never read any back |

## Configuration

API keys and library paths are **not** configurable from any client — they are environment variables.
`ApiKeyStatus` only reports whether they are set.

Native settings are three tabs (Playback, Effects, Downloads) plus Server on the phone. Everything
under System, Library, Integrations, Data and Developer is browser-only.

Roughly a third of the web's 25 settings files configure *the web player itself* —
`AudioEffectsSettings`, `OfflineSettings`, `OfflineTracksPanel`, `StorageQuotaDisplay`,
`PlaybackSettings`, `QueueSyncSettings`, `ThemeSettings`. Those retire with the player they
configure; they are not part of the management surface.

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

Eleven tags are generated into the Swift client (`VENDORED_TAGS` in
`backend/scripts/lint_openapi.py`). These 22 are not, so anything they serve is browser-only by
construction:

```
admin  settings  s3-backup  export-import  analysis  background  artwork
deduplicate  "Library Organization"  diagnostics  download  updates  videos
lastfm  new-releases  bandcamp  external-albums  ambient  outputs  playback
auth  health
```

## Retired, and deliberately not coming back

| | |
|---|---|
| Chat / AI assistant | ADR-0043 → ADR-0048. Familiar calls no model; an MCP host brings its own |
| Spotify favorites import | Retired 2026-08-10; the UI had been unreachable |
| Server-synced playback queue | ADR-0028 |
| Capacitor iOS app (`packages/ios`) | Superseded by ADR-0001. **Still builds against 100% of `frontend/src`** |

## Dead at the time of writing

💀 Ephemeral ("Unsaved") playlists — `addPlaylist` had zero callers and nothing dispatched
`show-ephemeral-playlist`, so the sidebar section, the `/ephemeral/:id` route and "Save to Library"
could never be reached. Removed in the same change as this document, along with ~2,150 further lines
whose only importers were themselves: three superseded Settings panels, `useOfflineQuery`,
`urlParams`, `useToast`, `MixedValueInput`, `StoreSearchLinks`, `useRetryableOperation`,
`useProfileInit`, `useFocusTrap`, `TrackSearchInput`, `uuid`, and the `playerPersistence` shim.

They are listed here because a "record of what we had" that includes things that never worked is
worse than no record.
