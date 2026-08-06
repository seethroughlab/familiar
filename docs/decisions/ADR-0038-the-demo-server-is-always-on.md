# ADR-0038: The Demo Server Is Always On

Status: proposed

Date: 2026-08-06

## Context

`docs/TEST-SERVER.md` opens with the reason this matters:

> Apple App Store review requires a working backend server with test data.

An App Store reviewer opens Familiar, is asked for a server, and has nothing to type. Without a
reachable server the app is a setup screen, and a submission that reaches a reviewer in that state
is rejected on functionality regardless of what shipped in it. That makes this a prerequisite for
every Apple-facing decision in the current set, not a piece of infrastructure housekeeping.

**The server exists. It is off, and what shipped is not what was designed.** Checked 2026-08-06:

| `docs/TEST-SERVER.md` specifies | `deploy/fly/fly.toml` does |
|---|---|
| app `familiar-test` | app `familiar-demo` |
| always-on `performance-2x`, 4 CPU / 8 GB, ~$55/month | `shared` CPU × 1, 1 GB |
| `auto_stop_machines = "off"`, `min_machines_running = 1` | `auto_stop_machines = 'stop'`, `min_machines_running = 0` |
| `fly.toml` at the repo root, built from `docker/Dockerfile` | `deploy/fly/fly.toml`, its own `deploy/fly/Dockerfile` |
| `fly/seed-music.sh` | does not exist |
| `.github/workflows/deploy-fly.yml` | shipped as `fly-deploy-demo.yml` |

And that workflow is `workflow_dispatch` only. Its `push:` block is commented out, above the line:

```
# Auto-deploy on push disabled while demo is offline.
```

So the server the submission depends on is scaled to zero, deploys only when someone remembers, and
— were it on — would cold-start under a reviewer against a health check with a 30-second grace
period.

**The document is not wrong so much as unreconciled**, and that is the failure worth recording: a
design document and an implementation that diverged in every particular, with nothing comparing
them, is how this became invisible for months. Anyone reading `TEST-SERVER.md` today would conclude
there is an always-on 8 GB machine called `familiar-test`.

**The parts that do work are the expensive ones.** `demo-library/` holds **32 CC-licensed tracks**
— Kevin MacLeod, Jahzzar, Hussalonia and Nicolas Falcon, CC-BY / CC-BY-SA / public domain, sourced
from the Internet Archive, with a generated `ATTRIBUTIONS.md`. Three scripts support it:
`scripts/fetch-demo-library.sh` fetches them, `scripts/analyze-demo-library.sh` (274 lines) runs a
full analysis pass against a throwaway local Docker stack, and `scripts/seed-demo-library.sh`
`pg_dump`s the result into Neon. `deploy/fly/entrypoint.sh` already ensures `pgvector` and runs
`alembic upgrade head` on boot. There is **no `DEMO_MODE` code path anywhere** in the backend or
the frontend, and there should not be — "demo" here is seeded data plus a separate deployment, not
a branch in the product.

**One env var deserves a second look.** `fly.toml` sets `DISABLE_CLAP_EMBEDDINGS = 'true'`, which
is what makes a 1 GB machine plausible — the CLAP model is ~1.5 GB. Reading
`backend/app/services/background/analysis.py`, that flag gates **computing** embeddings during
analysis, not using them. A database seeded from `analyze-demo-library.sh` already contains the
vectors, so similarity search and the Music Map work on the demo without the model ever being
loaded. That is a considerably better position than it looks from the flag name, and it should be
written down before someone "fixes" it by turning the flag off and running out of memory.

## Decision

1. **The demo server runs continuously.** `min_machines_running = 1` and `auto_stop_machines` off.
   A reviewer who hits a cold machine sees timeouts, and one rejection costs more in calendar time
   than the machine costs in a year.

2. **The size stays modest and the reason is recorded.** The 32-track library needs no analysis
   capacity, `DISABLE_CLAP_EMBEDDINGS` stays `true`, and the embeddings arrive pre-computed in the
   seed. `TEST-SERVER.md`'s `performance-2x` was sized for a machine that would analyse; this one
   never analyses. The monthly figure goes in the document, not in this ADR, because it is the
   thing most likely to change.

3. **`docs/TEST-SERVER.md` is corrected to as-built** — the app name, the machine, the file
   locations, the workflow name, and the seeding path that actually exists. A design document kept
   as intent after the implementation diverged is worse than no document, because it is read as
   fact.

4. **Auto-deploy from `main` returns.** The commented-out `push:` trigger is restored, scoped to
   `backend/**`, `deploy/fly/**` and the workflow itself. A demo that drifts from `main` is a demo
   that disproves the submitted build.

