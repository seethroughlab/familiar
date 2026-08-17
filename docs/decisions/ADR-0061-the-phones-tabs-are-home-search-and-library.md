# ADR-0061: The Phone's Tabs Are Home, Search and Library

Status: proposed

Date: 2026-08-17

Supersedes [ADR-0042](ADR-0042-the-phone-gets-a-persistent-tab-bar.md) point 2. The rest of that ADR
stands: the tab bar itself, per-tab stacks, the transport above it, and the partial supersession of
ADR-0018.

## Context

ADR-0042 point 2 decided **four tabs: Home, Tracks, Favorites, More**, and gave reasons — Tracks
because "it is this app's main list and the one point 5 admitted the change had cost", More because
ADR-0018's root list keeps its grouping and counts rather than becoming a new screen.

**The phone ships three: Home, Search, Library.** It has for some time.

This is not a proposal to change the app. It is the record catching up with it, and the interesting
part is how the gap opened.

### How it happened

The tab bar arrived inside a commit called **"Improve Home resume and listening history"**
(`familiar-apple` `6ca7e44`). Its only rationale is a one-line doc comment — *"The phone's primary
navigation, following the usual iOS music-app shape"* — and it names no ADR. Nothing was written
down, so nothing disagreed out loud: the ADR said four tabs and the app grew three, and both looked
right to anyone reading only one of them.

Found while cleaning up branches, not by anyone noticing the phone.

### Which is actually better

**The shipped design is better, and that is why this supersedes rather than corrects.**

- **Search is a real gap in ADR-0042.** Four tabs of browsing and no way to search from the root, on
  the device where typing a name is faster than walking a hierarchy. The library is 26,422 tracks.
- **Tracks and Favorites are one tap away, with counts.** ADR-0042 point 3 kept `LibraryRootList`
  intact as the More tab precisely so everything beyond the promoted tabs stays reachable, and
  ADR-0018 point 3's counts are what make Favorites findable there. Promoting them to tabs buys a
  tap and spends the slot Search now occupies.
- **"Library" reads better than "More".** More is a shrug; the tab holds the library's destinations
  and says so.

What ADR-0042 got right and this keeps: a persistent bar rather than a row one level down, each tab
owning its stack, and the transport sitting outside every stack.

### What is not reconciled

`codex/home-screen-changes` — an uncommitted worktree found in the same cleanup — proposes a third
arrangement: Home, Library, **Settings**, reframed as a top rail, with `search:` removed from the
grid views. It is superseded by what shipped, and its Settings tab runs against ADR-0013 point 2,
which keeps management surfaces off the phone. Recorded here so the next person who finds it knows
it was considered and rejected rather than forgotten.

## Decision

1. **Three tabs: Home, Search, Library.** This supersedes ADR-0042 point 2's four. Home and the
   library list survive under different labels; Tracks and Favorites cease to be tabs and remain
   rows in the Library tab, with their counts.

2. **Search is a tab because searching is a root action, not a destination.** On a phone it competes
   with browsing rather than sitting inside it, and ADR-0042 had no answer for it at all.

3. **`LibraryRootList` is the Library tab, unchanged.** Exactly ADR-0042 point 3, with the label
   corrected. Its grouping (ADR-0018 point 2), counts (point 3) and the ADR-0012 collection group
   are untouched.

4. **The rest of ADR-0042 is untouched** — points 1, 3 through 7. Only the tab list changes.

5. **A navigation change on either client needs an ADR, and this one did not get one.** That is the
   defect this ADR is really about. The cost was not the design, which is good; it was that the
   record and the app disagreed for weeks and neither one knew.

## Alternatives Considered

- **Change the app to match ADR-0042.** The orthodox reading: the ADR is accepted, so the code is
  wrong. Rejected because it would remove Search — a capability the ADR never considered and the
  phone plainly needs on a 26k library — to promote two destinations that are already one tap away
  with counts beside them. Enforcing a decision that has been overtaken makes the record an obstacle
  rather than a reference.

- **Edit ADR-0042 point 2 in place.** Smallest possible change and nobody would be misled by the
  result. Rejected by the convention, and for a reason that bites here: point 2's argument for
  Tracks is worth keeping visible, because it is the argument this ADR has to answer. Deleting it
  would leave a decision with no trace of what it overturned.

- **Leave it.** The app works and Jeff uses it daily. Rejected because the drift is already
  spending real time: it produced a third competing design in an abandoned worktree, and the only
  reason anyone looked was a branch cleanup. `docs/WEB-PARITY.md` went nine rows stale the same way,
  and ADR-0058 point 4 shipped an unreachable trigger for the same reason — a record nobody checks
  against the thing it describes.

- **Adopt the worktree's Home / Library / Settings rail.** Considered because it exists and someone
  wrote it. Rejected on two counts: a Settings tab contradicts ADR-0013 point 2, and it drops Search.

## Consequences

- **Positive:** the record matches the app, and the reasoning for the arrangement that actually
  shipped is written down for the first time.
- **Positive:** ADR-0042's good parts are preserved explicitly rather than by silence.
- **Tradeoff:** Tracks and Favorites stay one tap down. That is the cost ADR-0018 point 5 admitted
  and ADR-0042 point 2 tried to buy back; it is now paid deliberately, to spend the slot on Search.
- **Follow-up:** the uncommitted `codex/home-screen-changes` worktree should be discarded — it is a
  superseded design and its distinctive ideas are rejected above.
- **Follow-up:** nothing checks that an accepted ADR's decisions still describe the app. Three have
  now drifted — this, `WEB-PARITY.md`, and ADR-0058 point 4 — each found by accident. Worth
  considering whether the Apple clients need the equivalent of `WEB-PARITY.md`: a file that is
  wrong in an obvious way when the app moves.
