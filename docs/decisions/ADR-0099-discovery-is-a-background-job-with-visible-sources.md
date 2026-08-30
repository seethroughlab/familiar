# ADR-0099: Discovery Is a Background Job, and Its Sources Are Visible

Status: proposed

Date: 2026-08-30

Extends [ADR-0058](ADR-0058-the-web-app-is-an-administration-tool.md), whose point 2 makes the
Server destination the place you find out whether the thing is working.

## Context

On 2026-08-30 an MCP host asked Familiar for new releases and the tool hung. Measured: **240 seconds
with no response and no error**, which the host reports as a bare *"Tool execution failed"*.

The cause is upstream and ordinary. MusicBrainz rate-limits to **one request a second per client**
and answers **503** when that is exceeded, which happens whenever this runs alongside the background
artist resolver. `musicbrainzngs` retries with backoff, logs the retry at `INFO`, and tells the
caller nothing. Fifteen artists, each retried, turns a docstring promising "10–15 seconds" into a
request that never returns. A single artist measures **0.6 s** when it gets through, so the
arithmetic only fails under throttling — which is why it looked fine when it was written.

That has been bounded already: a 20-second budget, a 6-second per-artist timeout, partial results,
and a note that distinguishes "nothing new" from "we ran out of time". This ADR is about why the
request was talking to MusicBrainz at all.

### The precompute already exists, and nothing reads it

Measured on the production database:

| | |
|---|---|
| `external_album_cache`, `discovery_context = 'artist_new_release'` | **600 rows** |
| `artist_check_cache` | **520 rows** |
| a daily job at 03:00 (`daily_new_releases` in `background/manager.py:109`) | **runs** — eight log entries in 24 h |

`backend/app/services/new_releases.py` is 446 lines whose docstring says it "reads/writes the shared
`external_album_cache` table filtered to `discovery_context='artist_new_release'`".

**And `GET /library/artists/new-releases` does not read any of it.** Nor does the MCP handler
`_get_new_releases`, which duplicates the endpoint's logic rather than calling it. Both walk the top
fifteen artists and hit MusicBrainz live, on the request path, while a populated cache sits beside
them. This is the third capability-with-no-caller found in this codebase this week.

### The freshness nobody could see

The newest `artist_new_release` row is dated **2026-08-25** — five days old — while
`listening_profile_recommendation`, written by the neighbouring job, is from today. So the daily
new-release job is running and *not writing*, almost certainly hitting the same 503 wall the request
path hit.

Nothing surfaced that. `panels/server/ApiKeyStatus.tsx` is 55 lines and reports whether an API *key*
is configured, which is not the same question as whether a source is *working*. A source can have a
valid key, be scheduled, run daily, fail every time, and look identical to a healthy one.

### What is actually being asked of these sources

Discovery — finding music you do not own — currently uses:

- **MusicBrainz**, for new releases, external album recommendations and artist resolution. No key.
- **Last.fm**, for similar artists. Keyed.
- **Bandcamp**, for purchase recommendations. No key; reads their JSON endpoint.

Enrichment of music you *do* own additionally uses AcoustID, the Cover Art Archive, Wikipedia and the
community analysis cache, and is out of scope here.

**MusicBrainz is doing nearly all the discovery work alone**, which is why one upstream's rate limit
stopped everything at once. Last.fm and Bandcamp are integrated and barely used for it.

## Decision

1. **The request path never calls an external service for discovery.** `GET
   /library/artists/new-releases` and the `get_new_releases` MCP tool read `external_album_cache`
   and return immediately. A request may return stale results or none; it may not return slowly.

2. **The background job is the only thing that talks to MusicBrainz, Last.fm or Bandcamp for
   discovery**, and it is the only place that has to care about rate limits, retries and backoff.
   This is what `new_releases.py` was built for and what the 03:00 job already does.

3. **Discovery runs continuously rather than once a night.** A single daily sweep is why a rate-limit
   window costs a whole day: the job either wins the race at 03:00 or the library learns nothing for
   twenty-four hours. Instead it works a small, prioritised batch on a short interval, so throttling
   costs one batch and the next one picks up where it stopped. `artist_check_cache` already records
   per-artist progress, which is what makes resumption possible.

