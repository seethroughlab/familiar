# ADR-0112: The Server Keeps a Ceiling of Its Own

Status: proposed

Date: 2026-09-07

Implements the two server-side Follow-ups of
[ADR-0111](ADR-0111-the-client-queues-transfers-rather-than-fanning-out.md), which bounded the
Apple client and said of this half only that it was "wanted" and "separate work". It is separate
work; it is not optional, and the reason is in the Context below.

Implementation:
- Written before the code, as ADR-0111 was, and built the same day: `backend/app/api/concurrency.py`
  with `FileResponseLimiter` and `FileResponseConcurrencyMiddleware`, installed in `main.py` inside
  `TokenAuthMiddleware`; ten tests in `backend/tests/test_file_response_bound.py`. The client half
  of point 3 is in `familiar-apple`'s `DownloadManager`.
- **Deployed to the NAS on 2026-09-07** via `scripts/deploy-dev.sh --backend-only` (rsync,
  `docker cp`, restart; 208 files verified against the container). Measured there afterwards, with
  1 KB range requests so the load was negligible:

  | check | result |
  | --- | --- |
  | 24 concurrent sync stream requests | 4 served, 20 refused with `Retry-After: 30` |
  | playback while sync saturated its share | 206 in 54 ms |
  | 40 concurrent cover requests | 40 served, none refused |
  | covers while audio was over its ceiling | 20 of 20 served |

  Load on the box went 0.40 → 1.43 for the duration and back. No errors in the container log.
- **The first deploy found the defect in point 6**, which is recorded there rather than quietly
  fixed: covers shared the audio budget and 8 of 24 were refused. It is the one thing in this record
  that reasoning did not catch and one command against the real server did.

## Context

Two incidents, five weeks apart, same trigger, different resource.

**2026-08-02.** Bulk-downloading 1,720 favourites produced 2,416 `QueuePool limit ... timed out`
errors, because a `yield` dependency is held until a response finishes *sending* and every
in-flight download therefore pinned a database connection for the whole transfer. The fix released
the connection before the body (`streaming.py:118`). It worked: that failure has not recurred.

**2026-09-07.** The same 1,589-track sync took the disk and the thread pool instead. Load 41 on
eight cores, 82–89% iowait, 42 tasks blocked in uninterruptible reads — 37–39 of them uvicorn
threads sitting on anyio's process-wide 40-token pool, which `--workers 1` makes the only pool this
API has. Individual `/stream` requests completed in **180 to 424 seconds**. 4,849 stream requests
and 3,458 artwork requests against 97 playback starts.

**The finding is the relationship between those two paragraphs.** Fixing the scarcest resource does
not remove the queue; it moves it to whatever is next-scarcest. The database pool was fixed and the
pressure went to the threads and the spindle. Nothing in that sequence terminates, because there is
always a next resource, and the only place a bound holds for all of them at once is at admission.

ADR-0111 put that bound in the client, which is the fix that matters most and is still not
sufficient. A server whose only protection is the good behaviour of its clients is protected by
something it does not control: an old build of our own app that nobody has updated, a second
listener, a browser tab with an aggressive prefetch, or the next feature that reads files in a loop.
The client bound is unshipped as this is written, so the phone that caused this can still do it
again tomorrow.

One more thing the incident showed, which decides the shape below. `/health` was answering slowly
during the event — not because health checks are expensive, but because file reads for a background
sync had taken every thread in the pool. **A cache fill degraded playback and browsing for a person
sitting in front of the app**, and the server could not have prioritised differently even if it had
wanted to: both a sync and someone pressing play arrive as `GET /tracks/{id}/stream`, and nothing
distinguishes them.

## Decision

The API admits a bounded number of file responses, reserves most of that budget for playback, and
refuses the rest explicitly.

1. **A ceiling of twelve concurrent file responses, process-wide.** Against anyio's 40 threads, that
   leaves most of the pool for everything else — which is the specific harm on 2026-09-07, where the
   whole API queued behind file reads. Twelve rather than a number tuned for throughput: the library
   is on one 7,200 RPM disk serving on the order of 150 seeks a second, and a dozen scattered
   whole-file reads is already generous. The ceiling exists to stop forty.

2. **Four of those twelve, at most, may be background sync.** The reservation is the point of
   classifying at all: eight slots are always there for somebody pressing play, whatever a cache
   fill is doing. A well-behaved client presents at most three sync transfers (ADR-0111's client
   bound), so one syncing device fits and a second one waits rather than competing with playback.

3. **A client says which it is with `X-Familiar-Intent: sync`; unmarked traffic is playback.**
   A header rather than a query parameter, though the ops note offered both: a parameter is part of
   the URL, so a track would have two cache keys — one for the copy that was synced and one for the
   copy that was played — in the client's `URLCache` and in anything between. The distinction is
   about the intent of a request, not about which bytes are wanted. Unmarked traffic keeping a
   listener's priority is the safe default: an old client, a browser, or anything that has never
   heard of the header loses only the reservation.

4. **A request over the limit is refused with 503 and a `Retry-After`, never queued.** From the ops
   note, and it is the sharpest thing in this record: a client that is told to back off can back
   off; a client whose request is accepted and then takes 424 seconds cannot tell the difference
   between slow and broken. Sync is told 30 seconds and playback 5, because nothing is watching a
   spinner for a background transfer. The body is `docs/ERROR-CONTRACTS.md`'s ordinary envelope —
   the 2026-08-02 incident ended with a client storing 834 error bodies as `.mp3`, so an error
   shaped like every other error is worth more here than a bespoke one.

