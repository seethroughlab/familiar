# ADR-0036: Listening Sessions Signal Through Familiar's Own Server

Status: accepted

Date: 2026-08-06

## Implementation

All eight points shipped together.

**ADR-0037, the Apple half, was rejected** — a Mac cannot host, because `RTCAudioDevice` is not
exposed in `stasel/WebRTC`'s macOS slice. That matters here for one reason worth naming: this ADR's
Alternatives rejected *"Delete listening sessions properly rather than reviving them"* partly on the
grounds that "the feature is being asked for on the Apple clients (ADR-0037), and reviving it
correctly is the prerequisite for that." **That prerequisite no longer has anything to be a
prerequisite for.**

This decision still stands on the rest of its own argument, which never depended on ADR-0037: the
one feature involving other people was routing through a box the listener does not run, and it had
been broken in `pnpm dev` for five months. Both are fixed, in the web app, where the feature lives
and works. But anyone re-reading that Alternative should know half its reasoning has expired.

Point 5's generated `sessions` surface is the other casualty: it is generated for the Apple clients
and now has no Apple consumer. It is left in place — the backend lint cross-checks `VENDORED_TAGS`
against the Swift config, so removing it is a change on both sides, and iOS already compiles
management operations it never calls. Worth deciding deliberately rather than inheriting.

`backend/app/services/sessions.py` came back from `ceeb926^` unchanged — it was removed for scope
and there was no finding against it. `backend/app/api/routes/sessions.py` did not: the REST half is
typed to ADR-0007 (`SessionResponse`, `IceServersResponse`, `operation_id`s, `NotFoundError` rather
than a bare `HTTPException`), and `sessions` is now in `VENDORED_TAGS` and in the Swift generator
config — twelve tags, 265 operations, lint green, and both operations generate.

**ICE became a route as well as a join payload.** The shelved code exposed `get_ice_servers()` only
inside the socket's join responses, which is too late for two callers: the Apple clients need it
before joining (ADR-0037), and point 7 wants a client to be able to say "no TURN is configured" up
front rather than after a handshake hangs. `GET /sessions/ice-servers` reports `has_turn`
explicitly for that reason, and the socket now sends the same pair on `create` as well as on join —
a host behind symmetric NAT should learn that before inviting anyone.

**The guest page had to become a route, which the ADR filed as a follow-up.** It could not stay one:
`buildShareLink` produces `/listen/{code}` against this origin once the relay is gone, and there has
*never* been such a route in `App.tsx` — the relay served that page itself. Shipping point 3 without
it would have made the one thing a host hands to a friend a 404. `GuestListener.tsx` is restored
from `ceeb926^` and mounted **outside `AppShell`**, since a guest has no profile, no library and no
player. Two things in it were repaired rather than restored: it read the join code from nowhere, and
its WebSocket URL rewrote port 3000 to 8000 — a guess at a backend that has been on 4400 for a long
time, wrong for as long as it was unreachable. Both now use the same origin every other request
uses.

18 backend tests. The shelved file tested the service's dataclasses and nothing that crosses the
wire, which is precisely the half that now has a contract.

## Context

Listening sessions — create or join by code, the host streams what they are playing to guests, with
chat and reactions — are the product's one social feature. They are live in the web app:
`AppShell.tsx:151` mounts `SessionPanel`, backed by `hooks/useListeningSession.ts` (640 lines),
`hooks/useWebRTCStreaming.ts` (354), `components/Sessions/SessionPanel.tsx` (366),
`IceDiagnostics.tsx` (112) and `services/listeningSessionFamiliars.ts` (97). Seven commits in the
last six months.

**Where the signalling goes is the problem, and it takes a moment to see.**

`ceeb926`, on 2026-03-06, shelved the server half: `backend/app/api/routes/sessions.py` (425 lines,
already tagged `sessions`, with a `GET /sessions/by-code/{code}`, a `WebSocket /sessions/ws`, and a
`get_ice_servers()` returning two Google STUN servers plus an optional TURN from settings),
`backend/app/services/sessions.py` (319), `backend/tests/test_api_sessions.py` (100),
`docs/LISTENING_SESSIONS.md` (601) and `components/Guest/GuestListener.tsx` (475).

The client half was then rebuilt without it. `useListeningSession.ts:100` reads:

```ts
function buildWsUrl(): string {
  let base: string;
  if (RELAY_URL) {
    base = RELAY_URL.replace(/^http/, 'ws').replace(/\/$/, '');
  } else {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    base = `${proto}//${window.location.host}`;
  }
  return `${base}/api/v1/sessions/ws`;
}
```

`RELAY_URL` comes from `VITE_SESSIONS_RELAY_URL`, defaulting to `''`. Three places set it, all to
the same value: `docker/Dockerfile:32` (`ARG VITE_SESSIONS_RELAY_URL=https://familiar-sessions.fly.dev`),
`.github/workflows/release.yml:121`, and `scripts/deploy-dev.sh:34`. So:

