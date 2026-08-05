# ADR-0028: The Apple Client's Playback Session Is Local

Status: proposed
Date: 2026-08-05

Extends [ADR-0027](ADR-0027-shuffle-and-repeat-are-listener-modes.md) and
[ADR-0029](ADR-0029-the-server-stores-no-listener-preferences.md).
Retires ADR-0003 phase 4 for the Apple clients.

## Context

Quit the Mac app and everything about what you were listening to was gone: the queue, the position
in it, the position in the track. Relaunch and you were on an empty player. The request was simply
"I'd like the app to preserve state between launches".

There was already a launch-time restore, and it did not come from disk.
`queueAdopter.adoptOnce(into: player)` fetched the server's playback session and adopted it, per
ADR-0003 phase 4. So the client did start from stored state — just somebody else's, and only when
the network was up and two separate feature flags were on.

**Three drafts of this ADR were wrong before this one, and how they were wrong is the record worth
keeping.**

The first said resume *was* the server session, and that the Apple client "gains no private store of
what was playing". The second gated resume behind the queue-sync toggle, whose own interface copy
promises the opposite — "it never writes back" — so the gate governed something the label never
claimed. The third made resume local but kept adoption for the case where nothing local existed,
which is the same defect somewhere quieter: the one launch where a device has no session of its own
is exactly the launch where a silently adopted queue goes unnoticed.

Each draft was trying to preserve handoff while adding resume. **The two are not compatible while
one session per profile is all there is** — which ADR-0003 point 1 chose deliberately, so that
handoff would need no transfer step. Under one session, "what this Mac was doing" and "what any
device did most recently" are the same slot, and a launch has to pick one. Every draft that tried to
serve both put the wrong one first in some case.

**The resolution is that handoff was not wanted.** `queue_sync_enabled` ships `False` on the server
and `false` on every device; the Apple clients only ever adopted at launch, never on request; and no
listener has asked to pick up a queue. A feature that is off by default at both ends, that nobody
invokes, and that costs the feature that *was* asked for, is not worth protecting.

## Decision

1. **The Apple client's playback session is local, in both directions.** Each device persists its own
   queue, cursor, modes and position, and restores from that at launch — armed, never playing, with
   no network involved.

2. **Nothing is adopted from the server, at launch or on request.** `QueueAdopter` is removed rather
   than made explicit. An offer is still a prompt about a queue nobody asked to pick up, and the
   surface to decline it would be a cost paid at every launch for a feature that is not wanted.

3. **Nothing is written to the server.** ADR-0003 phase 4's deferred write-back is **not** completed;
   it is retired for these clients. An earlier draft argued the opposite — that a Mac which adopts
   but never writes silently degrades the shared session for every other client. That was true and
   is now moot: a client that never reads the session cannot be misled by it, and one that never
   writes cannot mislead anyone else.

4. **Queue sync leaves the Apple clients entirely.** The `familiar.queueSync.enabled` switch, the
   adopted-version bookkeeping, the Mac's Queue settings pane, the phone's toggle, `QueueAdopter`,
   `QueueAdoptionText`, `ServerQueueSource` and `QueueSyncStatus` all go. A dead switch that changes
   nothing would be worse than removing it.

5. **The server session stays exactly as it is, for the web app.** `PlaybackSession`,
   `GET/PUT /queue/session` and `queue_sync_enabled` are untouched. ADR-0003 keeps its status — it
   governs the server and the web client, both of which continue to work as specified. Only the
   Apple clients stop participating.

6. **`PlaybackSessionSnapshot` survives as the local format.** It already models exactly what needs
   saving, and its `resolvePlayOrder` already validates a shuffle permutation four ways. Those checks
   were written because the server validates none of its own fields; they are kept because a file on
   disk can be truncated or half-written, and a repaired order is a queue nobody built that plays
   convincingly enough to go unnoticed.

7. **Two files, split by how often they change.** The queue changes a few times an hour; the playhead
   changes four times a second. One file would mean rewriting up to 26,000 track ids twice a second
   for the length of a listening session — the flash-wear problem the web client already solved by
   splitting its reservoir into its own row. A signature ties them, and it is a content hash rather
   than `hashValue`: Swift seeds `Hasher` per process, so a stored hash would never match on the next
   launch and restore would silently do nothing, forever.

8. **Verification is in three layers, and the third is not optional.** Persistence and restore are
   pure and unit-tested in `FamiliarKit`; the round trip is asserted rather than each half
   separately, because a snapshot that encodes perfectly and restores into the wrong order is exactly
   as broken as one that fails to encode. And a launch-quit-relaunch cycle is checked by hand **with
   the network off**, because the failure this fixes is only visible across a process boundary and
   offline is the case the server-based design could never serve.

## Alternatives Considered

**Write, but never auto-read.** The Mac records what it played so another device *could* pick it up,
while launch always restores locally. This was the draft immediately before this one, and it is
coherent: it keeps ADR-0003 phase 4's deferral closable and costs the listener nothing at launch.
Rejected because it builds and maintains a synchronisation path for a handoff nobody performs, and
because writing is not consequence-free — a session this Mac publishes can be adopted on another
device without anyone asking, which is the same silent swap seen from the other end.

**Make handoff an explicit offer.** Keep the adopter, and when the server's session is newer, show a
"pick up from your phone?" affordance. Rejected as the worst of both: the full implementation cost of
adoption, plus a new decision at launch, in exchange for a feature whose flags have been off at both
ends since it shipped. If handoff is ever wanted, this is the shape to revisit — built because it was
asked for, not to avoid deleting something.

**Resume from the server rather than from disk.** The first draft. It cannot work offline, which is
the case a downloads-first client most needs; it makes resume depend on two feature flags that are
off by default; and under one session per profile it cannot distinguish this device's state from any
other's, so on a profile used from three devices it is not resume at all.

**Keep the queue-sync switch, wired to nothing, to avoid a migration.** Rejected because a control
that changes no behaviour is a lie with a longer half-life than the code behind it. The `UserDefaults`
keys are simply left behind: nothing reads them, and they cost a few bytes.

## Consequences

- **Positive.** The Mac and the phone reopen on what they were playing, offline included, with no
  dependence on a feature flag that ships off at both ends.
- **Positive.** A substantial amount of code goes — the adopter, its text, its status type, its
  server source, two settings surfaces and their tests. All of it existed to serve handoff.
- **Positive.** What remains is small enough to hold in your head: a file per device, read at launch,
  written on change. No conflicts, no versions, no reconciliation, no offer.
- **Tradeoff.** **There is no handoff between Apple devices, and no way to ask for one.** Starting an
  album on the phone and continuing on the Mac means finding it again. This is the deliberate price
  of point 1, and the thing most likely to be missed later.
- **Tradeoff.** The web app and the Apple clients now disagree about what "the queue" is. The web app
  continues to sync through the server; the Mac does not participate, so the two can show different
  queues for one profile with nothing to indicate why.
- **Tradeoff.** ADR-0003 phase 4 was built, shipped, and is now retired for the client it was built
  for. The server and web halves stand; the Swift-side adoption work is written off.
- **Follow-up.** The `queue` tag stays in the generator's filter list, so `queueGetPlaybackSession`
  and its siblings are still generated with no callers. Removing it touches ADR-0014's generated
  surface and is left as its own decision.
- **Follow-up.** `Tests/FamiliarAPITests/QueueSessionTests.swift` exercises an endpoint this client no
  longer calls. It still tests the generated client against a live server, so it stays — but it is
  now testing a contract this app does not consume.
