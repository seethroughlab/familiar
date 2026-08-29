# ADR-0094: The Artists Grid Toggles To A Sortable Table

Status: accepted

Date: 2026-08-28

Extends [ADR-0021](ADR-0021-track-lists-on-the-mac-are-sortable-tables.md), which made track lists
sortable tables on the Mac and scoped itself, in point 7, to lists *of tracks*. This applies the same
rule to a list of artists, which is a different question only because the row is not a track.

Implementation:

- **Shipped 2026-08-28**, `familiar` on `adr-0094-artists-table-impl` and `familiar-apple` on
  `adr-0094-artists-table`, stacked on the API cluster because `ADR-0073` had already edited
  `library_artists.py` and a branch from `main` would have conflicted.
- **`min_track_count` is applied as a `HAVING`, before the count** — the only subtle part of the
  server change. Counting first would tell a client there are more artists than it can ever page
  to, and a last page short for no visible reason is the kind of paging defect nothing raises. A
  test asserts `total == len(items)` and was checked to *fail* when the filter moves after the
  count.
- Point 2 landed on the store rather than per call: `ArtistsStore` holds `sort` and
  `minTrackCount`, and `apply(sort:minTrackCount:)` refetches from page one. Paging must ask for
  the ordering the first page used, or two slices are spliced from different sorts.
- **The offline cache sorts locally, and that is not an inconsistency.** `ADR-0021` point 3 puts
  sorting with whoever holds the whole list; offline, the store does. Server-side sorting is
  required for the *paged* path because 100 of ~3,500 rows is not the list.
- `ArtistSort` lives in `FamiliarKit` so `wireValue` can be asserted. It is a string the server
  branches on and **falls through to name-ordering for anything it does not recognise** — so a typo
  is not an error, it is the control silently doing nothing. Both the literal values and a
  "every case is recognised" check were verified to fail on a deliberate typo.
- Point 3 held: no new server field. The columns are `name`, `track_count` and `album_count`, all
  of which `ArtistSummary` already returned and rendered nowhere.
- One wrinkle the schema forced: `ArtistSummary.id` is `String?` and so cannot satisfy
  `Identifiable`, which `Table` requires. A small `ArtistRow` wrapper keys on `name` — the same key
  the grid's `ForEach` already used, so both views agree what one row is.
- Sorting is a toolbar picker, not column headers. A header that reordered the loaded page would
  order the accident of what has been scrolled to, which is what point 2 forbids.

## Context

The Mac and phone browse artists through `ArtistsGridView` (`App/Shared/BrowseViews.swift:117`) — a
`LazyVGrid` of circular artwork tiles, paged at 100, with a search field. It is the surface this ADR
is about, and **it works**: the circles are a good way to find an artist you can picture.

Three facts make the case that it should not be the *only* way.

**Half the tiles have no picture.** The view's own comment records the measurement: *1,703 of 3,475
artists carry a Last.fm `image_url`*. For the other 1,772 the grid renders a placeholder, so a
surface whose organising idea is recognition falls back to reading names in a layout optimised for
pictures.

**The data the grid does not show is already in the response.** `ArtistSummary` carries `id`, `name`,
`image_url`, `first_track_id`, `first_album`, **`track_count` and `album_count`**. The last two are
computed per artist on every request and rendered nowhere.

**The server can already sort by them, and nothing has ever asked it to.** `list_artists`
(`backend/app/api/routes/library_artists.py:51`) takes `sort_by` with `name`, `track_count` and
`album_count`, implemented at lines 114–116. The only Swift caller
(`App/Shared/BrowseStores.swift:218`) passes `search`, `page` and `pageSize` — never `sort_by`. This
is a capability with no caller, which `ADR-0077` would ordinarily delete; the reason it is being
wired up instead of removed is that there is a want for it, which is this ADR.

**The question this ADR was asked was "filters or a sortable list?"** — with "total number of tracks"
as the example. Those two examples pull apart under examination, and the distinction is the whole
decision: *number of tracks* is an attribute of each artist and belongs in a column, while *number of
artists* is a property of the whole list and is already returned as `total`. A filter panel built to
hold both would be answering two unrelated questions with one control.

`ADR-0021` point 3 is the constraint that shapes any answer here: **"Sorting is done by whoever holds
the whole list… A list must never sort the pages it happens to have."** The artists list holds 100
rows of roughly 3,500, so it is in exactly the position that point was written about.

## Decision

