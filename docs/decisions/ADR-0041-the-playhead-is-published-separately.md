# ADR-0041: The Playhead Is Published Separately from the Player

Status: accepted

Date: 2026-08-07

Extends [ADR-0028](ADR-0028-the-apple-clients-playback-session-is-local.md) point 7.

Implementation:
- Accepted 2026-08-07 and shipped in `familiar-apple` #82, in two commits kept separate because each
  is measurable alone: the per-pass list costs, then the split itself.
- **The measurement, in the state the baseline was taken in** — playing, queue pane open, Favorites
  on screen:

  | | main-thread samples | in `flushObservers` | CPU |
  |---|---|---|---|
  | Before | 2,712 | 2,320 — **86%** | 92–98% |
  | After the list fixes | 1,991 | 1,352 — **68%** | — |
  | After the split | 276 | 13 — **4.7%** | **5–9%** |

  The middle row is what isolates the split: it and the last were taken on comparable screens, so
  **1,352 → 13** is the split's own doing. The list fixes cut the cost per pass; the split stopped
  the passes.
- **Making the forwarders get-only is what found every write site.** Fourteen assignments to
  `currentTime`/`duration` inside `FamiliarPlayer`, each a compile error until routed through the
  playhead. Point 3's forwarders were written to keep callers compiling; they turned out to be the
  migration's safety net as well.
- Point 5's invariant test earned its place immediately. It asserted one wake per tick and got
  **two** — an unchanged `duration` was being re-assigned four times a second, and `@Published` does
  not compare before publishing. `Playhead.update` now checks first, halving the wakes in steady
  state. The assumption was wrong and what it uncovered was real.
- The four silent traps named in planning all held. `PlaybackSessionWriter` needed the second
  subscription or the position would have stopped being saved while queue writes carried on;
  `CastSnapshot` needed no change because `positionMS` reads the forwarder and the read that matters
  happens outside the sink; `CarPlayBridge`'s row diff stays as defence in depth with its comment
  updated to record that the cause is fixed; `CrossfadeWiringTests`' delegate signature is untouched.
- **Step 4 of the plan was correctly conditional and correctly skipped.** `TrackRowMenu`'s 71
  baseline samples were 71 samples *at 4 Hz*; after the split it registers zero. Restructuring a
  component with seven call sites on speculation would have been work for nothing.
- Two things the plan called for were dropped for the same reason: a search debounce and caching the
  derived `[TrackRowValue]`. Both were justified by the filter running per render, which it no longer
  does.
- **Follow-up.** `@Observable` still subsumes this entirely, per the third alternative. The split is
  compatible with it and would simply become redundant.

## Context

**The Mac app sits at 92–98% CPU while playing.** A five-second `sample` of the running app found
**2,320 of 2,700 main-thread samples inside `flushObservers`** — which is not four bursts a second.
It means a single render pass takes longer than the 250 ms until the next one, so the view graph
never catches up. The app is not doing four things a second; it is doing one thing forever.

The driver is one property. `FamiliarPlayer.currentTime` is `@Published`, and
`NativeAudioEngine`'s time timer fires every 0.25 s. **`@Published` emits `objectWillChange` on
every assignment regardless of equality**, so both `currentTime` and `duration` invalidate every
observer four times a second even when the value has not changed.

Ten types observe `FamiliarPlayer`. **Two of them display the playhead**: `NowPlayingBar` and
`FullPlayerView`, for the scrubber and the clock. The other eight —
`QueueView`, `ShuffleControl`, `LibraryView`, `ChatView`, `EmbeddedDiscoverView`,
`BrowseDetailView`, `DetailHost` and the app itself — re-render four times a second while reading
none of it. `QueueView` and `ShuffleControl` read *no* time state at all; `ChatView`,
`EmbeddedDiscoverView` and `DetailHost` read no published state whatsoever and are pure re-render
victims. On macOS the transport bar, the queue pane and the whole library window are all on screen
at once, so three of the heaviest observers re-evaluate together.

**This was found once before and defended against locally rather than fixed.**
`App/Shared/CarPlayBridge.swift:125-133` is the existing written record:

> **The comparison is not an optimisation.** `FamiliarPlayer.currentTime` is `@Published` and the
> engine's time timer fires every 0.25s, so `objectWillChange` emits four times a second throughout
> playback. Pushing sections on each one makes the head unit re-render the tab bar at that rate, and
> the selected tab's label visibly blinks — seen in the car, which is the only place it can be seen.

CarPlay added a row diff and moved on. `CastController.observe` accepted the same tick as costing
"a struct comparison". `PlaybackSessionWriter` throttles around it. Three components each absorbed
the cost privately; nothing addressed the cause, and no view could, because SwiftUI's observation
granularity is the **object**, not the property.

**The axis to split on is already established in this codebase**, one layer down.
`Sources/FamiliarKit/PlaybackSessionStore.swift:6-13`, from ADR-0028 point 7:

> **Two files, not one, and the split is the whole design.** The queue changes when the listener
> changes it — a few times an hour. The position changes four times a second, forever.

