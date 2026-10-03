# ADR-0143: The Install Section Is a Three-Step Chooser

Status: accepted

Date: 2026-10-02

Implementation:
- **Accepted 2026-10-02**, as written. Not yet built.

Supersedes point 2 of [ADR-0095](ADR-0095-the-install-section-is-platform-first.md), and extends
[ADR-0131](ADR-0131-the-server-is-its-own-app.md)

## Context

ADR-0095 made the site's install section platform-first: one toggle, the reader picks the machine
the server runs on, and sees that path. Since then ADR-0131 split Familiar into a server and the
clients that play from it, installed and paired separately, and the page has not caught up with
any of it. Read on 2026-10-02 (`site/index.html`, section `#install`):

- **The macOS panel installs Docker Desktop.** Familiar Server, the Mac app ADR-0131 recommends to
  a new user and which needs no Docker, appears nowhere on the page.
- **Step 2 says "Familiar needs no account."** Since ADR-0141 every new server starts with a token
  and prints a sign-in link to its log; the page sends the reader to `http://localhost:4400`, which
  answers a new server's API with 401.
- **It promises "roughly 1 second per track … a 20,000-track library is ~6 hours."** On Familiar
  Server on 2026-10-02, with one worker (ADR-0138 point 4), a track took minutes, even when the
  community cache answered and nothing was analysed locally.
- **Nothing connects a client to the server just installed.** The App Store badges sit in the hero
  and the closing call to action, and the install ends at "point it at your music". How a player
  reaches its server is the one step whose instructions depend on *two* choices: a player on the
  same Mac as Familiar Server uses its "Open in Familiar"; anything else pairs with a QR code.

That last point is why a single toggle no longer fits. The reader makes two choices — where the
server runs, where they listen — and the second's instructions depend on the first.

**Not yet proven, and the third step depends on it:** a phone pairing with Familiar Server.
ADR-0134 point 2 has the server bind `127.0.0.1` until a device pairs, then reopen on every
interface (`ServerLaunch.swift`, `lan ? "0.0.0.0" : "127.0.0.1"`). The pieces are built and each is
tested, but the whole has not been run on a real Mac and phone. The page must not describe it until
it has been.

## Decision

1. **The install section is three steps on one page.** *Where will your server run?* → that
   server's install → *Where do you want to listen?* → how that player connects to that server.
   Each step is a choice whose answer reveals the next; the chosen pair is in the URL
   (`#install?server=mac&client=iphone`), so a link to a coworker lands on their path.

2. **Step 1 offers five servers, the Mac first.** Mac (Familiar Server), then Synology,
   OpenMediaVault, Linux & other NAS, and Windows. The Mac is first because it is the one with no
   Docker, no terminal and no second machine; the NAS choices are equal to it, not beneath it,
   as ADR-0131 has them.

3. **Step 2's Mac path is Familiar Server, and only that.** Download, drag to Applications, open,
   choose your music folder. The Docker-on-macOS path moves to `docs/INSTALLATION.md` for the
   reader who wants it; the page offers one way per machine.

4. **Every server path ends signed in.** Familiar Server's "Open Admin"; the Docker paths'
   `docker logs familiar-api 2>&1 | grep '#token='`, or each NAS's log view for the panels with no
   terminal (ADR-0095 point 4). "No account" goes from the page.

5. **Step 3 offers two players: iPhone & iPad, and the Mac player.** Each links its App Store page,
   then says how it connects to the server chosen in step 1:
   - Mac player, server is Familiar Server on the same Mac: **Open in Familiar**, from Familiar
     Server's menu.
   - Any player, any other combination: **Pair a Phone…** (Familiar Server) or Server › Access (the
     web admin), and scan the QR code, or open the `familiar://pair` link on the Mac.
   The web admin and Claude are not players and are not in this step; the admin is where step 2
   ends, and Claude already has its place in the features section and the FAQ.

6. **Kept from ADR-0095:** each path is the shortest true one and links one canonical document
   (point 3); a path that needs a terminal says so first (point 4); with no JavaScript every step
   and every path is shown, headings and all (point 6); and the 700-word budget in `<main>` (point
   9) is measured on one path, which is what a reader sees.

7. **Claims that change go through `docs/SITE-CLAIMS.md`:** "installs with no Docker on a Mac",
   the sign-in step, and analysis time. The analysis figure is replaced by a measured one, per
   machine, or removed; it is not restated from memory.

8. **Step 3 ships when pairing has been run end to end** — a phone pairing with Familiar Server on
   a real Mac, and with a Docker server — and not before. Until then step 3 shows only the App Store
   links and "Open in Familiar".

## Alternatives Considered

- **A grid: servers as rows, players as columns, a cell per combination.** Shows the whole space at
  once, which is its appeal. Rejected: five by two is ten cells, most of which say the same thing
  ("pair with the QR code"), and on a phone a grid that size is either scrolled sideways or
  stacked into the steps anyway. The steps show a reader only their own path.
- **Keep ADR-0095's single toggle and add a "connect your phone" paragraph below it.** The smallest
  change. Rejected: the paragraph would have to describe every server's way of pairing at once, or
  pick one and be wrong for the others — the same "one path that is really one platform's" fault
  ADR-0095 was written to remove.
- **Detect the reader's machine and preselect step 1.** Rejected for ADR-0095's reason, still true:
  the user agent describes the device reading the page, and the likely reader is on a phone
  planning a server somewhere else.
- **Offer the web admin and Claude as clients in step 3.** Rejected: neither plays music. The admin
  is already the end of step 2, and putting Claude beside the players would make the step about
  everything that can reach the server rather than where the reader will listen.

## Consequences

- **Positive:** a coworker can be sent one link that is their path, from download to music playing.
- **Positive:** the page stops contradicting the product: Familiar Server, the sign-in link, and
  how long analysis takes.
- **Tradeoff:** three steps are more to keep true than one toggle. Point 6 keeps each path to one
  canonical document, so the long form still lives in one place per server.
- **Tradeoff:** the URL carries state (`?server=…&client=…`). A link with an unknown value shows
  step 1 unchosen, not an error.
- **Follow-up:** **the Mac download link has no stable URL.** Every release is a prerelease, and
  `releases/latest` skips prereleases (it redirects to `/releases`), while the `.dmg`'s name
  carries its version. The page needs a link the release job keeps true. That is its own decision.
- **Follow-up:** ADR-0096's remote-access section rests on "Familiar has no login", which ADR-0141
  made false for every new server. It needs revisiting, separately.
- **Follow-up:** the analysis-time claim needs a measurement on Familiar Server, which depends on
  the worker log times shipped in `v0.2.0-beta13` (#373).
