# ADR-0081: The Admin App Has One Component Tree

Status: accepted

Implementation:
- Built 2026-08-30 on `adr-0081-one-tree`, in two commits: the registry deletion (points 3–5) and
  the tree move (points 1, 2, 6). Net **−596 lines** then **−132**.
- **Point 4 had to come first.** Artist cleanup was the registry's only routed member, so moving it
  to `/tools/artists` is what reduced the registry to the state point 3 describes. The ADR presents
  them in the other order; the dependency runs the other way.
- **Point 3's premise was two members, not one.** `browsers/index.ts` registered `ArtistCleanupBrowser`
  *and* `DiscoverBrowser`. "One member that its only consumer bypasses" describes the state after
  point 4, which is worth saying because the point reads as a description of the state before it.
- **Point 5 measured: `DiscoverBrowser` read 2 of 24 fields.** It is now
  `components/Embed/DiscoverSurface.tsx`, beside its only renderer, with a two-field interface. The
  seam `EmbedDiscover` was protecting survives and improves — reading a third field is a compile
  error at the definition rather than depending on the caller having pre-supplied it.
- **`components/Library/` is not deleted, and I deleted it once by mistake.** Point 3 names symbols;
  the directory also holds `columnDefinitions`, `AlphabetBar`, `TrackContextMenu`,
  `SelectionIndicator` and the shared filter and context-menu types, which `components/shared/` and
  `hooks/` import — and point 6 keeps `shared/` precisely because the embed path runs through it.
- **Point 2's `panels/settings/` has no members**, and there is no `screens/SettingsScreen.tsx`. The
  point expected theme to survive as the one genuine setting; `ADR-0080` deleted the settings route
  entirely once theme was all that remained on it.
- **Point 6's orphan list had aged.** `SmartPlaylists/` and `Home/` were already gone. Of the rest,
  `TrackContextMenu` has two real consumers and `PlaylistPickerModal` is rendered by `AppShell`.
  Only `AlbumContextMenu.tsx` was genuinely dead — no importer anywhere, its only textual matches a
  same-named state interface, which went with it.
- **The navigation test is the load-bearing change.** It scanned `src/components/`, so splitting the
  tree would have silently dropped `app/`, `screens/` and `panels/` from its coverage — **84 files
  before, 196 after**. Its docstring warns that a list of files to check is the same shape of
  mistake as the bug it checks for; a directory root is the same trap wearing different clothes.
  Broadening it immediately produced a false positive: `App.tsx` explains its catch-all with the
  words *"this was `Navigate to=\"/settings\"`"*, and the scanner read that prose as a dead link. It
  now strips comments first.
- Verified at each stage: `tsc` reports the same **6 pre-existing errors** as `origin/main` and no
  new ones, **364 unit tests** pass, the web build succeeds, and `DiscoverSurface`'s chunk hash is
  unchanged — the embedded page both Apple clients load is byte-identical.

Date: 2026-08-18

Extends [ADR-0058](ADR-0058-the-web-app-is-an-administration-tool.md). Where `ADR-0080` decides the
chrome, this decides where the code lives.

## Context

The administration tool's file layout describes an application that no longer exists.

**`components/Settings/` is the real admin component library.** It holds 4,633 lines across 17
files, and **12 of them are rendered by `components/Admin/*Page.tsx` and never by `/settings`**. The
folder is named after its smallest consumer. `Settings/index.tsx` itself renders three sections, two
of which — playback and offline storage — leave with the player under `ADR-0058` point 5.

**`components/Admin/` is 905 lines of thin composition** whose page names do not match their routes:
`LibraryPage` is the index route `/`, while `/library/*` means something else entirely (browsers).
`AdminPage.tsx` exports `AdminPage` and `AdminSection` — about 50 lines — and that is the entire
design system. The card markup inside `LibraryPage` and `ToolsPage` is duplicated between them.

**Artist cleanup is an admin screen wearing a browser costume.**
`ArtistCleanupBrowser.tsx` is an 18-line shim that takes `BrowserProps`, ignores all 22 fields, and
renders `ArtistMergePanel` (472 lines) in a `max-w-4xl` div. Its only reason to exist is to be
reachable through `BROWSER_ROUTES` → `LibraryBrowser` → `LibraryView` → the browser registry. Getting
there drags in `LibraryView.tsx`, 328 lines of URL-parameter parsing for energy, valence, `fx`, `fy`
and `downloadedOnly` — filters this screen does not have and would not use. Its own header comment
says it was *"relocated out of Settings (it's an action queue, not a setting)"*, which was the right
instinct and the wrong destination.

**The browser registry outlives its purpose.** It exists to swap between library browsers —
Artists, Albums, Music Map, Proposed Changes, Pending Review, New Releases — every one of which has
been deleted. Once the track list goes with the player, **the registry has one member left**,
`DiscoverBrowser`, and the embed does not use the registry to reach it:
`components/Embed/EmbedDiscover.tsx:9` lazy-imports `DiscoverBrowser` directly, with a comment
explaining that this keeps the track list out of the embed bundle.

