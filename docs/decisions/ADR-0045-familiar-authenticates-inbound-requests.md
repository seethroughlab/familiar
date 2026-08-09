# ADR-0045: Familiar Authenticates Inbound Requests

Status: accepted

Date: 2026-08-07

Implementation:
- Accepted 2026-08-08 alongside [ADR-0043](ADR-0043-the-llm-surface-is-an-mcp-server.md) and
  [ADR-0044](ADR-0044-mcp-clients-actuate-playback-through-a-command-channel.md).
- **Five things were raised on acceptance that this ADR does not currently cover.** Recorded here
  rather than smuggled into the Decision, because each is arguably its own scope:
  1. Point 2 — closing the 158 operations — is the actual project. The token is a day's work; the
     allowlist in `lint_profile_contracts.py` spans ~30 modules.
  2. **Point 5 breaks the demo server.** [ADR-0038](ADR-0038-the-demo-server-is-always-on.md) runs a
     deliberately public instance with one shared profile so App Store reviewers can sign in. How it
     is exempted must be decided before point 5 ships, or a submission fails.
  3. Rate limiting is keyed on client IP (`app/api/ratelimit.py`). Once a token exists it is the
     better key — an MCP host behind CGNAT otherwise shares a bucket with strangers.
  4. **One shared token means no attribution.** Anyone holding it can act as any profile and the
     logs cannot say which client did what. Accepted deliberately, consistent with profiles being a
     convenience rather than a boundary.
  5. Rotation and revocation must exist from the start. A token that can only be changed by editing
     JSON on the NAS is a token nobody rotates.
- **Phase 1 shipped: the token exists and the gate is built, off until a token is configured.**
  `app/api/auth.py`, `app/api/routes/auth.py`, issue/read/rotate/revoke, and 23 tests. Enforcement
  is deliberately inert on an unconfigured server, because turning it on before any client can
  present a token takes the library offline rather than securing it. Point 5 — on by default, refuse
  a non-loopback interface without one — is a later phase and still blocked on the demo-server
  question in note 2 above.
- **Point 7 paid for itself, and corrects this ADR's own Context.** The Context describes the
  shelved Subsonic work as *"per-user bcrypt-hashed credentials"*. It stored
  `subsonic_credentials.password_token` — **the plaintext** — in the column beside the bcrypt hash,
  because the Subsonic protocol verifies `md5(password + salt)` and so cannot use a one-way hash.
  The hash guarded a secret sitting in the next column. The precedent is therefore weaker evidence
  than the Context implies, and nobody should re-derive it as a model.
- **Point 8 is settled: `bcrypt` is removed.** Not merely because nothing imported it — it was a
  dependency with one comment referring to a deleted API — but because it is the wrong primitive.
  bcrypt is deliberately slow to make guessing a *human-chosen* secret expensive. This token is 256
  bits from `secrets.token_urlsafe`; guessing is not the threat, and `hmac.compare_digest` is what
  the comparison needs.
- **Point 2's count conflates two axes, and only one of them is 160 units of work.** The number is
  real and has grown — **160 unauthenticated operations of 264 today, against the 158 recorded at
  write time**, which is this ADR's argument about permanent allowlists making itself. But
  *authentication* ("does the caller hold the token") is not per-operation here: one middleware
  gates every `/api/` path and `/mcp`, and the honest OpenAPI expression is a global `security`
  block, which the spec had never had at all. That is done, and it covers all 267 operations at
  once. *Profile scoping* ("which profile may this act as") is the per-operation half, is what
  `lint_profile_contracts.py`'s 30-module allowlist tracks, and is the genuinely large and dull
  remainder. Kept separate so the work cannot look finished while half of it has not begun.
- **The gate is a middleware because `/mcp` is not a route.** `MCPDispatch` answers before the
  router, so a router dependency would have protected all 264 REST operations and left the one
  endpoint ADR-0043 exists to expose as the only open door. Its position in `main.py` is load-bearing
  in three directions: inside CORS (preflight is answered, not refused opaquely), inside
  `RequestIDMiddleware` (a 401 correlates to a log line), outside `MCPDispatch` (`/mcp` is checked).
  Verified end to end — an unauthenticated `/mcp` returns **401 rather than the 400** it returns when
  the MCP app handles it.
