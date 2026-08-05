# ADR-0028: The Apple Client Writes Its Playback Session Back

Status: proposed
Date: 2026-08-05

Extends [ADR-0003](ADR-0003-server-owns-the-playback-queue.md) and
[ADR-0027](ADR-0027-shuffle-and-repeat-are-listener-modes.md)

## Context

Quit the Mac app and everything about what you were listening to is gone: the queue, the position
in it, the position in the track. Relaunch and you are on an empty player. The request was simply
"I'd like the app to preserve state between launches".

There is already a launch-time restore path, and it does not come from disk.
`queueAdopter.adoptOnce(into: player)` (`LibraryView.swift:904`, implemented at
`QueueAdoption.swift:76`) fetches the server's playback session and adopts it. So the Apple client
*does* start from stored state — the server's. What it never does is contribute to it.
`queueGetPlaybackSession` has exactly one caller (`ServerQueueSource.swift:17`);
`queuePutPlaybackSession` has **zero**, despite being generated and available, because the `queue`
tag is in the generator's filter list.

That asymmetry is not an oversight either. ADR-0003 phase 4 states the reason:

> Read-only by decision: the player has no `shuffle`, `repeat`, `consume` or reservoir concept, and
> a write would flatten a 1,732-track shuffled queue the web client was actively using. Handoff is
> the value; two-way sync waits for those concepts to exist natively.

**That condition has been met, and nothing revisited it.** `isShuffled`, `repeatMode` and `consume`
are all published properties of `FamiliarPlayer` today (`:27`, `:29`, `:31`), and ADR-0027 makes
them mean what the server's fields of the same names mean. The deferral was conditional and the
condition expired quietly, which is exactly the kind of thing an ADR set is supposed to catch.

The consequence is worse than a missing feature. Because the Mac adopts but never writes, an hour
of listening on the Mac leaves the server holding whatever the web app last pushed. The next device
to adopt — including the Mac itself, next launch — restores a session that is stale by however long
the Mac was in use. The Mac is not merely failing to save its state; it is being silently overwritten
by a less recently used client.

The web client is the existence proof that the other half works. `queueSyncService.ts` both pushes
(`:130`) and adopts (`:159`), reconciles on load (`:211`), and coalesces writes through an outbox so
that calling it often is cheap. Its payload (`:94`) already carries everything needed to resume:
`track_ids`, `cursor`, `shuffle_order`, `shuffle_index`, `shuffle`, `repeat`, `consume`,
`queue_source`, `position_seconds`, `version` and `updated_at`. **No schema work is required.** This
is a second implementation of an existing contract, not a new one.

## Decision

1. **Resume-across-launches is a local snapshot, and needs no network.** Each device persists its own
   queue, cursor, modes and position, and restores from that at launch — armed, never playing.

   **This reverses the first draft of this ADR, which said the opposite**: that resume was the server
   session and "the Apple client gains no private store of what was playing". Two things overturned
   it. Point 8 gated resume behind the queue-sync toggle, whose interface copy promises it "never
   writes back" — so the gate governed something the label never claimed. And
   [ADR-0029](ADR-0029-the-server-stores-no-listener-preferences.md) point 6 settled the general
   case: session state is device-authoritative, with the server as a handoff mirror. The web client
   has worked this way since ADR-0003 phase 3; the Apple client was the odd one out.

2. **The Apple client writes the playback session, completing ADR-0003 phase 4's deferred half.**
   `queuePutPlaybackSession` is called with the same fields the web client sends, on the same
   optimistic-concurrency contract — `version` in, conflict handled, as
   `familiar.queueSync.adoptedVersion.<profile>` already tracks for reads.

3. **Writes are coalesced and driven by change, not by a clock.** A signature over the queue,
   cursor and modes decides whether anything is worth sending, as the web client's outbox does.
   `position_seconds` is the exception and stays coarse — ADR-0003 already records as a follow-up
   that a handoff "can resume a few seconds" off, and that is a better trade than a write every
   tick.

4. **Nothing is written while the queue is adopted-but-untouched.** A device that adopts a session
   and does not play must not immediately write it back: that would bump `version` and let an idle
   client win a conflict against an active one. The first write follows the first change *this
   listener* made.

5. **Shuffle is still written as order, and now also as mode.** `shuffle_order` and `shuffle_index`
   are populated from the queue as it stands; `shuffle`, `repeat` and `consume` come from ADR-0027's
   modes. ADR-0003's observation — that a reader can flatten the order and skip the bookkeeping —
   is unaffected, because it governs reading and this governs writing.

6. **A conflict is resolved by taking the server's session, not by merging.** Two devices editing
   one queue has no correct merge, and the web client does not attempt one. The losing device adopts
   and continues from what the server had.

7. **Offline, nothing is queued for later.** A write that cannot be sent is dropped, not spooled.
   The state it described will be superseded by the next successful write, and a stale session
   replayed after a gap is worse than no write at all — it would resurrect a queue the listener
   abandoned hours ago. This is deliberately narrower than the web client's offline outbox, which
   exists for actions that must not be lost; a playback position is not one.

