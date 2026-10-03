# ADR-0145: Remote Access Is Explained by What the Token Does Not Cover

Status: accepted

Date: 2026-10-03

Implementation:
- **Accepted 2026-10-03**, as written.
- **Built 2026-10-03.** `site/index.html` `#remote`: the note leads with "Sign-in covers the library,
  not the music", the three facts, and the recommendation; Tailscale's paragraph gains the encrypted
  connection and stops at the server's `ts.net` address; the reverse-proxy warning is restated; the
  ADR-0045 footnote is gone. `docs/SITE-CLAIMS.md`: the no-login row removed, a sign-in row with
  this ADR's expiry, the reverse-proxy row restated. `site/e2e/toggle.spec.ts` asserts the new
  sentence, that "Familiar has no login" is nowhere in `<main>`, and that the section says nothing
  about what an app is told.

Supersedes points 2 and 6 of [ADR-0096](ADR-0096-remote-access-is-explained-not-instructed.md), and
extends [ADR-0141](ADR-0141-every-new-server-starts-with-a-token.md) and
[ADR-0143](ADR-0143-the-install-section-is-a-three-step-chooser.md)

## Context

ADR-0096 built the site's "Listening away from home" section on one fact: **Familiar has no
login**, so anything that can reach a server can use it, and "don't port-forward 4400" is the
difference between a private server and a public one. Its point 6 set the expiry itself: when
ADR-0045's token ships, the section and its `docs/SITE-CLAIMS.md` row are revisited.

**That has happened, so the section is now wrong.** The token gate exists (`backend/app/api/auth.py`);
ADR-0134 made the Apple clients send it; and since ADR-0141 every new server mints one at first
start, so a new server answers its API with 401 until signed in. The page still says, as of
2026-10-03:

- "**Familiar has no login.** There are no accounts and no password" — false for every server set
  up since ADR-0141, and for any older one whose owner created a token.
- "open the app and it finds your server" — a new server must be **paired** (ADR-0134); finding it
  is not enough. Pairing with Familiar Server has not yet been run end to end (ADR-0143 point 8).
- "Your apps then use `https://<server>.<tailnet>.ts.net`" — how a paired app is pointed at a second
  address, the tailnet's, has not been run either.
- A footnote saying authentication is "not yet built", linking ADR-0045.

**But the recommendation does not change, because the reason it rests on has moved, not gone.**
What the token does not cover, read from the code on 2026-10-03:

- **Music and artwork are served without it, on purpose.** `MEDIA_ROUTES` (`auth.py:98`) exempts
  `GET`/`HEAD` on track streams, artwork, artist images, video streams and posters, and avatars,
  because a WiiM or Sonos fetching a stream for itself, an `<img>`, and the Apple app's audio player
  cannot present a header. Stream URLs are keyed by v4 UUIDs, which cannot be enumerated with the
  rest of the API closed; album artwork is keyed by `sha256(artist|album)`, which can be derived,
  so it answers "is this album in the library?" — the exemption's one recorded leak.
- **The server speaks plain HTTP.** Nothing in `app/serve.py`, the image or Familiar Server
  configures TLS; HTTPS comes from what is in front of it — `tailscale serve`, as the section has
  recommended since ADR-0096. A
  token sent over port-forwarded HTTP can be read by anything on the path.
- **A server set up before ADR-0141 has no token unless its owner made one.** ADR-0141 point 3 keeps
  such servers serving, and warning.

So the honest sentence is no longer "there is no lock"; it is "the lock covers the library, not the
music, and it is only as private as the connection it travels over."

## Decision

1. **The section leads with what sign-in does and does not cover, stated once.** A new server asks
   for sign-in. The music and artwork are served without it, so speakers and the apps' players can
   fetch them; the server speaks plain HTTP; and a server set up before October 2026 may have no
   sign-in at all. From those three, the recommendation follows: keep it private, and let your own
   devices in. This replaces ADR-0096 point 2's "Familiar has no login", in ADR-0096 point 7's
   register: no scare copy, no adjectives.

2. **Tailscale stays the recommended default, and gains a reason.** ADR-0096 point 3's reasons hold,
   and there is a new one: it encrypts the connection, so the token is private on the way, and
   `tailscale serve` gives the HTTPS the server does not.

3. **The reverse-proxy warning is restated for a server that has a token.** An HTTPS proxy keeps the
   token private in transit, but it does not cover the music, which needs no token. A proxy that
   adds a login of its own covers everything, and the apps and speakers cannot answer it. Either way
   a proxy does not make Familiar safe to publish. ADR-0096 point 4's distinction, with the reason
   brought up to date.

4. **The section says nothing about what to type into an app, or how an app finds a server, until
   that has been run.** It describes making the server reachable over Tailscale and stops there.
   This is ADR-0143 point 8 applied here: pairing with Familiar Server, and pointing a paired app at
   a tailnet address, are written up once each has been done end to end, in one place.

5. **The footnote linking ADR-0045 as "not yet built" goes.** Nothing replaces it: the sign-in that
   exists is described in point 1.

6. **The new expiry names what the wording depends on** (replacing ADR-0096 point 6). Its
   `docs/SITE-CLAIMS.md` row records that it depends on the media exemption (`MEDIA_ROUTES`) and on
   the server speaking plain HTTP. If media is ever gated, or the server terminates TLS itself, the
   section is revisited — a scheduled edit, as before.

7. **Kept from ADR-0096:** its own section after Install (point 1), the alternatives listed (point 4),
   nothing about Tailscale's pricing or plans that has not been checked (point 5), and the register
   (point 7).

## Alternatives Considered

- **Now that there is a token, drop the warning, or allow port-forwarding behind it.** The simplest
  page, and it would read as progress. Rejected: the token does not cover the music, and over plain
  HTTP it is readable in transit. Saying "it has a login now" without both would be the vagueness
  ADR-0096's Alternatives already rejected, in the other direction.
- **Keep "Familiar has no login" until every server has a token.** True of servers set up before
  ADR-0141. Rejected: it is false of every new one, and the install section on the same page now
  ends every path signed in. The page would contradict itself one screen apart.
- **Describe the whole away-from-home setup, app included.** The most useful page, if it were true.
  Rejected for point 4's reason: pairing over Tailscale has not been run, and the section's current
  `ts.net` sentence is exactly the kind of untried instruction ADR-0143 point 8 holds back.
- **Gate the music, or make the server terminate TLS, and keep the page simple.** Each would remove
  one of the three facts. Rejected as the answer *here*: both are server decisions with their own
  costs — gating media breaks every speaker and the Apple players (ADR-0045's own record), and TLS
  needs certificates the operator must manage — and a page decision should not make them. Named as
  follow-ups.

## Consequences

- **Positive:** the page stops saying something false about every new server, and still gives the
  reason for its strongest recommendation.
- **Positive:** the reverse-proxy trap is described as it now is. With a token, a careful person is
  more likely to think a proxy is enough, not less.
- **Tradeoff:** the section names the media exemption and the album-artwork oracle on a public page.
  Both are in the repository already, and stating them is what makes the recommendation make sense
  — ADR-0096's argument, unchanged.
- **Tradeoff:** the section stops short of telling a reader how to connect the app from away. It is
  less complete until pairing over Tailscale has been run.
- **Follow-up:** run pairing over Tailscale end to end — a paired phone on cellular reaching
  Familiar Server and a Docker server through `tailscale serve` — and write the app's half once,
  shared with ADR-0143's step 3.
- **Follow-up:** the album-artwork oracle (ADR-0134's follow-up, artwork behind signed URLs) and a server that terminates
  TLS itself are server decisions, each needing its own ADR.
