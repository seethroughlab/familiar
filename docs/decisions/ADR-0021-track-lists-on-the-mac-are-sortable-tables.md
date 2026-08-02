# ADR-0021: Track Lists on the Mac Are Sortable Tables

Status: accepted

Date: 2026-08-02

Extends [ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md).

Implementation:
- Accepted 2026-08-02. Server half on `familiar` #72, the Tracks table on `familiar-apple` #50.
  Point 2's floor bump to macOS 14 shipped with it; iOS is untouched at 15.
- Point 4's `playCount` and `dateAdded` are live and verified against the real library — sorting by
  plays descending returns 42, 38, 35. A latent defect was fixed alongside: the play-history join
  was added only for `lastPlayed` *and* only when a profile existed, while the ordering column was
  applied regardless, so sorting by it without a profile would have had SQLAlchemy invent a cross
  join against every row of `profile_play_history`.
- **Two columns are deliberately absent, both built and then removed after seeing them render.**
  `dateAdded` sorts but `TrackResponse` carries no `created_at`; the audio features are on the
  response only when `include_features` is set, which this list does not request. A column that
  renders blank on every row while its header sorts is worse than an absent one — it reads as "the
  library has no tempo data". Filling them is a schema change and a query change respectively.
- Point 7's rollout to the other six lists has not happened yet; only Tracks is a `Table`. They hold
  their rows whole, so they sort on-device and need none of the store work Tracks required.
- Not yet exercised: clicking a header. The server round-trip is untested in the running app.

## Context

Every track list in the Mac app is the same two-line row: a title, then `artist · album` underneath,
with a duration on the right. It cannot be sorted, and most of what the library knows about a track
cannot be seen at all — play count, when it was added, year, genre, bitrate, tempo, key. A library of
26,396 tracks is browsed through a shape that shows four fields and orders them one way.

The web app answered this long ago. `columnStore.ts` defines **fifteen columns** with visibility,
order and width, persisted to `localStorage` as `familiar-columns`, and `PlaylistTrackList` renders a
header row whose cells sort. Three of those columns are on by default; the rest are there when
wanted. This ADR is the Mac catching up, and the web's arrangement is the model.

**The part that does not transfer, and is the reason this needs deciding rather than copying.** The
web sorts *in the browser*, with `useSortedTracks` over the rows it happens to hold. On a list that
pages, that sorts the loaded page and nothing else. `LibraryStore` pages the Mac's Tracks list at
**50**, so a client-side sort there would order fifty rows out of 26,396 and present the result as
the library's order.

That is not a hypothetical: it is the defect the library shuffle already shipped and had to fix.
`LibraryView.shuffleLibrary` records it — *"that made shuffle look like it played nothing but artists
beginning with 'A'. The order was random; the pool was fifty tracks deep."* Sorting has exactly the
same failure available to it, and would be harder to notice, because a wrong order looks like an
order.

**The server can already do it, mostly.** `/tracks` accepts `sort_by` and `sort_order`
(`backend/app/api/routes/tracks/listing.py:68`), against an allowlist of nine fields — artist, album,
title, duration, year, genre, trackNum, format, lastPlayed — plus twelve audio features
(`backend/app/api/routes/tracks/__init__.py:30-47`).

**Two of the columns most worth having are missing from it**, and both exist in the schema:
`ProfilePlayHistory.play_count` and `Track.created_at`. Play count and date-added are the two fields
that answer "what do I actually listen to" and "what is new here", and neither can be sorted by
today on any client.

**Which lists page, and which do not.** The distinction decides where sorting happens:

| list | loading | sort belongs |
|---|---|---|
| Tracks | paged, 50 at a time | server |
| Album, artist, playlist, smart playlist | fetched whole per entity | client |
| Favorites | whole — `limit: 10_000` against 1,720 (ADR-0012 point 3) | client |
| Downloads | on-device index | client |

**The platform constraint, and what it costs.** SwiftUI's `Table` gives sorting, resizing and
reordering from macOS 12. The built-in column chooser — `TableColumnCustomization`, which persists
visibility and order itself — is macOS 14. The Mac app currently targets **macOS 13.0**
(`Familiar.xcodeproj` and `Package.swift`), so the choice is a floor bump or a hand-built chooser
duplicating what the system offers.

## Decision

1. **Track lists on the Mac become `Table`s**, with a header row whose columns sort, resize and
   reorder, and a column chooser for what is shown.