- **Revocation was a silent no-op and is now tested.** `AppSettingsService.update` skips `None`
  values unless the key is declared nullable, so `update(access_token=None)` returned success and
  changed nothing — an operator would have read "revoked" while the old token kept working. This is
  the shape worth remembering: the acceptance note asking for rotation *and revocation* from the
  start was right, and the danger was not that revocation would be missing but that it would appear
  to work.
- **Acceptance note 2 is resolved: the demo server opts out explicitly, with
  `FAMILIAR_ALLOW_UNAUTHENTICATED=1`.** Decided 2026-08-09. Point 5 would otherwise refuse to listen
  on a non-loopback interface with no token and take
  [ADR-0038](ADR-0038-the-demo-server-is-always-on.md)'s public instance down, failing an App Store
  submission. The variable is set only in the demo's compose file, so **the demo declares itself
  insecure on purpose and every other install fails closed.** Chosen over publishing a real token in
  the App Store Connect review notes — which needs no exemption mechanism at all, but makes a
  working credential to Jeff's demo instance a permanent published string that rotating would
  require a metadata update to propagate. An env var is auditable in one `grep`, and a self-hoster
  who sets it has made a choice rather than inherited a default. **The startup refusal must name the
  variable**, or the first person to hit it will conclude the upgrade is broken rather than that it
  is working.
- **TLS stays out of scope, deliberately.** The application enforces none today; Tailscale provides
  it. Making Familiar safe to expose *without* Tailscale would pull termination, certificates and
  renewal into the product, which is the step from music player to hosting product that
  ADR-0038 point 7 declines.

Extends [ADR-0043](ADR-0043-the-llm-surface-is-an-mcp-server.md)

## Context

[ADR-0043](ADR-0043-the-llm-surface-is-an-mcp-server.md) point 7 confines the MCP server to
Tailscale and localhost, because hosted third-party clients cannot reach it and making them able to
is a larger decision. This is that decision.

**Familiar has no inbound authentication.** Verified against the repo at write time:

- The entire auth surface is an `X-Profile-ID` header (`backend/app/api/deps.py`). `profile_header`
  is declared as an `APIKeyHeader` only so it reaches the OpenAPI schema; both dependencies read the
  raw header. There is no token, key, bearer, session or cookie anywhere inbound. Every credential
  in `config.py` — `anthropic_api_key`, `lastfm_api_key`, `openai_api_key`, `s3_backup_*` — is
  outbound.
- **The profile ID is not a secret.** `GET /api/v1/profiles` returns every profile *including its
  ID*, with no security requirement; `POST /api/v1/profiles` creates one, also unauthenticated.
  Anyone who can reach the port can enumerate every profile and then act as any of them.
- **158 of the 261 operations in the committed `openapi.json` carry no security requirement at
  all**, and there is no global `security` block. Among them: `PUT` and `DELETE
  /api/v1/profiles/{profile_id}` (edit or delete any profile without holding it), all three
  `settings` operations, all thirteen `s3-backup` operations, all twenty-four `outputs` operations,
  `POST /api/v1/library/sync`, `DELETE /api/v1/library/missing/batch`, and
  `PATCH /api/v1/tracks/{track_id}/metadata`.
- `backend/scripts/lint_profile_contracts.py` does enforce `RequiredProfile` on mutating routes, but
  carries a 30-module `ALLOWLISTED_MODULES` set — which is where those 158 live. **The gap is
  known, allowlisted and unmeasured**, which is how it stayed at 158.
- CORS (`app/main.py:365-374`) sets
  `allow_origin_regex=r"^(https?|capacitor)://([a-zA-Z0-9-]+|\d+\.\d+\.\d+\.\d+)(:\d+)?$"` with
  `allow_credentials=True` and `allow_headers=["*"]`. Any single-label hostname or bare IPv4 on any
  port is an accepted origin, and since the client supplies `X-Profile-ID` itself, **there is no
  credential for a browser to withhold**.
- Nothing binds to loopback. `backend/Makefile` runs `uvicorn --host 0.0.0.0`, and
  `docker/docker-compose.prod.yml:59-60` publishes `${API_PORT:-4400}:8000` on all interfaces.

