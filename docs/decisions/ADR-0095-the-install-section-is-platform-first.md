# ADR-0095: The Install Section Is Platform-First

Status: accepted

Date: 2026-08-29

Implementation:
- Accepted and built the same day, on `adr-0095-0096-install-and-remote-access`. Four panels —
  macOS, Windows, Synology, Linux & NAS — in `site/index.html`, styled in `site/assets/site.css`,
  switched by `site/assets/install.js`, the site's first script.
- **The macOS panel does not use the site's old command, because `start.sh` is better for this
  reader.** It requires a `.env`, expands `~` itself (Compose does not), warns when the music path
  does not exist, detects `Darwin` and adds the logging override, and warns about CLAP on an 8 GB
  machine. That is four failure modes handled before the reader meets them, and it is what
  `MACOS_BEGINNER.md` already documents — so the panel and the guide agree by construction rather
  than by maintenance.
- **A false claim was found on the page and corrected.** The "Build from source" block said
  `./start.sh` "builds the image locally". It does not: `start.sh:84` runs
  `docker compose -f docker-compose.prod.yml`, which pulls `ghcr.io/seethroughlab/familiar:latest`,
  and the script contains no `--build` at all. Exactly the shape `ADR-0055` point 2 exists for, and
  found by reading the script to write a different panel.
- **Windows needs `docker-compose.macos.yml`.** The file only swaps `journald` for `json-file`, and
  Docker Desktop runs a Linux VM on both platforms, so the override applies to Windows too despite
  the name. The panel says this in one sentence, which is the honest fix and not a good one — see
  the follow-up.
- Verified: markup balanced (no unclosed tags, no stray closers); the four `data-panel` values match
  the four panel ids exactly; every internal anchor resolves; `site/scripts/check-claims.py` passes
  all four groups, including the six new external links.
- The new section uses `constellation.webp`, one of the nine marks `ADR-0054`'s Implementation block
  recorded as unreferenced when it was ratified the same day. **Eight now**, and the reserve is
  doing what that note predicted it was for.
- **Rendered length is ~1,158 words against 1,778 before, and `0055` point 4's budget is 700.**
  Hiding three panels accounts for ~338 of the reduction. Point 9 stands: the budget wins, and
  closing the rest of that gap is `0055`'s restructure, not this ADR's.

Supersedes point 1 of [ADR-0055](ADR-0055-the-site-is-restructured-around-five-things.md), and
rebuilds the "how to get it" half of its point 3. Reverses the hero clause of
[ADR-0039](ADR-0039-the-website-is-rebuilt-in-place.md) point 3.

## Context

**ADR-0055 point 1 says who the site is for, and this ADR disagrees with it.** Its words: someone
with a large library "who is comfortable enough to run `docker compose up`". Everything on the page
is measured against moving *that* person to the install.

The premise here is that the person worth reaching is one step earlier — someone who owns a lot of
music files, is tired of a streaming service refusing to play them, and has never used a terminal.
Not the r/selfhosted reader, who will manage regardless of what the page says.

**This is a product judgement, not a measurement.** Nothing instruments the site; there is no
funnel, no analytics, and no evidence in this repository about where readers stop. `0055` point 1
was written down precisely so the audience would stop being assumed, and replacing one assumption
with another is worth naming as exactly that. If it is wrong, the cost is a longer install section
serving a reader who did not need it.

### What the page does today

One path, and it is Linux's:

```
curl -LO .../docker-compose.prod.yml
curl -LO .../init-pgvector.sql
MUSIC_LIBRARY_PATH=~/Music docker compose -f docker-compose.prod.yml up -d
```

Three commands, two of them `curl`, one carrying an inline environment variable. macOS is demoted to
a `<details>` element titled "macOS? (journald swap + 8 GB RAM note)" — because the production
compose file uses `journald` logging, which is Linux-only, so **the page's headline command does not
work on a Mac as written**. Windows and Synology appear nowhere in the section at all, while the
requirements line above it claims Familiar is "Tested on macOS, Linux, OpenMediaVault, and Synology
NAS".