5. **It is ASGI middleware, not a route dependency, because the resource is held while the body is
   sent.** A dependency releases when the handler returns, which for a 40 MB file is the *beginning*
   of the transfer — the same mistake the 2026-08-02 fix was correcting one layer down. Wrapping
   `send` and releasing on the last body message is the only placement that bounds anything, and
   a `finally` releases on the paths that never reach it: an exception, a client hanging up
   mid-track. A slot that is taken and never given back ratchets the ceiling down to zero and stops
   the server serving files at all, silently — worse than the failure being fixed, and asserted
   against in the suite.

6. **Artwork is bounded on a budget of its own — sixteen — and it waits rather than being
   refused.** 3,458 of the requests in that window were `/artwork`, so a ceiling covering only audio
   leaves the same exhaustion reachable by another route.

   This point originally put covers in the audio budget, on the argument that a cover cycles through
   its slot in milliseconds and costs a stream almost nothing. **The deploy disproved it in one
   command**: 24 concurrent cover requests against the live ceiling produced 8 refusals, and a
   refused cover is a permanent hole in a grid, because nothing retries an `<img>`. The two are
   different work — 9–88 KB out of the artwork cache against a whole-file read scattered over 16 TB
   of spinning disk — and sixteen of the former is not sixteen of the latter.

   The waiting is the same rule as point 4 rather than an exception to it: **refuse when waiting
   would be indistinguishable from broken.** A stream lasts minutes, so a queued request tells a
   client nothing; a cover lasts milliseconds, so a two-second ceiling on waiting is invisible to a
   person and strictly better than a hole. Past two seconds it is refused, because a wait with no
   end is the failure this whole record replaces.

7. **The limiter counts refusals and its own high-water mark.** Both incidents were diagnosed from
   the outside, by counting route hits in the NAS's syslog, because the server recorded nothing
   about the pressure it was under. `peak_in_flight` says what it was actually asked to do; a
   refusal count only says when it said no.

8. **The client treats a 503 as an appointment rather than a failure.** In `familiar-apple`, a
   refused track goes back on the queue and the queue holds for `Retry-After` — it is not marked
   failed, because a red row for a server that is merely busy is wrong, and because failing would
   drop most of a favourites sync the first time two devices ran at once. Holding the *whole* queue
   rather than just that track is the load-bearing half: answering a refusal with the next track
   immediately is a tight retry loop against a machine that has just said it is saturated.

## Alternatives Considered

**Per-IP rate limiting with `slowapi`, which is already wired up.** Rejected as a substitute,
accepted as a possible complement. `ratelimit.py` exists and is applied to library scan, and a rate
limit on `/stream` would be cheap. But a rate limit is not a concurrency limit: both incidents were
produced by a modest *number* of requests that were each held open for minutes, and a limiter that
counts requests per minute cannot see that. Adding one now would create the appearance of a fix
without the substance.

**Size the anyio thread pool up.** Rejected: it moves the queue again, to the disk, which is the
resource that cannot be widened. Forty threads all blocked on a drive that serves 150 seeks a second
is not a thread shortage.

**More uvicorn workers.** Not available. `--workers 1` is pinned in the Dockerfile because CLAP
needs about 1.5 GB, and this is also what makes a module-level limiter correct: it bounds the whole
API rather than one worker's share. If that ever changes, the constant becomes per worker and has
to be divided by hand.

**Queue over the limit instead of refusing.** Rejected under point 4. It is also what the failure
looked like from the outside on 2026-09-07 — requests were accepted and then took 424 seconds, which
is a queue with no admission control and no way to tell a client anything.

**Let sync wait while playback is refused.** Rejected as backwards, and worth stating because it is
the natural shape of a priority queue. The listener is the one who can tell; a background sync
cannot be inconvenienced.

**Infer sync from the `User-Agent` or from request rate.** Rejected: both are guesses about a fact
the client already knows and can simply state. A guess that is wrong in the safe direction still
mislabels every browser prefetch, and one that is wrong in the unsafe direction throttles a person.

## Consequences

- **Positive.** The 2026-09-07 shape is no longer reachable from any client, updated or not. That
  is the whole point of putting it here as well as in the app.
- **Positive.** The server can now say something about its own load. Both incidents were reconstructed
  from syslog line counts on the NAS days after the fact.
- **Tradeoff, and the one to watch.** Twelve is a guess informed by one measurement of one disk. Too
  low and a legitimate multi-device household gets 503s during ordinary listening; too high and the
  ceiling does not bind before iowait does. It is one constant in one file, and `peak_in_flight` is
  what should be read before changing it.
- **Tradeoff.** Sync throughput is now bounded by the server as well as by the client, so a full
  1,589-track sync from two devices takes longer than it would have. That is the intended trade —
  the alternative measured 30.5 GB of partial files and 385 finished tracks.
- **Risk, named.** A refusal is only as good as the client's handling of it. Point 8 covers our
  client; the web player and anything else that fetches `/stream` will see a 503 they have never
  seen before, and the honest position is that this has not been checked. A 503 is at least an
  ordinary error to any HTTP client, where a 424-second response is not.
- **Deployed, but not yet observed under a real sync.** The measurements above are 1 KB range
  requests, which prove the accounting and nothing about a 40 MB `FileResponse` held open for
  minutes over Tailscale. The number to watch is `refused_interactive`: above zero during ordinary
  listening means twelve is too low. The first genuine test is the next favourites sync from a
  phone running the client half — which is not shipped yet.
- **Follow-up.** The counters are readable in the process and reported nowhere. A line in `/health`
  or the metrics collector would make the next incident diagnosable from inside the server rather
  than from the NAS's syslog, which is where both of these came from.
- **Follow-up.** ADR-0111's own follow-up about the monit threshold still stands: the NAS's
  five-minute load alert was raised 8.0 → 16.0 on the morning of the incident for unrelated reasons,
  and should come back down now that both halves of the bound exist.
