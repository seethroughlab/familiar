# ADR-0018: The Phone Navigates From a Root List

Status: accepted

Date: 2026-08-02

Extends [ADR-0012](ADR-0012-favorites-are-a-collection-not-a-library-section.md) and
[ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md).

Implementation:
- Accepted 2026-08-02, shipped on `familiar-apple` `feat/phone-root-list` (#44) and confirmed on the
  device. `LibraryRoot` gained a `.menu` case rather than the view gaining a `Bool` — and the
  exhaustive `switch` earned its keep, breaking both macOS branches at compile time instead of
  silently rendering the wrong column.
- Point 3's counts arrive only once a section's store has loaded, so the list is sparser on a cold
  launch than a minute later. Judged acceptable in use; a placeholder read worse.
- Playlists shows no count: that endpoint returns them all rather than paging, so there is no total
  to display without counting the list.
- Point 5's cost — a tap to reach Tracks — was accepted in use rather than merely on paper. Its
  follow-up (remembering the last destination) is still open.
- The Collections screen went with it, as point 4 anticipated. `collectionsSummary` was deleted in
  the same change.

## Context

The phone reaches its destinations three different ways, and which way depends on an argument nobody
using it can see.

| destination | how it is reached today |
|---|---|
| Tracks, Albums, Artists, Playlists | a segmented picker across the top |
| Favorites, Downloads | a toolbar button opening `CollectionsView`, which lists both and pushes one |
| Discover | not on the phone at all |

Each of those was decided well on its own. Together they are three mechanisms for one question —
*what am I looking at?* — and the reasons they differ are historical rather than legible.

**The picker's four segments are a hard ceiling, and that is the load-bearing constraint.**
[ADR-0012](ADR-0012-favorites-are-a-collection-not-a-library-section.md) point 1 measured it: a fifth
segment leaves each about 70pt on a 393pt phone, "which is where the labels abbreviate". So anything
new has to go somewhere else, and everything new has. That is why there are three mechanisms.

**ADR-0012 point 1 already argued for what this proposes, and could not have it.** Its own words, on
why the Collections grouping cost a tap:

> a toolbar button cannot show a number, and the number is what makes them read as collections
> rather than as actions. A sidebar row *can* show one

The Mac later proved that out — `LibrarySidebar` lists Favorites and Downloads with their counts
beside them, and ADR-0012's note says that is "what that decision wanted in the first place". The
phone kept the extra screen only because it had no row to put a number on. A root list is that row.

Measured against the live library on 2026-08-02: **26,396 tracks, 3,925 albums, 3,475 artists, 1,720
favorites.** Downloads is per-device and has no server-side figure.

**What this is not.** [ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md) point 2 says "iOS
stays the listening path. The phone is not a management client." Nothing here changes that. Every
destination below is a way of finding something to play; the management surfaces — smart playlists,
pending review, proposed changes, mixtapes — stay off the phone, and this ADR does not touch them.
Discover is discovery, not management, and ADR-0013 point 3 put it "in scope for the Mac" as a way of
scoping a body of work rather than as a ruling about where it may ever appear.

**The platform constraint.** iOS 15 is the floor (`Package.swift`), so `NavigationSplitView` does not
exist and neither does the `Layout` protocol. A root list needs neither: it is a `List` of rows that
push, which iOS has always had, and it is what `CollectionsView` already does for two of these
destinations.

## Decision

1. **The phone's browse column is rooted on a single list of destinations**, replacing the segmented
   picker and the Collections screen. One mechanism, one place to look, in the order the Mac sidebar
   uses so the two clients do not describe the same library differently.

2. **The list is grouped, not flat.** Library — Tracks, Albums, Artists, Playlists, Discover — then
   Collection: Favorites and Downloads. The grouping is the substance of ADR-0012 point 1 and it
   survives intact; only the extra screen goes.

3. **Rows carry their counts**, which is the thing ADR-0012 point 1 wanted and could not have from a
   toolbar button. Favorites shows its total, Downloads shows its size on this device.

4. **This changes where ADR-0012 point 1's entry lives, and not what it decided.** Favorites and
   Downloads remain one group, still not segments of a browse picker, still per-profile and
   per-device respectively. They are simply reached from a row instead of from a button and a screen.

5. **It costs a tap to reach Tracks, and that is the price.** The picker put four lists one tap away
   and everything else two or more; this puts everything at one. The library list is no longer the
   thing you land on, and for a phone whose most common action is "play something I already know"
   that is a real cost, accepted for a navigation that holds more than four things.

6. **The management surfaces stay off the phone**, per ADR-0013 point 2, which this does not
   reverse. If they ever arrive they need their own decision, and the list having room for them is
   not an argument that they should.

7. **macOS is untouched.** It already has this shape in `LibrarySidebar`, and a 200pt column beside
   the content is the right form there. This is the phone adopting the Mac's *arrangement*, not its
   layout.

## Alternatives Considered

**A menu button in the toolbar.** Keeps the phone landing directly on a browse list — no tap
added — and switches the column in place with no back stack. Rejected because it hides the map of the
app behind a press: the thing being fixed is that a listener cannot see what the phone can show them,
and a menu that must be opened to be read does not fix it. It also reproduces the counts problem,
since a button still cannot show a number.

**A fifth and sixth segment on the picker.** The smallest change, and no new screen. Rejected on the
measurement ADR-0012 point 1 already made: at six segments each gets about 47pt on a 393pt phone,
which is not a label but an abbreviation of one. The picker's ceiling is why there are three
mechanisms, so raising the ceiling is not available.

**A sidebar that slides over from the edge.** Closest to the Mac visually, and keeps the browse list
as the landing screen. Rejected on cost and fit: iOS 15 has no drawer, so it is a hand-built overlay
plus a gesture that competes with the system's own interactive back-swipe — and a drawer is a desktop
idiom borrowed onto a phone, where the platform's own answer to "many destinations" is a list you push
from.

**A tab bar.** The most conventional iOS answer, and the one Apple Music uses. Rejected because it has
the same ceiling as the picker — five tabs before it collapses into "More" — and this exists to hold
seven destinations now and more later. It would also be a third arrangement, agreeing with neither the
picker it replaces nor the Mac.

**Leave it alone.** The three mechanisms each have a good reason and nothing is broken. Rejected
because the reasons are invisible from inside the app: what a listener sees is that some destinations
are segments, one is a button, and Discover is missing — and no amount of individually-sound
reasoning makes that read as designed.

## Consequences

- **Positive:** One mechanism instead of three, and one that has room. A new destination is a row
  rather than an argument about which of three places it belongs in.
- **Positive:** Favorites and Downloads get their counts on the phone, which ADR-0012 point 1 wanted
  and could not reach. The extra screen it accepted as the price is no longer needed.
- **Positive:** The two clients describe the same library the same way, so a listener moving between
  them is not learning a second arrangement.
- **Tradeoff:** Tracks costs a tap it did not cost before, on the platform where that list is most
  often what someone wants. Named in point 5 rather than discovered later.
- **Tradeoff:** `CollectionsView` loses its reason to exist on the phone and should go with it, rather
  than lingering as a second way into two screens.
- **Follow-up:** Decide whether the root list should remember and restore the last destination, which
  would recover most of point 5's cost. Deliberately not decided here: it interacts with state
  restoration and with the adopted queue (ADR-0003), and it is a smaller question that reads better
  against a shipped list than against a description of one.
- **Follow-up:** Discover's row depends on
  [ADR-0019](ADR-0019-the-embedded-surface-comes-to-the-phone.md). The list ships without it if that
  is not accepted; the row simply arrives later.