5. **The demo library is seeded from a dump and reset on a schedule.** Reviewers and anyone with
   the link share one profile, so play counts, favourites and playlists accumulate from strangers.
   The Neon dump produced by `seed-demo-library.sh` is the source of truth and the volume is
   disposable; a scheduled reset restores it. (Whatever runs that reset must connect to Neon's
   **direct** host — the pooler ignores `ALTER ROLE SET search_path`, and a restore against the
   pooler will not find the schema.)

6. **The review account is recorded where the submission is prepared, not rediscovered.** The
   server URL and the profile a reviewer types belong beside the App Store Connect metadata, in
   the repository, with the demo credentials. Every submission otherwise begins by working out what
   they were.

7. **This is a review and demonstration server. It is not hosted Familiar.** No user accounts, no
   uploads, no expectation of durability, and no growth into a service. Familiar is self-hosted
   software; the moment this becomes something people rely on, it is a different product with a
   different set of decisions.

8. **The Fly footprint is accounted for as a whole.** `familiar-demo` is not the only Fly
   application in this project — `familiar-sessions.fly.dev` is the signalling relay that
   [ADR-0036](ADR-0036-listening-sessions-signal-through-familiars-own-server.md) retires. Once
   nothing points at it, it is shut down rather than left running and forgotten, which is how it
   came to be load-bearing without appearing in any decision.

## Alternatives Considered

**Keep scale-to-zero and accept the cold start.** Cheapest, and Fly's cold starts are usually a few
seconds. Rejected because "usually" is doing too much work: the health check has a 30-second grace
period, the container runs `alembic upgrade head` on boot, and the first request also has to warm
Postgres. A reviewer with a stopwatch and a rejection form is the wrong audience for a machine that
is *usually* quick.

**Run the demo on the NAS behind Tailscale, as everything else is tested.** No new hosting, no new
cost, and the library is real rather than 32 tracks. Rejected because Apple cannot reach it —
Tailscale is the whole point of that setup — and because the NAS is also this project's CI runner,
where heavy jobs already contend with streaming music. Adding an audience that can reject the app
to that machine is not a trade worth making.

**Ship a fixture or offline mode in the app so review needs no server at all.** Genuinely
attractive: no hosting, no cost, no cold start, and it would work for a reviewer with no network.
Rejected because it is a second code path through the client, built for an audience of one, and it
would exercise none of the thing under review — the app's entire behaviour is what it does against
a server. It would also be the first `DEMO_MODE` branch in a codebase that has deliberately never
had one.

**Bring the machine up by hand around each submission.** It is what happens now, and it is not
absurd — submissions are infrequent. Rejected because it is precisely the arrangement that produced
the current state: a manual step that was skipped once, a `push:` trigger commented out to match,
and a server that has been off long enough for the comment explaining why to become the
documentation.

**Use a hosted demo from a template — a Fly Postgres plus the published `ghcr.io` image, no
repository config.** Fewer files to keep in step. Rejected because the deploy would then exist only
in someone's shell history, which is a worse version of the divergence this ADR is written to fix.

## Consequences

- **Positive:** An App Store submission has a server to point a reviewer at, which unblocks every
  other Apple-facing decision currently proposed.
- **Positive:** A working public demo also exists — the thing the site has never been able to link
  to.
- **Positive:** A design document and its implementation are reconciled, and the reason they
  diverged is on record.
- **Positive:** The Fly footprint becomes two applications counted rather than one counted and one
  forgotten.
- **Tradeoff:** A recurring monthly cost, forever, for a machine that is idle almost all the time.
  That is the honest shape of point 1.
- **Tradeoff:** A publicly reachable Familiar instance with one shared profile is a small attack
  surface and a certain source of odd data. Point 5's reset bounds the damage; it does not remove
  it.
- **Tradeoff:** `DISABLE_CLAP_EMBEDDINGS` means the demo can never analyse anything new. A reviewer
  or a visitor who adds music — if that is even reachable — gets a track with no features and no
  embedding, which looks like a bug.
- **Follow-up:** CI/E2E against a real environment was the second reason `TEST-SERVER.md` gave for
  building this, and it has never happened. A demo that is always on makes it possible; whether
  tests should run against the same instance a reviewer might be using is its own question.
- **Follow-up:** The reset schedule in point 5 needs a mechanism. Fly has no cron; a scheduled
  GitHub Action against the direct Neon host is the obvious candidate and is not built.
- **Follow-up:** `deploy/fly/Dockerfile` and `docker/Dockerfile` are now two build definitions for
  one application. Whether the demo should build from the same image the release publishes is worth
  deciding rather than inheriting.
