# ADR-0042: The Phone Gets a Persistent Tab Bar

Status: accepted

Date: 2026-08-07

Supersedes [ADR-0018](ADR-0018-the-phone-navigates-from-a-root-list.md) points 1 and 5.
Extends [ADR-0032](ADR-0032-the-apple-clients-get-a-home-destination.md).

## Context

**The phone's main navigation is a small text link, and it is only on some screens.** Reaching
Artists means: leave whatever you are on, find `Label("Library", systemImage: "chevron.left")` at
`.font(.subheadline)` in a hand-rolled row, tap it, then tap Artists. Reported as *"it should be
always available and obvious since it's the main navigation"*, which is exactly right — nothing
about a subheadline-sized back link says "this is how you get everywhere".

ADR-0032 made this worse before it made it better. Home is now the landing screen, so the root list
that used to *be* the root is one row further down, behind a Library row that ADR-0032's own
Implementation block calls an interim. That row is the whole of this ADR's prompt.

**ADR-0018 saw this cost and accepted it, in writing.** Its point 5:

> **It costs a tap to reach Tracks, and that is the price.** The picker put four lists one tap away
> and everything else two or more; this puts everything at one. The library list is no longer the
> thing you land on, and for a phone whose most common action is "play something I already know"
> that is a real cost, accepted for a navigation that holds more than four things.

The prediction was right and the trade has not held up in use. It is now two taps rather than one,
and the thing standing in for a navigation is a back button.

**A premise underneath both ADR-0018 and the routing model has expired, and nothing noticed.**
`App/Shared/LibraryView.swift:11` and `Sources/FamiliarKit/LibraryRouting.swift:5` still say:

> iOS 15 is the floor (`Package.swift`), so `NavigationStack` and `NavigationSplitView` are both
> unavailable … One switcher that behaves identically on both platforms is the only shape that does
> not need two implementations.

**The floor has been iOS 17 since [ADR-0023](ADR-0023-the-phone-moves-to-ios-17.md)**
(`Package.swift` declares `.iOS(.v17)`; the project sets `IPHONEOS_DEPLOYMENT_TARGET = 17.0`), and
the phone already has a real `NavigationStack` — ADR-0023's follow-up, shipped in `familiar-apple`
#58. So the constraint that argued for "one switcher on both platforms" is gone, and has been for
weeks, in comments that still assert it. ADR-0018's conclusion was not *only* a constraint
argument — points 2 and 3 stand on their own merits — but the part of it that ruled out a
platform-shaped navigation no longer applies.

**The web app answers this with a bottom tab bar**, and has all along:
`components/MobileNav/MobileBottomNav.tsx` carries Home, Artists, Favorites, Chat and More, where
More opens a sheet holding Tracks, Albums, Music Map, Discover, Changes, Downloads and Settings.
That is the arrangement being asked for, and copying its *shape* while choosing our own contents is
the same move ADR-0018 made when the phone adopted the Mac's arrangement rather than its layout.

**ADR-0018 rejected a tab bar by name, and that rejection has to be answered rather than stepped
around.** Its Alternatives say:

> **A tab bar.** The most conventional iOS answer, and the one Apple Music uses. Rejected because it
> has the same ceiling as the picker — five tabs before it collapses into "More" — and this exists to
> hold seven destinations now and more later. It would also be a third arrangement, agreeing with
> neither the picker it replaces nor the Mac.

Both halves are addressed, and neither by disagreeing with the reasoning as it stood.

The ceiling is real and is **not a failure mode — it is the design**. "Collapses into More" describes
the web app, which has shipped `Home / Artists / Favorites / Chat / More` with seven destinations
behind More for as long as the phone has had a picker. A tab bar does not stop working at five; it
stops putting things one tap away at five, which is the same trade every navigation makes and one
this ADR takes deliberately — four tabs for the destinations that earn a permanent slot, the
remaining seven one tap deeper, in the list ADR-0018 designed and point 3 keeps intact. The picker's
ceiling was different in kind: it had no More, so a destination that did not fit was simply absent,
which is why Discover was missing.

The "third arrangement" objection has since dissolved on its own. It was written when the phone's
picker and the Mac's sidebar were the only two arrangements and the iOS 15 floor made a third
expensive. The floor is 17, the web app's tab bar is the arrangement a listener most likely already
knows, and after this there are two: a sidebar on the Mac and a tab bar everywhere else. That is
fewer than today, not more.

## Decision

1. **The phone's root is a `TabView`, always visible, on every screen.** This supersedes ADR-0018
   point 1's "rooted on a single list of destinations" and point 5's acceptance of the extra tap.
   Everything else ADR-0018 decided survives — see point 4.

2. **Four tabs: Home, Tracks, Favorites, More.** Tracks rather than the web's Artists, because it is
   this app's main list and the one point 5 admitted the change had cost. No Chat tab: ADR-0022
   built chat as a destination and it stays one, which also respects that chat is a lower priority
   here than analysis-driven playlists.

3. **More is ADR-0018's root list, unchanged.** Not a new screen and not a sheet of links —
   `LibraryRootList` becomes the More tab's content, keeping its grouping (point 2), its counts
   (point 3) and its ADR-0012 point 1 collection group exactly as they are. **This is what makes
   the supersession partial rather than total**: the list stops being the root and stays the way
   every destination beyond the three promoted ones is reached.

4. **ADR-0018 points 2, 3, 4, 6 and 7 are untouched.** The grouping, the counts, where ADR-0012's
   entry lives, management surfaces staying off the phone, and macOS being left alone. Only *where
   the list sits* changes.