So the page already branches by platform. It does it in a disclosure widget, after the command that
will fail.

### The material exists and is not on the site

This is mostly a surfacing problem, not a writing one:

- `docs/MACOS_BEGINNER.md` — 299 lines, and already in the register this ADR wants: "Step 1: Check
  Your Mac", "Step 3: Open Terminal", "Step 5: Find Your Music Folder", with separate branches for
  8 GB and 16 GB machines.
- `docs/INSTALLATION.md:241` — Synology, DSM 7.2+ Container Manager, with the supported-model list
  and a compose snippet using `/volume1/music`.
- `docs/INSTALLATION.md:72` — OpenMediaVault, step by step, including the permissions failure mode.
- `docs/MACOS.md` — Apple Silicon notes and `./start.sh`.

**`docs/WINDOWS.md` is not an install guide.** It is a compatibility audit dated 2026-01-14 listing
21 issues, four of them "Critical" — a hardcoded Unix root in the directory browser, Unix-only
`BLOCKED_PATHS`, a path comparison against `/`. Its own first section says why that does not block
this work: those issues affect **running the backend natively**, and under Docker "the host OS only
needs Docker installed" because the container is Linux. Windows is therefore fine in principle and
**has never been tested by this project** — the site's own requirements line lists four platforms
and Windows is not among them.

### The constraint nobody would guess

`site/` has **no build step and zero `<script>` tags**. It is hand-written HTML and one stylesheet.
ADR-0069 would add Eleventy and is `proposed`, unstarted, and gated on `0055` landing. So a toggle
here is the site's first JavaScript, and it has to work without a generator.

## Decision

1. **The site is written for someone who owns music files and wants off Spotify, not for someone
   who is comfortable in a terminal.** This supersedes `0055` point 1. The measure for what belongs
   on the page is unchanged in form — does it move that reader toward a working install — and only
   the reader changes.

2. **Install is platform-first: one toggle, four choices — macOS, Windows, Synology, Linux & NAS.**
   The reader picks the machine the *server* will run on and sees only that path. Splitting
   Synology out from Linux is deliberate: it is the case where the answer is a GUI and no terminal
   at all, which is the whole point of the exercise.

3. **Each panel is the shortest true path for that platform, and links exactly one canonical
   document in this repository for the long form.** The site does not fork the instructions. This is
   `0055` point 2's rule applied structurally rather than by audit: four copies of an install
   procedure is four things to keep true, and the audit that produced `0055` exists because that
   does not happen.

4. **A panel that needs a terminal says so before the first command, and a panel that does not need
   one never shows a command.** Synology's path is Container Manager; macOS and Windows begin with
   Docker Desktop, which is a download and a double-click. The generic `curl` pair belongs to Linux.

5. **Windows is offered and labelled honestly.** It gets a panel because Docker on Windows runs the
   same Linux container, and it carries a visible note that this project has not tested it, with the
   invitation to report back. Omitting the platform is worse than including it with a caveat;
   claiming it works is worse than both, and would violate `0055` point 2 outright.

6. **The toggle degrades to all four panels visible.** No JavaScript, no build step, and no reader
   who sees an empty section because a script did not load — the failure this project keeps
   producing is an affordance whose destination is not mounted, and a tab strip is an affordance.

7. **The hero stops leading with three shell commands.** `0039` point 3 put them there to sell "a
   five-minute install of MIT-licensed software", which was right for `0055`'s reader and is wrong
   for this one: a wall of `curl` is a competence test in the first screenful. The hero keeps the
   requirements line and gains a link to the install section; the commands live in the Linux panel,
   which is where they are true.

8. **The platform support table is a claim and gets a row in `docs/SITE-CLAIMS.md`; the
   instructions are not.** A procedure is checked by running it, which the ledger does not model.
   What the ledger carries is the assertion "Familiar installs on these four platforms", with
   Windows recorded as `unverifiable` until somebody runs it — which is what that verdict is for.

