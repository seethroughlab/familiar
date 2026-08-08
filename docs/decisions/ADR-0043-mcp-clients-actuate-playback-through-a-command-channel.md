# ADR-0043: MCP Clients Actuate Playback Through a Command Channel

Status: proposed

Date: 2026-08-07

Extends [ADR-0042](ADR-0042-the-llm-surface-is-an-mcp-server.md)

## Context

[ADR-0042](ADR-0042-the-llm-surface-is-an-mcp-server.md) point 2 exposes the 26 tools that need no
Familiar client and explicitly defers the three that do. This ADR decides those three:
`queue_tracks`, `control_playback`, and — by consequence rather than by tool — whether an external
host can start music at all.

**The server has never been able to play anything, and this is not an oversight.** `queue_tracks`
and `control_playback` write to in-memory fields on `ToolExecutor` (`handlers/playback.py:48`,
`:72`); `service.py` drains them into trailing SSE events; the events become real only inside the
event switch in `ChatPanel.tsx`, which calls `usePlayerStore.setQueue(...)` and
`setIsPlaying(...)` against an audio element in the browser process. Remove the chat panel and the
intents have no destination — the same shape as `familiar` #70, #74 and #76, but for the server's
own output rather than a page's.

**The architecture has been moving away from server-driven playback, deliberately.**
[ADR-0028](ADR-0028-the-apple-clients-playback-session-is-local.md) made the Apple client's
playback session local and **deleted queue sync entirely — 904 lines** — because `queue_sync_enabled`
shipped off at both ends and nobody used it. [ADR-0003](ADR-0003-server-owns-the-playback-queue.md) point
2 makes local-first mutation non-negotiable: playback never waits on the network. Writing
`PUT /queue/session` from an MCP tool therefore makes nothing happen, on any client.

**This ADR must not be read as reviving queue sync, and the distinction is the whole design.**
Queue sync was *state replication* — two devices each holding a queue, reconciled by `updated_at`
with an archive for the loser. A command channel carries *transient imperatives* in one direction
and stores nothing. ADR-0028's finding was that nobody wanted their phone's queue on their Mac; it
was not that nobody wants to say "play this".

**The mechanism has been described in the codebase and never built.**
`backend/app/services/outputs.py:168-178` defines `BrowserOutput` with the docstring:

> This output doesn't directly control playback—it signals to the frontend via WebSocket that
> playback should happen on a specific client.

There is no WebSocket endpoint anywhere in the backend, and `websocket_id` has **no readers and no
writers** — a grep of `app/`, `packages/frontend/src` and `packages/web/src` finds the declaration
and nothing else. This is the same failure the project has recorded twice before: the
`assertNavigationPolicyIsWired` guard that existed only in the comment naming it, and the Music Map
footer advertising a scroll-to-zoom nothing implemented. **A docstring describing a mechanism is
not a mechanism**, and the next reader would reasonably assume this one exists.

**Two facts that shape the transport choice:**

- Commands are **one-way, server to client**. There is no reply beyond "it happened", which the MCP
  tool can obtain by reading state it already has access to.
- The codebase already runs three SSE endpoints — `/chat/stream` and the two `/library/map/*/stream`
  variants — and [ADR-0007](ADR-0007-clients-are-generated-from-openapi.md) point 8 already carves
  SSE out of client generation. [ADR-0036](ADR-0036-listening-sessions-signal-through-familiars-own-server.md)
  proposes a `WebSocket /sessions/ws`, but that carries a genuinely bidirectional conversation
  between peers. This does not.

**The hard question is not transport, it is targeting.** A profile may have a Mac, a phone and a
browser tab open at once. ADR-0022 point 5's rule — *"One player, one queue, one now-playing
entry"* — was easy to honour when the chat lived inside the player. An external host is outside all
of them, and "play this" has to mean something specific.

## Decision

1. **A per-profile command channel exists, server to client, and it carries imperatives only.** It
   stores nothing, replays nothing, and reconciles nothing. **This is not queue sync and does not
   reopen ADR-0028**, whose finding was about replicating state between devices, not about a client
   accepting an instruction.

2. **The transport is SSE, not a WebSocket.** `GET /playback/commands` is a `text/event-stream` a
   client subscribes to. Commands are one-way, so the return half of a socket would be unused, and
   SSE is the pattern this codebase already runs three times. It is hand-written per client under
   ADR-0007 point 8, like every other stream here.

3. **A client subscribes only while it is able to act** — foregrounded on the Apple clients, tab
   alive in the web app — and unsubscribes otherwise. Subscription is the claim to be a player;
   there is no separate registration, and nothing to clean up when a device disappears.

4. **The target is chosen explicitly, and the MCP surface can see the choices.** A tool lists the
   attached players for the profile (name, platform, whether it is currently playing), and the
   playback tools take an optional target. **With no target given, the command goes to the
   most-recently-active subscriber** — which is the Mac the listener is sitting at, in the case
   that matters.

5. **No attached player is an answer, not a hang and not an error.** The tool returns "no player is
   attached" and says what to do about it. This is [ADR-0017](ADR-0017-the-embedded-surface-gets-a-null-audio-engine.md)
   point 4's rule — a capability check must answer, never throw — applied one layer out. A tool that
   spins is the `familiar` #74 defect, which is exactly what a play intent with no destination did
   last time.

