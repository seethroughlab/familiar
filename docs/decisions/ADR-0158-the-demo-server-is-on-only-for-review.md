# ADR-0158: The Demo Server Is On Only for Review

Status: accepted

Date: 2026-11-02

Implementation:
- **Accepted 2026-11-02**, the day it was proposed, on `docs/adr-0158-demo-on-for-review`.
- **Point 1** was done before this record was written: the machine (`7841503a41e4e8`) was stopped
  and its autostart disabled on 2026-11-02, and both were checked the same day.
- **Point 2** is `familiar-apple` `52f2424`, on that repository's `docs/demo-server-stopped`.
- **Point 3** is three steps in `fly-deploy-demo.yml`. *Record whether the demo is off* runs before
  the deploy. *Start the demo for the checks* starts anything still stopped, so the existing
  artist and Videos checks prove the new build either way, without relying on whether
  `fly deploy` starts a stopped machine. *Put the demo back off* runs with `always()`, so a red
  deploy does not leave the demo running.
- **Building point 3 found a failure the Decision did not anticipate.** Run against the live,
  stopped machine on 2026-11-02, `fly machine update --autostart=false --skip-start` failed with
  "could not reserve resource for machine: insufficient memory available ... on the current
  host", a transient Fly capacity error, on a machine that was not even being started. A failed
  update leaves the machine stopped *but wakeable*, and a check that read only the state would
  have passed. The update is now retried five times, 30 s apart, and the final check requires
  every machine to be `stopped` **and** to have autostart off.
- **Point 4** is a new `power` job in `fly-reset-demo.yml`. The `reset` job `needs` it and runs
  only when it reports the demo on, so a Sunday with the demo off is a skipped job with a notice,
  not a failure.
- **Point 5**: the `fly.toml` comment now says the settings describe the server while it is on.
  `docs/TEST-SERVER.md` and `CLAUDE.md`'s screenshot instructions are corrected to as-built.
- Both workflows pass `actionlint` 1.7.12. The off-detection and the final check were run against
  the live app; the workflows themselves first run on the next backend merge and on Sunday
  2026-11-08.
