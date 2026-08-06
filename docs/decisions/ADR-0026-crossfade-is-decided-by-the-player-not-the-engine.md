# ADR-0026: Crossfade Is Decided by the Player, Not the Engine

Status: accepted

Date: 2026-08-05

Extends [ADR-0015](ADR-0015-audio-effects-are-exposed-not-rebuilt.md) and
[ADR-0025](ADR-0025-the-phone-gets-a-settings-destination.md). Constrained by
[ADR-0031](ADR-0031-casting-is-the-macs-and-excludes-zones.md) point 6.

## Context

**The native apps do not crossfade, and nothing is broken.** `NativeAudioEngine.executeCrossfade`
exists at `NativeAudioEngine.swift:1512`, runs 77 lines, ramps two player nodes against each other on
a 60fps timer, and is called **zero times** in the entire Apple codebase — the only two references are
its own declaration and its own `print` at :1515. Tracks change by `handleTrackEnd` loading the next
file when the previous one ends.

**This is not quite the shape it looked like.** The first draft of this ADR filed it as a third
instance of ADR-0015's finding — a capability with no caller — and that is only half right:

| ADR | what was there | what was missing |
|---|---|---|
| 0015 | six audio effects, with setters | anything calling them |
| 0025 | `favorites_auto_download`, read every launch | anything setting it |
| **0026** | `executeCrossfade` | anything deciding *when* |

`preloadNext` and `isNextReady` do **not** belong in that row. `FamiliarPlayer.primeNext` calls
`engine.preloadNext` at `FamiliarPlayer.swift:954`, reached from thirteen `primeNeighbours()` call
sites, so the next track is already downloaded to a temp file at the *start* of every track — earlier
than the web's 15-second window, not later. Only the fade itself is unreachable. This matters twice
over: it deletes a tradeoff an earlier draft claimed (crossfade adds no download pressure, because the
download already happens), and it changes what the preload half of the ported decision is *for* — see
point 2.

All of it arrived the same way. The Capacitor app drove these methods across a JavaScript bridge;
[ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md) point 2 moved the engine "intact",
the bridge was deleted, and `executeCrossfade` was left behind it while the preload it depends on
found a new caller.

**The web does crossfade, and its design is the answer to where the decision belongs.** Nothing in
`WebAudioEngine` decides to fade. `useAudioEngine.ts:435-476` watches the clock, and the judgement is
four pure functions in `player/audio/eventHandlers.ts` — `getCrossfadeTrigger`,
`getEffectiveCrossfadeDuration`, `shouldHandleEnded`, `getErrorAction` — with 12 `expect` calls
against the trigger alone (17 assertions at run time; one case loops over six values) out of 32 in
`__tests__/eventHandlers.test.ts`. The file's own header says why: *"Pure functions extracted from
useAudioEngine event handlers for testability. These encode the guard/decision logic without side
effects."*

That split is the finding. **Fading two nodes is engine work; knowing when to start is queue work**,
because it depends on what is playing, what is next, whether the next thing is ready, and whether the
listener asked for it at all.

**What the web's rules actually are**, because they are the specification and were learned the hard
way:

- Two windows, not one. `preload` from `crossfadeDuration + 15s` remaining down to
  `crossfadeDuration + 1s`; `crossfade` from `crossfadeDuration` remaining down to `0.1s`.
- The fade is clamped to `timeRemaining - 0.5`, with a comment saying exactly why: *"so the old
  track's scheduleFile callback doesn't fire mid-crossfade"*. Under 0.5s it is skipped entirely —
  below that there is no meaningful fade, only a glitch.
- A network output forces the effective duration to **zero**, so a remote device plays each track to
  its true end.
- Guarded on the engine's declared capability, on `isCrossfading()`, on a queue transition already in
  flight, and on a known duration.

**"Network output" does not mean AirPlay, and an earlier draft of this ADR said it did.** Recorded
because the mistake inverts the rule. On the web it means a WiiM, Sonos or UPnP target — the local
engine is muted and the *device* fetches its own stream, so advancing the queue early clips the tail
on the device. `PlaybackSettings.tsx` says so on screen: *"Crossfade isn't available on network
outputs (WiiM / Sonos / UPnP)."* AirPlay is the opposite case, and ADR-0031 point 3 excludes it from
the Apple clients precisely because there the client stays the audio source and the OS routes the
rendered mix. Suppressing a fade over AirPlay would suppress it on the one route where it is fully
audible. ADR-0031 point 6 already states the correct rule and names this ADR; point 7 below carries it.