**One thing that looks dead is not.** `components/shared/` appears orphaned and is not:
`components/Discovery/DiscoverTrackList.tsx:3` imports `PlaylistTrackList` from it, and
`DiscoverTrackList` is on the embed path. **Deleting `shared/` would break Discover on the Mac and
the phone.** Genuinely orphaned, with no importer anywhere: `components/SmartPlaylists/` (787),
`components/Home/` (~640), the two `Sidebar/*ContextMenu.tsx` files (411), and
`Playlists/{FavoritesDetail,DownloadsDetail}`.

## Decision

1. **Three trees, named for what the user sees:**

   ```
   app/       App.tsx  routes.ts  AdminShell.tsx  TopBar.tsx  StatusMenu.tsx
   screens/   one file per route
   panels/    library/  tools/  server/  settings/ — the composable units
   ```

   `screens/` is a one-to-one map of the route table. `panels/` holds what screens compose.
   **Neither is called `Admin` or `Settings`**, because both names now describe a subset of what they
   contain.

2. **`components/Settings/`'s twelve admin components become `panels/`**, grouped by the destination
   that renders them. `screens/SettingsScreen.tsx` keeps only what is genuinely a setting — after
   `ADR-0058` point 5's second wave, that is the theme.

3. **The browser registry is deleted.** `LibraryBrowser`, `LibraryView`, `browsers/index.ts`,
   `browserRegistry`, `registerBrowser`, `getBrowser`, `getBrowsersByCategory`, `BrowserMetadata`,
   `DEFAULT_BROWSER_ID`, and `routes.ts`'s `BROWSER_ROUTES`, `PARKED_BROWSERS` and `LIBRARY_ITEMS`.
   A registry with one member that its only consumer bypasses is indirection with nothing on the
   other end.

4. **Artist cleanup becomes an ordinary screen at `/tools/artists`.** It is a job you run against the
   library, which is what Tools means under `ADR-0058` point 2, and it belongs beside Duplicates,
   Artwork and Organiser. `/library/*` then leaves the route table entirely.

5. **`DiscoverBrowser` gets an explicit, narrow props interface — not `any` and not a cast.** Its
   current `BrowserProps` is defended by a comment as a seam: a field it starts reading is a compile
   error at the boundary rather than a silent `undefined` inside a web view. That property is worth
   more than the 22 unused fields cost, so the replacement interface names the fields it actually
   reads and keeps the compile error.

6. **Orphans are deleted, and `shared/` is not one of them.** `SmartPlaylists/`, `Home/`, the two
   sidebar context menus and the two `Playlists` detail components go. `components/shared/` stays and
   moves with `Discovery/`, because the embed path runs through it.

## Alternatives Considered

**Rename `Settings/` to `Admin/` and merge them.** The one-step version, and it would fix the naming
without moving anything else. Rejected because it keeps a single flat folder of 29 components with no
distinction between a routed screen and a composable unit, which is the property that made the
current layout hard to read in the first place.

**Keep the browser registry for future browsers.** It is a working extension point, and Discover
still uses the `BrowserProps` shape. Rejected because "future browsers" is the assumption that has
been false for every browser it ever held — all six were deleted rather than joined by a seventh —
and because `ADR-0050` point 2 sends new listening surfaces to the native clients, so a seventh web
browser is against a standing decision.

**Route artist cleanup under Library rather than Tools**, since it is about the library. Genuinely
arguable, and it is where the link lives today. Rejected because `ADR-0058` point 2 puts *"run
something against the library"* under Tools, and artist merging is exactly that — it has a preview,
it mutates, and it is a job rather than a view.

**Leave `components/Library/` alone and only move the admin screens.** Rejected because the folder is
the player's browse layer, and after the strip its contents are one browser used exclusively by the
embed. Leaving it means a directory named for a destination that no longer routes there.

## Consequences

- **Positive** — the route table and the file tree become the same shape, so finding the code behind
  a screen requires no knowledge of what the application used to be.
- **Positive** — deleting the registry removes `LibraryView`'s 328 lines of filter parsing from the
  path to an admin screen that has no filters.
- **Positive** — roughly 1,800 lines of genuine orphans go, and the near-miss on `shared/` is
  recorded so the next person does not repeat it.
- **Tradeoff** — this is a large diff that moves almost every file in the admin tree, making
  `git log --follow` and any in-flight branch harder. It should land in as few commits as possible
  and not at the same time as behavioural change.
- **Tradeoff** — narrowing `DiscoverBrowser`'s props is a change to the embed's boundary, which is
  the one surface with no automated coverage. It must be exercised on a Mac and a phone.
- **Follow-up** — `components/Discovery/` and `components/Visualizer/` keep their names and are not
  reorganised here. They belong to the embedded surfaces rather than to the admin app, and moving
  them is a separate decision with a separate risk profile.
