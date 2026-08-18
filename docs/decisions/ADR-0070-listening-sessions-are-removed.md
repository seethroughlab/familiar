# ADR-0070: Listening Sessions Are Removed

Status: proposed

Date: 2026-08-18

Supersedes [ADR-0036](ADR-0036-listening-sessions-signal-through-familiars-own-server.md), which
built the server half. Closes the question [ADR-0037](ADR-0037-the-apple-clients-host-and-join-listening-sessions.md)
left open when it was rejected. Extends [ADR-0058](ADR-0058-the-web-app-is-an-administration-tool.md)
by removing the last listening surface from the administration tool.

## Context

Listen-together is the one capability the browser holds because an ADR decided it should, rather
than because nothing native does it yet. `ADR-0036` moved signalling into Familiar's own server;
`ADR-0037` would have had the Apple clients host and join, and was **rejected** on 2026-08-06. So
`ADR-0057` point 2 lists it as one of exactly two exceptions to "the browser keeps a capability only
while it has no native answer", and `ADR-0060` point 1 makes it the standing example of a row
excluded from the player's removal countdown by decision.

**What has changed is what the browser is.** `ADR-0058` made it an administration tool with three
destinations, and the fallback player's removal condition is now met. When that lands, `/listen/:code`
is the only route in the application that plays music to anybody. An administration tool that also
streams audio to guests is two products sharing a bundle, and no amount of routing it outside the
shell changes that.

**The generated Swift surface has carried this feature for a consumer that was decided against.**
`ADR-0036` point 5 added the `sessions` tag to the generated surface *in anticipation of* `0037`.
`0037` was rejected twelve days ago and the tag stayed. Both places that record it still describe
that rejected decision in the present tense:

- `familiar-apple/Sources/FamiliarAPI/openapi-generator-config.yaml:38` — *"ADR-0037 has the Apple
  clients host and join them"*
- `backend/scripts/lint_openapi.py:75` — *"Listening sessions (ADR-0036, consumed by ADR-0037)"*

Neither is true, and the schema shows it: `/api/v1/sessions/by-code/{code}` and
`/api/v1/sessions/ice-servers` are the two generated operations, and **neither has a caller in either
repository**. The one endpoint that does have callers — `WebSocket /sessions/ws` — is not in the
schema at all, which `ADR-0036` point 5 states deliberately. The generated half is dead code and the
live half is invisible to the contract.

**The feature is cleanly bounded.** `ADR-0036` point 8 said sessions "stay in process, and that is
stated rather than assumed", and it held: `SessionManager` keeps `self._sessions: dict[str, ListeningSession]`
in memory (`backend/app/services/sessions.py:88-92`). There is no model, no table and no migration
to unwind.

| | lines |
|---|---|
| `backend/app/api/routes/sessions.py` | 520 |
| `backend/app/services/sessions.py` | 319 |
| `backend/tests/test_api_sessions.py` | 221 |
| `packages/frontend/src/hooks/useListeningSession.ts` | 645 |
| `packages/frontend/src/components/Guest/` | 488 |
| `packages/frontend/src/components/Sessions/` | 479 |
| `packages/frontend/src/hooks/useWebRTCStreaming.ts` | 354 |
| | **3,026** |

## Decision

1. **Listening sessions are removed, both halves, in one change.** The route and its WebSocket, the
   in-process session manager, the guest listener at `/listen/:code`, the host panel, the WebRTC
   hook and the tests. This is `ADR-0057` point 5 — a capability and its affordances leave together —
   applied to a capability rather than to a link.

2. **The `sessions` tag leaves the generated surface, and that is a deletion of dead code rather
   than a loss of reach.** It goes from `filter.tags` in the generator config and from `VENDORED_TAGS`
   in `lint_openapi.py`, in the same change, as `ADR-0014` point 4 requires. No Swift call site
   changes, because there are none.

