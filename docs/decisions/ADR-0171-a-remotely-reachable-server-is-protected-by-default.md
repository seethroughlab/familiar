# ADR-0171: A Remotely Reachable Server Requires an Authentication Token

Status: accepted

Date: 2026-11-08

Implementation:

- **Phases 1 and 2 built 2026-11-09.** `backend/app/exposure.py` is the one policy: `decide()` is the
  start-up decision (`Start.LOOPBACK` added), `exposure_for()` says what it means for a tokenless
  request, and `request_is_local()` is the request rule (loopback peer, loopback `Host`, no
  `Forwarded`/`X-Forwarded-For`/`X-Real-IP`). `app.serve` records the decision in-process; a server
  started without it (bare `uvicorn`) gets LOCAL unless `FAMILIAR_OPEN_SERVER` is set. Docker,
  Familiar Server and `python -m app.serve` all start through `app.serve.main`, so point 2's one
  function is that one. `tests/test_exposure.py` is the matrix; 12 of its cases fail against the
  previous `TokenAuthMiddleware`.
- **Point 1:** a new reachable server mints a token (ADR-0141, unchanged). A tokenless server that
  is not open answers only its own machine, and cannot be claimed (`POST /api/v1/auth/token`) from
  anywhere else.
- **Point 4:** an existing tokenless library is grandfathered as OPEN and warns at every start; it
  is not locked out. Recovery is `python -m app.token --create`; `DELETE /api/v1/auth/token` from
  another machine is refused where it would lock the caller out. `docs/INSTALLATION.md`, "The
  server token", covers finding, making, rotating, removing, reverse proxies, MCP and rollback.
  **Not done:** an upgrade-and-recovery drill on a real installation. The exit condition needs one.
- **Point 7:** a LOCAL tokenless server refuses a non-loopback `Host`, which is the DNS-rebinding
  case. An OPEN tokenless server refuses `/mcp` unless `MCP_ALLOWED_HOSTS` is set, which turns on
  FastMCP's own protection. With a token, `/mcp` needs the token, which a rebinding page cannot
  supply.
- **Point 5:** media is untouched. `docs/HEALTH.md` keeps the artwork entry for Phases 3–4.
- **Found while building:** the web admin has no rotate or remove control. Both exist only as
  `POST`/`DELETE /api/v1/auth/token`, and the docs say so. The Overview's "open to anyone" warning
  also shows on a LOCAL tokenless server, where only this machine can reach it. Telling them apart
  needs a field on `TokenStatus`, a schema change left for a follow-up.

Extends [ADR-0045](ADR-0045-familiar-authenticates-inbound-requests.md) and
[ADR-0141](ADR-0141-every-new-server-starts-with-a-token.md)

## Context

The Mac server starts with a token, and `python -m app.serve` refuses a LAN bind without one.
Docker still permits a tokenless installation. `TokenAuthMiddleware` deliberately passes every
otherwise protected request when no token is configured, so a published Docker port can expose the
full server.

ADR-0045 exempts media GET and HEAD requests because artwork elements, Apple clients, WiiM, Sonos,
and other consumers cannot all attach the normal header. Track and video URLs contain unpredictable
UUIDs, but album artwork can be addressed by a hash derived from artist and album names. It remains
an oracle over the collection after the main API receives a token.

## Decision

1. A new server reachable beyond loopback has an access token. Docker generates one on first start
   or refuses the remote bind; absence of a token is not public mode.
2. Docker, `python -m app.serve`, and the Mac server use one policy function and test matrix for
   bind address, token presence, trusted proxies, and existing installations.
3. Explicit loopback development may remain tokenless and identifies itself clearly.
4. Existing installations are not silently locked out. Token discovery, rotation, re-pairing,
   recovery, reverse-proxy configuration, and rollback are documented before the default changes.
5. Main API authentication and media authorization are separate milestones. Enabling the first
   does not remove the artwork exposure from `docs/HEALTH.md`.
6. A focused follow-up ADR chooses signed or scoped media access and covers expiry, ranges, caches,
   delayed casting fetches, browser artwork, rotation, and credential-safe logs.
7. Remotely reachable MCP deployments enable DNS-rebinding/Host protection or refuse startup.

## Phased Delivery

1. **Policy:** centralize reachability checks and add the launcher test matrix.
2. **Docker:** generate a token or refuse exposure, with upgrade and recovery documentation.
3. **Media:** accept the follow-up authorization ADR and migrate clients compatibly.
4. **Close:** remove enumerable media access and the health-register entry.

**Exit condition:** tests prove every remotely reachable new installation is protected, an upgrade
and recovery drill succeeds, Host protection is effective, and residual media exposure is removed
or governed by an accepted, scheduled ADR.

## Alternatives Considered

**Always require a token, including loopback.** Rejected because it adds development friction
without changing the remote boundary.

**Keep Docker opt-in and improve warnings.** Rejected because compose warnings are easy to miss and
the consequence is a public administration API.

**Gate media with the current header immediately.** Rejected because real consumers cannot all
attach it; this would break playback and artwork while appearing safer.

## Consequences

- **Positive:** the easiest installation path is no longer the least protected.
- **Positive:** every launcher applies the same rule.
- **Tradeoff:** upgrades and pairing require compatibility work.
- **Tradeoff:** expiring media access is harder for casting and caches.
- **Follow-up:** write the media authorization ADR in Phase 3.
