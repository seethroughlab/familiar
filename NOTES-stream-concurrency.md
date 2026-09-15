# Note: `/tracks/{id}/stream` has no concurrency bound

**Date:** 2026-09-07
**From:** ops session on the `openmediavault` NAS
**Status:** diagnosed, not fixed. Root cause is client-side; this is the server half.
**Companion note:** `../familiar-apple/NOTES-download-concurrency.md`

---

## Summary

The iOS client's favourites auto-download queued ~4,800 simultaneous track
downloads at the NAS. The server accepted all of them, and for two hours the box
ran at load 41 with 82–89% iowait and 42 tasks blocked on disk. 37–39 of those
blocked tasks were `uvicorn` threads.

The client is where the fix mainly belongs — see the companion note. But the
server currently has **no ceiling of its own**, so any client bug, any second
client, or a browser tab with an aggressive prefetch can do this again. That is
worth closing here regardless of what the client does.

## The mechanism

`stream_track` — `backend/app/api/routes/tracks/streaming.py:84` — ends in
`stream_file()`, which returns Starlette's `FileResponse`. `FileResponse` performs
its `stat` and its reads via `anyio.to_thread.run_sync`.

That thread pool is process-wide and, by default, **40 tokens**. Uvicorn here runs
`--workers 1` (the docstring at `backend/app/api/streaming.py:22-26` explains why:
CLAP needs ~1.5 GB, so more workers would OOM). So there is exactly one pool for
the entire API.

Roughly 40 concurrent `/stream` responses therefore occupy every worker thread in
the process — and each one is parked in a blocking read against a 7,200 RPM disk
that can service ~150 seeks/sec. The measured 37–39 blocked `uvicorn` threads sits
right at that 40-token default, which is what points at this being the binding
constraint.

**Please verify the 40 figure before building on it.** It is anyio's documented
default and it matches the thread count observed from outside the container, but I
did not read the running config to confirm nothing overrides it.

Once the pool is saturated, *every* endpoint that needs a thread queues behind
bulk downloads. That is the part that makes this a server concern and not merely a
client one: `/health` was answering slowly during the event because file reads for
a background sync had taken every thread.

## This is the same trigger as 2026-08-02

The comment at `streaming.py:107-113` records the prior incident:

> Bulk-downloading 1,720 favourites on 2026-08-02 produced 2,416
> `QueuePool limit ... timed out` errors, and the Mac client stored 834 of the
> resulting 500 bodies as `.mp3`.

Releasing the DB connection early (`await release_connection(db)`,
`streaming.py:118`) was the right fix for the symptom then, and the pool
exhaustion has not recurred. But nothing bounded *concurrent file reads*, so the
same client behaviour has now produced the same shape of failure against a
different resource — the anyio thread pool and the disk instead of the SQLAlchemy
pool.

The generalisable lesson: an unbounded client fanning out against a single-worker
server will find whichever resource is scarcest. Fixing them one at a time just
moves the queue.

## Suggested changes

1. **Bound concurrent streaming responses.** A module-level
   `asyncio.Semaphore` held across the `FileResponse` — sized to something like
   8–12 — keeps the disk usefully busy while leaving threads for everything else.
   The subtlety: the semaphore must be released when the response finishes
   *sending*, not when the handler returns, or it will not actually bound
   anything. A background task on the response, or an ASGI middleware wrapping the
   route, are the two shapes that get this right.

2. **Prefer 503 + `Retry-After` over unbounded queueing** once the limit is
   reached. A client that is told to back off can back off; a client whose request
   is accepted and then takes 424 seconds cannot tell the difference between slow
   and broken. Note the 2026-08-02 incident ended with a client writing HTTP error
   bodies to disk as `.mp3` — an explicit, well-formed rejection is much easier for
   a client to handle correctly than a timeout.

3. **Distinguish bulk sync from playback.** Both currently use
   `/tracks/{id}/stream`, so the server cannot prioritise a person pressing play
   over a background cache fill. If the client marks sync traffic (header or query
   param — see the companion note), the two can get separate, differently-sized
   limits. Interactive playback should always win.

4. **`slowapi` is already wired up.** `backend/app/api/ratelimit.py` defines a
   limiter keyed on client IP and it is applied to the library scan
   (`library_sync.py:57`). A per-IP rate limit on `/stream` would be a cheap first
   line of defence, though note it is a *rate* limit, not a *concurrency* limit —
   the two are different and this incident was concurrency. Use it as a complement,
   not a substitute.

5. **The artwork endpoint needs the same treatment.** 3,458 requests to
   `/tracks/{track_id}/artwork` rode along with the 4,849 stream requests.

## Testing

`backend/tests/test_stream_concurrency.py` uses `max_workers=3` throughout. That is
below the level where any of this appears, so the suite passed through both
incidents and would pass again. A useful test needs to assert a **bound** —
e.g. that the N+1th concurrent request is rejected or made to wait, rather than
merely that nothing raises.

## Observed numbers, for reference

```
window            2026-09-07 11:08 – 13:10 (partial resumption after)
load average      41.20  35.35  22.55     (8 cores)
iowait            82–89%
procs_blocked     42  (37–39 of them uvicorn threads)
familiar-api      read 75.2 GB / wrote 2.4 MB
per-request time  180–424 s for /stream
stream requests   4,849
artwork requests  3,458
playback starts   97          ← the ratio that identifies this as bulk sync
```

Caveat on provenance: these came from the archived syslog. The live journal for
part of this window was lost to an unrelated journald size cap applied mid-incident,
so treat the route counts as covering the archived portion rather than every minute
of the event.