2. **The Mac's deployment target moves to macOS 14.** This is the load-bearing cost of point 1, and
   it is stated as its own point because everything after it inherits the freedom: any later Mac code
   may use macOS 14 APIs without an availability check. **iOS is untouched at 15** — the floor is per
   platform, and ADR-0001's reasoning about not regressing the Capacitor app's devices applies to the
   phone, not to a Mac app that has never shipped to anyone.

3. **Sorting is done by whoever holds the whole list.** The Tracks list sorts through the server's
   `sort_by`/`sort_order`, and resorting refetches from the first page. Every other list is fetched
   whole and sorts on the device. A list must never sort the pages it happens to have.

4. **The server's sort allowlist gains `playCount` and `dateAdded`**, mapping to
   `ProfilePlayHistory.play_count` and `Track.created_at`. `lastPlayed` already joins the play-history
   table per profile, so play count needs no new join — only an entry.

5. **Column choice, order and width are per-device and not synced.** They follow ADR-0015 points 5
   and 6: a display preference belongs to the screen it is displayed on. A 13-inch laptop and a
   34-inch monitor want different columns, and a column set that followed a listener between machines
   would be wrong more often than right. `TableColumnCustomization` persists them itself.

6. **The column identifiers match the web's**, so the two clients name the same things — `artist`,
   `album`, `duration`, `year`, `genre`, `trackNum`, `format`, `lastPlayed`, `bpm`, `key`, and the
   audio features. The stores stay separate; only the vocabulary is shared.

7. **In scope: every main track list** — Tracks, album, artist, playlist, smart playlist, favorites,
   downloads. One table component, one column preference across them.

8. **Out of scope: the queue.** Its order *is* the playback order, so a sortable queue either
   reorders playback or displays an order that is not the one playing. Both are worse than a list.
   The now-playing bar and the full player are transport, not browsing, and are untouched.

## Alternatives Considered

**Stay on macOS 13 and hand-build the column chooser.** No floor bump, and `Table` still gives
sorting and resizing — only the show/hide chooser would be ours, as a toolbar menu backed by
`UserDefaults`. Rejected on cost against benefit: it is a persisted preference model, a menu, and the
plumbing to rebuild the table's columns from it, written to avoid raising a floor on an app that has
never been released. If the app had users on macOS 13 this would be the answer.

**Build the whole thing by hand, mirroring `PlaylistTrackList`.** Maximum control, matches the web
exactly, and could share column definitions conceptually. Rejected because it reimplements sorting,
resizing, reordering and keyboard behaviour that `Table` provides and that Mac users already know
from Finder and Mail — and every one of those is a place to be subtly worse than the system.

**Sort everything client-side, as the web does.** Simplest, one code path, no server work. Rejected
outright: it would ship the shuffle bug again on a surface where it is harder to see. Sorting 50 of
26,396 tracks by play count produces a plausible-looking list that is wrong, which is worse than a
list that cannot be sorted at all.

**Load the whole library and sort it locally.** `/tracks/ids` already returns all 26,396 ids in one
request, so the precedent exists. Rejected because ids are not rows: sorting by play count needs the
play counts, and fetching 26,396 full track rows to sort them on the device is a great deal of work
to avoid an `ORDER BY` the database is already able to do.

**Sync column preferences through the server, as one profile-wide layout.** Consistent across
machines, and there is precedent for profile settings. Rejected for the reason ADR-0015 gives about
audio effects: it is a property of the screen, not of the listener. It would also invent server state
for something that has never had any.

## Consequences

- **Positive:** The library becomes answerable — most played, recently added, longest, by year — on
  the platform ADR-0013 made the management surface.
- **Positive:** Sorting the Tracks list is correct rather than plausible, because it happens where the
  whole library is.
- **Positive:** `playCount` and `dateAdded` become sortable for every client, including the web,
  which cannot sort by them today either.
- **Tradeoff:** Macs on macOS 13 can no longer run the app. Named in point 2 rather than discovered
  at a build failure.
- **Tradeoff:** Two sorting paths — server for one list, client for the rest — and the rule for which
  is which lives in point 3 rather than being obvious from a call site. The alternative was one wrong
  path.
- **Tradeoff:** A table is denser and less forgiving than a two-line row. Long titles truncate where
  they previously wrapped to a second line, and the phone keeps the row shape, so the two clients now
  present the same list differently.
- **Follow-up:** Whether the *phone* should gain sorting without columns — a sort menu rather than a
  table, since a 393pt screen has no room for a header row. It is the same question ADR-0018 answered
  for navigation, and the answer here may well be different.
- **Follow-up:** The web sorts client-side over loaded rows and has the defect described above. This
  ADR does not fix it; it only avoids repeating it. Worth its own change once the server allowlist is
  wider.