**Settings are per-device, and the vocabulary already exists.** `player/audioSettingsStore.ts`
persists `crossfadeEnabled` (default **on**) and `crossfadeDuration` (default **3s**, clamped 0–10)
to `localStorage`, with a UI in `PlaybackSettings.tsx`. They have never been server state, exactly
like the audio effects ADR-0015 point 5 keeps local. Both platforms now have somewhere to put them:
ADR-0025 point 2 reversed ADR-0015's macOS-only scope, and `EffectsSettingsView` is already one pane
used by `SettingsWindow` and `PhoneSettingsView` both.

**Three things about the engine are worth knowing before building on it.**

*The auto-advance guard has never run.* `handleTrackEnd` opens at `NativeAudioEngine.swift:1747` with
`if isCrossfadingFlag { return }` and a comment explaining that otherwise auto-advance would load the
next track a second time and "stomp the in-flight fade". The flag has never been true. Turning
crossfade on turns that code path on for the first time — and `NativeAudioEngineCrossfadeGuardTests`
covers the `scheduleFile` and `seek` callbacks but **not this one**.

*`finishCrossfade` notifies nobody.* It swaps the players, promotes `currentTrackId`, clears the
preload state and calls its `completion` — it never calls `audioEngineDidAutoAdvance`. So the fade
path bypasses everything `FamiliarPlayer.swift:1139-1171` does on a normal advance: the cursor move,
`concludeCurrentTrack(reason: .natural)`, `consumePlayedTrack`, `reportingTrack`, the `trackEpoch`
bump, `publishNowPlaying` and `primeNeighbours`. The last is the sharp edge — `finishCrossfade` clears
`nextTrackId` but leaves `pendingNextUrl` pointing at the track that just *became* current, so an
un-re-primed engine would auto-advance that track into itself. And with ADR-0030 scrobbling now
shipped, a skipped `concludeCurrentTrack` means every crossfaded track goes unreported. This is the
part of the work that is correctness rather than polish.

*The cast mute cannot be broken by a fade.* Checked rather than assumed, because it looked like a
collision: `setVolume` writes `engine.mainMixerNode.outputVolume` (`NativeAudioEngine.swift:1163`)
while the crossfade ramp writes `playerNode.volume` and `nextPlayerNode.volume` (:1574-1575). Separate
nodes, so a fade cannot leak audio out of a muted Mac. Point 7 exists for the queue-timing reason,
not for a volume one.

## Decision

1. **The player decides when to crossfade; the engine only performs it.** `FamiliarPlayer` watches
   playback position through the `audioEngineDidUpdateTime` delegate it already implements
   (`FamiliarPlayer.swift:1117`, 4Hz) and calls the engine's existing `preloadNext` and
   `executeCrossfade`. No new DSP, and nothing inside `NativeAudioEngine`'s processing changes —
   ADR-0015 point 2's rule applies here unchanged.

2. **The decision is pure, lives in `FamiliarKit`, and mirrors the web's numbers.** `CrossfadeDecision`
   ports `getCrossfadeTrigger` and `getEffectiveCrossfadeDuration` with the same windows, the same
   bounds and the same answers, asserted case for case against the web's suite. Not because sharing
   is elegant, but because two clients that disagree about when a fade starts would sound different
   on the same library. **The identifiers are Swift's, not JavaScript's** — `CrossfadeDecision.trigger`
   and `.effectiveDuration`, matching `QueueAdvance.next` rather than importing `getX` naming into a
   package that has none. ADR-0021's precedent is that clients share the *vocabulary*; the doc
   comments name their web counterparts so a search across both repositories still finds the pair.

3. **The ported `preload` window is a repair, not a preload.** The next track is already primed at
   track start (see Context), so acting on `preload` the way the web does would be redundant. It is
   kept for the one case nothing else covers: `preloadNext` gives up after a 10-second timeout
   (`NativeAudioEngine.swift:1371`), sets `preloadState = .failed`, and **nothing ever retries**. The
   player acts on the `preload` trigger only when `isNextReady()` is false. The function keeps the
   web's shape so the boundaries stay comparable; the caller does not.

4. **The 0.5s clamp and the 0.1s floor are carried across as-is**, with the web's reasoning attached.
   They are not tuning constants; they are the boundary either side of which the old track's
   completion callback fires inside the fade. **They become a third function rather than staying
   inline.** The web computes the clamp at its call site in `useAudioEngine.ts` and asserts it
   nowhere, so the two most load-bearing numbers in this ADR are the two with no test behind them.
   `CrossfadeDecision.fadeDuration` returns the clamped length or nil when what is left is too short
   to hear, and a swept property test holds it to the invariant the whole clamp exists for: a fade
   never runs into the audio the trigger measured it against.

5. **Settings are per-device**, in `UserDefaults` alongside `AudioEffectSettings`, clamped on read for
   the reason that type's own comment gives — a settings blob written by an older build is not a
   slider. Offered on both platforms through the shared panes ADR-0025 point 8 built.
   `crossfadeEnabled` defaults **on** and `crossfadeDuration` to **3s**, clamped 0–10, matching the
   web so a listener moving between clients is not surprised. No server endpoint, for the reason
   ADR-0015 point 6 gives: this is a property of how this device plays, not of the listener.

