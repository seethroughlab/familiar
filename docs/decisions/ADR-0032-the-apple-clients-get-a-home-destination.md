# ADR-0032: The Apple Clients Get a Home Destination

Status: proposed

Date: 2026-08-06

Extends [ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md) and
[ADR-0018](ADR-0018-the-phone-navigates-from-a-root-list.md).

## Context

There is no `Home` anywhere in the Swift app. The phone opens on
`LibraryNavigation.phone`, which is `LibraryNavigation(root: .menu)` — the root list of
destinations [ADR-0018](ADR-0018-the-phone-navigates-from-a-root-list.md) built. The Mac opens on
the Tracks table. Both are indexes: places to *find* something, with nothing on them that starts
anything.

The web app has had an answer since April. `packages/frontend/src/components/Home/HomeScreen.tsx`
is the index route — `App.tsx` redirects both `index` and `*` to `/home` — and
`docs/ENTRY-EXPERIENCE.md` is a full purpose document for it, opening with the aim of *"a single
coherent entry experience instead of treating the home screen and chat onramp as separate ideas."*
**That document is not an ADR**, which is why this one exists: the Apple clients cannot inherit a
decision that was never recorded as one.

**The first instinct was to embed it, and it is worth writing down why that loses**, because
Discover is embedded and the two look like the same kind of screen.

[ADR-0016](ADR-0016-embedded-web-surfaces-on-the-mac.md) point 1's test is churn and size. All
three rows re-measured 2026-08-06, so the comparison is like for like:

| surface | lines | files | commits, 6 months | ADR-0016 put it |
|---|---|---|---|---|
| Discover | 3,020 | 27 | 14 | embedded |
| Music Map | 720 | 1 | 2 | native |
| **Home** | **650** (+ `stores/homeStore.ts`, 177) | **1** | **4** | — |

ADR-0016 measured Discover at 2,943 across 26 files and the map at 690 in one; both have grown
slightly and the conclusion is unchanged. Home sits on the Music Map's side of that line, not
Discover's, and by a wide margin on both axes.

Three things settle it beyond the measurement:

1. **The bridge cannot address what Home links to.** Home's Quick Picks and library shortcuts point
   at Favorites, Downloads, Tracks, Artists, Albums, Music Map and Playlists.
   [ADR-0020](ADR-0020-the-embedded-surface-can-ask-the-app-to-navigate.md) point 1 carries artist
   and album and nothing else, and point 2 caps the bridge at two messages until an ADR says
   otherwise. An embedded Home needs a third message on its first day and a fourth soon after — and
   ADR-0020 point 4 already ruled year, genre and mood out of scope for exactly this reason.

2. **Home is the root, and the root has to work offline.** ADR-0016 point 7 says an embedded
   surface with no server shows a native "unavailable" state, and `EmbeddedDiscoverView` phrases it
   as *"You're offline. This is the one screen here that has no offline version."* That sentence is
   tolerable about Discover. As the first thing seen on every launch it contradicts
   [ADR-0028](ADR-0028-the-apple-clients-playback-session-is-local.md), whose whole point is that
   the app reopens on what it was playing with no network involved.

3. **Embedding would buy no reuse where it matters.** The web Home *starts nothing*. Its Quick
   Picks are `<Link>`s; nothing on it launches weighted shuffle, radio or ambient. What is being
   asked for here is quick links to **play options**, which is new work on either side of the
   embed/native line. Embedding a screen to reuse the half that is not wanted is not a saving.

**What the web version has that this deliberately will not take.** `homeStore.ts` keeps
per-profile module preferences — show, hide, reorder — behind a "Customize" panel, plus a recents
list. That is listener preference state, and
[ADR-0029](ADR-0029-the-server-stores-no-listener-preferences.md) says the server stores none, so
on the Apple side it would be a third local preference store standing beside the playback session
and the shuffle modes. For a screen with six rows, that is machinery in search of a problem.

## Decision

1. **Home is a native destination**, by ADR-0016 point 1's own test applied to a third surface. This
   is an application of an existing rule, not a new one — the rule was written to be reused, and
   650 lines in one file with 4 commits in six months is the settled end of it.

2. **Home is the landing root on both platforms.** `LibraryNavigation.phone` becomes
   `LibraryNavigation(root: .home)` and the Mac's initial sidebar selection becomes Home. ADR-0018
   is not reversed: the phone's root list survives intact as a destination reached *from* Home, and
   it remains the one mechanism by which every other destination is reached.

3. **Home's rows start playback. They are not links.** This is where the Apple version diverges
   from the web version rather than porting it, and the divergence is the feature. A row that
   navigates somewhere you must then press play on is the screen the app already has.

