# ADR-0171: A Remotely Reachable Server Requires an Authentication Token

Status: proposed

Date: 2026-11-08

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