That reasoning produced a cold file and a hot file. This ADR applies the identical reasoning to
*publication* rather than storage: the same two cadences, the same two homes.

## Decision

1. **Fast-changing playback state is published separately from slow-changing state.** `currentTime`
   and `duration` move to their own small `Playhead` observable. Queue, cursor, modes, track
   identity, loading and error state stay on `FamiliarPlayer`, where they change a few times an
   hour rather than four times a second.

2. **A view observes the playhead only if it draws the playhead.** That is two views today. Any
   view that wants to know *what* is playing keeps observing the player; only a view that wants to
   know *where* in the track observes the playhead. This is the rule the ADR exists to state,
   because the storm returns one view at a time if it is not written down.

3. **`FamiliarPlayer.currentTime` and `duration` survive as non-published forwarders**, reading
   through to the playhead. This is what keeps the change tractable: `considerCrossfade()`,
   `seek(to:)`, `previous()`'s three-second rule, `persistableSnapshot`, `concludeCurrentTrack` and
   both the adopt and restore paths keep compiling unchanged, as do roughly twenty assertions
   across six test files.

4. **A view reading those forwarders will never update, and that is the trap.** They are not
   `@Published`, so SwiftUI sees no change. This is stated plainly here because it is the one way
   this decision can hurt someone later: the symptom is a scrubber that sits still, which reads as
   a broken engine rather than a wrong subscription.

5. **The rule is enforced by a test, not by this document.** A time tick must **not** fire
   `FamiliarPlayer.objectWillChange`, and must fire the playhead's. If anyone re-adds `@Published`
   to `currentTime`, or routes the playhead back through the player, that test fails loudly instead
   of the storm quietly returning. A convention with no enforcement is a comment.

6. **The existing local defences stay.** CarPlay's row diff, the cast reducer's snapshot comparison
   and the session writer's throttle are all still correct and still useful — they guard against
   more than this one publisher. CarPlay's comment is updated to record that the cause behind it is
   now fixed, so the next reader does not diagnose it a second time.

7. **The engine's delegate signature does not change.** `audioEngineDidUpdateTime(currentTime:
   duration:)` stays exactly as it is; only where the player puts the values changes. Seven tests
   in `CrossfadeWiringTests` drive that method by hand and must remain untouched.

## Alternatives Considered

**Leave it, and let each consumer defend itself.** The status quo, and it is not absurd — CarPlay,
casting and the session writer each already do, and each defence is individually cheap. Rejected
because the cost is not paid by the consumer that can see it: the expensive victims are large SwiftUI
lists that have no idea why they are being invalidated, and cannot defend themselves at all, because
observation is per-object. Three components paying attention did not stop the app reaching 98% CPU.

**Throttle the engine's timer, or only publish when the value changes materially.** Much smaller: emit
`currentTime` once a second, or only when the whole-second value changes. Rejected because it trades
scrubber smoothness for CPU on every client forever, and because it does not fix the shape of the
problem — the queue pane would still re-render for the playhead, just less often. It also puts the
fix in the audio engine, which ADR-0015 point 2 and ADR-0024 both work to keep free of view concerns.

**Adopt `@Observable` (the Observation framework) instead, so SwiftUI tracks per-property access.**
This is the *right* long-term answer and would make the split unnecessary: SwiftUI would invalidate
only views that actually read `currentTime`. Rejected for now on scope — it is a migration of every
observable type and every view in the app, it interacts with `@MainActor` isolation that ADR-0024
only just settled, and macOS 14 / iOS 17 floors make it available but the rewrite is far larger than
the problem. Worth revisiting as its own decision; recorded as a follow-up rather than dismissed.

**Make the two transport views take the time as a plain value passed from a parent.** No new
observable at all — the parent observes and hands down a `Double`. Rejected because the parent that
would observe is `LibraryView`, the single most expensive victim; it would keep re-rendering four
times a second and pass the cost straight down. It moves the subscription rather than narrowing it.

## Consequences

- **Positive.** Eight of ten observers stop re-rendering four times a second, including the whole
  library window, the queue pane and the embedded `WKWebView` host.
- **Positive.** The rule generalises: any future fast-changing playback state has an obvious home,
  and any future view has an obvious question to answer before it observes.
- **Positive.** The invariant in point 5 makes the regression detectable in `swift test` rather
  than in Activity Monitor months later.
- **Tradeoff.** There are now two objects where there was one, and a view author has to know which
  to observe. Point 4's failure mode — a view that silently never updates — is the price, and it is
  quieter than the problem being fixed.
- **Tradeoff.** `FamiliarPlayer` gains a forwarder pair whose only purpose is to keep existing
  callers compiling. That is deliberate migration scaffolding, and it is the reason this change is
  not a rewrite — but it does leave two ways to read the same value.
- **Follow-up.** `@Observable` would subsume this entirely, per the third alternative. Whoever picks
  that up should read this ADR first: the split here is compatible with it and would simply become
  redundant.
- **Follow-up.** `CastSnapshot` reads the playhead for its resume position, consumed only on a track
  change. Nothing tests that path; a cast started mid-track is the way to see it.