4. **The rows are: Resume, Shuffle Everything, the weighted presets, Favorites, Downloads.** Resume
   restores from ADR-0028's local snapshot and needs no network. Shuffle Everything is
   `LibraryView.shuffleLibrary()`, which exists today and is reachable only from a button on the
   phone's Tracks list. The weighted presets arrive with
   [ADR-0035](ADR-0035-weighted-shuffle-is-a-preset-the-server-applies.md) and are absent until it
   lands.

5. **A row whose destination is not reachable is absent, not disabled and not failing.** This is
   ADR-0022 point 3's rule — the chat destination is absent when no provider is configured — applied
   again, and it is the correction for the three defects
   [ADR-0017](ADR-0017-the-embedded-surface-gets-a-null-audio-engine.md) records: an affordance
   whose destination is not mounted, failing silently. Offline, the server-backed rows are gone and
   Resume, Favorites and Downloads remain.

6. **No customise panel, no reorder, no per-profile module preferences.** Rejected for the reason in
   the Context: it is a third preference store for six rows. If the row set turns out to be wrong,
   the fix is a different row set.

7. **The routing change goes through `LibraryRouting.swift` and nowhere else.** `case home` is added
   to `SidebarItem` and `LibraryRoot`; `LibraryRoot.init(selecting:)` and `sidebarItem(section:)`
   then fail to compile until handled, as do the deliberately-exhaustive switches in `LibraryView`
   (`:405`, `:438`, `:1151`). That file's doc comment already argues that adding a destination
   anywhere else is how a defect got in, and this ADR takes it at its word.

## Alternatives Considered

**Embed Home in a `WKWebView`, as Discover is.** The fastest route, it stays current with the web
app for free, and it is what the request first described. Rejected on the three grounds in the
Context, of which the second is decisive: an embedded root means the first screen of every offline
launch is an "unavailable" state, in an app that
[ADR-0009](ADR-0009-offline-downloads-are-background-transfers.md) and ADR-0028 both went to
considerable trouble to make work with no server. The bridge arithmetic is the second: seven
destinations that the two permitted messages cannot address, on a screen that is mostly those
destinations.

**Put the quick-play rows into the existing root list instead of adding a screen.** Cheapest
possible version — no new destination, no routing change, five rows added to
`LibraryRootList.swift`. Rejected because the list is a navigation index and this would mix verbs
into it: a list where "Albums" takes you somewhere and "Shuffle Everything" starts music is two
mechanisms wearing one appearance, which is the confusion ADR-0018 removed three mechanisms to
end. It also has no answer for the Mac, whose sidebar is the same index.

**Hybrid: a native shell with the web app's Discovery module embedded inside it.** Keeps the
offline shell alive while reusing the churniest three columns — recommended artists, unheard
tracks, deep cuts. Rejected because it costs a second embedded document, a second surface marker
(`EmbedIntent.surfaceMarker` is a single value, `"embed"`), and a second `WKWebView` host, all for
three rows whose data comes from `/library/discover` through the generated client anyway. The
embed machinery is justified by 2,943 lines, not by three rows.

**Port the web Home faithfully, modules and customise panel included.** Consistency across
clients, and no decisions to make. Rejected because it ports the part that does not work — a home
screen with no play actions — and adds a preference store to do it. Consistency is worth less than
the screen being good, and the two clients already differ where it matters (ADR-0028 gave the
Apple clients a local session the web app does not have).

## Consequences

- **Positive.** The app opens on something that starts music. Resume, which ADR-0028 built and
  which currently has no affordance beyond the transport, finally has a surface.
- **Positive.** `shuffleLibrary()` stops being reachable only from a button on one list on one
  platform.
- **Positive.** The embed/native test has now been applied three times with three different
  outcomes, which is what ADR-0016 point 1 was written to allow.
- **Tradeoff.** The two clients' home screens diverge on purpose: the web app's navigates, the
  Apple app's plays. Anyone comparing them will find the same name over different screens, and this
  ADR is the only place that says why.
- **Tradeoff.** Every destination now has one more tap in front of it on the phone, because the
  root list moved down a level. That is the cost of point 2 and it is real for anyone whose habit
  is Library → Artists.
- **Follow-up.** `docs/ENTRY-EXPERIENCE.md` describes a screen only one client has, and now
  describes it incompletely for that one. It should either be widened to both or scoped to the web
  app in its own first paragraph.
- **Follow-up.** The web Home's Prompt Onramp is hidden when `chatSurfaceAvailable` is false, citing
  ADR-0022 point 3. If a prompts row is ever wanted here, `/library/discover/prompts` carries the
  `library` tag and is already generated — the route the phone's chat empty state already takes.
