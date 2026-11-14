# ADR-0181: The Apps Show What's New

Status: accepted

Date: 2026-11-14

Extends [ADR-0179](ADR-0179-each-profile-has-a-whats-new-list-and-the-server-records-how-far-it-has-looked.md),
[ADR-0168](ADR-0168-a-server-names-what-it-can-do.md) and
[ADR-0177](ADR-0177-playlist-writes-from-mcp-notify-attached-clients.md)

Built second, with ADR-0179, as the first slice.

## Context

Discover in the iPhone and Mac apps is the server's `/embed` page in a web view
(`familiar-apple` `App/Shared/EmbeddedDiscoverView.swift`). The app knows nothing native about
what Discover holds, and nothing outside it says there is anything new:

- **The Discover rows carry no detail.** `LibrarySidebar.swift` (Mac) and `LibraryRootList.swift`
  (iPhone) give every row a `detail: String?` slot, used for counts on Favorites and Downloads and
  "Playing" on Ambient. Discover passes none.
- **Home has no new music.** It shows collections, recently heard albums and artists, and
  Rediscover, which is tracks already owned (`HomeView.swift`, `HomeStore.swift`).
- **The pieces this needs exist.**
  - ADR-0178's pattern: a pure decision in FamiliarKit (`ServerUpdateNotice.swift`), state in
    `ServerConfiguration`, and tests built from generated `Output` values with no socket.
  - ADR-0177's notice handling: `PlaybackCommand.decode` to `PlaybackCommandClient.apply` to an
    `InterfaceCommands` token that views watch.
  - An hourly iOS background refresh (`BackgroundRefresh.swift`).

## Decision

1. **The Discover row says what's new.** Mac and iPhone pass ADR-0179's `new_count` as the row's
   detail: "New" for one, "3 new" for more. With nothing new, or a server in state `never_run` or
   `disabled`, there is no detail.

2. **Home gains a "New releases" section.** Up to six of ADR-0179's items, each with its reason
   line and a Bandcamp link (ADR-0154: Familiar points to where music is sold and stops). The
   header opens Discover. With nothing to show, the section is absent rather than empty, as Home's
   other sections are.

3. **The decision is pure and in FamiliarKit.** `WhatsNew.swift` holds `marker(newCount:state:)`
   and the Home selection, tested without a server.

4. **The app refreshes what's new** on launch, on return to the foreground, in the iOS background
   refresh, and on ADR-0179's `whats_new_changed` notice. That notice is decoded beside
   `playlists_changed`, so a release seen on one device clears the marker on the others while they
   run.

5. **Opening Discover clears the marker at once on this device.** The `/embed` page records `seen`
   on the server (ADR-0179 point 5); the app does not write it a second time.

6. **An older server shows nothing.** The app asks only when the server advertises
   `discover.whats_new` (ADR-0168); a `ServerFeature` case maps to it. No "needs a newer server"
   message: nothing the listener chose is missing.

## Alternatives Considered

**A banner above the library, like ADR-0178's update notice.** Rejected: the banner stack shows only
on the Tracks list (`LibraryView.tracksList`), so the listener would rarely see it, and it would
compete with messages about the server. A marker on Discover and a Home section are where someone
looking for music already is.

**Show new releases natively instead of in Discover.** Rejected as the primary surface: Discover
is the one destination for finding music (ADR-0101 point 5), and a second native list would drift
from it. Home shows a few and sends the listener to Discover for the rest.

**A badge on the app icon or dock.** Rejected: a number on the icon reads as obligations, the
opposite of an invitation, and the iPhone app has no badge permission today.

## Consequences

- **Positive:** the listener sees new music where they already look, and the reminder clears
  everywhere once they have looked anywhere.
- **Tradeoff:** a release seen on the phone still shows on a Mac that is not running until the Mac
  next refreshes; the notice only reaches running apps.
- **Tradeoff:** the app now calls one more endpoint on launch and foreground.
- **Follow-up:** ADR-0182 turns the same list into a weekly notification.
