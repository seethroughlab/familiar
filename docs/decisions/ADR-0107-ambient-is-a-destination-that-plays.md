# ADR-0107: Ambient Is a Destination That Plays

Status: accepted

Date: 2026-09-01

Implementation:
- **Built on `familiar-apple` branch `ambient-mode`** (`familiar`'s half of point 2 is on
  `worktree-ambient-mode-revival`). `FamiliarKit` gains `AmbientSession`, `AmbientPolicy`,
  `AmbientController`, `AmbientSynthEngine` and `AmbientAudioTransport`; `App/Shared` gains
  `AmbientView` and `ServerAmbientSource`; `NativeAudioEngine` gains `init(role:)` and nothing else.
  Both schemes build; 1,071 tests pass with 50 skipped, 42 of them new.
- **Point 1's forcing functions both fired.** `LibraryRoutingTests` and `NavigationCommandTests`
  failed until `ambient` was added to their hand-maintained lists, and the routing switches failed
  the build until every arm was written. The sidebar row is the one site nothing checked, exactly as
  the point says.
- **The transport had to live in `FamiliarKit`, not `App/Shared`.** `NativeAudioEngine` is internal
  to the module, so nothing in the app target can construct the `.secondary` engine point 5
  describes. That is convenient rather than awkward — the second instance sits beside the rules
  about what a second instance may do.
- **Point 12's rewrite was larger than "not as-is" suggests.** Beyond the three faults listed, the
  synth needed `nonisolated(unsafe)` on the state pointer with its invariant written beside it,
  because `UnsafeMutablePointer` is not `Sendable` even when its pointee is.
- **A defect this work introduced and the tests caught**: the controller's two waits — a window
  ending and an intermission passing — were one injected clock, so a test clock that returned
  instantly made every window end the moment it began and ran a session to the end of its plan.
  They are named separately now, which is also the honest description of what they are.
- **Not verified, and it is the part that matters: nobody has heard it.** No assertion distinguishes
  a drone that glides from one that steps. See the Consequences.
- **A prerequisite this uncovered, unrelated to ambient.** Re-vendoring the current schema stopped
  the macOS target compiling: ADR-0099/0101 replaced `unheard_tracks` and `deep_cuts` with
  `rediscovery`, and `HomeStore` still read the removed fields. Home now shows one Rediscover
  section carrying the provenance ADR-0101 added, rather than a flattened list — dropping the
  "because you played X" would leave the old Unheard section under a new heading.

Depends on [ADR-0106](ADR-0106-ambient-mode-returns-as-a-reachable-surface.md), which **executes
first** and now has: the three endpoints this surface is built on exist, are generated, and reach
Swift as `ambientSeed`, `ambientCandidates` and `ambientDescriptor`. Extends
[ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md) and takes point 2 at its word: this
lands on the Mac first, and the phone follows as its own phase rather than riding along.

## Context

`ADR-0106` restores the server half of ambient mode and records why the feature's disappearance was
never a decision. What it does not answer is the shape of the thing on the client, and the old shape
does not survive the move.

The deleted implementation was a **full-screen mobile overlay**: a row in the More sheet set
`uiStore.showAmbientScreen`, and `AppShell` mounted `AmbientScreen` as `fixed inset-0 z-50 md:hidden`
over whatever was underneath. That worked in a single-screen web app with a bottom nav and a More
sheet. The Mac has neither. It has a sidebar of destinations, a main column, and one full-player
presentation already spoken for.

Three shapes were available and two are wrong:

- **A `PlayerBackdrop` case.** `Sources/FamiliarKit/PlayerBackdrop.swift` is the enum that chooses
  between cover art, the visualizer and a music video, and `ADR-0085` deliberately wrote it as an
  enum so two booleans could not both say yes. Ambient does not fit: a backdrop decides what is
  *drawn* behind a player that is playing a queue, and ambient decides what is *played*. Nothing in
  a backdrop picks tracks.
- **A mode of `FullPlayerView`.** Much the cheapest — it would inherit Escape-to-dismiss, the
  three-second controls fade and both platforms' presentations for nothing. Rejected because
  ambient has a seed picker, four controls and a history, and none of those belong on a
  now-playing screen. It would also make starting a session require first having something playing,
  which is exactly backwards.
- **A sidebar destination.** What this ADR chooses, and the shape the surface actually has.