3. **The two stale comments are deleted with the entries they annotate**, rather than corrected.
   A comment asserting that a rejected ADR is live is worse than no comment, and this one survived
   twelve days precisely because it sat beside a config key nobody had reason to read.

4. **TURN configuration goes with the feature.** `settings.turn_server_url`, `turn_server_username`
   and `turn_server_credential` (`backend/app/config.py:67-69`) exist only to serve
   `/sessions/ice-servers`. `ADR-0036` point 3 deleted `VITE_SESSIONS_RELAY_URL` rather than
   defaulting it, for the reason that a configuration key outliving its consumer is a trap; the same
   reasoning applies to its own keys now.

5. **`ADR-0060`'s first exclusion rule keeps its wording and loses its only member.** The rule —
   "excluded by decision" — is still correct and still needed; the list it points at becomes empty.
   The row leaves `docs/WEB-PARITY.md` with the capability, in the same commit, under `ADR-0057`
   point 5. `ADR-0060` point 3's requirement that a *new* exclusion needs an ADR is untouched.

6. **`ADR-0036` is superseded rather than reversed on its merits.** Its premise — that a listening
   session should not depend on a third-party relay — was right and is not in dispute. What changed
   is the surface it was built on, so the record should read as a product decision about the browser,
   not as a finding that the signalling design was wrong.

## Alternatives Considered

**Keep it, and document why it is there.** The cheapest option: leave `/listen/:code` outside the
admin shell with a comment and an ADR line saying it is a deliberately-hosted listening surface. It
was rejected because the goal is that the *organization* answers a newcomer's question — a record
that explains an exception is weaker than not having the exception, and this is the only one left.

**Give it its own Vite entry point**, like `/embed` and `/visualizer`, so the admin bundle carries no
playback code. This is genuinely tidier than the status quo and was the closest call. Rejected
because it answers "where does the code live" and not "does this belong in this product": it would
preserve all 3,026 lines, the server half included, and add a fourth document to build and vendor.

**Delete the web UI, keep the server half.** Rejected on the same rule that motivates most of this
restructure — an endpoint with no client is indistinguishable from a working feature until someone
tries it, and `ADR-0036` built the server half *for* a client that no longer exists.

**Revive `ADR-0037` and build it natively.** That decision was made on 2026-08-06 with reasons that
still hold, and nothing since has changed them. Re-proposing it would need a new argument, not a new
opportunity.

## Consequences

- **Positive** — the administration tool contains no listening path at all. After this and the
  player's removal, nothing in the web app plays audio, which is the property `ADR-0058` describes
  and has not yet been able to claim.
- **Positive** — 3,026 lines go, and with them an in-process stateful service that had to be
  reasoned about separately from everything else in the backend.
- **Positive** — the generated Swift surface loses a tag that has produced dead code since
  `ADR-0037` was rejected, and the two comments asserting a rejected ADR is live go with it.
- **Positive** — `ADR-0060`'s exclusion list empties, so the player's removal trigger no longer
  depends on a row that can never clear.
- **Tradeoff** — a working capability is lost and has no other home. `ADR-0037` was rejected, so
  this is not "the native clients will pick it up"; it is a decision that Familiar does not do
  listen-together. Anyone using it loses it at the next upgrade.
- **Tradeoff** — `ADR-0036`'s work is discarded twelve days after it was decided. That is the cost
  of building a server half before its consumer was decided, and it is worth recording as such:
  `0036` point 5 widened a client contract for `0037`, which was rejected the same day `0036` was
  accepted.
- **Follow-up** — when this is accepted, `ADR-0036`'s `Status:` becomes `superseded by ADR-0070`.
  `ADR-0037` stays `rejected`; a rejected ADR whose subject is deleted needs no new status.
- **Follow-up** — `ADR-0057` point 2's "two exceptions, and they are the whole exception list" now
  has one member, the infrastructural one. The point is not edited; a later ADR that touches that
  list should note it.
