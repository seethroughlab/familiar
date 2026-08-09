# The Demo Server

`https://familiar-demo.fly.dev` — a public, always-on Familiar instance with a small library of
CC-licensed music. It exists so an **App Store reviewer has a server to type into the setup screen**;
without one the app is a setup screen, and a submission that reaches a reviewer in that state is
rejected on functionality regardless of what shipped in it.

It doubles as the public demo the website has never been able to link to.

> **This document describes what is built.** It previously described a design that was never
> implemented — an always-on 8 GB machine called `familiar-test`, a `fly/seed-music.sh`, a
> `deploy-fly.yml`, a `fly.toml` at the repo root — and diverged from the implementation in every
> particular, with nothing comparing the two. That is how the server came to be off for months
> without anyone noticing. See [ADR-0038](decisions/ADR-0038-the-demo-server-is-always-on.md).

**This is a review and demonstration server. It is not hosted Familiar.** No user accounts, no
uploads, no durability guarantee, and no growth into a service. Familiar is self-hosted software.

## As built

| | |
|---|---|
| Fly app | `familiar-demo`, region `sjc` |
| Config | `deploy/fly/fly.toml` — invoked from the repo root, see the comment at its top |
| Image | `deploy/fly/Dockerfile` (not `docker/Dockerfile`) |
| VM | `shared-cpu-1x`, 1 GB, one machine, **always on** |
| Volume | `demo_data` mounted at `/data` |
| Database | **Neon** Postgres with `pgvector` |
| Deploy | `.github/workflows/fly-deploy-demo.yml` — on push to `main` under `backend/**` or `deploy/fly/**`, and by hand |
| Reset | `.github/workflows/fly-reset-demo.yml` — weekly, Sunday 04:00 UTC |

`deploy/fly/entrypoint.sh` ensures the `pgvector` extension and runs `alembic upgrade head` on every
boot, so a deploy carries its own migrations.

### Why 1 GB is enough, and why not to "fix" the CLAP flag

`fly.toml` sets `DISABLE_CLAP_EMBEDDINGS = 'true'`. The CLAP model is ~1.5 GB, so that flag is what
makes a 1 GB machine plausible — but the important part is what it does *not* disable. It gates
**computing** embeddings during analysis, not using them: the database arrives pre-seeded with
vectors, so similarity search and the Music Map work here without the model ever being loaded.

The consequence is that **the demo can never analyse anything new.** A track added to this instance
gets no features and no embedding, which looks like a bug and is not one.

## The library

`demo-library/` holds **32 CC-licensed tracks** — Kevin MacLeod, Jahzzar, Hussalonia and Nicolas
Falcon, CC-BY / CC-BY-SA / public domain, sourced from the Internet Archive — with a generated
`ATTRIBUTIONS.md`. Three scripts, in order:

```bash
scripts/fetch-demo-library.sh     # download the tracks
scripts/analyze-demo-library.sh   # full analysis pass against a throwaway local Docker stack
scripts/seed-demo-library.sh      # pg_dump the result into Neon
```

**Use Neon's direct host, never the pooler.** Neon's pgbouncer ignores `ALTER ROLE SET search_path`,
so anything run through a `-pooler` hostname will not find the schema and fails in a way that looks
like a corrupt dump. `seed-demo-library.sh` takes `DEMO_NEON_URL` and says so; the reset workflow
refuses a pooler URL outright.

## Bringing it up

The repository side is done — `fly.toml` is always-on and the deploy workflow is armed. What remains
needs a Fly account:

```bash
flyctl deploy . \
    --config deploy/fly/fly.toml \
    --dockerfile deploy/fly/Dockerfile \
    --remote-only
```

Then verify:

```bash
flyctl status -a familiar-demo                       # one machine, health checks passing
curl https://familiar-demo.fly.dev/api/v1/health     # 200
```

### Secrets

| Secret | Where | Notes |
|---|---|---|
| `FLY_API_TOKEN` | GitHub Actions | Used by both workflows |
| `DEMO_DATABASE_URL_DIRECT` | GitHub Actions | Neon, **direct host** — the reset job rejects a `-pooler` URL |
| `DATABASE_URL`, `REDIS_URL` | Fly | Set with `flyctl secrets set -a familiar-demo` |

### The weekly reset, and the golden seed

`fly-reset-demo.yml` restores the demo every Sunday, because reviewers and anyone with the link
share one profile and their play counts, favourites and playlists accumulate.

It restores from **`deploy/fly/demo-seed.sql.gz`, committed to this repository** — a `--data-only`
dump of `profiles`, `artist_info`, `tracks` and `track_analysis`. No secret, no hosting, and it is
versioned next to the schema that produced it, so a migration that invalidates the seed shows up in
the same pull request.

Produce or refresh it two ways:

```bash
# From the live demo — seconds, and the usual case. Reads the app's own secret, so there is no
# password to retype: the script strips `+asyncpg` and translates `ssl=` to `sslmode=` itself.
DEMO_NEON_URL="$(flyctl ssh console -a familiar-demo -C 'printenv DATABASE_URL' \
  | tr -d '\r' | sed 's/-pooler//')" ./scripts/capture-demo-seed.sh

# From scratch, when the library itself changes — hours, needs the analysis stack.
./scripts/seed-demo-library.sh
```

Then commit the file.

**Capture from a clean demo.** The script snapshots whatever is there, so running it after people
have been listening bakes their play counts into the copy the reset restores — the exact thing the
reset removes. It counts `play_events` and refuses above 25 unless you pass `ALLOW_DIRTY=1`.

> This used to be a `DEMO_SEED_URL` secret pointing at a published dump. Nothing ever published one,
> because `seed-demo-library.sh` wrote its dump to `mktemp` with a `trap` deleting it on exit — the
> golden copy was destroyed every time it was made.

## The review account

The server URL and profile a reviewer types belong beside the App Store Connect metadata, in this
repository, so that preparing a submission does not begin by working out what they were. That
location is **not yet chosen** — ADR-0038 point 6, unfinished.

## The Fly footprint

**One app: `familiar-demo`.**

`familiar-sessions.fly.dev` was the WebRTC signalling relay.
[ADR-0036](decisions/ADR-0036-listening-sessions-signal-through-familiars-own-server.md) retired it —
signalling runs on the listener's own server now — and it was **destroyed on 2026-08-09**
(`flyctl apps destroy familiar-sessions`), confirmed by the hostname no longer resolving to
anything. It had still been running and answering 200 for the hours between the code shipping and
someone remembering the app existed, which is how it became load-bearing without appearing in any
decision in the first place.

If a second Fly app ever appears here, it belongs in this section on the day it is created.
