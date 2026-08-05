# ADR-0026: Crossfade Is Decided by the Player, Not the Engine

Status: proposed

Date: 2026-08-05

Extends [ADR-0015](ADR-0015-audio-effects-are-exposed-not-rebuilt.md) and
[ADR-0025](ADR-0025-the-phone-gets-a-settings-destination.md).

## Context

**The native apps do not crossfade, and nothing is broken.** `NativeAudioEngine.executeCrossfade`
exists, is 80 lines long, ramps two player nodes against each other on a 60fps timer, and is called
**zero times** in the entire Apple codebase — the only two references are its own declaration and its
own `print`. Tracks change by `handleTrackEnd` loading the next file when the previous one ends.

This is the third time this exact shape has been found, and the count is the point:

| ADR | what was there | what was missing |
|---|---|---|
| 0015 | six audio effects, with setters | anything calling them |
| 0025 | `favorites_auto_download`, read every launch | anything setting it |
| **0026** | `executeCrossfade`, preload, `isNextReady` | anything deciding *when* |

All three arrived the same way. The Capacitor app drove these methods across a JavaScript bridge;
[ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md) point 2 moved the engine "intact",
the bridge was deleted, and the methods were left behind it. **The engine is not missing features.
It is missing callers.**

**The web does crossfade, and its design is the answer to where the decision belongs.** Nothing in
`WebAudioEngine` decides to fade. `useAudioEngine.ts` watches the clock, and the judgement is four
pure functions in `player/audio/eventHandlers.ts` — `getCrossfadeTrigger`,
`getEffectiveCrossfadeDuration`, `shouldHandleEnded`, `getErrorAction` — with 15 assertions against
the trigger alone in `eventHandlers.test.ts`. The file's own header says why: *"Pure functions
extracted from useAudioEngine event handlers for testability. These encode the guard/decision logic
without side effects."*

That split is the finding. **Fading two nodes is engine work; knowing when to start is queue work**,
because it depends on what is playing, what is next, whether the next thing is ready, and whether the
listener asked for it at all.

**What the web's rules actually are**, because they are the specification and were learned the hard
way:

- Two windows, not one. `preload` from `duration + 15s` remaining down to `duration + 1s`;
  `crossfade` from `duration` remaining down to `0.1s`.
- The fade is clamped to `timeRemaining - 0.5`, with a comment saying exactly why: *"so the old
  track's scheduleFile callback doesn't fire mid-crossfade"*. Under 0.5s it is skipped entirely —
  below that there is no meaningful fade, only a glitch.
- A network output (AirPlay) forces the effective duration to **zero**, so a remote device plays each
  track to its true end.
- Guarded on the engine's declared capability, on `isCrossfading()`, on a queue transition already in
  flight, and on a known duration.

**Settings are per-device, and the vocabulary already exists.** `audioSettingsStore.ts` persists
`crossfadeEnabled` (default **on**) and `crossfadeDuration` (default **3s**, clamped 0–10), with a
UI in `PlaybackSettings.tsx`. They have never been server state, exactly like the audio effects
ADR-0015 point 5 keeps local.

**The engine has one behaviour worth knowing before building on it.** `handleTrackEnd` opens with
`if isCrossfadingFlag { return }` and a comment explaining that otherwise auto-advance would load the
next track a second time and "stomp the in-flight fade". That guard has never fired, because the flag
has never been true. Turning crossfade on turns that code path on for the first time.

## Decision

1. **The player decides when to crossfade; the engine only performs it.** `FamiliarPlayer` watches
   playback position and calls the engine's existing `preloadNext` and `executeCrossfade`. No new DSP,
   and nothing inside `NativeAudioEngine`'s processing changes — ADR-0015 point 2's rule applies here
   unchanged.

2. **The decision is pure, lives in `FamiliarKit`, and mirrors the web's function for function.**
   `getCrossfadeTrigger` and `getEffectiveCrossfadeDuration` are ported as Swift with the same names,
   the same windows and the same clamps. Not because sharing is elegant, but because two clients that
   disagree about when a fade starts would sound different on the same library, and the web's version
   is the one with fifteen assertions behind it.

3. **The 0.5s clamp and the 0.1s floor are carried across as-is**, with the web's reasoning attached.
   They are not tuning constants; they are the boundary either side of which the old track's
   completion callback fires inside the fade.

4. **Settings are per-device**, in `UserDefaults` alongside the audio effects, offered on both
   platforms through the surfaces ADR-0025 built. `crossfadeEnabled` defaults **on** and
   `crossfadeDuration` to **3s**, clamped 0–10, matching the web so a listener moving between clients
   is not surprised. No server endpoint, for the reason ADR-0015 point 6 gives: this is a property of
   how this device plays, not of the listener.

5. **Nothing is synced and no ADR-0003 interaction is introduced.** A crossfade is a rendering
   decision made locally, at the moment of a transition. The server-owned queue says what plays next,
   never how the join sounds.

6. **`handleTrackEnd`'s crossfade guard is treated as untested code, because it is.** It has never run.
   The first stage of work is a test that puts the engine in `isCrossfadingFlag` and asserts
   auto-advance declines — before anything can reach that state in the field.

7. **Crossfade is off on a network output**, following the web. A device at the end of an AirPlay
   link has its own buffering and its own idea of when a track ends; overlapping two streams into it
   produces a fade nobody can predict.

8. **Verification is in three layers, and the third is not optional.** The decision functions are unit
   tested. The state machine — that a transition cannot both crossfade and auto-advance, and that the
   two players are never both silent — is unit tested against the engine's own flags. **And then
   somebody listens**, per ADR-0024 point 9, because no test in this repository can hear a gap. The
   listen is specified in Consequences rather than left as "try it".

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

**Share the decision code with the web through a common package.** Genuinely tempting given point 2
copies fifteen tests' worth of logic. Rejected because there is no such package and inventing one for
two functions would be a build-system change to avoid re-typing forty lines. ADR-0021 set the
precedent: share the *vocabulary*, keep the implementations separate, and let tests on each side hold
them to the same numbers.

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
- **Positive:** an 80-line method that has never run becomes reachable, and `handleTrackEnd`'s guard
  gets exercised for the first time — point 6 makes that deliberate rather than incidental.
- **Positive:** the decision arrives with tests, because it is pure. The hard part of crossfade is
  knowing when, and that part is checkable without a speaker.
- **Tradeoff:** a transition that used to be one code path becomes two, and the second only runs when
  a setting is on. The failure mode is a track that fades into silence rather than into the next one,
  which is worse than a gap.
- **Tradeoff:** preloading the next track earlier means more downloads in flight on a paged library.
  Bounded — one track — but it is the same class of pressure that exhausted the server's connection
  pool on 2026-08-02, and worth remembering rather than rediscovering.
- **Follow-up, and the specification of the listen point 8 requires.** Confirm continuous playback
  across: a normal track end; a track end with the next track not yet downloaded; skipping *during* a
  fade; seeking backwards past the trigger point; pausing mid-fade; a queue change mid-fade; the last
  track in a queue; and a fade with an effect enabled. Each on both platforms. The engine's own
  comments name the first, third and fourth as the cases that have bitten before.
- **Follow-up:** whether the phone should crossfade at all on cellular, given the preload it implies.
  Not answered here; the download work has a precedent in `isDiscretionary` worth reading first.
