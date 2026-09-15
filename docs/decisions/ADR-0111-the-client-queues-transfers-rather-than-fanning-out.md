# ADR-0111: The Client Queues Transfers Rather Than Fanning Out

Status: accepted

Date: 2026-09-07

Extends [ADR-0009](ADR-0009-offline-downloads-are-background-transfers.md), whose point 1 chose
background transfers and never said how many. Point 6 of that ADR deferred acting on
`favorites_auto_download`; it has since shipped, and this is what that turned out to cost.

Implementation:
- **Accepted 2026-09-15.** In the App Store since 1.4 build 36 (2026-09-08) and through the first 1,740-track sync under ADR-0118 without a refusal. Point 4's in-memory queue turned out to have a cost the record did not name — with the session discretionary, a background sync waited on iOS to wake the app for every three tracks — which ADR-0009's amendment of the same day records and answers.
- **Written before the code**, which is the order ADR-0107, ADR-0108 and ADR-0109 each failed to
  keep and the last of which asked, in its final Follow-up, for the rule to change or the practice
  to. This is the practice changing.
- Built the same day on `familiar-apple` branch `worktree-ambient-synthesiser`, in the order the
  points are numbered. `DownloadManager` gained `queued`, `pump()` and `cancelRetiredSessions()`;
  `ArtworkFetcher` and `ConcurrencyGate` are new in `FamiliarKit`; `ArtworkThumbnail` no longer uses
  `AsyncImage`; `Downloads.shared` replaces the `@StateObject` handoff. Twelve tests across
  `DownloadConcurrencyTests` and `ArtworkConcurrencyTests` assert the bounds.
- **The regression test was checked against the bug, not just against the fix.** With
  `maximumConcurrentTransfers` temporarily raised to 40, the census recorded a peak of 24 concurrent
  transfers for 24 requests — the fan-out itself, reproduced. That also proves the test measures the
  queue rather than the connection cap, since its stub session allows 64 per host.
- Accepting this is Jeff's; nothing here has been reviewed yet, and none of it has run against the
  real server or on the phone.
- The client half is planned in `PLAN-download-concurrency.md` on `familiar-apple` branch
  `worktree-ambient-synthesiser`. The diagnosis is in two ops notes written the same day:
  `familiar-apple/NOTES-download-concurrency.md` (client) and `familiar/NOTES-stream-concurrency.md`
  (server). They are the measurements; this is the decision.
- **How the client half is verified on a device**, because it cost an hour to establish and is not
  guessable: `idevicesyslog` and `devicectl --console` do not surface the app's `Logger` output, and
  `log collect --device-udid` needs a TTY for `sudo`. What works is reading the container —
  `xcrun devicectl device info files --device $DEV --domain-type appDataContainer
  --domain-identifier com.familiar.player --username mobile` — and counting
  `Library/Application Support/Familiar/Downloads/` against `CFNetworkDownload_` staging files.
  Note that macOS formats the times in that listing with U+202F before AM/PM, so a regex with an
  ASCII space silently matches nothing.

## Context

Favourites auto-download has now taken the server down twice, five weeks apart, by the same
mechanism against two different resources.

**2026-08-02.** Bulk-downloading 1,720 favourites produced 2,416 `QueuePool limit ... timed out`
errors, and the Mac client filed 834 of the resulting 500 bodies as `.mp3`. The fix released the
database connection before the response body was sent (`streaming.py:118`), and the pool exhaustion
has not recurred.

**2026-09-07.** The same trigger, against the disk. For two hours the NAS ran at load 41 on eight
cores with 82–89% iowait and 42 tasks blocked in uninterruptible reads, 37–39 of them `uvicorn`
threads sitting on anyio's process-wide 40-token pool — which `--workers 1` makes the only pool the
API has. Individual `/stream` requests completed in **180 to 424 seconds**. The window carried 4,849
stream requests and 3,458 artwork requests against **97 playback starts**: fifty files pulled per
track played is a cache fill, not listening. `familiar-api` read 75.2 GB off one 7,200 RPM disk,
spread across the library rather than sequentially, so readahead bought nothing.

