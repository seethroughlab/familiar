# ADR-0153: Album and Artist Tables Keep Their Own Column Layout

Status: accepted

Date: 2026-10-20

Implementation:
- Accepted 2026-10-20. Built in `familiar-apple` #230: `TrackTableLayout` in FamiliarKit, the
  two keys and width caps in `TrackTable.swift`, the v2 migration in `FamiliarApp.init`.

Supersedes point 7's "one column preference across them" in
[ADR-0021](ADR-0021-track-lists-on-the-mac-are-sortable-tables.md), for the album and artist lists
only.

## Context

ADR-0021 point 7 gave every Mac track list one `TableColumnCustomization`, stored under one
`@AppStorage` key (`familiar.trackTable.columns.v2`, `familiar-apple/App/Shared/TrackTable.swift`),
so that turning on Year once turned it on everywhere. Its implementation record checked the risk it
saw — that a two-column album screen would empty the library's choice of columns — and found it did
not. **It checked visibility and not widths, and a customization holds both.**

A Mac table always fills its width. On an album page (`TrackListKind.album` fills `duration` and
`trackNum`, and `trackNum` opens hidden) the title is the only column that can grow, so it grows to
the window and that width is saved under the shared key. Favorites opens next with it. Reported on
2026-10-20: "every time I open my favorites, the Title column is taking up way too much width… the
next time I launch, it is back to the original super-wide Title column." The stored layout on that
Mac read `title` at `currentWidth: 943` and `album` at `391`, with Title, Added, Time, Artist,
Album and Year visible, in that order. Everything after Added was off the right edge of the
window, so the listener narrowed Title, visited an album, and got the wide width back.

The premise that one layout serves every list holds for **which** columns are shown and in what
order. It does not hold for width, because width depends on how many other columns share the row,
and that ranges from two to seventeen. `TableColumnCustomization` has no public API to store
visibility and width apart, so the split has to be between keys.

## Decision

1. **The album and artist lists keep their own column layout**, under
   `familiar.trackTable.columns.v3.entityPage`. Tracks, playlists, smart playlists, Favorites and
   Downloads keep sharing one, under `familiar.trackTable.columns.v3`, as point 7 intended. The
   mapping is `TrackListKind.tableLayout` in FamiliarKit, with tests.
2. **Outside an entity page, Title, Artist and Album are capped** — 520pt for the title, 360pt for
   artist and album — so a wider window shows more columns, not a longer title. On an album or
   artist page nothing is capped: the title has to fill the row, and a cap would leave a blank band
   at the right of every album.
3. **The v2 layout carries over without its widths.** At launch, before any table reads its key, the
   v2 value is copied to the v3 `lists` key with every `currentWidth` removed, and the v2 key is
   deleted. Chosen columns and order survive; every column reopens at its ideal width. The entity
   page starts fresh: every width in v2 is wrong for it, and it has four columns at most.

## Alternatives Considered

**One key per list.** Simplest, and every list would get exactly its own widths. Rejected because it
gives up the reason point 7 exists: Year turned on in Favorites would not appear in Tracks or a
playlist, and the column chooser would have to be visited seven times. The defect comes from the
lists with two to four columns, and only those need to move.

**Cap the title everywhere and keep one key.** It would stop Favorites inheriting a 943pt title
without splitting anything. Rejected because the cap that suits a ten-column list leaves an album
page with a short title and blank space where the rest of the row should be. The two screens need
different widths, and while they share a key, one of them always gets the wrong width.

**Bump the key to v3 and drop v2 entirely.** No dependence on the encoded shape. Rejected because it
forgets every column the listener turned on, which ADR-0021's own record already calls "the only way
this change is visible" when `.v2` did it once. Point 3 edits the JSON `TableColumnCustomization`
encodes, whose shape Apple does not document. If that shape changes, `currentWidth` is simply not
found and the layout is copied as it was: the old behaviour, not a worse one.

## Consequences

- **Positive:** a width chosen in Favorites stays chosen; visiting an album no longer resets it.
- **Positive:** a wide window spends its extra width on Artist and Album, not on the title.
- **Tradeoff:** a column turned on in an album or artist page no longer turns on in the other lists,
  and the reverse. The two entity pages share one layout with each other. Put to the listener on
  2026-10-20, who judged it the more intuitive behaviour, not merely an acceptable cost: an album
  page is a different kind of screen, and its columns are expected to be its own.
- **Tradeoff:** every saved width is forgotten once, at the first launch with this change.
- **Follow-up:** the migration in point 3 can be deleted, along with `legacyStorageKey`, once no
  build that wrote v2 is still offered.
