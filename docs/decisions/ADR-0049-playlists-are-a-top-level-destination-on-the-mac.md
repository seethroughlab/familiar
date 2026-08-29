# ADR-0049: Playlists Are a Top-Level Destination on the Mac

Status: accepted

Date: 2026-08-10

Implementation:
- **Already built when ratified.** Accepted 2026-08-29 on `adr-0049-ratify-playlists-section` after
  checking all eight points against `familiar-apple` as it stands. Like ADR-0061, this had shipped
  and the record had not caught up.
- Verified point by point: the Playlists section sits between Library and Manage
  (`LibrarySidebar.swift:111`, after Library ends at `:109` and before Manage at `:116`); "All
  Playlists" heads the enumeration (`:153`) followed by one `ForEach` over every playlist with no
  provenance grouping (`:156`); Smart Playlists live inside the section (`:160-175`); `SidebarItem`
  has no `.playlist` case and `LibraryRouting.swift` and its tests are untouched (point 5's own
  test, and it passes); the highlight is derived from `openPlaylist`, with
  `isSelected = selection == item && openPlaylist == nil` (`:295`) so an open playlist takes the
  highlight from the root it was reached through (point 6); both stores load in their own `.task` at
  launch (`LibraryView.swift:1181`).
- **Three things shipped beyond the Decision**, all improvements, none of them recorded until now:
  the `+` is a *menu* offering "New Playlist" and "New Smart Playlist" rather than a bare button,
  because moving smart playlists inside this section had pushed making one from two clicks to three
  at the same moment it took making a regular one down to one (`:196-202`); playlist rows carry a
  rename/delete context menu (`:221-224`); and smart playlist rows carry "Edit rules…" (`:236-238`),
  which had no menu at all while the manual playlist beside it had two items.
- **`PlaylistGrouping` no longer exists.** It was deleted with the quarantine when point 3 was
  corrected, so the Tradeoff below that offered `PlaylistGrouping.split` as the one-line escape
  hatch for ordering has been rewritten to name where that edit actually lives now.
  `PlaylistRowKind.swift:9` records it as "the surviving half" of that file.
- **The accumulation premise still holds, 19 days on.** Live against the NAS: 4 playlists, 3
  auto-generated, and `generation_prompt like 'seed:%'` still matches **zero** — nothing has ever
  been seeded-generated. Three of the six chat-era playlists named in the Context (*Neon Pulse
  Drift*, *Echoes of Stillness*, *Binary Dreamscape*) have since been deleted, which the Mac can now
  do; no claim is made about whether that is why. *Demo Analysis*, called a test artifact above, is
  still there with 26 tracks.

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

**ADR-0048 raises a scaling question, and an earlier draft of this ADR answered it with the wrong
evidence.** `POST /playlists/generate` saves a playlist on *every* "Make a playlist" click, so
generated playlists can accumulate while hand-made ones do not. Point 3 originally quarantined them
on that basis, citing **6 generated against 1 manual** as proof it was already happening.

**None of those six came from that mechanism.** Every one is from the retired chat surface, created
deliberately between 2026-01-27 and 2026-04-30, 9 to 32 tracks each — *Essential IDM Albums*,
*Crystalline Reverie*, *Neon Pulse Drift*, *Echoes of Stillness*, *Binary Dreamscape*, *Merck Records
IDM - Like Ilkae*. `select count(*) from playlists where generation_prompt like 'seed:%'` returns
**0**: nothing has ever been seeded-generated.

So `is_auto_generated` does not mean "disposable byproduct". It means **"made through a feature we
deleted"**, and those are the listener's real playlists. The single hand-made one, `Demo Analysis`,
is a test artifact. A count was taken as evidence for a cause that produced none of it, and the
quarantine built on it hid the collection while leaving the scratch file on show.

## Decision