There is a precedent for the odd part of it. `SidebarItem`'s own documentation says of `.home`:

> First, and a kind of its own: everything else here is a way of *finding* something, and this is the
> one destination whose rows begin playing rather than open a list.

Ambient is the second of that kind, and `LibrarySidebar.swift` says the same thing from the other
side — Home is in **its own `Section` above everything**, because "grouping it with the browse
sections would file it as a fifth way of asking the library a question". So ambient goes there,
beside Home, and not under Library beside Music Map, Discover and Videos: those three are there
because `ADR-0016` point 3 and `ADR-0085` point 7 read them as ways of *finding* something to play,
which is exactly what ambient is not.

**Three facts about this codebase decide the rest of it, and the first two point the opposite way
from the intuition.**

The intuition is that ambient should drive the player the app already has — one engine, one
now-playing entry, a session flag to say who owns the transport. That is what the deleted web
version did, with an `activeSessionStore` mutex, and it did it because a browser tab has one
`AudioContext` and no choice. This process has a choice, and taking the shared engine costs more
than it saves. `FamiliarPlayer.play(_:startingAt:)` calls `concludeCurrentTrack(reason: .user)` and
then **replaces `logicalQueue` and `queue`** — so entering a session destroys the listener's queue
and, through `PlaybackSessionWriter`, the persisted one; `stop()` clears it outright. Every snippet
advance would emit a `.user` conclusion, which is an `ADR-0004` skip event per eight-second window.
`setVolume` is write-only from the player's side and `CastController` "owns the only readable copy
of the volume", so dropping to 0.15 and restoring afterwards means guessing what to restore to. And
`FamiliarPlayer` is 1,928 lines with `NativeAudioEngine.engine` private, so a session-ownership
concept has to be threaded through play, pause, next, previous, crossfade, casting and six remote
command handlers.

A second `NativeAudioEngine` has none of those problems and one real one:
`init()` calls `setupRemoteCommands()` unconditionally (`NativeAudioEngine.swift:817`), which adds
targets to six commands on `MPRemoteCommandCenter.shared()` — a process singleton. Two instances
means the space bar drives both. That is a six-line fix at the initializer, against threading
ownership through 1,928 lines, and the class already carries the seam to test it:
`private(set) var wiredRemoteCommands: Set<String>`, which exists because `MPRemoteCommand` cannot
be asked whether a target is attached.

The third fact is about the network, not the audio. `NativeAudioEngine.load(url:)` is a
`URLSession.downloadTask` — **the whole file lands before anything plays.** An eight-second window
costs a full-track download, and the deleted coordinator called `playSnippet` *after* awaiting the
intermission, so the download began at the moment the fade should have. Over Tailscale against a
60 MB FLAC that is a stall where the piece wants a seam.

**The synth is the one piece that ports.** `ADR-0001`'s readiness audit listed
`FamiliarAmbientSynth/AmbientSynthEngine.swift` at 266 lines among the 2,686 that "move as-is",
imports Capacitor-free. It was deleted with the Capacitor app on 2026-08-11 without ever being
moved. It does not in fact move as-is, and the reasons are in point 12 — but it is a self-contained
`AVAudioEngine` graph of three oscillators and three effects, and it is the reason this feature
sounds like anything at all.

## Decision

1. **Ambient is a sidebar destination**, not a backdrop and not a mode of the full player. It adds
   `SidebarItem.ambient` and `LibraryRoot.ambient` in `Sources/FamiliarKit/LibraryRouting.swift`, and
   a row in `App/Shared/LibrarySidebar.swift`'s **first section, beside Home** — the section that
   exists precisely to hold the rows that start music rather than open a list. Not under Library.
   **Five of the six routing sites are exhaustive switches the compiler enforces; the sidebar row is
   a literal and is not**, which that file's own comment already warns about: "Adding a `SidebarItem`
   case does not break this file … so the compiler is no help here."

2. **The command vocabulary gains `"ambient"` in second place, in both repositories.**
   `SidebarItem.allCommandRoutes` and the server's `NAVIGATION_DESTINATIONS`
   (`app/mcp/playback.py`), immediately after `"home"`, because
   `NavigationCommandTests.testTheVocabularyMatchesTheServers` asserts the two lists are equal **in
   order**, not merely as sets. `ADR-0053` point 2 keeps that list closed on purpose; the ordering
   assertion is what stops the two halves drifting into a command that is accepted into nothing.