**The security model is written down, and it is a deployment convention.**
`packages/frontend/src/services/profileService.ts:5` states it: *"No passwords needed - protected by
Tailscale."* `docs/CONFIGURATION.md` recommends `tailscale serve`. Nothing in the application
enforces or checks it. If the host's firewall is open, so is the library.

**This is a finding about Familiar as it is today, not a risk created by ADR-0043.** The MCP server
does not widen it — it runs behind the same tailnet. What ADR-0043 does is make the question
unavoidable, because "any LLM can do this" is only true if the LLM can reach the server.

**The premise that most needs checking is whether public exposure is wanted at all.**
[ADR-0038](ADR-0038-the-demo-server-is-always-on.md) point 7 is explicit: *"This is a review and
demonstration server. It is not hosted Familiar. No user accounts, no uploads, no expectation of
durability, and no growth into a service. Familiar is self-hosted software."*
[ADR-0036](ADR-0036-listening-sessions-signal-through-familiars-own-server.md) point 2 retires an
external relay on the same principle — *"a self-hosted music player should not route its listeners'
session codes, chat and reactions through infrastructure the listener does not run"*. A NAS on the
public internet serving a personal library to a hosted third party is in tension with both, and this
ADR says so rather than treating reach as self-evidently good.

**There is direct precedent for the shape of this.** `d36c906` added a Subsonic API "for CarPlay and
native music app support", with per-user bcrypt-hashed credentials in a `subsonic_credentials`
table — the only inbound credential this project has ever had. `bc53ef0` shelved it to
`feature/subsonic-api` and `migrations/versions/20260306_drop_subsonic_creds.py` dropped the table.
The `bcrypt` dependency in `backend/pyproject.toml` is all that remains, and the real code is at
`feature/subsonic-api`'s deletion commit rather than on the branch tip.

## Decision

1. **Familiar authenticates inbound requests with a token, and the token is server configuration.**
   It is issued and revoked in the admin UI and lives in `data/settings.json` beside the outbound
   credentials. Under [ADR-0029](ADR-0029-the-server-stores-no-listener-preferences.md) point 2 this
   is unambiguously category one — the server acts on it with no client present — so it raises none
   of that ADR's device-local questions.

2. **Every operation carries a security requirement, and the allowlist goes to zero.** The 158
   unauthenticated operations are closed and `ALLOWLISTED_MODULES` in `lint_profile_contracts.py`
   empties. **A burn-down list is acceptable; a permanent allowlist is what produced 158.** This
   follows [ADR-0007](ADR-0007-clients-are-generated-from-openapi.md) point 6's rule that
   regressions must fail a build, applied to authorisation rather than to schema.

3. **The profile header stops being an authorisation claim.** It continues to select *which* profile
   a request acts as, and the token decides whether the request may act at all. Keeping the header
   is what makes this change small: no client's profile handling changes, and `GET /profiles` can
   stay listable because listing is no longer sufficient to act.

4. **CORS narrows to configured origins.** The single-label-and-any-IPv4 regex goes. Local
   development origins and `FRONTEND_URL` stay; anything else is configured explicitly. With
   `allow_credentials=True` and a real credential in play, a permissive origin regex stops being
   theoretical.

5. **Authentication is on by default, and a server with no token configured refuses to start
   listening on a non-loopback interface.** An install that is secure only if the operator reads
   `docs/CONFIGURATION.md` is the arrangement this ADR exists to end. The Tailscale deployment
   remains recommended and becomes defence in depth rather than the whole defence.

6. **Tailnet-reachable MCP is unblocked by this ADR. Hosted third-party MCP is not.** Points 1–5
   make the server safe to expose; they do not make it exposed. Remote MCP for a hosted client
   requires OAuth with dynamic client registration, a public HTTPS endpoint and a consent surface —
   a different mechanism from a static token, aimed at a different threat model. **It gets its own
   ADR, and that ADR has to answer ADR-0038 point 7 first.**

