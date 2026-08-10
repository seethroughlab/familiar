# ADR-0049: Playlists Are a Top-Level Destination on the Mac

Status: proposed

Date: 2026-08-10

Extends [ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md), and follows
[ADR-0048](ADR-0048-seeded-playlists-are-generated-from-analysis.md)

## Context

Two problems, both surfaced by using the Mac app rather than by reading it.

**You could not create a playlist on either Apple client.** Not hidden behind a menu — absent. The
only playlist affordance was `Menu("Add to playlist")` in `App/Shared/DownloadControls.swift:201`,
which adds a track to an *existing* playlist and hides itself entirely when the server has none
(`DownloadControls.swift:198`). A fresh library was a closed loop: nothing could make the first
playlist, so the one affordance that existed never appeared.

`playlistsCreatePlaylist` has been in the generated client since the `playlists` tag entered
`Sources/FamiliarAPI/openapi-generator-config.yaml`, with **no caller anywhere in the app**. The
backend has supported it all along — `POST /api/v1/playlists` accepts `{name, description?,
track_ids: []}` and returns 201 (`backend/app/api/routes/playlists/crud.py:153`), where an empty
`track_ids` is valid. This is the *capability with no caller*: the inverse of the `#70`/`#74`/`#76`
family, where an affordance pointed at a destination that was not mounted.

**Playlists sat inside a "Library" section that had come to mean three different things.**
`App/Shared/LibrarySidebar.swift` grouped Tracks/Albums/Artists (what you *have*), Playlists and
Smart Playlists (what you *made*), and Music Map and Discover (ways to *find* something) under one
header.

**A premise in that file was contradicted and nothing noticed.** Its doc comment claimed the
arrangement "mirrors the web app's sidebar rather than inventing a second one for the same items:
the four browse sections under Library". That was true when written. The web sidebar has since grown
separate `Playlists` and `Smart Playlists` headers, each with a `+` and each enumerating the
individual playlists beneath it (`packages/frontend/src/components/Sidebar/Sidebar.tsx:336-419`). So
the two surfaces diverged, the comment kept asserting they had not, and ADR-0012 point 1's stated
principle — mirror the web sidebar's grouping "rather than inventing a second arrangement for the
same two things" — had quietly stopped being followed for playlists while still being followed for
collections.

**ADR-0048 turned a preference into a scaling problem.** `POST /playlists/generate` saves a playlist
on *every* "Make a playlist" click. Generated playlists therefore accumulate without bound while
hand-made ones do not, and each one would otherwise become a permanent sidebar row. On the live
server today: **6 generated, 1 manual, 3 smart.** A flat list is already dominated by the ones nobody
chose to keep.

## Decision

