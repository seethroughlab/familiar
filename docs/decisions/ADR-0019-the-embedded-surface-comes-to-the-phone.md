# ADR-0019: The Embedded Surface Comes to the Phone

Status: accepted

Date: 2026-08-02

Extends [ADR-0016](ADR-0016-embedded-web-surfaces-on-the-mac.md) and
[ADR-0017](ADR-0017-the-embedded-surface-gets-a-null-audio-engine.md).

Implementation:
- Accepted 2026-08-02, shipped on `familiar-apple` `feat/embed-discover-phone`. Point 3 held: the
  representable was the only new code of substance. `EmbedIntent`, the marker check and the
  navigation policy were already in shared code, so the phone inherited the fixes the Mac had just
  been through — including the two the Mac found the hard way, a bridge wired to a prop nothing
  called and `target="_blank"` links with no `WKUIDelegate`.
- The two platform halves are a `UIViewRepresentable` beside the `NSViewRepresentable`, over one
  shared coordinator. The web view's own setup — handler name, delegates, back-forward gesture off —
  moved into that coordinator rather than being copied into both, which is where two representables
  would otherwise drift.
- `allowsBackForwardNavigationGestures` stays off on the phone for a second reason the Mac did not
  have: it would fight the system's own edge-swipe.
- Discover sits under Library in the phone's root list (ADR-0018), not in a section of its own.

## Context

[ADR-0018](ADR-0018-the-phone-navigates-from-a-root-list.md) gives the phone a list with a Discover
row in it. This decides what that row opens.

**A premise worth correcting before it is inherited.** It would be natural to say that ADR-0016 made
embedding macOS-only and that this reverses it. It did not. ADR-0016's Decision has eight points and
**none of them mentions a platform** — unlike
[ADR-0015](ADR-0015-audio-effects-are-exposed-not-rebuilt.md), whose point 7 says "macOS only, per
ADR-0013 point 2" in as many words. The `#if os(macOS)` around `EmbeddedDiscoverView` is
implementation that followed ADR-0013 point 3 scoping a body of work to the Mac, which is not the same
as a ruling that the phone may never have it. So this extends ADR-0016 into a question it left open
rather than overturning an answer it gave.

Likewise [ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md) point 2 — "iOS stays the
listening path" — is about management. Discover is how you find something to play, which is the
listening path, and ADR-0018 point 6 keeps the actual management surfaces off the phone.

**What already exists, verified on 2026-08-02 against the live server.** The whole mechanism is built
and working on the Mac:

- `/embed` serves its own document, marked `familiar-surface="embed"`, loading an entry point that
  registers `NullAudioEngine` rather than `WebAudioEngine` (ADR-0017).
- The page reads its profile from `?profile=` and nothing else (ADR-0016 point 6).
- A play intent posted through `window.webkit.messageHandlers.familiar` arrives natively and parses:
  `play(trackIDs: ["t1","t2","t3"], startingAt: "t2")`, start index 1.
- Discover renders from the live library — 72,853 characters of DOM, no page errors.
- Pointed at a path an older server answers with the app instead, the marker check refuses it.

`WKWebView` and `WKScriptMessageHandler` are iOS APIs as much as macOS ones, and `EmbedIntent` — the
parsing and the marker check — is already in `FamiliarKit`, which both platforms compile. What is
macOS-only is roughly a hundred lines of `NSViewRepresentable`.

**The honest cost, which is not code.** A web view on a 393pt phone is a more noticeable compromise
than one in a 1,400pt window. ADR-0016 already named this tradeoff — "scrolling, text selection and
focus will not match the rest of the app" — and everything that makes it noticeable is worse on a
phone: momentum scrolling inside a scroll view, text selection on long-press where the rest of the app
has none, and a keyboard that the page rather than the app manages.

## Decision

1. **The phone's Discover row opens the same embedded surface the Mac uses**, pointed at the same
   `/embed` document on the same server.

2. **Every rule ADR-0016 and ADR-0017 set applies unchanged.** The null engine, the explicit profile,
   the one-message bridge, the marker check, the native unavailable state. None of them is
   platform-specific and none is relaxed here.

3. **The representable is the only new code.** `UIViewRepresentable` beside the existing
   `NSViewRepresentable`, sharing the coordinator, the intent parsing and the marker check — all of
   which are in `FamiliarKit` already. If this appears to need changes to `EmbedIntent`, that is a
   signal the two platforms are diverging and worth stopping for.

4. **The bridge stays one message wide**, per ADR-0016 point 5. A phone does not get a second message
   shape because it is smaller.

5. **Nothing else is embedded on the phone.** This is Discover, because ADR-0018 puts Discover in the
   list. It is not a precedent for embedding a management surface, which ADR-0013 point 2 keeps off
   the phone regardless of how it would be rendered.

6. **ADR-0016 point 1's test still decides the next one.** Embed when a surface is large and moving;
   build native when it is small and settled. That the phone can now host a web view does not lower
   the bar for using one — the Music Map is still native on both.

## Alternatives Considered

**Build Discover natively for iOS.** No web view on the phone at all, and the compromises above simply
do not arise. Rejected on the measurement ADR-0016 made and this does not get to re-make: Discover is
2,943 lines across 26 files that track external services, so a native rebuild is a second
implementation to change every time the first one does. That argument is not weaker on a phone; if
anything a third implementation is worse than a second.

**Leave Discover off the phone and ship ADR-0018's list without that row.** Costs nothing, breaks
nothing, and the list is the thing that was actually asked for. Rejected as a smaller version of the
problem ADR-0018 exists to fix — the phone would still be missing a destination the Mac has, and the
list would advertise its own gap. It stays the fallback if this ADR is not accepted, and ADR-0018 is
written so that it can.

**Open Discover in Safari from the phone.** Honest, trivial, no representable and no bridge. Rejected
for the reason ADR-0016 rejected the same idea for the Mac: leaving the app is the friction these
decisions exist to remove, and on a phone the return trip is worse, not better.

**Embed on the phone but without the bridge, browse-only.** Sidesteps the play path entirely — the
page shows recommendations and the listener finds the track themselves. Rejected because it makes the
surface an advertisement rather than a way to play something, and because the bridge is the part that
already works: it is verified on the Mac and needs no new code here.

## Consequences

- **Positive:** Discover arrives on the phone for roughly a hundred lines, because the parsing, the
  marker check, the null engine and the server route are all already built and verified.
- **Positive:** One implementation of Discover serves the web app, the Mac and the phone, and stays
  current with the web version on all three at once.
- **Tradeoff:** The phone gains a screen that scrolls, selects and focuses unlike the rest of the app,
  and that is more noticeable at 393pt than it is on a desktop. This is the cost, stated plainly.
- **Tradeoff:** A `WKWebView` resident on a phone costs memory that a native screen would not — the
  same objection ADR-0016 weighed for the Music Map and answered differently there, because that
  surface was small and settled and this one is neither.
- **Tradeoff:** The seam ADR-0016 named as embedding's main risk now spans two native clients rather
  than one. A web-app change that breaks the contract breaks both, which raises the value of the
  marker check and the intent tests rather than changing what they do.
- **Follow-up:** Decide what an embedded surface does with navigation *inside* it — an artist link in
  Discover currently goes nowhere on either platform, because `EmbedDiscover` supplies no-op handlers
  and the embed router returns to Discover. This is ADR-0017's open follow-up, it is now visible on
  two platforms rather than one, and it is the next thing worth deciding about this surface.
