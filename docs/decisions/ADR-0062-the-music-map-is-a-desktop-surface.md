# ADR-0062: The Music Map Is a Desktop Surface

Status: proposed

Date: 2026-08-18

Extends [ADR-0016](ADR-0016-embedded-web-surfaces-on-the-mac.md), whose point 3 built the map
natively for the Mac. Adds an exclusion under [ADR-0060](ADR-0060-the-players-removal-trigger-must-be-reachable.md)
point 1.

## Context

`docs/WEB-PARITY.md` shows Music Map as `Web ✅ / Mac ✅ / iPhone ❌`, and under ADR-0060's rule
that ❌ is one of two rows standing between the web player and deletion.

**It was never a gap.** ADR-0016 is titled *Embedded Web Surfaces on the Mac* and its point 3
decides the map is built native there; ADR-0013 put Discover and Music Map on the Mac. No ADR has
ever said the phone should have one. The cell was empty because nobody had decided, and the
countdown read "not decided" as "not yet done" — which is the failure mode of deriving a to-do list
from a matrix that records capability rather than intent.

**And the port is not what makes it a bad idea.** Scoped before deciding, so the decision is not
resting on an assumption that it would be hard:

- The layout, projection and geometry are already platform-agnostic — 492 lines in
  `Sources/FamiliarKit/MusicMap.swift`, tested.
- `MusicMapStore.swift` is gated `#if os(macOS)` but contains **zero** AppKit references. The gate
  is incidental.
- `MusicMapView.swift` already uses `MagnifyGesture`, `DragGesture` and single/double
  `onTapGesture` — the whole iOS interaction model, already written. Only three things in its 591
  lines are genuinely Mac-only: the `NSEvent` scroll-wheel monitor, `.onContinuousHover`, and
  `.help` tooltips. All three wrap in `#if os(macOS)`.

So it would compile on the phone in about an hour. **The reason not to is that it would be bad to
use**, which is Jeff's call and is the only reason that matters here.

The map's own source says why, at `MusicMap.swift:257`: at 500 artists "the same zoom draws two and
a half times as many names in the same space". Earlier work on the map established that **drawing is
not the bottleneck, text is**. A dense 2D field of overlapping labels, navigated by pinch and pan, is
a desktop interaction: it wants a large surface, a precise pointer, and hover to disambiguate — the
one affordance a phone does not have and the map uses to tell crowded names apart.

## Decision

1. **The Music Map is macOS-only, by decision rather than by backlog.** It is not built for the
   phone, and the iPhone ❌ on its parity row is a statement of intent.

2. **The row is excluded from the player's removal countdown** under ADR-0060 point 1's first rule —
   *excluded by decision* — and marked `**not a blocker:**` in the Listening table alongside
   listen-together. This ADR is the record point 3 of that ADR requires before an exclusion is added.

3. **This does not reverse ADR-0016 point 3 or ADR-0013.** Both are Mac-scoped and stay exactly as
   written. It also does not touch ADR-0019, which put embedded Discover on the phone: Discover is a
   list, and a list works on a phone.

4. **If it is ever wanted on the phone, this ADR is what to supersede** — and the work is the density
   problem, not the port. Recorded so nobody re-derives the port cost to reach the same answer.

## Alternatives Considered

- **Ship it with a lower artist cap on the phone.** The obvious compromise, and it was the plan
  before this decision: fewer labels, less crowding. Rejected because the cap is what makes the map
  worth looking at — ADR-0016's map earns its place by showing the shape of a whole library, and a
  phone-sized subset is a different, weaker thing wearing the same name. Cutting it until it fits
  produces something that fits and is not worth opening.

- **Ship it and let the density be bad.** Would close the row and take the countdown to one, which
  is a genuine pull. Rejected because that is optimising the bookkeeping rather than the product,
  and ADR-0060 point 3 exists precisely to stop a countdown becoming a reason to ship something.

- **Embed the web map in a `WKWebView`, as ADR-0016 considered and rejected for the Mac.** Cheapest
  possible route. Rejected for the same reason it was there — and more so here, since the three.js
  map is heavier than the native one and the phone is the device with less to spend.

- **Leave the row as an open ❌ and simply not do it.** What is happening today. Rejected because it
  keeps the player's removal blocked on work nobody intends to do, which is exactly the unreachable
  trigger ADR-0060 was written to fix — arrived at from the other direction.

## Consequences

- **Positive:** the countdown drops from two rows to one. Only New Releases detail remains, and
  that one needs a decision about the embed bridge before it needs code.
- **Positive:** the parity matrix stops implying an intention nobody has. A ❌ that means "we decided
  not to" now says so, next to the one that means "not yet".
- **Tradeoff:** a listener on the phone cannot see the map. That is the whole point, and it is a
  real loss for anyone who uses it to find something to play — Discover, which is on the phone, is
  the intended route to the same end.
- **Follow-up:** `MusicMapStore.swift`'s `#if os(macOS)` is incidental rather than meaningful, since
  the file has no AppKit in it. Harmless, and worth a comment saying the gate is about where the map
  is shown rather than what the store can compile against.