4. **Sources are polled independently, and one being down does not stop the others.** MusicBrainz
   returning 503 must not prevent Last.fm from answering, and today it effectively does, because the
   scan is a single sequential loop over one source.

5. **Last.fm and Bandcamp become discovery sources, not just recommendation lookups.** Both are
   already integrated. Using them widens what "new music" can mean beyond "a release group appeared
   in MusicBrainz", and removes the single point of failure point 4 is about.

6. **Every source reports health, and it is a first-class surface on the Server destination**
   (ADR-0058 point 2). For each source: when it last succeeded, when it last failed and with what,
   how many items it has contributed, and whether it is currently backing off. **Not whether a key is
   configured** — that is what exists today and it is the question that let a five-day-stale table go
   unnoticed.

7. **Staleness is visible where the data is used, not only in the dashboard.** A discovery response
   carries the age of what it is returning, so a host reading it aloud can say "as of five days ago"
   rather than presenting stale results as current. The bounded-scan work already established that a
   caller must be able to tell "nothing" from "we did not finish"; this is the same rule applied to
   time.

8. **A source that has never succeeded is reported as such, and is not silently skipped.** The
   failure mode this ADR exists to prevent is a component that runs, fails, and looks like a
   component that ran and found nothing.

## Alternatives Considered

- **Keep the request path as it is and rely on the timeouts already added.** Cheapest, and it fixes
  the hang. Rejected because it makes every discovery request a network call to a rate-limited
  third party: the best case is slow, the common case under throttling is partial, and the cache
  that would answer instantly is right there. The timeouts are a floor, not a design.

- **Cache the request-path call with a TTL instead of moving to a job.** Simpler than a scheduler,
  and the first request warms it. Rejected because the first request still pays the full cost, and
  under throttling the first request is the one that hangs — so the miss path is exactly the failure
  being fixed. It also gives no place to put backoff state that outlives a request.

- **Poll harder rather than continuously.** Increase the daily job to hourly and leave the rest
  alone. Rejected as insufficient on its own: it narrows the window but keeps a single sequential
  MusicBrainz loop, so point 4's problem — one source's outage stopping the others — is untouched.

- **Add a "sources" page rather than integrating health into Server.** A dedicated screen has room
  for detail. Rejected by ADR-0058 point 2: the Server destination is where you find out whether the
  thing is working, and a second place to look is how a five-day-stale table stays unnoticed for
  five days.

- **Report health only in logs.** It is already there — the 503s were logged at `INFO` throughout.
  Rejected because that is precisely what failed: the information existed, in the one place nobody
  reads until something is already known to be wrong.

## Consequences

- **Positive** — discovery requests answer immediately, from data that is already there. The tool
  that hung for 240 seconds becomes a database read.
- **Positive** — the five-day-stale table becomes visible the day it happens rather than when
  somebody investigates an unrelated hang.
- **Positive** — Last.fm and Bandcamp start contributing to discovery, which is both more music and
  less exposure to one upstream's rate limit.
- **Tradeoff** — results are as fresh as the last successful run, not as fresh as the request. Point
  7 makes that visible rather than pretending otherwise, but a user asking at 09:00 may be told
  about a release found at 03:00.
- **Tradeoff** — continuous polling is more total requests to services that rate-limit, and the
  prioritised batch has to stay small enough to be a good citizen. `musicbrainzngs`'s 1 req/sec
  limiter is per-process, so this needs care if the work is ever parallelised.
- **Follow-up** — the endpoint and `_get_new_releases` duplicate each other's logic. Both were
  bounded separately on 2026-08-30 because fixing one fixed nothing the user hit. Moving the read to
  the cache is the moment to make one call the other.
- **Follow-up** — `musicbrainzngs` retries 503s internally and reports nothing to its caller. Point 6
  needs a real signal, which probably means wrapping the client rather than reading its logs.
- **Follow-up** — nothing here decides how a *user* triggers a refresh when they know something is
  new. Point 1 forbids a synchronous scan; an explicit "check now" that enqueues a job and returns is
  the obvious shape, and is not decided.