6. **A completed fade reports itself through the existing auto-advance path.** `finishCrossfade` calls
   `delegate?.audioEngineDidAutoAdvance(loadedTrackId:)`, and `executeCrossfade`'s completion is left
   to clear the in-flight flag and handle failure only. One path for "the engine changed track by
   itself" rather than two, and the player's handler is already written to *follow* rather than lead.
   That handler gains one change serving both callers: it rebases `lastCountedTime` from
   `engine.getCurrentTime()` instead of leaving the zero `concludeCurrentTrack` defers
   (`FamiliarPlayer.swift:762`). On a normal advance that reads ~0 and nothing moves; after a fade the
   new track is already `crossfadeDuration` seconds in, and the tick guard `delta < 2`
   (`FamiliarPlayer.swift:1124`) would otherwise discard exactly that much played time from every
   crossfaded track.

7. **Crossfade is suppressed while casting, and is not suppressed over AirPlay.** Per ADR-0031
   point 6, read from `CastController.isCasting` (`Casting.swift:110`) and reaching `FamiliarPlayer`
   as an injected predicate, in the style of the `downloadedFileURL` and `artworkURL` closures it
   already takes — `FamiliarKit`'s player does not learn about casting to answer one question. AirPlay
   is deliberately excluded from the suppression: ADR-0031 point 3 keeps the client the audio source
   there, so the fade is rendered locally and heard.

8. **Nothing is synced and no ADR-0003 interaction is introduced.** A crossfade is a rendering
   decision made locally, at the moment of a transition. A queue says what plays next, never how the
   join sounds.

9. **`handleTrackEnd`'s crossfade guard is treated as untested code, because it is.** It has never
   run, and the existing suite does not reach it. The first stage of work is a third case in
   `NativeAudioEngineCrossfadeGuardTests` covering it — asserted against the source text like its two
   siblings, because `isCrossfadingFlag` and `handleTrackEnd` are both `private` and the engine cannot
   be driven without hardware. Naming that limit is the point: this ADR does not claim a state test it
   cannot write.

10. **A pause cancels an in-flight fade rather than suspending it.** Found while building point 1 and
    recorded here because it is a decision, not a detail: `pause()` pauses `playerNode` and not
    `nextPlayerNode`, and the ramp measures itself against `Date()` rather than against playback. So
    a pause during a fade left the incoming track playing on alone, rising to full volume, and
    promoted it — while the listener believed they had stopped the music. Unreachable until now for
    the reason this whole ADR exists. Cancelling costs one fade: the outgoing track keeps the
    transition and hands over normally at its own end.

11. **Verification is in three layers, and the third is not optional.** The decision functions are
    unit tested against the same numbers as the web's suite. The guards are asserted against the
    source, per point 9. **And then somebody listens**, per ADR-0024 point 9, because no test in
    either repository can hear a gap. The listen is specified in Consequences rather than left as
    "try it".

## Alternatives Considered

**Put the decision in the engine, since it already owns the timer.** The engine runs a 60fps timer
during a fade and a 4Hz one during playback; adding "start a fade when the track is nearly over"
looks like three lines. Rejected because the engine does not know what is next, whether it is
downloaded, whether the queue is about to change, or whether the listener wants a fade at all — every
one of those would have to be pushed into it, which is the queue moving into the audio graph. The web
learned this and put the decision in `useAudioEngine`; the ADR-0009 download work made the same
choice for the same reason.

**Reimplement the fade in Swift rather than calling `executeCrossfade`.** Rejected outright: the
method exists, shipped in the Capacitor app, and ramps real nodes. This is ADR-0015's finding again —
"audio effects on the Mac" sounded like a DSP project and was a settings screen.

**Advance the cursor from `executeCrossfade`'s completion closure instead of the delegate** (point 6's
rejected half). Tempting because it keeps the change on the player's side of the boundary and leaves
the engine untouched. Rejected because it duplicates the eight-step tail of `audioEngineDidAutoAdvance`
at a second call site, and the failure mode of the copy drifting from the original is a track that
scrobbles twice or not at all. `finishCrossfade` promoting a track without telling its delegate is a
defect on its own terms, whoever calls it.

