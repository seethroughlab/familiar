# ADR-0099: Discovery Is a Background Job, and Its Sources Are Visible

Status: accepted

Implementation:
- **Phase 0** (`familiar` #243) — the crash. `save_discovered_release` deduped on `release_id`
  alone against a table whose uniqueness is three *partial* indexes, one per context. One release in
  two contexts stopped nineteen consecutive nights. Fixed as an upsert scoped by context, plus
  per-artist fault isolation with the rollback that makes it work. Verified live: the 75-artist batch
  that had been dying completed with `0 failed`.
- **Phase 1** (#244) — point 1. The MCP tool that hung for 240 seconds now reads the cache and
  answers in **12 ms**. `GET /library/artists/new-releases` was *deleted* rather than converted: it
  had no callers in either repository, because the Discover page the Mac and iPhone show is the
  embedded web surface, which already read the cached endpoint. Point 7 shipped with it, as three
  states rather than two — never run, stale, current.
- **Rotation gate** (#246) — not a point here, a bug ADR-0101 named. The batch selected *from*
  `ProfilePlayHistory`, hiding 2,614 of 3,453 owned artists. Widening the pool alone changed nothing,
  because the played set already oversubscribed the rotation; a reserved share for never-checked
  artists is what makes coverage advance. A second defect surfaced only on deployment: artists
  MusicBrainz cannot match were re-selected every batch forever, so the backlog never drained.
- **Phase 2** (#247) — points 2 and 3. Ten artists every twenty minutes, ~1% duty cycle, with
  `max_instances`/`coalesce` that a daily job never needed. Profiles now take turns rather than the
  first one deciding for the household. `check_priority` dropped: profile-relative value, table keyed
  per artist.
- **Phase 3** (#248) — points 4, 6, 8, 10. `discovery_source_health` in Postgres, because Redis
  expires and the jobstore is in-memory. `backoff_until` is read by the batch, not just rendered.
  A `not_instrumented` state was added after deployment showed the aggregate badge reading
  `never_succeeded` forever for sources nothing had wired — which is the ADR's own conflation, one
  level up.
- **Point 11** (`familiar` #250) — ListenBrainz, chosen over point 5's sources after probing all three
  against the live services. One unauthenticated call returns 7,713 fresh releases carrying
  MusicBrainz ids; 87 matched this library and 63 were new, the other 24 collapsing onto rows
  MusicBrainz had already written. That collapse is the point: `release_group_mbid` *is*
  `external_album_cache.release_id`, so the existing partial unique index dedupes across sources with
  no fuzzy matching anywhere. Runs every three hours — one request, then local filtering — against
  MusicBrainz's one-per-second-per-artist.
- **Point 12** (#251) — `discovery_enabled` plus a flag per source. Off means no discovery request
  leaves the machine; the read path still serves what is cached. The half that needed care is that a
  disabled source keeps its last success forever, so without an explicit `disabled` state it read
  `working` indefinitely after being switched off — this ADR's own confusion, reintroduced by the
  switch meant to resolve it.
- **Point 5 is not built, and should not be built as written.** Its premise — "both are already
  integrated" — is true and misleading, and probing the live services is what showed it.
  **Last.fm has no release API**; it was retired in 2016. It offers similar artists, so it cannot
  produce a release and can only feed more artists into MusicBrainz, which means it does not remove
  the single-upstream exposure point 5 credits it with. **Bandcamp returns no release dates** from
  either its search or its album endpoint, so a 2026 record is indistinguishable from a 2002 one;
  its search also answers "Coil" with *Dödsrit — Mortal Coil*. The date is reachable inside the
  page's `data-tralbum` attribute at ~1.9 s per album, scraped, with no API contract — a project
  rather than an integration, and worth doing only for the *purchasable* angle rather than for
  freshness. Both report `not_instrumented`, which is the honest state.

**Four of the fixes in this ADR were inert when first written** — correct in the code and changing
nothing observable — and each was caught by checking the running system rather than the test suite.
That is the same lesson the original defect taught, and it is the most reusable thing here.

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
| `artist_check_cache` | **520 rows**, **0 checked in the last 24 h**, `check_priority` **0.0 on all of them** |
| a daily job at 03:00 (`daily_new_releases` in `background/manager.py:109`) | **runs and crashes** — every night since 2026-08-11 |

`backend/app/services/new_releases.py` is 446 lines whose docstring says it "reads/writes the shared
`external_album_cache` table filtered to `discovery_context='artist_new_release'`".

**And `GET /library/artists/new-releases` does not read any of it.** Nor does the MCP handler
`_get_new_releases`, which duplicates the endpoint's logic rather than calling it. Both walk the top
fifteen artists and hit MusicBrainz live, on the request path, while a populated cache sits beside
them. This is the third capability-with-no-caller found in this codebase this week.

### The freshness nobody could see

The newest `artist_new_release` row is dated **2026-08-25** — five days old — while
`listening_profile_recommendation`, written by the neighbouring job, is from today.

#### The premise that was wrong: it is not the rate limit, it is us

This ADR was first drafted saying the daily job was "almost certainly hitting the same 503 wall the
request path hit". **That is false, and checking it before implementing is what found the real
defect.**

The job has not been throttled. It has *crashed*, every night since at least 2026-08-11 — nineteen
consecutive nights — with `sqlalchemy.exc.MultipleResultsFound`, raised at
`services/new_releases.py:196` inside `save_discovered_release` and reached from
`tasks/new_releases.py:216`.

`save_discovered_release` deduped on `release_id` alone. `external_album_cache` does not enforce
uniqueness that way: it carries **three partial unique indexes**, one per `discovery_context`
(`ix_eac_artist_new_release_unique`, `ix_eac_listening_profile_unique`, `ix_eac_playlist_rec_unique`),
so the same release legitimately exists once per context. Production held exactly **one** such
release — `b9df3445-4699-4221-9994-734c1c912468`, "Reality Awaits", in both `artist_new_release` and
`listening_profile_recommendation` — and `scalar_one_or_none()` raises on two rows.

**One row stopped nineteen nights of discovery**, because the exception escaped the only `try` in the
path — `_check_artist_against_musicbrainz` guarded the MusicBrainz call and nothing else — into a
batch loop with no per-artist guard.

Two consequences for what this ADR decides. First, **source health as originally argued would not
have caught this**: the failure was ours, not an upstream's, and MusicBrainz answered fine throughout
— which is why point 10 below now exists. Second, point 8's "runs, fails, and looks like a component
that ran and found nothing" stops being a hypothesis; it is a literal description of nineteen logged
crashes nobody read. Points 1–8 otherwise stand.

Two further corrections to this ADR's own framing, found the same way. **`GET
/library/artists/new-releases` has no callers in either repository** — the Discover page the Mac and
iPhone display is the embedded web surface, whose `NewReleasesSection.tsx` calls the *cached*
`GET /new-releases`. So the user-facing read path already satisfies point 1 and has all along; it was
serving a cache the crash had frozen. The 240-second hang came through the MCP tool
`get_new_releases`, which carries its own copy of the live-scan logic. And **`get_check_status`
derives `last_check_at` from `max(ArtistCheckCache.last_checked_at)`**, which read 2026-08-28 while
every run since 08-11 crashed — a freshness signal computed from a side effect of partial work.

Nothing surfaced any of it. `panels/server/ApiKeyStatus.tsx` is 55 lines and reports whether an API *key*
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

9. **One artist's failure costs one artist.** A discovery batch is fault-isolated per item: an
   exception on one artist is recorded, the transaction rolled back to the last commit, and the batch
   continues. The nineteen-night outage was one bad row taking a whole run with it, and no amount of
   source health would have prevented that — only the isolation would. The rollback is the
   load-bearing half: catching without it leaves the session in a failed transaction, so every later
   artist fails too and the fix changes nothing.

10. **Health covers the job's own outcome, not only its upstreams'.** Did the batch run, did it
    finish, did it write. A source that answered perfectly while our own writer crashed must not read
    as healthy — which is exactly the state that held for nineteen nights, and which points 6 and 8
    as originally written would have rendered green.

### 11. The sources, and why these

| source | what it adds | key | notes |
|---|---|---|---|
| **MusicBrainz** | release groups per artist | none | already integrated; rate-limits at 1 req/s and answers **503** silently |
| **ListenBrainz** | `GET /1/user/{user}/fresh_releases` — releases by artists you actually listen to | token | **shares MusicBrainz IDs**, so it joins to existing rows with no new matching |
| **Last.fm** | similar artists → their releases | yes, configured | already integrated and barely used for discovery; free tier is 5 req/s |
| **Bandcamp** | what is purchasable, and its editorial layer | none | already integrated for purchase recommendations |

**ListenBrainz is the significant addition.** It is the same MetaBrainz family as MusicBrainz, so
its identifiers are the ones already in the database — no fuzzy artist matching, which is where
cross-source discovery usually goes wrong. Its fresh-releases endpoint is *personalised to listening
history* rather than to what is in the library, which answers a different question than MusicBrainz
does. And it rate-limits **explicitly**, returning `X-RateLimit-Remaining` and `X-RateLimit-Reset-In`
headers with a `429` — a source that says how much budget is left, rather than a silent 503 with a
retry buried in a library's `INFO` log.

**Deferred, with reasons.** *Deezer* has a usable free tier but introduces a second identifier space
and would need matching logic that ListenBrainz does not. *Spotify* requires registering an OAuth
application, and a project whose premise is not depending on a streaming service should not need one
to find out what came out this week. *SoundCloud* has no dependable free API.

### 12. Discovery is configured the way everything else is, and can be turned off

`AppSettings` already has a shape for this: a credential field beside an `_enabled` flag, persisted
in `data/settings.json`, edited in the admin UI —
`lastfm_api_key`/`community_cache_enabled`/`s3_backup_enabled` and the rest. Discovery follows it
rather than inventing a second mechanism.

**`discovery_enabled`, defaulting to on, switches the whole subsystem off.** There is no such
setting today, and there needs to be. This ADR turns an occasional nightly job into a process that
continuously contacts four third parties about what a person listens to; that is a change in
posture, not just in cadence, and a self-hosted music server should let its owner decline it in one
place. Off means the background job does not run and no discovery request leaves the machine — the
read path still serves whatever is already cached.

**Each source has its own `_enabled` flag**, because they fail and cost differently and point 4
polls them independently. Turning MusicBrainz off while leaving Last.fm on has to be expressible, or
the response to one source misbehaving is to disable discovery entirely — which is what effectively
happened on 2026-08-30.

**A source that is enabled but unconfigured is an error state, not a silent skip.** Last.fm without
a key, ListenBrainz without a token: the health surface reports *"enabled, cannot run: no token"*.
Silently skipping is how a source configured months ago and broken since goes unnoticed, which is
the failure this whole ADR is about.

**Cadence is a single interval setting, not per-source.** Per-source cadence sounds more flexible
and is a trap: four intervals interact with four rate limits and nobody can predict the result. One
interval, with each source's own limiter deciding how much of a batch it can take.

**Disabling a source does not delete what it found.** Its rows stay, marked with their `source`
from a `source` column, and stop being refreshed. Deleting on disable would make a toggle destructive and make
"turn it off and see" an expensive experiment. What a disabled source's stale rows look like to a
reader is point 7's job.

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
  bounded separately on 2026-08-30 because fixing one fixed nothing the user hit. Since the endpoint
  turned out to have no callers, the resolution is to **delete it** (ADR-0077's precedent) and have
  the MCP tool read the cache through `NewReleasesService`, rather than to make one call the other.
- **Follow-up** — `musicbrainzngs` retries 503s internally and reports nothing to its caller. Point 6
  needs a real signal, which probably means wrapping the client rather than reading its logs.
- **Follow-up** — nothing here decides how a *user* triggers a refresh when they know something is
  new. Point 1 forbids a synchronous scan; an explicit "check now" that enqueues a job and returns is
  the obvious shape, and is not decided.
