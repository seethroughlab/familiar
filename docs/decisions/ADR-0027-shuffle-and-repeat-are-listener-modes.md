# ADR-0027: Shuffle and Repeat Are Listener Modes

Status: accepted
Date: 2026-08-05

Extends [ADR-0003](ADR-0003-server-owns-the-playback-queue.md)

Implementation:
- Accepted 2026-08-05 and shipped in `familiar-apple` #70, alongside
  [ADR-0028](ADR-0028-the-apple-clients-playback-session-is-local.md) — the two were built together
  because point 7's deferral only holds if the thing it defers to lands in the same change.
- Point 2's split is in `Sources/FamiliarKit/FamiliarPlayer.swift`. `play(_:startingAt:)` no longer
  assigns `isShuffled = false`; the doc comment at `:216` now records that shuffle survives it and
  why it used to not.
- Point 5's reading of an adopted session is moot in practice: ADR-0028 removed adoption entirely
  in the same PR. `adoptLogicalOrder` remains and still sets `isShuffled = false` (`:358`), which is
  what `restoreSession` must *not* call — a local snapshot's play order is not a flattened server
  order, and restoring through the adoption path would give back a shuffled queue that can never be
  straightened out again. That distinction is the point-2 split doing its job on the first thing
  that touched it.
- Point 7's persistence question is answered by ADR-0028's cold file, which carries `repeatMode` and
  `consume` with a defaulting decoder so a snapshot written before those fields existed still loads.
- Point 4's `playShuffled(_:)` keeps its meaning and now leaves the mode on (`:255`).
- **Follow-ups not done:** the transport-affordance check across all three surfaces, and the
  annotation on ADR-0003's phase 4 bullet.

## Context

Shuffle switches itself off when you click a track. Reported from the Mac, and true on every
surface: `FamiliarPlayer.play(_:startingAt:)` sets `isShuffled = false`
(`FamiliarPlayer.swift:153`), and all **twelve** call sites that start playback from a list go
through it — the library, favourites, downloads, browse, chat and the embedded Discover surface.

Nothing decided this. The method's documentation does not mention shuffle at all; the assignment is
part of installing a fresh queue in the order it was handed. That falls out of how the flag is
modelled: `isShuffled` is documented as "whether `queue` is a shuffled view of `logicalQueue`"
(`FamiliarPlayer.swift:26`). It is a statement about the *current queue*, not about the listener.
Build a new queue and there is nothing shuffled about it, so the toggle is off — correctly, by its
own definition, which is why no test caught it and no comment flags it.

**A premise from ADR-0003 needs correcting here, because it reads as if it settled this.** That ADR
says shuffle "is consumed as order rather than reimplemented as a mode", and its phase 4 bullet
says the Swift player "has no `shuffle`, `repeat`, `consume` or reservoir concept". Both were true
and neither is now. The first was a statement about *reading* the server's session — flattening
`shuffle_order` into a play order so a reader need not reconstruct the mode — and it says nothing
about what the toggle should mean to someone using it. The second has simply been overtaken:
`isShuffled` (`:27`), `repeatMode` (`:29`) and `consume` (`:31`) all exist natively today.

The server has never agreed with the client here. `PlaybackSessionWrite` carries `shuffle`,
`repeat` and `consume` as fields in their own right, *alongside* `shuffle_order` and
`shuffle_index`. The mode and the order are separate things in the schema, and the web client sends
both (`packages/frontend/src/services/queueSyncService.ts:94`). Only the Apple client collapses them.

The behaviour is also inconsistent with itself. `toggleShuffle()` deliberately preserves the
listener's intent across a queue change — `logicalQueue` exists solely so that switching shuffle off
can straighten an album out again, and `QueueShuffle.disabling` reconstructs the original order.
Considerable care went into shuffle surviving one kind of change, and none into it surviving the
most common one.

## Decision

1. **Shuffle, repeat and consume are properties of the listener, not of a queue.** They persist
   across queue replacement. Starting playback from a list no longer clears them; a listener who
   turned shuffle on stays in shuffle until they turn it off.

2. **`isShuffled` splits into a mode and a fact.** The published mode is what the toggle sets and
   what survives. Whether `queue` currently *is* a permutation of `logicalQueue` stays as it is —
   internal, derived, and what `QueueShuffle.disabling` needs to straighten an album out. Collapsing
   the two is what caused this, so the fix must not re-collapse them under a new name.

3. **Starting playback with shuffle on shuffles the remainder, not the choice.** Clicking a track
   plays *that* track and permutes what follows, as `toggleShuffle()` already does mid-listen. It
   does not re-randomise the opening track: the listener picked it, and honouring that pick is the
   whole point of clicking a row rather than pressing Shuffle.

