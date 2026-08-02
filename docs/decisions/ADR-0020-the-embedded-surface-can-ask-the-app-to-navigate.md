# ADR-0020: The Embedded Surface Can Ask the App to Navigate

Status: accepted

Date: 2026-08-02

Extends [ADR-0016](ADR-0016-embedded-web-surfaces-on-the-mac.md) and
[ADR-0017](ADR-0017-the-embedded-surface-gets-a-null-audio-engine.md).

Implementation:
- Accepted 2026-08-02. Page half on `familiar` #73, native half on `familiar-apple` #49. Artist and
  album links open the app's own screens; confirmed working in use.
- **Point 5's "a missed intent must be inert" was tested for real, by a miss.** `EmbedDiscover`
  wired the bridge to the `onPlayTrack` prop, and `DiscoverTrackList` never calls it — it drives
  `usePlayerStore.setQueueByTrackId` directly. So pressing a track in "Unheard in Your Library"
  posted nothing, and the null engine correctly made no sound. The failure was silent rather than
  loud, exactly as designed; what was missing is that nothing told the page, so the row spun
  forever. Fixed in `familiar` #74 by intercepting at the store — where every play path converges —
  rather than at a prop that can be missed.
- Purchase links opened nothing until `familiar-apple` #52: `target="_blank"` needs a `WKUIDelegate`
  and there was none. That fix also added a navigation policy, without which an external link with
  no target would have navigated the embed itself away with no way back.
- Point 4's excluded targets (year, genre, mood) remain inert, as decided.

## Context

Embedded Discover shipped with every link in it dead. Tapping an artist, an album or "See all" does
nothing at all — not an error, not a wrong screen, nothing. It was reported twice from use before
being decided, which is the honest reason this ADR exists.

That was deliberate, and recorded at the time.
[ADR-0017](ADR-0017-the-embedded-surface-gets-a-null-audio-engine.md)'s final follow-up says:
*"Decide what an embedded surface does with navigation inside it — an artist link in Discover
currently goes nowhere on either platform, because `EmbedDiscover` supplies no-op handlers and the
embed router returns to Discover."* This is that decision.

**The rule being amended, and why it was right to begin with.**
[ADR-0016](ADR-0016-embedded-web-surfaces-on-the-mac.md) point 5:

> The bridge is one-way and narrow: the page posts an intent — play these track ids, starting at
> this one — and the native side owns the queue, the playback and the reporting.

and in its consequences:

> **Tradeoff:** The bridge is a new seam between two clients that were previously independent, and a
> web-app change could break the native app through it. It should be narrow enough — one message
> shape — that this stays unlikely.

That reasoning holds. The seam is the main risk of embedding, and every message added is surface a
web-app change can break the native app through. So this widens it by exactly one, and says what the
bar is for a third.

**What makes navigation different from the other things the page could ask for.** The native app
already has artist and album screens, reached from four other places, and they are better than the
web equivalents would be inside a web view — native scrolling, native context menus, artwork from
the same cache the rest of the app uses. Discover's links are the only route into them that does not
work. So this is not new capability; it is connecting a surface that was left unconnected.

The alternative shape — rendering artist and album routes *inside* the embed — is what
ADR-0017 point 1 rejected in a different guise. It rejected "the full web app with its chrome
hidden" because hiding is not preventing; growing the embed one route at a time arrives at the same
place more slowly, and each route added is another chance for a play affordance to appear on a
surface whose engine is deliberately null.

**A constraint the native side already carries.** Albums and artists are addressed *by name*,
because that is what the API offers. Names containing a slash cannot be addressed at all — there are
**79 such artists** in this library (`backend/app/main.py:546`), and `BrowseDetailView` already
degrades to a filtered track list for them rather than failing. Navigation from the embed inherits
that behaviour rather than inventing a second answer to it.

## Decision

1. **The bridge carries a second message: `navigate`.** The page posts an intent to open an artist
   or an album; the native app pushes its own screen for it. The bridge stays one-way — nothing is
   sent back, and the web view is never told what the app is showing.

2. **Two messages is the cap until an ADR says otherwise.** ADR-0016 point 5's argument is unchanged
   and this is not a licence to grow. A third message needs a decision of its own, and the test it
   must pass is the one in point 3.

3. **The bar for a message is: the native app already does this better, and the page cannot.**
   Navigation clears it — the artist screen exists, is native, and Discover cannot reach it. A
   message that merely saves the page some work does not clear it.

4. **Navigation targets are limited to artist and album.** They are what Discover links to, they are
   what the native app has screens for, and they are addressed by name through paths the app already
   uses. Anything else — a playlist, a settings pane, an external URL — is out of scope and would
   need point 3 applied again.

5. **An unroutable name degrades rather than fails.** A name the path-keyed API cannot address
   already lands on a filtered track list with a note saying so; navigation from the embed reaches
   the same place. It does not silently do nothing, which is the behaviour this ADR exists to end.

6. **The page keeps no navigation state.** It does not know whether the app honoured the intent, and
   it does not change what it shows. There is one navigation stack and it is the app's, exactly as
   there is one queue.

7. **Both platforms, once each has the surface.** This is a property of the bridge rather than of a
   window, so it applies to the Mac now and to the phone if
   [ADR-0019](ADR-0019-the-embedded-surface-comes-to-the-phone.md) is accepted.

## Alternatives Considered

**Render artist and album routes inside the embed.** No bridge change, no native work, and the links
would work today. Rejected as ADR-0017 point 1's rejection arriving by instalments: it rejected the
full app with its chrome hidden because hiding is not preventing, and adding routes one at a time
reaches the same surface area with the same hazard — a play affordance on a page whose engine is
deliberately null. It would also give the app two artist screens that drift.

**Leave the links dead and remove them from the embedded page.** Honest, and cheaper than either
alternative: a surface with no links cannot have broken ones. Rejected because the links are most of
what Discover *is* — a recommendation you cannot open is a poster, not a discovery surface — and
because stripping them means a purpose-built variant of the page, which is the maintenance cost
ADR-0016 embedded Discover to avoid.

**Open the artist in the default browser.** Trivial, no bridge. Rejected for the reason ADR-0016
rejected it for Discover itself: leaving the app is the friction ADR-0013 exists to remove, and it
is worse from a screen already inside the app.

**Make the bridge generic — let the page post any route and have the app interpret it.** One message
forever, no future ADRs about a third. Rejected because it inverts the seam: an open-ended route
string means the web app decides what the native app can be asked to do, and a typo becomes a silent
no-op on a client that cannot be debugged from the page. Two named intents can be exhaustively
handled in Swift and tested; a route string cannot.

## Consequences

- **Positive:** Discover's links work, and land on native screens rather than web ones — the artist
  page you reach from a recommendation is the same one you reach from the library.
- **Positive:** The embed stays a single screen. Nothing about the null engine or the browse-only
  rule is weakened, because navigation leaves the web view rather than deepening it.
- **Positive:** There is now a stated bar for a third message, instead of a precedent that the
  bridge grows whenever something is inconvenient.
- **Tradeoff:** The seam ADR-0016 named as embedding's main risk is twice as wide. Two shapes to
  keep in step across a TypeScript half and a Swift half that no compiler checks against each other.
- **Tradeoff:** A link that lands on a degraded track list, for one of the 79 slash-named artists,
  looks like a worse result than the web app would give — the web app has the same limitation but
  reaches it by a different route.
- **Follow-up:** Decide what "See all" should do. It is a link to a *list* rather than to an entity,
  and the native app has no screen for "all new releases" — so it is out of scope here and is the
  most likely candidate for testing point 3 in earnest.
