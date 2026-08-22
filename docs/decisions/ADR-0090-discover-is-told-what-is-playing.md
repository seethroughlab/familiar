# ADR-0090: Discover Is Told What Is Playing

Status: accepted

Date: 2026-08-22

Extends [ADR-0033](ADR-0033-the-embed-bridge-gains-a-return-channel.md) to a second surface, and
supersedes the second sentence of [ADR-0016](ADR-0016-embedded-web-surfaces-on-the-mac.md) point 5 —
"The web view is never told what is playing and never renders a transport." The first half of that
sentence stops being true here. **The second half does not**: Discover still renders no transport,
and every play still goes to the native player as an intent.

## Context

`ADR-0016` point 5 made the embed bridge one-way: the page posts an intent, the app owns the queue,
the playback and the reporting, and the page is told nothing back. The reason given was
*"One player, one queue, one now-playing entry, exactly as with CarPlay"* — which is about
**ownership**, and telling a page read-only state takes no ownership from anyone.

`ADR-0033` had already made the first hole in it, deliberately and with the reasoning written down:
the visualizer surface is *sent* analysis frames and playhead position, as
*"a separate channel with its own contract, its own file and its own tests"*, explicitly not an
addition to the page → app bridge whose cap `ADR-0020` point 2 guards. So an app → page direction
exists, is accepted, ships, and has tests. What it does not have is a second consumer.

**The prompt is a defect that has been visible since Discover was embedded.** A Discover row shows a
playing indicator. On the Mac and the phone it never lights, because the page has no idea what the
native player is doing. Until now that was disguised: the components read `playerStore`, which is
not mounted on `/embed`, so the selectors returned nothing and the indicator was simply always off.
`ADR-0083` removed those reads and moved the state to props, which turns an invisible defect into an
explicit hole — the parent has nowhere to get the values from.

**A contradicted premise, recorded so it is not re-derived.** `ADR-0083` point 1 says the embedded
parent "supplies what it knows, which is nothing, and the components render no playing indicator
there". That was written believing no channel existed. One does; it was built by `ADR-0033` for the
surface next door.

## Decision

1. **The Discover surface is sent what is playing, on the `ADR-0033` channel.** One frame shape,
   carrying the current track id and whether it is playing. Not the queue, not the position, not the
   track's metadata — the page already fetches everything else it draws.

2. **It is the same mechanism, not a second one.** `VisualizerPump`'s shape — coalesced frames
   evaluated into the web view, a sink installed at module load, no React in the path — is reused
   rather than reimplemented. Two hand-rolled channels is how two surfaces come to disagree about
   what a frame means.

3. **Page → app is untouched, and `ADR-0020` point 2's cap still binds.** Nothing is added to the
   intent bridge. This is the direction `ADR-0033` opened, which that ADR's point 2 was careful to
   keep separate precisely so the cap could go on meaning something.

4. **Discover still renders no transport.** No play/pause button, no scrubber, no queue. The
   indicator says *what is playing*; it does not offer to change it beyond the intent Discover
   already posts. `ADR-0016` point 4 — an embedded surface never plays audio — is untouched and
   remains the load-bearing rule.

5. **The frame is advisory.** A surface that never receives one shows no indicator and works exactly
   as it does today; a page built against an older app must not break. This is the same property
   `ADR-0087` gives `familiar:stats`, and for the same reason: an optional channel that a surface
   depends on is not optional.

## Alternatives Considered

**Leave it, as `ADR-0083` point 1 says.** Coherent, and it is what is currently shipping. Rejected
because the indicator is already in the markup and already renders — it is simply always off, which
is not "no indicator", it is a wrong one. A row that can show "playing" and never does is the defect
shape this project keeps finding: an affordance whose source is not mounted, failing silently.

**Have the page poll the server for the playback session.** No new channel, and the server already
owns a queue (`ADR-0003`). Rejected on latency and honesty: the session is written by the app after
the fact, so the page would lag the speakers by seconds and would be wrong whenever the app is
offline — while the app it is embedded in knows the answer exactly, for free.

**Widen the page → app bridge so Discover can ask.** Rejected: it is the wrong direction, it costs
one of the two messages `ADR-0020` point 2 allows, and a request/response over a channel designed
for fire-and-forget intents is a worse fit than the push channel that already exists.

**Give Discover the whole `ADR-0033` frame, analysis included.** Rejected as a capability with no
caller — Discover draws no spectrum. The visualizer's frame carries an FFT because it draws one; a
row list needs an id and a boolean.

## Consequences

- **Positive.** A Discover row on the Mac and the phone shows what is playing, which it has always
  had the markup to do. The web app is unaffected: it has no player, passes nothing, and shows
  nothing — correct rather than degraded.
- **Positive.** `ADR-0033`'s channel gets its second consumer, which is when a "separate channel
  with its own contract" starts earning the separation rather than just asserting it.
- **Tradeoff.** A second surface now depends on the app → page direction, so a change to that frame
  format has two consumers to keep in step. Point 5 is what keeps that cheap: a surface that gets
  nothing degrades to today's behaviour.
- **Tradeoff.** `ADR-0016` point 5 no longer reads as an absolute, and its remaining force is the
  ownership rule rather than the silence. That is the honest position — `ADR-0033` had already
  taken the absolute away and left the sentence standing.
- **Follow-up.** `ADR-0083` point 1's closing clause is contradicted by this and should be read
  through it; the props it introduced are exactly the seam this fills.