5. **Each tab owns its own navigation stack.** Switching tabs and coming back returns you to the
   depth you left, which is the behaviour a tab bar promises and the reason it is not merely a
   picker. `LibraryView`'s single `[BrowseRoute]` becomes one path per tab.

6. **The transport sits above the tab bar, outside every tab's stack.** `NowPlayingBar` is currently
   a sibling of the `NavigationStack` inside `mainColumn`, for the reason recorded there — a stack
   replaces its content when it pushes, so a transport inside one vanishes the moment you open an
   album. The same hazard applies per tab and the same answer works: attach it to the `TabView`
   rather than to any tab. Two stacked bars is what every music app on the platform does.

7. **The tab bar is not a second `LibraryRoot`.** Which tab is showing and what that tab is rooted
   on are different questions, and `LibraryRouting.swift` exists because the app once answered a
   question like this with a pile of booleans. The selected tab is its own value; `LibraryRoot`
   keeps meaning what the *column* is rooted on.

8. **macOS is untouched**, as in ADR-0018 point 7. Its sidebar is already always-visible and
   obvious, which is the property this ADR is buying for the phone.

9. **The two stale comments are corrected as part of this**, not left for someone to trip over. A
   comment asserting an iOS 15 floor in an iOS 17 app is worse than no comment: it is a reason not to
   try something, and the reason is no longer true.

## Alternatives Considered

**Keep the root list and make the Library affordance bigger.** The cheapest thing that answers the
literal complaint — a real toolbar button with an icon instead of a subheadline text link, on every
screen. Rejected because it fixes the *obvious* half and not the *always available* half: it is
still a control that takes you to a screen that takes you to a destination, which is two taps to
Artists no matter how large the first one is. It also reintroduces exactly what ADR-0018 deleted, a
chrome control as a second way of getting somewhere.

**Make Home itself the navigation — put every destination on it as a row.** No new mechanism at all,
and ADR-0032 point 6 already licenses changing the row set. Rejected because it makes Home two
things at once: a screen whose rows start music (ADR-0032 point 3) and a list whose rows open
screens. That is the "two mechanisms wearing one appearance" ADR-0032's own Alternatives rejected
when it declined to put play actions into the root list, and it reads the same way from the other
side.

**A `NavigationSplitView`, now that iOS 17 allows it.** The Mac's shape on the phone, and it would
make the two clients genuinely one implementation — which is what the expired premise wished for.
Rejected because on a 393pt phone a split view collapses to a stack with a hamburger, which is a
worse version of the button this ADR is removing. The Mac's arrangement is right on the Mac because
the sidebar is *simultaneously* visible; on a phone only a tab bar achieves that.

**Five tabs, adding Downloads.** Genuinely tempting: Downloads is the one surface that works with no
server, which is the situation a phone most often meets, and `CarPlayBridge` already puts it first
among the collections for that exact reason. Rejected on width — four tabs plus a transport bar is
already two rows of chrome on a small screen — and because Downloads is one row down in More rather
than absent. Worth revisiting if the offline path becomes the common one.

**Do nothing until the tab bar can be measured against real use.** Defensible: ADR-0018's point 5
was also a considered judgement and it was wrong, which is an argument for humility about this one
too. Rejected because the evidence is already in — the person who built the app cannot find its
navigation — and because ADR-0018's price was accepted on a phone that then gained Discover, Chat,
Settings and Home. A list that grew from six rows to ten is a different thing from the one that was
judged.

## Consequences

- **Positive.** The main navigation is visible from every screen, which is the whole ask. Tracks,
  Favorites and Home go from two taps to one.
- **Positive.** Each tab keeping its own stack means leaving an album to check something and coming
  back no longer loses your place — a thing the single shared `[BrowseRoute]` cannot express.
- **Positive.** The phone and the web app finally describe themselves the same way, which ADR-0018
  wanted for the phone and the Mac and could not have for the phone and the browser.
- **Positive.** Two comments asserting a constraint that expired weeks ago stop being read as fact.
- **Tradeoff.** **Two bars of chrome at the bottom of a 393pt phone.** The transport plus a tab bar
  is roughly 130pt of a 852pt screen. Every major music app makes this trade; it is still a real
  cost on the smallest supported device, and the transport has already been through one round of
  height-tuning for exactly this reason.
- **Tradeoff.** ADR-0018 point 1's "one mechanism, one place to look" is genuinely weakened. There
  will be two ways to reach Tracks — the tab and the More list — and two ways to reach anything is
  the shape that ADR's whole argument was against.
- **Tradeoff.** Per-tab stacks mean `LibraryView`'s navigation state stops being one value. That
  file's own doc comment records what a pile of independent navigation state cost last time, and
  this reintroduces a bounded amount of it deliberately.
- **Follow-up.** The Library row on Home becomes redundant once More exists and should be removed in
  the same change, or Home will offer a route to a list that is already permanently on screen.
- **Follow-up.** `LibraryRoot.menu` becomes the More tab's root rather than a phone landing state.
  Whether it still earns a case, or whether More is simply a tab whose content is `LibraryRootList`,
  is an implementation question this ADR does not settle.
- **Follow-up.** CarPlay has its own tab bar built from `CarPlayBrowse`, with Queue, Downloads and
  Favorites. It is unaffected, but the two are now the same kind of thing on the same device and
  should probably agree about what belongs at the top level.