- **Every released build signals through `https://familiar-sessions.fly.dev`** — a separate Fly
  application, outside the user's own server, in a product whose premise is that nothing leaves
  your network.
- **Every development build falls back to same-origin `/api/v1/sessions/ws`**, a route deleted five
  months ago. The panel opens, the socket 404s, and the feature has been broken in `pnpm dev` since
  the day it was shelved.
- **Guests never touch the user's server at all.** `buildShareLink` returns
  `https://familiar-sessions.fly.dev/listen/{code}` when the relay is set, and `/listen/` is not a
  route in `App.tsx` either way.

That is the finding this ADR exists to act on. It is not a defect in WebRTC or in the session code,
both of which work. It is that the one feature which involves other people routes through a box the
listener does not run, and the fallback for anyone who does not set a build argument points at
nothing.

**The shelving was for scope, not for defects.** `ceeb926`'s message is *"Remove listening
sessions, WebRTC streaming, and guest listener features. Code preserved on
feature/listening-sessions branch"*, made the same afternoon as `dbdef05` shelved the plugin
system. Nothing in either commit says the code was wrong.

**But `feature/listening-sessions` does not exist**, and this was checked rather than assumed:
not on `origin`, not locally, under any name. `dbdef05`'s counterpart branch —
`feature/community-plugins` — *is* still there, locally only, so the convention was real and this
one was simply lost. The code survives at **`ceeb926^`** and reads out intact
(`sessions.py` 425 lines, `GuestListener.tsx` 475), so nothing is gone; but the recovery path is
history, not a branch, and a plan written against the branch would have failed at its first step.
Recorded because the same sentence is in the commit message, where it will be read again.

**Two properties of the shelved implementation are worth surfacing before it comes back.**

`services/sessions.py` held an in-process `SessionManager`. Sessions did not survive a restart and
would not be visible across workers. That was acceptable for an ephemeral listening party and it is
still arguable, but it should be a decision rather than an inheritance.

And `WebSocket /sessions/ws` was the **only** WebSocket route this backend has ever had. Searching
for one today finds a docstring — `backend/app/services/outputs.py:173` describes signalling *"to
the frontend via WebSocket"* for browser-based outputs, and there is no such route; the
multi-room path carries a `websocket_id` field and nothing serves it. So reviving this is not
adding a socket beside existing ones. It is reintroducing the only one, along with whatever
deployment characteristics a long-lived connection brings to a server that currently has none.

## Decision

1. **Signalling moves into the Familiar server.** The shelved `sessions.py` and
   `services/sessions.py` come back rather than being redesigned, because they were removed for
   scope and there is no finding against them. `GET /sessions/by-code/{code}`, the
   `WebSocket /sessions/ws` and `get_ice_servers()` return as they were, adjusted only for the
   contract rules in point 5.

2. **The external relay is retired, and the reason is the product's premise rather than a fault.**
   `familiar-sessions.fly.dev` works. It is being removed because a self-hosted music player should
   not route its listeners' session codes, chat and reactions through infrastructure the listener
   does not run — the same argument the README makes about the library, applied to the one feature
   that had drifted from it.

3. **`VITE_SESSIONS_RELAY_URL` is deleted, not defaulted.** A build argument that silently sends
   traffic elsewhere is worse than the same behaviour written down, and leaving it in place with an
   empty default would restore the broken same-origin path as the fallback for everyone. The
   `ARG`/`ENV` pair in `docker/Dockerfile`, the line in `release.yml` and the export in
   `deploy-dev.sh` all go.

4. **The server signals; it never carries audio.** Peers connect directly, as they do today. A
   listening party must not turn a NAS into a streaming host, and this is the boundary that keeps
   the feature's cost proportional to running a WebSocket.

5. **The `sessions` tag joins the generated surface, and the WebSocket does not.** The REST half —
   session lookup, ICE configuration — is typed to
   [ADR-0007](ADR-0007-clients-are-generated-from-openapi.md)'s rules: typed 2xx JSON, declared 401,
   404, 422 and 500, `operationId` under 60 characters, entries in both
   `Sources/FamiliarAPI/openapi-generator-config.yaml` and `VENDORED_TAGS` in
   `backend/scripts/lint_openapi.py`. The socket is hand-written on every client, for the reason
   ADR-0007 point 8 already excludes the two SSE map variants: the generator has nothing to
   generate for it.

6. **ICE stays as the shelved code had it — Google STUN by default, TURN by configuration.**
   `turn_server_url`, `turn_server_username` and `turn_server_credential` return to `config.py`.
   Familiar does not run a TURN server and does not promise one.

