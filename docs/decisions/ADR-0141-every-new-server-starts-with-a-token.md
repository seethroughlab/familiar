# ADR-0141: Every New Server Starts with a Token

Status: proposed

Date: 2026-10-01

Extends [ADR-0045](ADR-0045-familiar-authenticates-inbound-requests.md) and supersedes its point 5;
extends [ADR-0134](ADR-0134-clients-pair-with-a-server.md)

## Context

The two forms of the server (ADR-0131 point 2) give their owners different first experiences of
the one thing that makes a server private. **Familiar Server mints a token on first run**
(`ServerController`, ADR-0134 point 2), keeps the server on loopback until the owner allows phones
to connect, and hands the token to the web admin in a link. **A Docker server has no token until
someone presses "Create server token"** in Server → Access, and until then it answers anyone who can
reach it: everything on the LAN, and everything on the tailnet.

That difference is not designed. ADR-0045 point 5 already decided that authentication is on by
default and that a server with no token refuses to listen on a non-loopback interface. Its
Implementation block records why point 5 never shipped: phase 1 made enforcement inert on an
unconfigured server, because switching it on before any client could present a token would take the
library offline rather than secure it, and point 5 was **left blocked on the public demo server**
(ADR-0038), which App Store reviewers sign into with no credentials.

Point 5 was built, but only on one path. `python -m app.serve` (ADR-0132 point 6), which Familiar
Server runs, refuses a non-loopback host without a token (`REFUSAL` in `app/serve.py`). The Docker
image never goes through it: `docker/Dockerfile` starts `uvicorn app.main:app --host 0.0.0.0`
directly, as does the demo's `deploy/fly/Dockerfile`, so the image listens on every interface with
no token and no refusal.

Two facts make the missing piece small. The web admin already signs in from a link:
`takeTokenFromFragment` (`packages/frontend/src/api/base.ts`) reads `#token=…` and removes it from
the address bar at once, which is how Familiar Server's Open Admin works. And the server already has
a signal for "this is a new installation": `_initial_import_pending` in
`app/services/tasks/library_sync.py` treats a library with no tracks as a first import.

Point 5 as written would also refuse every **existing** Docker server that has no token, including
the author's own NAS, on the upgrade that shipped it, taking its players offline until someone
created a token and re-paired each one. That consequence is why this ADR supersedes point 5 rather
than shipping it.

## Decision

1. **A new server mints its token at first start.** "New" means no token in `settings.json` and no
   tracks in the library, the same signal a first import uses. The token is made exactly as "Create
   server token" makes it today, so nothing downstream changes.

2. **The owner gets it from the server's own log, as a sign-in link.** At first start the server
   writes one line to its log: a link of the form `http://<host>:<port>/#token=…`, built from
   `FRONTEND_URL` when it is set, and otherwise with `<host>` left for the owner to fill in, since a
   container cannot know the name the owner reaches it by. Opening the link signs the web admin in,
   and the admin's existing pairing page shows the QR for phones. `python -m app.token` prints the
   link again on demand (`docker exec familiar-api python -m app.token`), so the first start's log
   line is not the only copy.

3. **An existing server without a token keeps working, and says so loudly.** It is not refused and
   not given a token on upgrade. It logs a warning at every start, and the web admin's Overview
   lists "This server is open to anyone who can reach it" as something needing attention, with the
   way to create a token. "Create server token" says, beside the button, that it switches
   authentication on for every client, and that each will need to pair once.

4. **`FAMILIAR_OPEN_SERVER=1` runs a server without a token on purpose.** No token is minted, the
   warning in point 3 becomes a single line at start saying the server is open by choice, and the
   Overview item does not appear. The demo's `deploy/fly/fly.toml` sets it, beside the
   `FAMILIAR_ALLOW_WRITABLE_LIBRARY` it already sets for the same kind of reason. That resolves the
   question ADR-0045's Implementation block left point 5 blocked on.

5. **The Docker image starts through `python -m app.serve`,** the path Familiar Server takes, so
   both forms start, migrate and decide about tokens in one place. Its refusal (`REFUSAL`) becomes
   points 1–4: it never meets a new server without a token, because point 1 mints one; it lets an
   existing server through with point 3's warning; and it lets an open server through under point 4.

## Alternatives Considered

- **The first browser to open the admin claims the server.** No log to read at all. Rejected:
  whoever on the network loads the page first owns the server, and on a tailnet that need not be the
  owner. The log is readable only by someone who already controls the machine.
- **The owner sets the token in the compose file** (`FAMILIAR_ACCESS_TOKEN`, required to start).
  Explicit and scriptable. Rejected as the default: one more thing to configure before anything
  works, and the token would live in a file that gets copied, committed and pasted into forum posts.
  An owner who wants this can still create the token and rotate it to a value of their choosing.
- **Mint a token on upgrade for every server** (point 5 as written). Immediate parity. Rejected:
  every client of every existing server, the author's players included, would answer "not
  authorised" the moment the image updated, on an upgrade nobody planned around.
- **Give the demo a token and put a sign-in link in the App Store review notes.** Nothing exempt.
  Rejected: reviewers gain a step, and a token in review notes is effectively public, which makes it
  an open server with extra ceremony.

## Consequences

- **Positive:** a new NAS server is private from its first start, as Familiar Server already is,
  and its owner signs in and pairs with one link and one scan.
- **Positive:** an existing server's owner chooses when to turn authentication on, and is told what
  it will cost before pressing the button.
- **Positive:** both forms start through one command, so a rule about starting cannot again apply
  to one and silently not the other.
- **Tradeoff:** a Docker owner has to read the container's log once (or run `app.token`). The README
  and `docs/CONFIGURATION.md` say how, in the install steps rather than a security section.
- **Tradeoff:** existing tokenless servers stay open until their owners act. Point 3 makes that
  visible; it does not end it.
- **Follow-up:** the media exemption (`MEDIA_ROUTES`, ADR-0134) keeps WiiM devices and other
  token-less players working once a server has a token; nothing here changes it.
