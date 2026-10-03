# ADR-0146: The Site Leads with the Mac

Status: proposed

Date: 2026-10-03

Supersedes point 1 and point 11 of [ADR-0055](ADR-0055-the-site-is-restructured-around-five-things.md)
and what remains of point 3 of [ADR-0039](ADR-0039-the-website-is-rebuilt-in-place.md); refines
point 1 of [ADR-0095](ADR-0095-the-install-section-is-platform-first.md). Extends
[ADR-0131](ADR-0131-the-server-is-its-own-app.md) and
[ADR-0135](ADR-0135-familiar-server-is-a-separate-app.md).

## Context

The site was written for self-hosting enthusiasts, and every decision that shaped it says so.
ADR-0055 point 1 defined its reader as someone "comfortable enough to run `docker compose up`";
ADR-0039 point 3 made the hero "a five-minute install of MIT-licensed software", with Docker in the
requirements line; ADR-0055 point 11 made Install the one call to action. ADR-0095 moved the reader
one step earlier, to someone who owns music files and has never used a terminal, but kept the shape:
the page's answer to "how do I get it?" is still a five-way "Where will your server run?".

Familiar is now a Mac product first. Familiar Server is a notarized menu-bar app (ADR-0135); the
player is in the Mac App Store and the iPhone App Store. A Mac owner installs two apps, and nothing
about Docker, servers or licences is theirs to understand. Read on 2026-10-03, the page tells that
reader otherwise before they scroll:

- the `<title>` is "self-hosted streaming for your own music library", and the description and
  social tags lead with hosting and MCP;
- the hero says "on your own server" and "A Mac with Apple Silicon, or any machine with Docker ·
  MIT licensed", lists Synology, OpenMediaVault, Linux and Windows, and puts an unlabelled
  `v0.2.0-beta13` pill — the server's release, one part of the system — straight under the tagline;
- neither app is named in the hero and nothing in it downloads anything: the one button scrolls to
  a chooser whose first question is where a server will run;
- the primary nav carries GitHub and "Remote" (Tailscale).

The audit that prompted this is recorded in the redesign plan; the parts that change the decisions
are above. ADR-0131 point 2 still holds — Docker on a NAS or Linux is first-class, "neither is the
secondary route" — and this ADR does not demote it inside Install. It changes what the *page* leads
with.

**Not yet proven, and point 7 depends on it:** a phone pairing with Familiar Server end to end
(ADR-0143 point 8). A page that invites Mac owners in is inviting the people least able to work
around a pairing problem.

## Decision

1. **The hero names the two apps and offers both downloads.** "Download Familiar Server for Mac"
   links the `.dmg` directly (ADR-0148), with "Then get the player" and Apple's Mac App Store and App
   Store badges beside it. A NAS or Linux reader's door is a quiet link to Install, below them.
   This supersedes ADR-0055 point 11: the call to action is the two downloads, not Install.

2. **One sentence under the hero says why there are two**, as ADR-0135's Consequences asked: the
   server holds your music and analyses it; the app plays it, on your Mac and your iPhone; they pair
   once.

3. **The reader is a Mac owner with music files** (refining ADR-0095 point 1, superseding ADR-0055
   point 1). "Server", "Docker", "MIT", "MCP" and "self-hosted" do not appear above the fold, nor in
   the title or the description. Familiar Server is described by what it does for the reader.

4. **The version moves next to the thing it versions, labelled:** "Familiar Server v… · Release
   notes" under the download button. It stays the `version-dot` span, so ADR-0097's deploy check
   reads it unchanged, and ADR-0055 point 9's "the page states its own age" still holds.

5. **The developer material stays, below the Mac story.** MCP becomes the last feature, written for
   someone who uses an AI assistant rather than someone who writes tools for one. The comparison
   table is reframed around what a Mac owner weighs (native apps, no subscription, the files they
   own) with every competitor cell re-checked. "Listening away from home" (ADR-0145) leaves the nav
   and keeps its section. GitHub moves from the nav to the footer.

6. **Inside Install, nothing is demoted.** ADR-0143 point 2's "NAS choices equal to the Mac" stands:
   the Mac leads the page, not the chooser.

7. **The Mac-led hero ships only after a phone has been paired with Familiar Server end to end.**
   Changes that make no new promise — the FAQ, privacy page, nav, footer and tests — may ship first.

## Alternatives Considered

- **Keep Install as the one call to action, with the Mac first inside it.** The smallest change, and
  ADR-0143 already puts the Mac first in the chooser. Rejected: the reader still meets "Where will
  your server run?" before anything downloads, which is the intimidation this ADR exists to remove.
  Mac software is sold with a download button; a chooser reads as infrastructure.
- **Two sites, one for Mac owners and one for self-hosters.** Each audience gets a page written for
  it. Rejected: two pages to keep true, against ADR-0055 point 2's whole lesson, and ADR-0131 says
  the two server forms are one product.
- **Drop Docker from the landing page and leave it to `docs/INSTALLATION.md`.** Cleaner for the Mac
  reader. Rejected by ADR-0131 point 2: the NAS is first-class, and the person who has one should
  find their path on the page that names it.
- **Remove the version entirely.** It is what read as "beta, for developers". Rejected: ADR-0097's
  deploy check needs a fingerprint on the live page, and labelling it next to the download says what
  it is instead of hiding it.

## Consequences

- **Positive:** a Mac owner can go from the first screen to a download without reading the word
  "server".
- **Positive:** the version stops reading as a status for the whole product.
- **Tradeoff:** the hero now promises something — two downloads that work together — and point 7
  holds it back until that promise has been kept on a real phone.
- **Tradeoff:** two downloads, one from GitHub and one from the App Store, is more than a Mac app
  usually asks. ADR-0135 accepted that; the hero states it plainly rather than hiding it.
- **Follow-up:** new screenshots, taken by hand (the Familiar Server menu, the iPhone player, a
  playlist made from a track), since tooling cannot drive the Mac app.
- **Follow-up:** `site/e2e` runs in no CI workflow today. It is added with the first change, so the
  rules above are checked rather than remembered.