1. **Playlists are a top-level section in the Mac sidebar**, between Library and Manage. "Library"
   is left meaning one thing — the music you have — with Music Map and Discover kept there as ways
   of finding something to play (ADR-0016 point 3's reasoning, unchanged).

2. **Individual playlists are enumerated in the sidebar**, as the web app and as Spotify and iTunes
   do. An "All Playlists" row is kept above them, opening the existing `PlaylistsListView`: 200pt of
   sidebar is not where you find one playlist among two hundred, and that list has search.

3. **Every playlist is listed together, regardless of how it was made.** The sidebar does not group
   by `is_auto_generated`.

   **This point previously said the opposite** — that generated playlists were quarantined in a
   collapsed subgroup — and it was wrong on the evidence. See the Context above: the six playlists
   cited as proof of generate-flooding were not generated that way, and the flag marks a retired
   feature rather than a disposable playlist. Corrected before acceptance, which is what `proposed`
   is for.

   The accumulation concern is real but hypothetical, and provenance is the wrong lever for it: how a
   playlist was made says nothing about whether the listener wants it, and there is **no way to
   change the flag after creation** — `PlaylistUpdate` carries only `name`, `description` and
   `auto_download`, so a generated playlist you decide to keep can never become a regular one. A
   grouping nobody can escape is a filing system, not a preference.

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

7. **Creating a playlist is reachable on both platforms.** On macOS from the `+` menu on the section
   header and from the `PlaylistsListView` toolbar; on iOS from that same toolbar, reached through
   the Library tab's Playlists row, plus a "New Playlist" button in the empty state.

   **This point said "macOS only" and called iOS "a known gap, not an oversight".** The app now says
   otherwise: `LibraryView.swift:670` constructs `PlaylistsListView` outside any `#if`, passing
   `onCreate` on both platforms, and `BrowseViews.swift:453` renders a toolbar item whenever that
   closure is non-nil. There is an iOS `PlaylistEditorSheet` presenter to match
   (`LibraryView.swift:1360`, inside the `#else` branch). Corrected before acceptance rather than
   after, which is the only reason it could be corrected at all.

   **The ADR-0013 point 2 question was never actually answered** — the Follow-up below asked for a
   decision about whether the phone should manage playlists, and the capability arrived without one.
   Recorded rather than reverted, because on the evidence the shipped behaviour is coherent: the
   phone can also *add* tracks to a playlist (`DownloadControls.swift:270`, outside that file's
   macOS block), so a playlist created there is fillable rather than permanently empty. Creating a
   playlist to listen to is the listening path; editing a smart playlist's rules is management, and
   that stays on the Mac. The follow-up below now asks for the decision to be written down, not for
   the feature to be built.

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

2. **Quarantining generated playlists in a collapsed subgroup.** This was point 3 as first written,
   and it shipped before the evidence was checked. Rejected on the numbers above: the flag marks a
   retired feature rather than a disposable playlist, so the group hid the collection and showed the
   scratch file. Kept here rather than deleted because the reasoning was plausible and someone will
   propose it again.

3. **A `sparkles` badge on generated rows in the sidebar**, marking provenance without hiding
   anything. Rejected as re-asserting a distinction that is only ever interesting once — the badge
   already exists in `PlaylistsListView`, where a mark on a list you deliberately opened is
   information rather than a permanent label on a row you use every day.

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
- **Positive** — the sidebar shows the listener's actual playlists, which the first version of point
  3 had collapsed out of sight.
- **Tradeoff** — the Mac and the phone now arrange playlists differently. This is the same shape as
  ADR-0012 point 1's split between the Mac's sidebar and the phone's `CollectionsView`, and is
  accepted for the same reason: a 200pt column and a 393pt phone are not the same surface.
- **Tradeoff** — sidebar rows follow the server's `updated_at DESC` ordering, so a row can move when
  a playlist is edited. Alphabetical would be steadier for muscle memory; consistency with All
  Playlists was chosen instead. This originally offered `PlaylistGrouping.split` as the one-line fix
  if that proved wrong; that type was deleted along with the quarantine when point 3 was corrected,
  so the edit is now a sort on `playlists.playlists` at `LibrarySidebar.swift:156`.
- **Tradeoff** — the disclosure state is `@State` and resets each launch rather than persisting.
- **Follow-up** — this asked whether the phone *should* create a playlist, as an ADR-0013 point 2
  question rather than an oversight to be quietly patched. It was then quietly patched: the phone can
  create one, and no ADR says so. Point 7 above now describes the behaviour and argues it is
  coherent; what is still owed is the ADR-0013 reading, which should also say where the line falls
  for the phone's other playlist actions rather than settling this one case.
- **Follow-up** — the accumulation ADR-0048 makes possible is still unaddressed, and is a real risk
  once seeded generation is actually used. The lever should be recency, pinning, or an expiry — not
  provenance, and not a group the listener cannot get out of. **Still entirely hypothetical at
  acceptance**: `seed:%` matches zero playlists 19 days after this was written.
- **Follow-up (discharged)** — `is_auto_generated` was read as a *capability* in two places, which
  nothing defended: `GET /playlists/{id}/recommendations` answered **400** for a hand-made playlist,
  and the web "Add to playlist" picker passed `include_auto=false`. Both are gone —
  `recommendations.py` no longer mentions the flag at all, and `PlaylistPickerModal.tsx:36` now calls
  `playlistsApi.list(true)` explicitly. The Mac and the web finally offer the same playlists.
- **Follow-up (discharged)** — `generation_prompt` was printed raw by both surfaces that displayed
  it, so an ADR-0048 playlist would have shown the listener `seed:album:OK Computer`. The web
  renderer was deleted with the player, and the Mac routes through
  `Self.blurb(prompt:description:)` (`DetailStore.swift:204`), whose comment names that exact string
  as what it exists to suppress.
- **Follow-up (discharged by deletion)** — two unrelated web defects found while investigating:
  mobile web filtered its playlist list to `is_auto_generated`, and the "Unsaved"
  ephemeral-playlist system was unreachable. `MobileMoreSheet.tsx` and `ephemeralPlaylistStore` no
  longer exist; ADR-0058's narrowing of the web app removed both. Neither was fixed, which is worth
  distinguishing from being solved.
- **Follow-up (discharged)** — renaming and deleting a regular playlist are now possible on the Mac,
  from a context menu on the sidebar row (`LibrarySidebar.swift:221-224`) through
  `PlaylistEditorSheet`. `playlistsUpdatePlaylist` and `playlistsDeletePlaylist` have callers.
