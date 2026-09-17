# ADR-0121: A Batch of Downloads Is a Live Activity

Status: accepted

Date: 2026-09-17

Implementation:
- **Accepted 2026-09-17**, the day it was proposed, as written. Client only; the server is not
  involved.
- **Built 2026-09-17** in `familiar-apple` (branch `download-live-activity`): a
  `DownloadActivityWidget` extension target embedded in the iOS app, `DownloadActivityAttributes`
  and `CancelDownloadsIntent` compiled into both, `DownloadActivityController` driven from
  `Downloads`' coalesced phase stream, `DownloadManager.cancelAll()` with a test,
  `NSSupportsLiveActivities` in the app's plist. Seen working on an iPhone 17 Pro simulator: the
  lock-screen card and the Dynamic Island counted a favourites sweep up from the home screen, and
  the stop button — pressed by an XCUITest against SpringBoard, not by hand — reached the app and
  cancelled 1,344 queued and 3 moving transfers. The finished card is unverified on a screen as
  this is written; the code path ran and logged. Not yet on TestFlight.

## Context

A phone that has just been told to download its favourites shows nothing about it once it is
locked. The Downloads screen learned to list what is still on its way (ADR-0111's follow-up: "3
downloading, 1,214 waiting") and that was the right fix for the screen — but the screen is inside
the app, and the moment someone puts a download on is the moment they put the phone down. From
the lock screen, a sync that is working and a sync that is wedged look identical: a blank screen.
That is the exact blindness ADR-0111 opened `DownloadManager.log` for, on the one surface the log
cannot reach.

Spotify shows what this should look like, and Jeff sent the two screenshots on 2026-09-17: a
lock-screen card with the app's mark, "Downloading 59 of 98", a ring with a stop square in it,
then the same card reading "Finished" with a tick. It is a Live Activity — an ActivityKit activity
the app starts, updates and ends, drawn by a widget extension — and it survives the app being
suspended, because the extension draws whatever it was last given.

### What the client already has

Everything that makes this hard is already solved for another reason:

- **A rate the card can be updated at.** `DownloadManager.states` changes on every progress
  callback, thirty-four times a second, and `Downloads` collapses that to `DownloadPhase` before
  deciding anything changed — because publishing at the raw rate re-created the phone's transport
  accessory and swallowed its taps. ActivityKit budgets updates and throttles a card that asks for
  more than it will give; the collapsed stream changes a handful of times per transfer, and only
  a landing or a failure changes what the card says.
- **A process that exists when the phone is locked.** `Downloads.shared` is a static that outlives
  the scene (ADR-0111 point 9) and `handleEventsForBackgroundURLSession` rebuilds the stack on a
  background relaunch. Every `didFinishDownloadingTo` is a moment the app is running and may
  update the card.
- **A single cancellation** (`cancel(trackID:)`), and the rule that every exit pumps the queue
  (ADR-0111 point 2), which is what a cancel-all has to respect.
- **A device-wide answer to "transcode or direct"** (ADR-0118): the phone asks for files no
  larger than AAC and the server encodes a lossless source once, which is why the first of a
  batch can sit at "downloading" for a while. The card can say which mode it is in; it cannot
  say which fate each file met, because the request does not carry the source's format.

## Decision

1. **A batch of downloads is one Live Activity.** A batch begins when the in-flight set becomes
   non-empty and ends when it drains. There is one queue, so there is one card: an album queued
   while the favourites sweep runs joins the batch and grows its total rather than starting a
   second card. The card shows the app's mark, "Downloading *n* of *m*", the track at the head
   of the queue, the delivery mode, failures when there are any, and a ring with a stop button in
   it; the Dynamic Island shows the mark and the count.

2. **The counts are the card's, not the manager's.** `DownloadManager.states` keeps `.finished`
   for the life of the process and includes tracks `start` skipped as already stored, so counting
   it would say "59 of 98" about a batch that queued twenty. What is counted is what was seen in
   flight while the card was up: landed, failed, still moving, still waiting. A track cancelled
   individually leaves the total, as a decision rather than an outcome.

3. **The card is driven from `Downloads`' coalesced stream and from nothing faster**, and an
   update is sent only when the content differs from the last one sent, coalesced over half a
   second. A 1,700-track sweep is about 1,700 updates over an hour.

4. **Starting a card needs the app in front; adopting one does not.** A background relaunch that
   finds a card in `Activity.activities` adopts it and carries its counts forward; one that finds
   none files its transfers without a card. Not an error, and not retried into the budget.

5. **A drained queue ends the card as "Finished", dismissed after five minutes** — long enough to
   be read by someone coming back to the phone, short enough not to be stale by the afternoon.
   When the queue drained because the process that held it was gone (ADR-0111 point 4: the
   queue is in memory, and a background relaunch finishes only what the daemon kept), the card
   says "Stopped at 62 of 98 — open Familiar to continue" instead, because "Finished" would be
   a lie about 36 tracks.

6. **The stop button empties the whole queue, and it is the first control that does.** A card
   that says "Downloading 59 of 1,589" with no way to stop it is a commitment the listener did
   not make in those terms. `DownloadManager.cancelAll()` forgets everything waiting, cancels
   every task in the session, removes the states rather than marking them failed, and pumps.
   Nothing is lost for good: the favourites sweep re-derives what is missing at the next launch.
   The card is ended *before* the queue is emptied, so the drain does not arrive as a finish.

7. **The button is a `LiveActivityIntent`, performed in the app, reached through a hook the app
   installs at launch.** The intent type is compiled into the extension (which builds the button)
   and the app (which performs it); the extension links neither `FamiliarKit` nor the app, so
   the intent calls a static closure that `AppDelegate.didFinishLaunching` sets — on every launch,
   including a cold one the intent itself causes, when no scene will ever build `Downloads`.

8. **The card says whether the batch is a transcode or direct** — "Transcode · AAC" or "Direct ·
   original files" — from the preference in force (ADR-0118), read when the card is updated so a
   change in Settings shows on the next update. The mode, not the fate of each file: a lossy
   source is passed through either way, and the request does not carry the source format. Naming
   each file's fate would need the format on `DownloadRequest` and in the task description, and
   is left.

9. **What lives where.** `App/DownloadActivity/` holds the attributes and the intent, compiled
   into both targets and into nothing else — not `App/Shared`, which is the Mac's too, and not
   `FamiliarKit`, which the extension must not pull in. The controller is in `App/Shared` under
   `#if os(iOS)`. The widget draws the app's six bars from the measurements `FamiliarWordmark`
   records rather than loading the asset it cannot see, and copies six theme colours for the
   same reason.

## Alternatives Considered

- **A local notification per milestone** ("50 of 98 downloaded"). Rejected: notifications pile
  up, cannot be updated in place, and cannot carry a button that does anything while locked.
  The one thing the lock screen needs here is a number that changes.

- **Push-to-start / push updates from the server.** The server has no view of the phone's queue
  and no push credentials; the app is running whenever the number changes, because a background
  transfer finishing is what wakes it. Local updates are sufficient and simpler.

- **A card per collection** ("Favorites", "OK Computer") the way Spotify names the playlist.
  The manager has one queue and no notion of where a request came from; naming batches would
  mean labelling requests at five call sites for a card that would then have to choose which
  label to show when two overlap. Left, and the current track does most of the work.

- **Counting from `DownloadManager.states` directly.** Rejected for the reason in point 2.

- **Linking `FamiliarKit` into the extension** to share `DownloadFormat`. Rejected: the kit is
  the audio engine, and an extension that draws a card should not carry it.

## Consequences

- The lock screen and the Dynamic Island say what the Downloads screen says, while the phone
  is locked, which is when it matters.
- A new target, `DownloadActivityWidget`, embedded in the iOS app under
  `com.familiar.player.DownloadActivity`. Its `CURRENT_PROJECT_VERSION` and `MARKETING_VERSION`
  are duplicated from the app's in the project file, which is what the release script rewrites,
  so the two stay equal — App Store validation requires it.
- `NSSupportsLiveActivities` in the iOS plist; iOS asks the listener to allow Familiar's Live
  Activities the first time one appears.
- A cancel-all exists, and a queue can now be discarded from the lock screen.
- Not verified on a phone as this is written; the release build is what to test, because a
  Debug build cannot take background downloads (the −3000 tell) and would look like the card
  stopping when the phone locks.