7. **A session that cannot establish says so, naming the reason.** `IceDiagnostics.tsx` exists
   because this fails in the field, and behind symmetric NAT with no TURN configured it will fail
   for reasons no amount of retrying fixes. The failure is reported as a connectivity result, not
   as a spinner.

8. **Sessions stay in process, and that is stated rather than assumed.** They are ephemeral by
   nature — a code, some peers, a conversation — and persisting them would mean a table, a
   lifecycle and a cleanup job for something that ends when everyone leaves. The consequence is
   that a server restart ends every session, and a multi-worker deployment would need this
   revisited.

## Alternatives Considered

**Keep the relay and document it.** It works today, it costs nothing to leave alone, and a public
relay is genuinely easier for a guest who has no account and no access to the host's network —
which is most guests. Rejected on the premise in point 2, and it should be said that this is a
values decision rather than a technical one: the relay is not broken, it is just not ours. The
honest cost is recorded in the Consequences.

**Fix the fallback instead — point same-origin at a revived backend, keep the relay as an
override.** The smallest change that makes development builds work, and it preserves the guest
story. Rejected because it leaves two signalling paths, one of which is chosen by a build argument
nobody sets deliberately, and the difference between them is invisible at runtime. Two paths where
one is a silent default is how this became hard to see in the first place.

**Signal over polling or SSE instead of a WebSocket, so the backend keeps having no long-lived
connections.** This was investigated on the strength of `backend/app/services/outputs.py:173`,
which describes signalling *"to the frontend via WebSocket"* — but that is a docstring for a route
that does not exist, so there was nothing to reuse and the choice is between a socket and no
socket. Rejected: WebRTC signalling is a bidirectional negotiation with sub-second latency
requirements, offer and answer and a stream of ICE candidates in both directions. SSE is one-way
and polling would make handshake latency the dominant cost of joining. The 12-second handshake
timeout in `useListeningSession.ts` exists because this is already tight.

**Delete listening sessions properly rather than reviving them.** Defensible: it was shelved once
for scope, nothing in the repo suggests it is used, and the panel currently 404s in development
without anyone noticing. Rejected because the feature is being asked for on the Apple clients
([ADR-0037](ADR-0037-the-apple-clients-host-and-join-listening-sessions.md)), and reviving it
correctly is the prerequisite for that. If it were not wanted, deleting it would be the right
answer and this ADR would say so.

**Use a hosted signalling service — Ably, Pusher, a managed WebRTC provider.** Removes the socket,
the session manager and the TURN question in one step, and is what most products do. Rejected for
the same reason as the relay, and more strongly: a third-party dependency for the one path that
carries listeners' identities and messages.

## Consequences

- **Positive:** The one feature routing through infrastructure the listener does not run stops
  doing so. A self-hosted install becomes self-hosted in full.
- **Positive:** Development builds stop 404ing. The feature has been broken in `pnpm dev` since
  2026-03-06 and nothing said so.
- **Positive:** The Apple clients get a signalling endpoint on the server they are already
  configured against, with the profile they already hold — which is what makes ADR-0037 tractable.
- **Positive:** A tag that was already written, already typed and already tested comes back rather
  than being designed again.
- **Tradeoff:** **Guests must be able to reach the host's server.** This is the real cost of point
  2 and it is significant: today a share link works from anywhere, and afterwards it works only for
  someone who can reach a Familiar instance — over Tailscale, a tunnel, or a public address. For a
  listener whose server is on a home NAS behind a router, inviting a friend becomes a networking
  problem.
- **Tradeoff:** Every host now needs to answer the TURN question themselves. The relay presumably
  had one; a NAS does not, and point 7 means the failure will be visible rather than mysterious —
  but it will be more common.
- **Tradeoff:** Point 8 means a deploy ends every session in progress. On a server that redeploys
  with `make deploy-dev` during ordinary work, that is not rare.
- **Follow-up:** `docs/LISTENING_SESSIONS.md` was 601 lines and went with the shelving. Whether it
  returns, or is replaced by this ADR plus something shorter, is unresolved.
- **Follow-up:** `/listen/{code}` is not a route in `App.tsx`. A share link needs somewhere to land,
  and the shelved `GuestListener.tsx` (475 lines) is what used to be there.
- **Follow-up — done, 2026-08-09.** `familiar-sessions.fly.dev` was a second Fly application in the
  project's footprint. This ADR shipping is what orphaned it; it was destroyed the same day and the
  hostname no longer resolves. [ADR-0038](ADR-0038-the-demo-server-is-always-on.md) point 8 is where
  the Fly footprint is accounted for, and it is now one app.