3. **Mac first; the phone is a later phase.** The enum case is shared because the generated client
   and `FamiliarKit` are, but the phone gets no row in `App/Shared/LibraryRootList.swift` until its
   own phase. This is exactly how `music_map` and `videos` are Mac-only today, and
   `NAVIGATION_DESTINATIONS` already carries the comment describing that pattern. The phone's phase
   is not cosmetic: it adds the `AVAudioSession` coordination macOS does not have, and iPad compiles
   the iOS branch of every `#if` and needs an answer rather than an inheritance.

4. **Ambient drives a second `NativeAudioEngine`, not the shared one.** It never touches
   `FamiliarPlayer`'s queue, cursor, volume or reporting, for the four reasons in the Context: the
   queue is destroyed by `play`, every advance is an `ADR-0004` skip, the volume has no readable
   copy to restore, and the ownership flag would have to reach 1,928 lines. The listener's queue is
   left exactly as it was — not preserved-and-restored, simply untouched — and `FamiliarPlayer` is
   paused rather than stopped.

5. **`NativeAudioEngine` gains one initializer parameter and nothing else.** `init(role:)`, where
   `.secondary` skips `setupRemoteCommands()` and never writes `MPNowPlayingInfoCenter`. Without it
   a second instance adds a second target to six `MPRemoteCommandCenter.shared()` commands and the
   space bar drives both engines. `wiredRemoteCommands` is the assertion seam and already exists.
   The secondary engine also gets no play cache — eight seconds of a track is not "played bytes",
   and `ADR-0010`'s store should not fill with material nobody heard — and calls `disableAnalysis()`,
   since `onAnalysisFrame` is a single slot the visualizer's `VisualizerPump` claims.

6. **The next snippet is loaded during the intermission, not when it is due to start.** `load(url:)`
   downloads the whole file; the deleted coordinator called `playSnippet` after awaiting the pause,
   so the download began exactly when the fade should have. Twenty-five to forty seconds of
   intermission is ample, and using it is the difference between a seam and a stall.

7. **`RadioController` must not insert while a session runs.** It is app-scoped and reacts to track
   changes, and would otherwise slip a full-length track into a session of eight-second windows.
   `FamiliarPlayer` gains `audioIsClaimedElsewhere`, built in the shape of the existing
   `isCasting` closure, so a media-key press cannot resume the main player over the drone.

8. **The session outlives the screen.** Navigating to Tracks leaves it playing, the sidebar row
   shows that it is running, and `Stop Session` is the only thing that ends it — `RadioController`'s
   reasoning, that a controller has to outlive whichever view happens to be on screen. The web
   version stopped on close because it was a modal overlay; a sidebar destination is not one.
   `AmbientController` is therefore a `@StateObject` on `FamiliarApp`, beside `radio`.

9. **A session holds `.idleSystemSleepDisabled`, and not `.idleDisplaySleepDisabled`.** The machine
   stays awake so the piece keeps playing; the screen sleeps normally, because an ambient piece is
   something listened to with the display off and an hour of lit 5K is the wrong default. First use
   of `ProcessInfo.beginActivity` in this codebase; it needs no entitlement, so it is sandbox-safe.
   **The token must be stored and `endActivity` called exactly once** — an unbalanced pair leaks a
   power assertion for the life of the process.

10. **The aesthetic is preserved exactly.** Snippet volume 0.15, eight-second fades, a drone that
   sounds continuously from the first snippet to the last and glides rather than steps between keys,
   intermissions of 25–40 seconds in which only drone and motif are audible. The four controls keep
   their split: `intensity` and `filterPreset` go to the server and change ranking only;
   `snippetLength` and `transitionDensity` stay on the client and change the window and the motif
   recipe. **Nothing changes the synth's mix at runtime** — `configure` is called once per session.
   This is a decision and not an omission: the deleted `AmbientSynthBridge` declared `updateMix` and
   `stopImmediate` and `AmbientCoordinator` never called either, so they are not ported.
   `ADR-0077`'s rule applies to a revival on its first day as much as to anything else.