4. **`playShuffled(_:)` keeps its distinct meaning and now also sets the mode.** Pressing Shuffle on
   an album should still surprise you with the opening track, which is why it exists separately from
   `play(_:startingAt:)` plus a toggle. What changes is that it leaves the mode on afterwards rather
   than describing only the queue it built.

5. **An adopted queue still claims nothing.** ADR-0003's reasoning stands unchanged: a session
   arrives flattened, so this device cannot tell whether the order it received was shuffled, and
   asserting a mode would offer to "un-shuffle" into an order the server never had. Adoption
   continues to record the order as the order it is. It may now *read* the session's `shuffle` field
   to set the mode, because that field says what the listener chose rather than what the order looks
   like — but the order itself is still taken as given.

6. **Clearing the queue clears the modes.** `clear()` returns the player to its initial state, and a
   listener who has stopped everything and emptied the queue is not mid-session. This is the one
   place the modes do not survive, and it is deliberate rather than an oversight.

7. **The modes are not yet persisted anywhere.** They survive queue changes within a launch and
   nothing more. Where they are stored across launches is [ADR-0028](ADR-0028-the-apple-clients-playback-session-is-local.md)'s
   decision, and deliberately not this one — this ADR is executable on its own and fixes the
   reported defect on its own.

## Alternatives Considered

**Leave it: clicking a track is a deliberate exit from shuffle.** There is a real argument that
picking a specific track means "play this, in order, from here" — and it has the merit of being
what the code does today. Rejected because it is not discoverable in the slightest: the toggle
silently changes state as a side effect of an unrelated action, with no indication that it was the
click that did it. If it were the intent, the toggle would be disabled or the change announced.
Neither happens, and the behaviour was reported as a bug by the person who built the app.

**Make `play(_:startingAt:)` preserve the flag without splitting the concept.** The one-line fix:
capture `isShuffled` and restore it. Rejected because the flag would then be lying — it would claim
`queue` is a shuffled view of `logicalQueue` when it is not, and `toggleShuffle()` reads exactly
that to decide whether to straighten out. The next person to call `QueueShuffle.disabling` on that
state gets an order that never existed. The concept has to split or the bug moves rather than
leaves.

**Reimplement shuffle as the server models it, with `shuffle_order` maintained client-side.** This
is what the web client does, and it would make write-back (ADR-0028) a direct mapping instead of a
translation. Rejected as the wrong order of work: ADR-0003 found that consuming the order rather
than reconstructing the mode was "the one observation that made the phase tractable instead of a
port of `queueStore.ts`", and that remains true. Maintaining a permutation and an index alongside
the queue is a substantial rewrite of working code, justified only if write-back proves it
necessary — and ADR-0028 argues it does not.

**Persist the modes in `UserDefaults` as part of this change.** Tempting, because it is small and
gets most of what was asked for. Rejected because it would put playback state in a second place
that launch-time adoption already writes from (`LibraryView.swift:904`), and two sources of truth
for what is playing is precisely the hazard ADR-0028 exists to resolve. Doing it here would
pre-empt that decision by making the wrong half irreversible.

## Consequences

- **Positive.** The reported defect goes away, and shuffle behaves the way it does in every other
  player: a mode the listener sets, not a property of whatever list they last touched.
- **Positive.** The client stops disagreeing with its own server. `shuffle`, `repeat` and `consume`
  have been fields in `PlaybackSessionWrite` all along; after this the Apple client has something
  truthful to put in them, which is what makes ADR-0028 possible.
- **Positive.** The split in point 2 makes the invariant testable in `FamiliarKit`:
  the mode is a published property with defined behaviour across queue replacement, and
  `QueueShuffle` is already pure and covered.
- **Tradeoff.** Twelve call sites change behaviour at once, and none of them asked to. A listener
  who has grown used to clicking a track as a way *out* of shuffle loses that gesture, and the
  replacement — the toggle — is one they may never have used.
- **Tradeoff.** Point 3 means clicking a track in shuffle produces a queue whose order depends on
  where you clicked, which is harder to reason about than "the list, shuffled". It is the same rule
  `toggleShuffle()` already follows mid-listen, so the inconsistency being removed is larger than
  the one being introduced.
- **Follow-up.** The transport gives no indication that shuffle is a persistent mode rather than a
  per-queue state. Now that it survives, it is worth checking that the control reads as on when it
  is on, across all three surfaces.
- **Follow-up.** ADR-0003's phase 4 bullet should be annotated to record that its "no `shuffle`,
  `repeat`, `consume`" premise has expired, so nobody re-derives the deferral from it. Its Decision
  is not edited; the note belongs with the implementation record.