**That is the finding, and it is more general than either fix.** Capping the downstream resource
relocates the queue; it does not remove it. The DB pool was fixed and the pressure moved to the
threads and the spindle. The only place a bound holds for every downstream resource at once is the
source.

Three things in the client produced it.

1. **There is no queue.** `DownloadManager.start(_:)`
   (`Sources/FamiliarKit/DownloadManager.swift:201`) resumes every request in the array the moment
   it is handed one, and `startFavoritesAutoDownloadIfEnabled()`
   (`App/Shared/LibraryView.swift:1741-1768`) hands it the whole missing-favourites set — about
   1,589 tracks. `downloadAll` on the album, playlist and favourites screens funnels into the same
   call, so the shape repeats at smaller scale.

2. **The only bound was a connection cap, and it did not hold.** `httpMaximumConnectionsPerHost = 2`
   has been set since build 32 (`DownloadManager.swift:138`); the server saw roughly forty
   concurrent reads anyway. The ops note asserting the property was never set was read against
   `main` and is wrong on that point — which matters, because it means the cap was tried and the
   evidence is that something defeated it. `isDiscretionary` is not a second bound: it governs
   *when* the system starts transfers, and on wifi and power it started a great many at once.

3. **So almost nothing finished.** Measured on the phone at 13:24: 7,152 partial files holding
   **30.5 GB** in the session's staging directory, against **385** tracks filed in
   `Application Support/Familiar/Downloads/`. Bytes arrive; whole files rarely do. Under a bound the
   same bytes would have been about 300 finished tracks.

And a fourth defect, found on the device rather than in either note: **completions only land while
the app runs.** `AppDelegate.handleEventsForBackgroundURLSession` (`App/Shared/Downloads.swift:227`)
returns early when `AppDelegate.downloads` is nil, and that reference is assigned by `FamiliarApp`
at `FamiliarApp.swift:165`, inside work that runs when the SwiftUI scene appears. On a background
relaunch the scene generally does not appear, so the handler calls back immediately and the finished
transfers are never filed. With the app not running, completions held at 385 across three and a half
minutes; launching it filed 237 in four — a backlog being released, not fresh downloads. ADR-0009's
own device test proved the system relaunches us to deliver results, so what is being discarded is a
capability that was measured working.

## Decision

The client bounds its own outbound concurrency, and the bound is a tested property rather than a
constant somebody set.

1. **`DownloadManager` keeps a pending queue and resumes at most three transfers.** The next starts
   when one finishes, fails, or is cancelled, pumped from the delegate callbacks at
   `DownloadManager.swift:309-430`. Three rather than one because a queue of one makes an album
   serial and the point is to leave the worker answerable, not to stop downloading; three rather
   than forty because a 7,200 RPM disk services on the order of 150 seeks per second and whole-file
   reads spread across a library are nearly all seek. Wall-clock for a full sync is expected to
   improve, not regress: the disk stops thrashing.

2. **Every exit from a transfer pumps the queue**, including rejection by `DownloadIntegrity`,
   explicit cancellation, and `didCompleteWithError`. A path that forgets leaves the queue one slot
   short for the life of the process, and enough of those is a stall — a failure mode strictly worse
   than the fan-out this replaces, because it is silent and looks like the feature being broken.

3. **`isInFlight` comes to mean "has a task *or* is queued".** It means "has a task" today
   (`DownloadManager.swift:284`), and `start(_:)` skips anything in flight, so without this change
   every later call re-adds tracks that are already waiting.

4. **The pending queue lives in memory and nothing new is persisted.** Resumed tasks are already
   durable — `nsurlsessiond` holds them and `resumeExistingTasks()` recovers them — and a queued
   track has no task, so it is lost on termination. It is re-derived rather than restored: the
   favourites sweep recomputes the missing set on launch, which is the same reconciliation ADR-0009
   point 4 chose when it made the filesystem the truth and the index a cache of it. The cost is
   named in Consequences and it is real.

5. **The connection cap matches the queue and is demoted to a backstop.** It is no longer the
   mechanism; it is what bounds the damage if point 2 has a hole. Because a background session's
   configuration is persisted by `nsurlsessiond` against its identifier, changing the value is inert
   on every device that already has `.v2` — so **the value and the identifier change together**, to
   three and to `.v3`.

