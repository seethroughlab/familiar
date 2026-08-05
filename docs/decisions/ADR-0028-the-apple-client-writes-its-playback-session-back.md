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

1. **Resume-across-launches is the server session, not a local snapshot.** The Apple client gains no
   private store of what was playing. It already restores from the server on launch; this ADR makes
   that restore meaningful by ensuring the server holds what this device did.

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

8. **With queue sync disabled, none of this happens and nothing is preserved.** The existing
   `familiar.queueSync.enabled` setting (`ServerConfiguration.swift:48`) governs writes as it governs
   reads. A listener who has turned sync off has asked for this device not to participate, and
   inventing local persistence for them would be answering a question they did not ask — see the
   alternatives.

9. **Verification is against a real server, in three layers.** The payload construction is pure and
   unit-tested in `FamiliarKit`; the conflict and adoption paths extend the existing
   `QueueAdopterTests`; and a launch-quit-relaunch cycle is checked by hand against the live server,
   because the failure this fixes is only visible across a process boundary.

## Alternatives Considered

**Persist to `UserDefaults` or a local file, and leave sync alone.** Much smaller, works offline,
and needs no server round trip. Rejected because launch-time adoption already exists and already
writes the player's state from the server — so a local snapshot creates two sources of truth that
disagree on exactly the launch where it matters, and something must arbitrate. It also fixes the
symptom while leaving the cause: the Mac would still be silently overwriting itself on the server,
and the phone and web app would still be adopting a stale session after an hour of Mac listening.

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

- **Positive.** The Mac resumes where it left off, which is what was asked for — and so does the
  phone, and so does handoff between all three, because they resume from the same place.
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
- **Tradeoff.** Point 8 means the request is not granted for anyone who has turned queue sync off:
  they get no persistence at all. That is defensible and it is not obvious, and it may be the point
  reviewers most want to push on.
- **Tradeoff.** Point 3's coarse `position_seconds` means a resumed track can start a few seconds
  from where it stopped. ADR-0003 already carries this as a follow-up; this ADR inherits it rather
  than fixing it.
- **Follow-up.** Point 4's rule — do not write an adopted-but-untouched session — is the kind of
  invariant that is easy to state and easy to violate later. It wants a test that fails if adoption
  alone produces a write.
- **Follow-up.** If point 8 proves too strict in use, the answer is a local cache *behind* the same
  restore path, not beside it: one source of truth on launch, with the server preferred when both
  exist.