1. **The grid gains a table view, toggled. It is not replaced.** The circles stay the default. The
   missing-artwork measurement is an argument for offering an alternative, not for removing the
   thing that works for the 1,703 artists that do have a picture.

2. **The table sorts server-side, through the `sort_by` the endpoint already has.** Changing the sort
   refetches from page 1, exactly as `ADR-0021` point 3 requires and for the same reason: with 100 of
   3,500 rows loaded, sorting locally would order the accident of what has been scrolled to, and a
   wrong order looks like an order.

3. **The columns are the fields `ArtistSummary` already returns** — name, track count, album count.
   No new server field, no new aggregate, no new join. A column that needs one is a separate change
   with its own cost.

4. **Sorting answers the question; a filter panel is not added.** "Which are my biggest artists" is a
   sort, not a filter, and the three sorts the server offers already answer it. Adding a filter panel
   as well would be two mechanisms for one question — the conflation `ADR-0072` point 1 exists to
   stop, in the interface rather than in the schema.

5. **One filter earns its place, and it is a single control: a minimum track count.** The long tail
   is real — an artist with one track is usually a compilation straggler rather than someone in the
   library — and sorting cannot answer it, because ascending order shows those artists first and
   descending merely buries them. Neither removes them. This adds one query parameter,
   `min_track_count`, and one stepper. It is the only new server surface in this ADR.

6. **The toggle and the sort are Mac-only; the phone keeps the circles.** `TrackTable.swift` is
   `#if os(macOS)` and `ADR-0021` point 2 took only the Mac to macOS 14 for
   `TableColumnCustomization`. A multi-column table on a phone is a worse grid, not a better list.

7. **The chosen view and sort are per-device and not synced**, following `ADR-0021` point 5 and
   `ADR-0015` points 5 and 6: a display preference belongs to the screen it is displayed on.

## Alternatives Considered

**A filter panel, as the question proposed.** Rejected as the primary answer under point 4, but not
because filtering is wrong — point 5 keeps the one filter that sorting genuinely cannot express. What
it will not do is build a panel: every filter needs a control, a piece of state, a server parameter
and a way to see what is currently applied, and for "which artists have the most tracks" all of that
is bought by a column header that already has a server implementation waiting.

**Replace the grid with the table.** Cheaper — one view instead of two, no toggle, no per-device
preference. Rejected because it is a regression for the half of the library that has artwork, and
because the grid is the surface the request explicitly said it liked. The measurement cuts both ways:
1,703 artists are well served by circles.

**Sort the loaded page on the device and skip the server work.** Rejected under `ADR-0021` point 3,
which was written about precisely this and is cited in point 2. Worth restating because it is the
tempting option: it looks correct while scrolling and is wrong at every page boundary.

**Add the columns to the grid instead — track and album counts under each tile.** Genuinely
considered, and it is the smallest possible change. Rejected because a grid cannot be sorted by
something it merely displays; the counts would be visible and still not answer "which are the
biggest", which is the question being asked.

**Do albums at the same time.** `AlbumsGridView` is the same component with the same shape, and
`list_albums` already takes `sort_by` with `name`, `year`, `track_count` and `artist` — so the second
one is nearly free once the first exists. Rejected only to keep this to one decision, per the
convention; it is recorded as a follow-up rather than as a future ADR, because it introduces nothing
new.

## Consequences

- **Positive** — two `ArtistSummary` fields that are computed on every request start being shown, and
  a `sort_by` parameter that has never had a caller starts having one.
- **Positive** — the artists with no artwork become browsable by something other than a placeholder.
- **Positive** — the pattern generalises to albums for almost nothing, since the endpoint is already
  there.
- **Tradeoff** — two views of one list is more code than one, and the toggle is a preference that has
  to live somewhere. Point 7 puts it on the device, which is the cheap answer and the right one.
- **Tradeoff** — `min_track_count` is a new server parameter, and the first filter is the one that
  makes the second easy to argue for. Point 4 is what should be cited when that argument is made.
- **Tradeoff** — sorting refetches from page 1, so changing sort on a long-scrolled list loses the
  scroll position. That is inherent to server-side sorting of a paged list and is the cost `ADR-0021`
  point 3 already accepted for tracks.
- **Follow-up** — `AlbumsGridView` takes the same toggle, with `name`, `year`, `track_count` and
  `artist` as its columns.
- **Follow-up** — `has_embeddings`, an existing parameter on the same endpoint, is also uncalled from
  Swift. It is a similarity-search filter rather than a browse control, so it is out of scope here,
  but it is on the list `ADR-0077` point 1 governs and should be either used or removed.
