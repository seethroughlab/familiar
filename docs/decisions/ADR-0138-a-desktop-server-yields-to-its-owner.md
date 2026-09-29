# ADR-0138: A Desktop Server Yields to Its Owner

Status: proposed

Date: 2026-09-29

Extends [ADR-0131](ADR-0131-the-server-is-its-own-app.md),
[ADR-0136](ADR-0136-familiar-server-runs-in-the-background.md)

## Context

Everything about how Familiar's background work behaves was tuned for a NAS: a machine with no
battery, no one sitting at it, and nothing else to do. Under ADR-0131, Familiar Server runs
the same backend in the background of a laptop its owner is working on. What background work does today:

- **A library sync starts every two hours, by itself.** `services/background/manager.py`
  schedules `_periodic_sync` with `CronTrigger(hour="*/2", minute=0)`, and has done so since at
  least `e0bde30e` (2026-02-20). A sync queues whatever analysis is behind.
  **This contradicts how the project describes itself.** `CLAUDE.md` says re-analysis happens
  "only during a library sync — nothing is scheduled", and `VERSIONING.md` says "there is no
  scheduler for it". Both are true of analysis narrowly: it has no scheduler of its own. Both read
  as though nothing happens until someone asks, and on a laptop that difference is the whole
  question.
- **Other scheduled jobs reach the network without being asked:** `discovery_batch`,
  `recording_backfill`, `daily_external_albums`, `listenbrainz_fresh_releases`,
  `daily_update_check` and `soulseek_poll`, all in the same scheduler.
- **Analysis yields only by `nice`.** `_analysis_worker_init` sets `os.nice(10)`
  (`services/background/executors.py`). Workers default to one (`max_analysis_workers`,
  `app/config.py:96`), and compose raises this to two (`docker/docker-compose.prod.yml`). A single
  worker decoding a 57-minute file measured 2.01 GB peak RSS (ADR-0105, on the GPU path).
- **Work can be cancelled, not paused.** `POST /library/sync/cancel` exists
  (`api/routes/library_sync.py`). Nothing suspends background work and resumes it where it
  stopped.

`nice` decides who gets the CPU when the machine is busy. It does not stop a fan, a hot lap or a
battery draining on a train, which is what makes someone uninstall a background app.

## Decision

1. **The server can pause background work, and says why.** A platform-neutral pause and resume,
   with a reason string, is exposed through the API and Familiar Server's menu.
   - While paused: no new analysis task is dispatched, scheduled jobs defer their next run, and a
     sync that is due waits.
   - Work already in flight finishes its current track, which `max_tasks_per_child=1` keeps short,
     and is not cancelled.
   - **Serving never pauses.** Streaming, the API, and transcodes for a phone's downloads
     (ADR-0118) carry on, because they are what the owner and their phone are waiting for.
   - The NAS gains the same control, whether or not anything calls it.

2. **Familiar Server pauses for the owner's machine and resumes when it recovers:**
   - on battery power
   - in Low Power Mode
   - at a thermal state of `serious` or worse
   - by the owner's hand from the menu

   The menu shows the reason ("Paused — on battery"). The owner can override it ("Analyse anyway
   for an hour"), and the override expires by itself.

3. **Analysis runs at background priority as the platform defines it.** The pool initialiser keeps
   `nice` and, on Darwin, also applies the background QoS clamp (`PRIO_DARWIN_BG`). On Apple
   silicon that places the work on efficiency cores and throttles its I/O. This is a platform branch
   inside the server, which ADR-0131 point 4 permits: the server adapts to where it runs, and no
   feature depends on macOS.

4. **A desktop server runs one analysis worker, always.** Throughput is not the goal on a machine
   someone is using. On Macs with 8 GB of memory or less, Familiar Server also delays the CLAP phase
   while memory pressure is high, rather than recommending `DISABLE_CLAP_EMBEDDINGS`, which costs
   Find Similar and suggested tracks.

5. **Familiar Server never keeps the Mac awake.** It holds no power assertion for analysis, for a sync
   or for a client. When the Mac sleeps, work stops. On wake, it checks the server's health
   and the scheduler resumes. A sync due while asleep runs once, not once per missed slot.

6. **On the desktop, the scheduled sync is a backstop.** With ADR-0136 point 10's folder watch, new
   music is noticed when it arrives, and the two-hourly sync catches what the watch missed. Both
   obey point 1.

## Alternatives Considered

- **No policy: rely on `nice` and a single worker.** Nothing to build. Rejected: `nice` only
  arbitrates the CPU. A first sync of a large library is days of one core at full use, and on
  battery that is hours of charge, with no sign in the interface of why.
- **Work only when the machine is idle** (no input for some minutes). It never competes with the
  owner. Rejected: on a machine used all day, a first analysis might never finish. The background
  QoS clamp (point 3) already yields to foreground work, and the complaints this ADR prevents are
  about battery and heat, which point 2 addresses directly.
- **Analyse overnight only.** It is predictable. Rejected: laptops are asleep overnight, and point 5
  will not wake them.
- **Let the Mac sleep less while a first sync is running**, so it finishes sooner. Rejected: a
  background app that changes how the owner's machine sleeps is the behaviour this ADR exists to
  rule out.

## Consequences

- **Positive:** Familiar does not appear in a laptop's battery or heat complaints, and when it
  pauses it says so.
- **Positive:** pause and resume is a real control for the NAS as well, where only cancel existed.
- **Tradeoff:** a first analysis on a laptop takes longer in wall-clock time than on a NAS, by an
  amount that depends on how often the machine is on power. The menu shows progress so that "slow"
  is visible rather than mysterious.
- **Follow-up:** correct `CLAUDE.md`'s "nothing is scheduled" and the matching sentence in
  `VERSIONING.md`. Both are true of analysis narrowly and misleading about the machine.
