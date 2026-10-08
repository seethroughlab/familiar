# ADR-0152: On the Phone, Search Belongs to the Screen

Status: accepted

Date: 2026-10-07

Implementation:
- Accepted 2026-10-07.

Supersedes points 1 and 2 of [ADR-0061](ADR-0061-the-phones-tabs-are-home-search-and-library.md).

## Context

ADR-0061 ratified three tabs, **Home, Search and Library**, on the grounds that "searching is a root
action, not a destination". The owner, using the phone while travelling on 2026-10-07, found two
things wrong with how that turned out:

- **The Search tab only searches tracks.** `phoneSearchRoot` (`familiar-apple`
  `App/Shared/LibraryView.swift:1059`) is the tracks list with `.searchable(prompt: "Search
  tracks")`. Looking for an artist there finds the artist's tracks, never the artist.
- **The phone already searches artists and albums, and nobody could find it.** The Library tab's
  section screens carry a field scoped to what they show — "Search artists", "Search albums",
  "Search tracks", "Filter playlists" (`searchPrompt`, `LibraryView.swift:2040`) — applied at
  `LibraryView.swift:735`. On this SDK the system puts that field at the **bottom** of the screen
  (noted at `LibraryView.swift:1548`), under the transport and beside a tab bar that has a
  magnifying glass of its own. A listener who wants to search reaches for that tab, and the tab
  searches something else.

So the phone has two searches with different scopes, and the visible one is the narrower one.
The owner's ask is the scoped one, made visible: **on the Artists screen you search artists, on
Albums you search albums.**

ADR-0061 point 5 requires an ADR for a navigation change on either client. Removing a tab is one.

## Decision

1. **Two tabs: Home and Library.** The Search tab is removed. This supersedes ADR-0061 points 1
   and 2. Its points 3 and 4 stand: the Library tab is `LibraryRootList`, unchanged.

2. **Every list screen's search field sits at the top**, under the title, always visible
   (`.searchable(placement: .navigationBarDrawer(displayMode: .always))`), and searches what that
   screen lists: Tracks searches tracks, Artists artists, Albums albums, Playlists and Smart
   Playlists filter by name. The scopes and prompts are the ones the screens already have; only the
   placement changes.

3. **Screens with nothing to search get no field**, as now: Home, Discover and Ambient
   (`isSearchable`, `LibraryView.swift:738`).

4. **The Mac is untouched.** Its sidebar and toolbar search already follow the selected section.

## Alternatives Considered

- **Keep the Search tab and make it search everything**: artists, albums and tracks in one list of
  results, the shape the Music app uses. It keeps ADR-0061's "root action" and needs no navigation
  change. Rejected for now: no endpoint answers all three (the only `/search` route, in
  `admin_artists.py`, finds artists for the admin tools), so it would be three requests merged on
  the device, ranked by nothing, and it would still leave a second, differently scoped field on
  every section screen. It could come back as its own ADR, and nothing here prevents it.
- **Keep the Search tab as it is and only move the section fields to the top.** The smallest change.
  Rejected: the phone would then show two magnifying glasses with different scopes on the same
  screen, which is the confusion that prompted this.
- **Make the Search tab open the Library section in use with its field focused.** One search,
  reached from the tab bar. Rejected: a tab that navigates another tab is a surprise, and on Home it
  would have to pick a section arbitrarily.

## Consequences

- **Positive:** one search per screen, where the eye goes, and its scope is the screen's title.
- **Positive:** artists and albums are searchable from where they are browsed, with no new endpoint.
- **Tradeoff:** searching for a track takes one more tap than today: Library, then Tracks.
  ADR-0061 argued that cost was worth a tab; this ADR argues the scoped field is worth more.
- **Tradeoff:** a field that is always visible takes a row of every list screen.
- **Follow-up:** the placement must be checked on an iOS 26 device, not only a simulator on an older
  runtime: iOS 26 moved search into the tab bar, and a simulator on 18.5 has hidden a bug that only
  existed on 26 before.