11. **The first phase is online-only, and says so rather than degrading.** `ADR-0006`'s precomputed
   manifest already carries `AMBIENT` variants per filter preset, and no Apple client reads a
   manifest — `RadioController` records the same gap and makes the same choice. A session that
   cannot reach the server does not start, with a stated reason. It does not fall back to something
   arbitrary, which is the failure `ADR-0032` point 5 and `ADR-0035` point 6 are both written
   against.

12. **The synth is ported into `FamiliarKit` and made real-time-safe, not copied.** Three things in
   the deleted file are wrong and one of them will not compile under Swift 6:
   its `AVAudioSourceNode` render blocks capture `[weak self]` and read mutable stored properties
   from the audio thread, which is a lock on the render path; `stopWithRelease(releaseMs:)` ignores
   its argument entirely and always releases at the fixed smoothing rate; and `freqSmoothingCoeff`
   is shared by both drone voices and never reset by `startDrone`, so one session's glide rate leaks
   into the next. The pattern to follow is already in the repository —
   `NativeAudioAnalysisProcessor` (`NativeAudioEngine.swift:248`) is a `final class … @unchecked
   Sendable` with a `nonisolated` render path under `ADR-0024` — and oscillator parameters move
   behind a plain-old-data block the render function reads without touching the object.

13. **Ambient emits no listening events in this phase.** A sixteen-second window played at 0.15
   volume is not evidence of taste, and a completion ratio computed against the full track would
   read as a hard skip on every snippet — the shape that made 795 of `ADR-0004`'s first 823 rows
   worthless by construction. The `'ambient'` `PlayContext` stays unemitted rather than filled with
   numbers no tuning query should trust. Reversing this needs two things together: a ratio measured
   against the snippet window, and `FEEDBACK_TRUSTWORTHY_SINCE`-style exclusion of the context from
   any weight tuning.

14. **Everything with a decision in it lives in `FamiliarKit`.** The window selection, the drone and
   motif recipes, the key-to-MIDI arithmetic and the session policy — advance, previous,
   intermission timing, prefetch depth — are values and pure functions there, tested against a fake
   source and an injected clock. `App/Shared` gets the SwiftUI and one thin
   `ServerAmbientSource` that translates wire types and decides nothing, in the shape
   `ServerRadioSuggestionsSource.swift` established. `swift test` cannot see `App/`, and a session
   coordinator that lives there is a session coordinator with no tests.

## Alternatives Considered

**A mode of `FullPlayerView`.** The cheapest option by a wide margin: Escape-to-dismiss, the
`lastPointerActivity` controls fade and both platforms' presentations all come for free, and no
routing changes at all. Rejected because the seed picker has nowhere to go. A now-playing screen is
reached by having something playing; ambient is reached in order to start playing, and putting the
entry there would mean queueing a track before starting a session that then discards it.

**A fourth `PlayerBackdrop` case.** Rejected on `ADR-0085`'s own reasoning. `PlayerBackdrop` exists
to make "what is drawn behind the player" a single value that cannot half-transition. Ambient is not
drawn behind anything; it selects and schedules audio. Adding it would make the enum mean two things
and would reintroduce exactly the ambiguity the enum was written to remove.

**Its own window on macOS, or a `fullScreenCover`.** Attractive for something this close to a
screensaver, and there is no full-screen presentation anywhere in the app yet. Rejected for this
phase as an unforced first: it would be the codebase's first `NSWindow` full-screen handling and its
first `fullScreenCover`, in the same change as a revived feature and a ported audio graph. The
destination renders in the main column like every other one, and a full-screen presentation stays
available as a follow-up with a smaller blast radius.

**Drive the shared `NativeAudioEngine` through `FamiliarPlayer`, with a session-ownership flag.**
The obvious design, the one the deleted web version used, and the one this ADR started out
recommending. Rejected once the player was actually read: `play(_:startingAt:)` replaces
`logicalQueue` and `queue` and concludes the outgoing track as `.user`, so entering a session
destroys the listener's queue and every eight-second advance writes an `ADR-0004` skip event
against a track the recommender will then demote for ninety days. `setVolume` has no readable
counterpart to restore — `CastController` owns the only one. And the ownership flag would have to be
respected by play, pause, next, previous, crossfade, casting and six remote-command handlers across
1,928 lines. The one advantage it has over a second engine is that it cannot double-register remote
commands, and that turns out to be a six-line `init(role:)` change on the other side.