8. **Queue sync governs handoff only. Resume is never gated.** `familiar.queueSync.enabled`
   (`ServerConfiguration.swift:48`) decides whether this device writes to and picks up from the
   shared session — which is exactly what its interface copy already says. It has nothing to do with
   whether the app reopens on what you were playing, because that is local and needs no server at
   all. **An earlier draft of this point gated resume behind the toggle**; that was the defect this
   revision exists to remove.

9. **Handoff is offered, not applied.** `QueueAdopter` currently swaps the queue at launch whenever
   the server's version is newer. With point 1 restoring a local session first, a silent swap would
   throw away what this device was doing. So adoption splits into a check, an offer the listener
   acts on, and a dismissal that is remembered. The arm-don't-play rule survives it: picking up a
   queue arms the transport, it does not start audio.

   A consequence worth stating because it is easy to miss in code review: `QueueAdopter`'s
   `guard player.isIdle` becomes `isIdle || isArmed`. After point 1 the player is *armed* at launch,
   so the existing guard would reject every handoff.

10. **Verification is in three layers, and the third is not optional.** Persistence, restore and the
    payload construction are pure and unit-tested in `FamiliarKit`; the check/adopt/dismiss paths
    extend the existing `QueueAdopterTests`; and a launch-quit-relaunch cycle is checked by hand,
    **including with the network off**, because the failure this fixes is only visible across a
    process boundary and the offline case is the one the server could never serve.

## Alternatives Considered

**Persist locally and leave sync alone** — resume from a local file, never write back. Smaller, and
it grants the original request in full. Rejected because it fixes the symptom and leaves the cause:
the Mac would still never record its listening, so the phone and the web app would go on adopting a
session that is stale by however long the Mac was in use. Points 1 and 2 are separable, and both are
needed.

**Resume from the server rather than from disk** — the first draft of this ADR, rejected on review.
It reads as the tidier design, since one source of truth needs no arbitration. It fails on three
counts: it cannot work offline, which is the case a downloads-first client most needs; it makes
resume depend on a feature flag that is off by default on both the server and the client; and with
one session per profile it cannot distinguish "what this Mac was doing" from "what any device did
most recently", so on a profile used from three devices it is not resume at all. The two-sources
objection is answered by point 1 rather than avoided: local is authoritative, the server is a mirror,
and the listener arbitrates via point 9's offer.

**Write only `position_seconds`, treating the queue as the web client's to own.** Cheap, and would
deliver most of "resume where I left off" for a listener who uses the Mac alone. Rejected because
the queue is the part that is actually lost — a position into a queue nobody restored is not useful
— and because it entrenches the asymmetry rather than resolving it.

**Reimplement the web client's `queueStore.ts` shuffle bookkeeping first, so the payload is a direct
mapping.** Rejected for the reason ADR-0003 gives: consuming order rather than reconstructing mode
was "the one observation that made the phase tractable instead of a port of `queueStore.ts`". The
write direction can populate `shuffle_order` from the queue it has without maintaining a permutation
continuously, so the rewrite buys symmetry with the web client and nothing a listener would notice.

**Wait for a real conflict-resolution design before writing at all.** The safest option, and the
status quo. Rejected because the status quo is not neutral — it is a client that loses its own state
every launch and degrades the shared session for every other client. Point 6 adopts the same
last-writer-wins rule the web client has run on since ADR-0003 phase 3, which is a known quantity
rather than a new risk.

## Consequences

- **Positive.** The Mac resumes where it left off, which is what was asked for — offline included,
  and with no dependence on a feature flag that ships off by default at both ends.
- **Positive.** The Apple client stops silently degrading the shared session. This is the larger
  defect and it was invisible: nothing on any surface indicates that the Mac's listening was never
  recorded.
- **Positive.** No schema, no new endpoint, no generator change. `PlaybackSessionWrite` and
  `queuePutPlaybackSession` already exist and are already generated; the write is a second consumer
  of a contract with a working reference implementation to check against.
- **Positive.** ADR-0003 phase 4's deferral is closed rather than left as a conditional that
  quietly expired. That the condition had been met for some time, unnoticed, is the argument for
  writing this down.
- **Tradeoff.** Two clients now write one session, so conflicts become real rather than theoretical.
  Point 6 resolves them by discarding one side's recent listening — correct, and still a loss.
- **Tradeoff.** Handoff stops being automatic. A listener who liked opening the Mac onto whatever
  the phone was playing now has to accept an offer, and an offer that goes unnoticed is a feature
  that has quietly stopped working. Point 9 buys resume at handoff's expense; they cannot both be
  the silent default while one session per profile is all there is.
- **Tradeoff.** State now lives in two places for real, and they can diverge. The mirror is not a
  backup — a device that never enables queue sync has exactly one copy of its session, on its own
  disk, per ADR-0029 point 7.
- **Tradeoff.** Point 3's coarse `position_seconds` means a resumed track can start a few seconds
  from where it stopped. ADR-0003 already carries this as a follow-up; this ADR inherits it rather
  than fixing it.
- **Follow-up.** Point 4's rule — do not write an adopted-but-untouched session — is the kind of
  invariant that is easy to state and easy to violate later. It wants a test that fails if adoption
  alone produces a write.
- **Follow-up.** If point 8 proves too strict in use, the answer is a local cache *behind* the same
  restore path, not beside it: one source of truth on launch, with the server preferred when both
  exist.