7. **The shelved Subsonic credential code is read before anything is written.** It solved the same
   problem in this codebase and was removed for scope rather than for a fault. Whether it is revived
   or not, it is evidence about what fits here, and it is at the deletion commit's parent rather
   than at the branch tip.

8. **`bcrypt` is kept deliberately or removed deliberately.** It is currently a dependency whose
   only justification is a comment referring to an API that no longer exists.

## Alternatives Considered

**Do nothing and keep relying on Tailscale.** It has worked, the threat model for a home NAS is
genuinely modest, and it costs nothing. Rejected because it is not enforced anywhere in the
application: the same code runs on `0.0.0.0` in Docker with a published port, and the only thing
between a personal library and the internet is a firewall the application knows nothing about. It
also cannot be the answer for ADR-0043 point 7's public half, and the 158 operations mean the
blast radius is the whole server rather than one profile.

**Per-profile passwords, as the Subsonic API had.** Closest to a conventional design, already
prototyped in this codebase, and it would let profiles genuinely protect each other. Rejected as
the wrong first step: Familiar's profiles are a Netflix-style convenience for people who already
share a house, not a security boundary, and turning them into one imposes a login on every client
for a threat that does not exist inside the tailnet. Point 3 keeps the profile a selector; if
profiles ever need to be a boundary, that is a separate decision.

**Bind to loopback and require a reverse proxy to add authentication.** Zero application code, and
it is how a lot of self-hosted software handles this. Rejected because it moves the requirement out
of the product and into the operator's nginx config, where nothing verifies it — a variant of the
failure this ADR is fixing. It also breaks the LAN and Tailscale access that every client depends
on today.

**mTLS or a Tailscale-identity header instead of a token.** Stronger than a bearer token and, with
`tailscale serve`, nearly free. Rejected because it binds the product to one deployment topology.
Familiar runs in Docker on machines with no Tailscale, and an MCP host that speaks HTTP with a
header is the lowest common denominator that works everywhere.

**Scope this to the MCP endpoint only** — authenticate `/mcp` and leave the REST API as it is.
Much smaller, and it unblocks ADR-0043 immediately. Rejected because it protects the new door on a
building with 158 open windows, and because the MCP tools call the same handlers the REST API
exposes. It would let the change look complete while changing nothing about the actual exposure.

## Consequences

- **Positive.** The gap between the documented security model ("protected by Tailscale") and the
  enforced one (nothing) closes, and it closes in the application rather than in a deployment guide.
- **Positive.** Point 2 makes the 158 measurable and falsifiable. It is a number that can go to zero
  and stay there, checked by the linter that already exists.
- **Positive.** ADR-0043's MCP server becomes safe to reach from anything on the tailnet without
  each new client re-opening the question.
- **Tradeoff.** Every client gains a credential to hold, configure and get wrong — the web app,
  both Apple clients, and any MCP host. Point 3 keeps the profile handling unchanged, which is what
  stops this being a rewrite, but "it stopped working after the update" is the predictable outcome
  and needs a migration story as deliberate as ADR-0029's seed.
- **Tradeoff.** Point 5 will break existing installs on upgrade, by design. A server that silently
  kept listening unauthenticated would defeat the point, and a server that refuses to start is a
  worse first impression than any of the alternatives — the shape of that failure needs care.
- **Tradeoff.** Point 2 touches 158 operations across roughly 30 modules. This is the largest
  mechanical change in the current ADR set and it is not interesting work.
- **Tradeoff.** A shared token authenticates the *client*, not the *person*. Anyone holding it can
  act as any profile. That is a deliberate match to what profiles already are and would be wrong the
  moment profiles became a boundary.
- **Follow-up.** Hosted third-party MCP — OAuth, public HTTPS, consent — is explicitly out of scope
  per point 6 and needs its own ADR, which must first answer whether ADR-0038 point 7 permits it at
  all.
- **Follow-up.** `docs/CONFIGURATION.md` and `profileService.ts:5` both state the old model and both
  become wrong on the day this lands. ADR-0038 point 3 is the precedent: a document kept as intent
  after the implementation diverged is read as fact.
- **Follow-up.** The demo server (ADR-0038) is deliberately public with a shared profile. How point
  5 applies to it needs deciding, or the demo stops working the day this ships.