6. **Retiring a session identifier obliges cancelling the one it replaces.** Renaming to `.v2`
   orphaned the `.v1` session, and nothing opened it again: 1,984 of the 7,152 staging files predate
   build 32 and no code will ever finish them. On first run the fixed build opens each retired
   identifier and calls `invalidateAndCancel()`, guarded so it happens once. `.v3` makes `.v2` the
   second entry in that list on the day it is created, which is the point of writing it as a rule
   rather than as a one-off cleanup.

7. **The bound is asserted by a test against a stub session, not read off a constant.**
   `DownloadConcurrencyTests` today asserts `httpMaximumConnectionsPerHost == 2`
   (`Tests/FamiliarKitTests/DownloadConcurrencyTests.swift:58`) — it passed on both days that the
   server drowned, because the property was set and something else did not honour it. The
   replacement counts concurrent resumptions and asserts the peak never exceeds N. The server's
   `test_stream_concurrency.py` has the mirror-image flaw: `max_workers=3` is below the threshold
   where any of this appears, so it too passed through both incidents. **A concurrency test whose
   load is under the bound proves nothing**, and between them these two tests are most of why the
   same bug shipped twice.

8. **Artwork is bounded too, and by a different mechanism, because it is not our session.**
   `ArtworkResolver` hands back a `URL` (`Sources/FamiliarKit/ArtworkResolver.swift`) and the fetch
   is `AsyncImage`'s, which means `URLSession.shared`, which cannot be configured. So artwork
   surfaces move onto a session this app owns, with the same per-host cap. **It must be constructed
   with `URLCache.shared`**, which `FamiliarApp.swift:30` sizes at launch: the resolver's caching
   story is entirely the server's `Cache-Control: public, max-age=31536000` landing in that cache,
   and a fresh session with a default cache would silently refetch every cover forever. One number
   governs both paths; two mechanisms enforce it, because the client only issues one of them.

9. **`Downloads` outlives the SwiftUI scene.** A shared instance the `AppDelegate` can construct on
   demand, with `FamiliarApp` adopting it in place of its own `@StateObject`
   (`FamiliarApp.swift:48`). `handleEventsForBackgroundURLSession` then builds the stack, hands the
   completion handler to the manager, and lets the delegate deliver — the handler being called
   *after* the results are handled rather than instead of handling them. The existing early return
   is not a wrong choice given a nil reference; the wrong thing is that the reference can be nil in
   the one process state this method exists for.

## Alternatives Considered

**Keep N at two and avoid the session rename.** Genuinely attractive: the cap is already two, the
identifier stays `.v2`, and no partials are orphaned. Rejected because point 6 has to be written
anyway for `.v1`, which makes the rename nearly free, and because two connections against a disk
that can serve more leaves throughput on the table for a 1,589-track sync that already takes hours.

**Rely on `httpMaximumConnectionsPerHost` alone, set correctly this time.** This is what build 32
did, and the server observed roughly forty concurrent reads from a client asking for two. Whether
that is because the property is not honoured for background sessions, because the traffic came from
the uncapped orphaned `.v1` session, or because the phone was on a pre-32 build for part of the
window is still open. A queue makes the answer not matter, which is the argument for the queue.

**Persist the pending queue in the `DownloadStore` index.** Rejected: ADR-0009 point 4 has launch
reconciliation drop any index entry with no file on disk, so a persisted pending entry is precisely
the shape that reconciliation deletes. Making it survive means teaching reconciliation about intent,
which is a second source of truth about what should exist — the failure ADR-0006 and ADR-0009 both
already record.

**Fix it on the server with a semaphore and leave the client alone.** Rejected as sufficient,
accepted as necessary. It is the same move as the 2026-08-02 DB fix, and it relocates the queue
rather than removing it; it also cannot see whether a request is a sync or a person pressing play,
since both take `/tracks/{id}/stream`. But the server having no ceiling of its own means any second
client, or a browser tab with an aggressive prefetch, can reproduce this. Both halves are wanted;
this ADR is the client's, and the server's lives in `NOTES-stream-concurrency.md`.