**Suspend the fade across a pause instead of cancelling it** (point 10's rejected half). The
listener's intent is arguably "hold everything", and resuming into the middle of a fade is what a
tape would do. Rejected on cost against benefit: it means pausing the second player *and* rebasing
the timer's start instant, which is a stopwatch threaded through a 60fps volume ramp — the piece of
this engine least able to absorb a subtle bug — for a difference nobody can hear. Cancelling loses
one crossfade at a moment the listener has already interrupted.

**Share the decision code with the web through a common package.** Genuinely tempting given point 2
copies a tested function. Rejected because there is no such package and inventing one for two
functions would be a build-system change to avoid re-typing forty lines. ADR-0021 set the precedent:
share the *vocabulary*, keep the implementations separate, and let tests on each side hold them to the
same numbers.

**Ship crossfade without a settings control, always on at 3s.** Fewer moving parts, and matches what
most listeners would want. Rejected because crossfade is genuinely unwanted for some material —
gapless albums, classical, anything with applause between tracks — and an effect that cannot be
turned off is worse than one that is off by default. The web already offers the switch.

**Leave it.** Defensible: nobody has complained, and gapless-by-loading works. Rejected because the
capability is already paid for and unreachable, which is the same state ADR-0015 and ADR-0025 both
found and both judged worth fixing. It is also asymmetric in a way that is hard to explain — the web
client crossfades the same library on the same server.

## Consequences

- **Positive:** two clients stop sounding different on the same library.
- **Positive:** a 77-line method that has never run becomes reachable, and `handleTrackEnd`'s guard
  gets exercised for the first time — point 9 makes that deliberate rather than incidental.
- **Positive:** the decision arrives with tests, because it is pure. The hard part of crossfade is
  knowing when, and that part is checkable without a speaker.
- **Positive, and unplanned:** point 3 gives the preload a retry it has never had. A next track whose
  download timed out at track start currently stays failed until the track ends and the slower
  `handleTrackEnd` path reloads it from scratch.
- **Positive:** point 6 fixes a systematic undercount in scrobbling that predates this work in
  principle and would have shipped with it in practice — every crossfaded track would have reported
  `crossfadeDuration` seconds fewer than it played.
- **Tradeoff:** a transition that used to be one code path becomes two, and the second only runs when
  a setting is on. The failure mode is a track that fades into silence rather than into the next one,
  which is worse than a gap.
- **Tradeoff:** point 6 changes an engine file this ADR otherwise promises not to touch. It is one
  delegate call outside the render path, and ADR-0015 point 2's test — "if exposing an effect appears
  to require engine changes, stop and reconsider" — was applied rather than waved past: the
  reconsideration is the third alternative above.
- **Positive, and the one that justifies point 11's middle layer:** building the caller made a
  latent engine defect reachable and it was caught by reading, not by listening. Pausing mid-fade was
  on the listen list below as one case among eight; point 10 answers it by construction instead.
- **Tradeoff, and the finding the listen actually produced.** The first real listen restarted the
  incoming song: the fade ran, then a hard cut, then the new track from zero. Three places schedule
  audio whose end should advance the queue — a load, a seek, and the incoming half of a fade — and
  they carried three *different* subsets of the same three guards. The listen had seeked to near the
  end of the track, so the live callback was the seek one, which lacked `activePlayerIndex`;
  `finishCrossfade`'s `playerNode.stop()` fired it, and it reached `handleTrackEnd` while
  `pendingNextUrl` still named the track the fade had just promoted. A second instance of the same
  divergence was still silent: the fade's own callback had no seek-token guard, so seeking a track
  that *arrived* by crossfade would have skipped it. Both are now one factory with one guard set, and
  `handleTrackEnd` has exactly one caller — which is the invariant worth asserting, and is asserted.
- **The durable lesson, and it is about the tests rather than the engine.** Two guard tests passed
  against the broken code. They asserted that each callback *contained* `isCrossfadingFlag`, and each
  did — what neither asked was whether that flag could still be true when the callback ran. It cannot:
  `finishCrossfade` clears it before any `DispatchQueue.main.async` body gets a turn, so it only ever
  catches a callback firing *during* a fade. `activePlayerIndex` is the guard that holds afterwards,
  because it is a durable fact about which node is live rather than a flag in flight. **A test that a
  guard exists is worth much less than a test that there is only one way to reach the thing it
  guards.**
- **Follow-up, and the specification of the listen point 11 requires.** Confirm continuous playback
  across: a normal track end; a track end with the next track not yet downloaded; skipping *during* a
  fade; seeking backwards past the trigger point; **pausing mid-fade, which must stop everything and
  lose the fade rather than keep one player running** (point 10); a queue change mid-fade; the last
  track in a queue; a fade with an effect enabled; **while casting, which must not fade**; and **over
  AirPlay, which must**. Each on both platforms, except casting, which is macOS-only per ADR-0031
  point 7. The engine's own comments name the first, third and fourth as the cases that have bitten
  before.
- **Follow-up:** whether the phone should crossfade at all on cellular. Weaker than it looked when
  this ADR was drafted, since the preload it implies already happens — but a fade means the next
  track's download must *succeed* rather than merely be attempted, so the question is not empty. The
  download work's `isDiscretionary` precedent is worth reading first.