6. **Commands are ephemeral and in-process.** A server restart drops every subscription and clients
   resubscribe; an undelivered command is lost rather than queued. This follows ADR-0036 point 8's
   reasoning and its stated consequence: a multi-worker deployment needs this revisited, and that
   is written down rather than discovered.

7. **The client executes commands through its own player, and local-first playback is untouched.**
   A command is an input to `FamiliarPlayer` or `usePlayerStore` exactly as a tap is. ADR-0003 point
   2 still holds — nothing in the playback path waits on the network — because the network is what
   *delivers* the command, not what services it.

8. **`clear_existing` becomes real here or it goes.** ADR-0042's Context records it as inert at both
   ends. The command carries an explicit replace-or-append, and whichever is chosen, the schema and
   the behaviour agree.

9. **`BrowserOutput.websocket_id` is deleted or wired.** It is currently a field with no readers
   describing a channel that does not exist. If the browser becomes a target under point 3 it is
   wired to this; otherwise it goes, with the docstring.

10. **The Mac first, then the phone and the web app.** Same order as every client surface since
    ADR-0016, and the Mac is where the MCP hosts in ADR-0042 point 7 actually run.

## Alternatives Considered

**Have the MCP server write `PUT /queue/session` and let clients adopt it.** Uses ADR-0003's
existing model, no new endpoint, no new transport, and the archive/conflict story is already built.
Rejected because it does not work: ADR-0028 removed queue-sync adoption from the Apple clients
entirely, `queue_sync_enabled` ships off, and adoption was read-only and arm-not-play by design.
Reviving it would reverse a decision made five days earlier on the evidence that nobody used it, in
order to serve a different problem it was not shaped for.

**Poll instead of subscribe** — the client asks "any commands?" every few seconds. No streaming
endpoint, no subscription lifecycle, trivially survives restarts and multiple workers. Rejected on
the interaction: a listener who says "skip this" and waits three seconds concludes it did not work.
It also puts a request on every idle client forever to serve an action taken a few times a day,
which is the shape of cost ADR-0041 has just finished removing from this app.

**Let the MCP server be a local process that drives the Mac app directly** — an XPC service, a URL
scheme, or AppleScript. No server involvement at all, and the strongest possible targeting: it is
the app on this machine. Rejected because it only ever works for one platform and one machine, it
duplicates ADR-0042 point 1's rejected split-process design, and driving the Mac app from outside
has been tried and does not work — synthetic media keys and accessibility traversal both fail
against it.

**Make the command channel bidirectional so the host can read now-playing.** Tempting, because "what
am I listening to?" is an obvious question. Rejected as scope: it reverses
[ADR-0016](ADR-0016-embedded-web-surfaces-on-the-mac.md) point 5 for a second surface (ADR-0033
already does it for the visualizer), and now-playing is better answered by the server's own
listening events from [ADR-0030](ADR-0030-scrobbling-is-the-servers-job.md) than by a channel built
for imperatives. Worth its own decision if wanted.

**Do not build it — MCP produces artifacts, and the listener presses play.** The honest minimum, and
it is genuinely defensible: playlists are durable, the app is already open, and ADR-0042 delivers
its value without this. Rejected because "queue this up" is the request that motivated the whole
direction, and because a playlist created and never surfaced is one more affordance whose
destination is not mounted. Recorded as the fallback if point 4's targeting proves worse than it
looks.

## Consequences

- **Positive.** ADR-0042's three deferred tools come back, and the MCP surface can do everything the
  chat panel could — which is the bar the replacement has to clear to be a replacement.
- **Positive.** The server gains a general way to say something to a client, which several
  half-built things have wanted: `BrowserOutput`'s docstring, the casting path, and any future
  "your scan finished" notification.
- **Positive.** Point 1's distinction gives a rule for the next person who wants server-driven
  behaviour: imperatives yes, state replication no. ADR-0028's finding stays intact rather than
  being quietly eroded.
- **Tradeoff.** A streaming connection per attached client per profile, held open for the whole
  session. This project has been bitten by exactly that before — a FastAPI `yield` dependency
  outliving its handler turned 834 downloads into 83-byte error bodies, and peak concurrency ran to
  337 streams against a pool of 20+20. **The subscription must not hold a database session**, and
  that is a build requirement, not a note.
- **Tradeoff.** Point 4's implicit targeting will sometimes be wrong — the most-recently-active
  client is a heuristic, and a listener with a Mac and a phone both open can be surprised. The
  explicit target exists because the heuristic is not always right.
- **Tradeoff.** Point 6 means commands are lost across a restart with no indication. Acceptable for
  imperatives; it would not be for anything durable, which is why nothing durable travels here.
- **Follow-up.** Multi-worker deployment breaks point 6, exactly as it breaks ADR-0036 point 8.
  Whichever of the two lands first should decide whether that is worth solving once for both.
- **Follow-up.** Now-playing readback is deliberately excluded and is the obvious next request.
- **Follow-up.** `get_visible_tracks` remains dead under this ADR. A command channel does not give
  an external host a viewport, and nothing here changes that.