**Space transfers by a delay rather than bounding them.** Rejected: a rate is the wrong variable.
What the disk cares about is how many reads are outstanding at once, and a fixed spacing that is
safe against 400-second responses is absurdly slow against 40-millisecond ones.

**Leave `Downloads` a `@StateObject` and have the `AppDelegate` build a throwaway manager.** Rejected
on the platform: a second `URLSession` created with an identifier already in use is not a second view
of the same session, and the results would be delivered to a delegate whose store is not the one the
app reads.

## Consequences

- **Positive.** The two incidents get one fix rather than two, and it is at the source. Whatever the
  server does with its threads, a client that cannot ask for more than three files at once cannot
  produce either failure again.
- **Positive, and the largest user-visible change.** Files will finish. 30.5 GB of bytes bought 385
  tracks; the same bytes under a bound are most of an album collection. The complaint that started
  this was "downloads don't work", and it was accurate — they were all starting and none arriving.
- **Tradeoff, taken.** Renaming to `.v3` orphans the `.v2` partials, and a listener who upgrades
  mid-sync loses in-progress bytes. Point 6 cancels them deliberately rather than leaving them, which
  is what makes this a one-time 30 GB recovery on those devices instead of a second permanent leak.
- **Tradeoff, and the honest cost of point 4.** An explicit album or playlist download interrupted by
  termination resumes only the three transfers that had tasks; the rest are dropped, and unlike
  favourites there is no sweep that re-derives them. The screen will show them as not downloaded,
  which is true, and the listener has to press it again. Persisting intent would fix it and is
  deliberately not done here.
- **Open, and worth closing even though the queue makes it moot.** Whether
  `httpMaximumConnectionsPerHost` is honoured for a background session at all. Point 6 removes the
  orphaned-session explanation, so the next sync's numbers answer it.
- **Open.** Whether the system relaunches us and point 9's early return discards the events, or
  whether it does not relaunch at all. ADR-0009 measured a relaunch on this device class, so the
  first is likely; `sudo log collect --device-udid` in a real terminal would settle it.
- **Correction to point 2, found while building it.** "Every exit pumps" is satisfied best by
  having one exit rather than five. `didCompleteWithError` is the only callback `URLSession`
  promises for every task exactly once — success, rejection, failed staging move and cancellation
  all arrive there — so it owns the slot accounting and the outcome paths own only the outcome.
  Distributing the release across five paths is what makes a forgotten one possible, and the
  original phrasing invited exactly that. One exit cannot come through it: cancelling a track that
  is still queued, which never had a task, and which therefore pumps itself.
- **Point 8 needed a second gate, not a shared one.** Artwork and downloads use the same number and
  separate budgets, because a track takes seconds to minutes and a cover is 40 KB: sharing three
  slots would starve every cover on screen for as long as a sync runs. `ConcurrencyGate` is its own
  small actor for the artwork side, since a grid has no array to hold back — only a stream of
  independent arrivals to admit — where `DownloadManager` is handed 1,589 requests at once.
- **Artist images stay on `AsyncImage`, and that is a deliberate exception to point 8.** They are
  Last.fm URLs the server enriched, on a CDN — a different host, not the one 7,200 RPM disk this
  ADR is about. Putting a grid of 3,475 circles behind a gate sized for a spinning disk would slow
  the app to protect a machine that is not being asked for anything.
- **Follow-up, server side — now taken up by
  [ADR-0112](ADR-0112-the-server-keeps-a-ceiling-of-its-own.md).** A bound on concurrent file
  responses, and a way for a client to mark sync traffic so it can be deprioritised, since the two
  are indistinguishable today. The client half of that marker — `X-Familiar-Intent: sync` on every
  download, and a refusal treated as an appointment rather than a failure — landed here with it.
- **Follow-up, ops.** The NAS's monit five-minute load threshold was raised 8.0 → 16.0 earlier on
  2026-09-07 for unrelated reasons, and that is why this event produced fewer alerts than it should
  have. It should come back down once the bound is in.