**Give the second engine its own now-playing entry, so the lock screen shows the ambient track.**
Rejected: `MPNowPlayingInfoCenter` is a process singleton, so two writers produce whichever wrote
last. The secondary engine writes nothing, and the surface that knows a session is running is the
one that should say so.

**Keep the drone on the server as rendered audio, and stream it.** Removes the synth entirely and
would work on any client, including the web app. Rejected: the drone must glide between keys in
response to a transition the client schedules, so streaming it means either a round trip inside
every transition or a stream that cannot respond to one. A three-oscillator graph is small, local
and already written.

**Report listening events with `context: "ambient"`, as the enum invites.** The slot exists, the
schema already carries it, and `ADR-0003` point 8 named ambient a listening context precisely so
this would be possible. Rejected for now on point 13's grounds — not because the events are
unwanted, but because the ratio they would carry is meaningless against a full-track denominator,
and a feedback table is easier to keep clean than to clean.

**Hold `.idleDisplaySleepDisabled` as well, so the surface stays lit.** Defensible for something
this close to a screensaver, and right if the destination is left up on a second monitor. Rejected
as a default: the piece is designed to be listened to, not watched — 25–40 seconds out of every
minute are near-silence with nothing on screen changing — and an hour of lit 5K to play audio is a
cost the listener did not ask for. Point 9 keeps the machine awake, which is the part that would
otherwise stop the music.

**Stop the session when the listener navigates away.** Simpler, and what the deleted version did,
though only because it was a modal overlay with nowhere else to go. Rejected: it would make Ambient
the one destination in the app you cannot browse out of without losing what you were doing, and it
would put a stop button behind a sidebar click that reads as navigation. Point 8's cost — audio
running whose controls are not on screen — is answered by the row showing that it is.

## Consequences

- **Positive.** The Mac gains a listening mode that is not a queue, on a surface where a whole screen
  of drone and slowly-arriving snippets makes sense. The engine `ADR-0106` restores gets its first
  real consumer.
- **Positive.** Point 14 puts the session policy somewhere `swift test` can reach it. The deleted
  `AmbientCoordinator` was 662 lines of untested orchestration, and it carried at least two defects
  that a test would have caught: `skipToPrevious` never popped its history, so pressing previous
  twice returned the same snippet forever, and `fadeOut` took the volume to zero without pausing, so
  the previous track decoded silently through every intermission.
- **Positive.** Fixing the synth under point 12 makes `stopWithRelease` mean what its signature says
  for the first time, and point 6 removes a stall the original had at every seam.
- **Positive.** Point 4 leaves the listener's queue *untouched* rather than saved and restored,
  which is strictly less to get wrong than the ownership flag the web version needed.
- **Tradeoff.** `LibrarySidebar.swift`'s rows are hand-written literals and the compiler does not
  check them, so a destination can be fully wired and invisible. The routing switches are total and
  will fail the build; the row will not. `LibraryRoutingTests` walking `LibraryRoot.allCases` is what
  catches the rest.
- **Tradeoff.** Two `AVAudioEngine`s for playback where there was one. The engine is not written to
  be instantiated twice, and point 5's `role:` is the only place that is currently known to care —
  which means it is the only place currently *known* to. Anything else global that
  `NativeAudioEngine` touches becomes a second-instance question.
- **Tradeoff.** Point 8 means audio can run with its controls off screen. That is the same
  arrangement every other player has and the sidebar row reports it, but it is a state the app has
  not had before.
- **Tradeoff.** The feature cannot be verified by anything automated. It is entirely about how it
  sounds, and no test can tell a drone that glides from one that steps. That is `ADR-0040` point
  13's position on radio, arrived at for the same reason.
- **Follow-up.** The phone, per point 3 — the row, the presentation, and `AVAudioSession`
  coordination between the playback engine and the synth's second graph. macOS has no audio session,
  so the first platform does not answer this question at all.
- **Follow-up.** Offline ambient, per point 11. This weakens `ADR-0077` point 4's justification for
  keeping the manifest's `AMBIENT` variants rather than strengthening it: a `ManifestEntryResponse`
  is `{track_id, neighbours}` with no `key` and no `duration_seconds`, so it can choose the next
  track but can neither tune the drone nor place a window. The variants need a reader *and* a
  descriptor lookup before they serve this.