- **The first real deploy (run `41508840614`, 2026-11-02, on the merge of #426) was red, and point
  3 held.** The demo was recorded off, deployed, started, and put back off
  (`stopped/autostart_off=true`, checked afterwards). But the artist check failed one curl in: Actions
  runs steps under `bash -e`, so a `curl` timing out (exit 28) against a machine started one second
  earlier ended the step before its retry loop could retry. The loop had never been exercised,
  because the demo had always been warm. Both checks now tolerate a failed `curl`
  (`fix/demo-deploy-cold-start`).
- **Numbered 0158, not 0156**: drafted as 0156 on a local `main` 15 commits behind `origin`, where
  0156 and 0157 were already the recap ADRs.

Supersedes point 1 of [ADR-0038](ADR-0038-the-demo-server-is-always-on.md), and qualifies point 4.

## Context

`ADR-0038` point 1 keeps `familiar-demo` running continuously, because a reviewer who hits a cold
machine sees timeouts and one rejection costs more in calendar time than the machine costs in a
year. Its Consequences named the price honestly: a recurring monthly cost, forever, for a
machine that is idle almost all the time.

**What it costs, and what it is for, as of 2026-11-02.** The machine is `shared-cpu-1x` with 1 GB
in `sjc` (`7841503a41e4e8`), about $5.70 a month at Fly's list price, plus the 1 GB `demo_data`
volume and the `familiar-demo-redis` Upstash instance. Its only audience is App Store review:
the site stopped linking to it on 2026-08-15 and 2026-10-03 (`docs/SITE-CLAIMS.md`, the "Try the
live demo" and "Try the demo" rows), and `site/e2e/pages.spec.ts` asserts that no link to it
exists. The last submission, 1.5.1, shipped on 2026-10-26 (`familiar-apple/APP-REVIEW-NOTES.md`).
Submissions are weeks apart; the machine runs all the time in between.

**It was stopped on 2026-11-02**, with `fly machine stop` and then
`fly machine update --autostart=false --skip-start`, so the Fly proxy does not wake it on
request. Checked the same day: both health and root requests time out, and the machine stays
`stopped`.

**`ADR-0038` rejected exactly this option**, "bring the machine up by hand around each
submission", for a reason that has to be answered rather than ignored: it was the arrangement
that produced the server it found, a manual step that was skipped once, a `push:` trigger
commented out to match, and a comment that became the documentation. That failure had two parts.
The step lived nowhere anyone would read it at submission time, and the deploy path was disabled
to match the server's state, so the demo drifted from `main`.

**Two things will undo or break the stop as it stands.**

- `.github/workflows/fly-deploy-demo.yml` deploys on every push to `main` touching `backend/**`,
  `deploy/fly/**` or itself. `deploy/fly/fly.toml` still says `auto_stop_machines = 'off'`,
  `min_machines_running = 1`, so the next backend merge starts the machine and keeps it on.
  Nothing fails and nobody is told.
- `.github/workflows/fly-reset-demo.yml` runs every Sunday at 04:00 UTC, restarts the app
  (its *Restart, so the entrypoint links artists and albums again* step) and then requires the
  health, profile, track-count and artist checks (*Confirm the app still serves music*) to pass
  against `familiar-demo.fly.dev`. With the machine stopped it either
  starts it or fails every week. The first run after the stop is 2026-11-08.

## Decision

1. **The demo server is stopped between reviews and on during them.** It is started at least a
   day before an App Store submission and stopped once that version is approved. Off means
   stopped with autostart disabled, not scale-to-zero, so nothing wakes it.

2. **The switch lives where the submission is prepared.** `familiar-apple/APP-REVIEW-NOTES.md`
   opens with the start, check and stop commands (`familiar-apple` `52f2424`). That is the file
   read to fill in App Store Connect's review notes, so the step cannot be skipped without
   skipping the notes too. This answers the first half of `ADR-0038`'s rejection, in the place
   its point 6 already chose for review facts.

3. **Deploys continue, and leave the machine as they found it** (qualifies `ADR-0038` point 4).
   `fly-deploy-demo.yml` keeps its `push:` trigger. If the machine was stopped before the
   deploy, the workflow deploys, runs its artist-page check, then stops the machine and disables
   autostart again. The demo still tracks `main` and every backend change is still proven
   against it, which answers the second half of the rejection: the deploy path is not disabled
   to match the server.

4. **The weekly reset skips a stopped demo.** `fly-reset-demo.yml` checks the machine's state
   first and exits successfully, saying so, when it is stopped. A database nobody can reach does
   not need resetting, and a reset that starts the machine would undo point 1.

5. **`deploy/fly/fly.toml` keeps its always-on settings.** They describe the server *while it is
   on*, during a review, and a deploy during a review window must not leave a reviewer facing a
   cold start. The comment above them is updated to say the machine is off between reviews and
   to cite this ADR.

## Alternatives Considered

**Keep `ADR-0038` point 1, always on.** The cost is small, about $70 a year in compute, and
nothing has to be remembered. Rejected because the machine serves nobody between submissions:
the site has not linked to it since August, and the single audience it was built for arrives a
few times a year. "Cheap" was the argument for keeping it; "unused" is the argument against, and
with point 2 the remembering is put somewhere it will not be missed.

**Scale to zero between reviews**: `auto_stop_machines = 'stop'`, `min_machines_running = 0`,
autostart on. It costs almost nothing idle, wakes for any visitor, and needs no change to either
workflow, since deploys and resets wake it. Genuinely attractive, and the closest competitor.
Rejected for now because it trades one thing to remember for another: the always-on settings
would have to be restored before every review, so the cold start `ADR-0038` rejected is not met
by a reviewer, and a forgotten restore fails *silently*. The machine still answers, just slowly
under exactly the audience that matters. A stopped machine that was not restarted fails loudly
on the check in point 2. It also keeps the screenshot workflow in `CLAUDE.md` (its screenshot steps 1 and 2)
working, which point 1 does not; that is the cost of this choice.

**Destroy the app and recreate it for each review.** No cost at all between reviews. Rejected
because recreation is the work `ADR-0038` spent its Implementation block making reliable once:
secrets, the `demo_data` volume, the Neon connection, and a deploy whose artist check found two
months of a demo with no artists. Paying cents a month for a stopped machine and volume to keep
all of that intact is the right trade.

**Disable the deploy and reset workflows while it is off.** The simplest change to the two
workflows. Rejected because it is the second half of what `ADR-0038` found: a `push:` trigger
commented out "while demo is offline", and a demo that then drifted from `main` for months.

## Consequences

- **Positive:** The demo's compute cost goes to near zero between reviews. The stopped machine
  and the 1 GB volume still bill a few cents.
- **Positive:** The demo stays deployed from `main` and the backend stays proven against it, as
  `ADR-0038` point 4 intended.
- **Tradeoff:** A submission now has a step before it, and one after approval. Point 2 makes it
  hard to miss but cannot make it automatic. Approval is the event that ends the window, and
  nothing here observes it.
- **Tradeoff:** The screenshot workflow in `CLAUDE.md` against `familiar-demo.fly.dev` only works
  while the demo is on. Start it, or use a local backend.
- **Tradeoff:** A deploy while the demo is off runs the machine for the length of its check, a
  few minutes per backend merge.
- **Follow-up:** The workflows' first real runs are the next backend merge to `main` and Sunday
  2026-11-08. Check both: the deploy should end with the demo `stopped/autostart_off=true`, and
  the reset should be a skipped `reset` job.