1. **Playlists are a top-level section in the Mac sidebar**, between Library and Manage. "Library"
   is left meaning one thing — the music you have — with Music Map and Discover kept there as ways
   of finding something to play (ADR-0016 point 3's reasoning, unchanged).

2. **Individual playlists are enumerated in the sidebar**, as the web app and as Spotify and iTunes
   do. An "All Playlists" row is kept above them, opening the existing `PlaylistsListView`: 200pt of
   sidebar is not where you find one playlist among two hundred, and that list has search.

3. **Generated playlists are quarantined in a collapsible subgroup**, collapsed by default, rather
   than interleaved with hand-made ones. This is the point that follows from ADR-0048 rather than
   from taste: a surface that grows by one row per click is not the same kind of thing as a list you
   curate, and mixing them would make the sidebar mostly disposable within a week of ordinary use.
   The web app interleaves them today and will meet this problem later.

4. **Smart Playlists move into the Playlists section.** They are something you made, not library
   contents. ADR-0013's reason for making them a sidebar item rather than a fifth `BrowseSection`
   still holds and is unaffected: `BrowseSection` also drives the phone's root list.

5. **An individual playlist is a pushed route, not a `SidebarItem` case.** `SidebarItem` could have
   grown `.playlist(id)`; that would force a case into `LibraryRoot(selecting:)` and make
   `LibraryRoot.sidebarItem(section:)` unimplementable, since that reverse mapping has no id to hand
   back. `LibraryRoot.isCollection` already records the precedent — Favorites and Downloads "are
   reached by pushing a route rather than by swapping the column's contents." Consequence worth
   stating as a test: **`Sources/FamiliarKit/LibraryRouting.swift` and its tests are untouched by
   this change.** If either needs editing, the design has drifted.

6. **The sidebar highlight derives from the pushed route**, not from a second stored selection.
   `mainColumn` prefers `path.last` over the section list, so the highlight asks the same value the
   column does. This is why arriving at a playlist from the sidebar and arriving at it from All
   Playlists light the same row. `LibraryRouting.swift` exists because a highlight computed
   separately from the column drifted out of agreement with it once already; a second flag here
   would be that defect returning by a different door.

7. **Creating a playlist exists on macOS only.** Reachable from the `+` on the section header and
   from a toolbar button on All Playlists, mirroring `SmartPlaylistsListView`. **iOS is unchanged**
   and still cannot create one — ADR-0013 point 2 keeps the phone on the listening path, and its
   root list is a different construction. This is a known gap, not an oversight.

8. **The playlist stores load at launch on macOS.** Previously they loaded only when their section
   was opened, which was correct when each was one row leading elsewhere and is wrong once the rows
   *are* the contents — the section would render empty until visited.

## Alternatives Considered

1. **Extend `SidebarItem` with `.playlist(PlaylistSelection)` and give `LibraryRoot` a matching
   case.** This keeps one source of truth in the routing model and is the more orthodox shape. It
   costs eight edit sites, and only five are compiler-enforced: the silent ones include
   `LibraryNavigation.select`'s `if case .section(let chosen)`, which would capture nothing for a
   playlist and leave every playlist row lighting the last one selected. Rejected because point 6
   achieves the same single source of truth by reading `path.last` — the value the column already
   draws from — at a fraction of the surface area, and because the routing model staying untouched
   is independently verifiable.

2. **A flat list with a `sparkles` badge on generated playlists**, which is what the web app does and
   what `PlaylistsListView` already does for its rows. Rejected on the arithmetic: 6 of 7 rows would
   be generated today and the ratio only worsens, so the badge would be marking the majority rather
   than the exception.

3. **Keep generated playlists out of the sidebar entirely**, reachable only through All Playlists.
   Rejected because a playlist you just generated would not appear where you would look for it, and
   ADR-0048 point 6 was explicit that generation *saves* rather than previews precisely so the result
   is somewhere findable.

4. **Leave Playlists as one row and just add a create button.** The smaller change, and it fixes the
   stated complaint. Rejected because it leaves "Library" meaning three things, leaves the Mac
   diverging from the web sidebar while a comment claims otherwise, and does not address what
   ADR-0048 does to the number of playlists.

5. **Put creation only in the `PlaylistsListView` toolbar**, matching `SmartPlaylistsListView`
   exactly and touching the sidebar not at all. Rejected because it is not where a listener looks —
   the web app's `+` is on the sidebar header, and a create button reachable only after navigating to
   a list is a step removed from the place the list is named.

## Consequences

- **Positive** — the Mac can create a playlist at all, closing a loop where the only playlist
  affordance required a playlist to already exist.
- **Positive** — `LibraryRouting.swift` and `LibraryRoutingTests.swift` are unchanged, so the
  routing model's guarantees are untouched and the claim is checkable rather than asserted.
- **Positive** — loading the stores at launch also fixes a pre-existing gap: the "Add to playlist"
  submenu was empty until you had visited the Playlists section.
- **Positive** — the Mac is now ahead of the web app on the one point ADR-0048 makes urgent, so the
  web has a design to adopt rather than a problem to rediscover.
- **Tradeoff** — the Mac and the phone now arrange playlists differently. This is the same shape as
  ADR-0012 point 1's split between the Mac's sidebar and the phone's `CollectionsView`, and is
  accepted for the same reason: a 200pt column and a 393pt phone are not the same surface.
- **Tradeoff** — sidebar rows follow the server's `updated_at DESC` ordering, so a row can move when
  a playlist is edited. Alphabetical would be steadier for muscle memory; consistency with All
  Playlists was chosen instead, and this is one line in `PlaylistGrouping.split` if that proves
  wrong.
- **Tradeoff** — the disclosure state is `@State` and resets each launch rather than persisting.
- **Follow-up** — the phone still cannot create a playlist. Whether it should is an ADR-0013 point 2
  question, not an oversight to be quietly patched.
- **Follow-up** — the web sidebar still interleaves generated playlists with hand-made ones and will
  hit point 3's problem. Adopting the same grouping there is the obvious next step.
- **Follow-up** — two unrelated web defects found while investigating: mobile web filters its
  playlist list to `is_auto_generated`, so a hand-made playlist never appears there
  (`MobileMoreSheet.tsx:49-56`); and the entire "Unsaved" ephemeral-playlist system is unreachable,
  since `ephemeralPlaylistStore.addPlaylist` has zero callers and nothing dispatches the
  `show-ephemeral-playlist` event `useAppBootstrap.ts:83` listens for.
- **Follow-up** — renaming and deleting a regular playlist are still not possible on the Mac, though
  `playlistsUpdatePlaylist` and `playlistsDeletePlaylist` are generated and unused. Same shape as the
  gap this ADR closes.