9. **This does not change `0055` point 4's budget of six claims and 700 words in `<main>`.** A
   toggle shows one panel at a time, so the section's rendered length is one platform's worth. If
   the budget and this collide, the budget wins and the panels get shorter, not the other way round.

## Alternatives Considered

- **Keep one generic path and write it more kindly.** The smallest change, and it treats the real
  problem as tone. Rejected because the generic path *is* the Linux path and does not run on macOS —
  the `journald` override in the `<details>` is proof the page already needs branches. Better prose
  on a command that fails is worse than no prose.

- **Four links to the four documents, no toggle.** Nearly free, and the documents are already good.
  Rejected because it hands the reader the one choice they cannot make: someone with a Synology does
  not know whether "Linux" means them, and someone on a Mac does not know whether `MACOS.md` or
  `MACOS_BEGINNER.md` is theirs. A chooser exists to answer that.

- **Detect the platform from the user agent and show one panel.** The obvious refinement, and it is
  wrong here for a specific reason: the user agent describes the machine *reading the page*, not the
  machine that will run the server. The likely reader is on a phone or a laptop planning to install
  on a NAS in a cupboard, and auto-selecting would show them the wrong panel confidently.

- **Ship a one-click installer — a `.dmg`, an `.exe`, a Synology package.** The honest answer to
  "make it dead simple", and eventually right. Rejected as out of scope: it is a build-and-signing
  pipeline per platform, and the Apple app is a *client* — there is no packaged server today. This
  ADR makes the existing install legible; it does not replace it.

- **Leave the audience where `0055` put it.** Genuinely defensible: self-hosting a music server with
  a Postgres and a Redis is not a beginner activity, and a page that promises otherwise sets up a
  failure later, at the point where a library path or a permission is wrong. Rejected because the
  three hardest steps are already documented for beginners in this repository and simply not
  surfaced — the promise is closer to true than the page implies.

## Consequences

- **Positive** — the page stops leading with a command that does not work on the most likely
  reader's machine.
- **Positive** — Synology and Windows readers are addressed at all, and the requirements line stops
  claiming support the section never explains.
- **Positive** — `MACOS_BEGINNER.md` and `INSTALLATION.md`'s Synology walkthrough get a caller.
  Both are good documents that nothing on the site links to.
- **Tradeoff** — the site gains its first JavaScript, on a page whose whole virtue is that it is
  static HTML. Point 6 caps the cost: the script only hides panels, so its failure mode is the page
  as it would have been anyway.
- **Tradeoff** — four panels is four things to keep true. Point 3 limits the exposure to the
  shortest path plus a link, but it is more surface than one path.
- **Tradeoff** — a beginner audience will produce support questions this project has no channel for
  beyond GitHub issues.
- **Follow-up** — Windows is `unverifiable` until someone installs it. Worth doing before the panel
  claims more than it does.
- **Follow-up** — `docker-compose.macos.yml` is misnamed. Its content is "this host is not Linux",
  which covers Docker Desktop on Windows equally, and the Windows panel now has to explain why it is
  telling a Windows user to fetch a file called `macos`. That is the single most confusing sentence
  in the new section, and it is confusing because of a filename. Renaming it to
  `docker-compose.desktop.yml`, with the old name kept as a copy so existing instructions keep
  working, would remove the explanation entirely. Not done here because it touches `docker/` and
  `start.sh`, which this ADR has no business changing.
- **Follow-up** — remote access is the second half of "make it simple" and is deliberately not here.
  Today it is step 4 of the install, one command and a link, which explains *how* and never *why*.
  See ADR-0096.
- **Follow-up** — `0055` and `0069` both remain `proposed`, and this ADR rebuilds a section `0055`
  also rebuilds. Whichever lands second inherits the merge; `0069` point 6's ordering rule is
  unaffected because this changes content rather than tooling.
