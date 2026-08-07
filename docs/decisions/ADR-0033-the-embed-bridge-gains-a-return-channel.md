# ADR-0033: The Embed Bridge Gains a Return Channel

Status: proposed

Date: 2026-08-06

Extends [ADR-0016](ADR-0016-embedded-web-surfaces-on-the-mac.md),
[ADR-0017](ADR-0017-the-embedded-surface-gets-a-null-audio-engine.md) and
[ADR-0020](ADR-0020-the-embedded-surface-can-ask-the-app-to-navigate.md).
Amends [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md) point 5 and
[ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md) point 4.

## Context

[ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md) point 5 put the visualizer
*"explicitly out of v1, remaining web-only and possibly permanently"*, measuring it at **4,017 lines
of three.js/React-Three-Fiber across 23 files**. That measurement re-checked on 2026-08-06 holds:
`packages/frontend/src/components/Visualizer/` is **3,985 lines across 22 TypeScript files**. The
surface has not grown; ADR-0001's arithmetic was sound. What needs revisiting is the word
"permanently", and the reason is churn rather than size.

Applying ADR-0016 point 1's test — churn and surface size, not performance — to every screen that
has been through it:

| surface | lines | files | commits, 6 months | decided |
|---|---|---|---|---|
| Discover | 3,020 | 27 | 14 | embedded (ADR-0016 pt 2) |
| **Visualizer** | **3,985** | **22** | **14** | — |
| Chat | 965 | 3 | 6 | native (ADR-0022) |
| Music Map | 720 | 1 | 2 | native (ADR-0016 pt 3) |

The visualizer is the largest surface in the web app and tied for the most active. On the stated
test it lands on the embedded side more clearly than Discover did.

**But the thing that decides this ADR is not the test.** It is that an embedded visualizer cannot
work under the rules the embed currently runs by, and the rule it breaks is the one every other
embed ADR leans on. ADR-0016 point 5:

> The bridge is one-way and narrow: the page posts an intent … the native side owns the queue, the
> playback and the reporting. **The web view is never told what is playing** and never renders a
> transport.

A visualizer's entire job is to be told what is playing, sixty times a second.

Inside `/embed` the engine is `NullAudioEngine`, which omits all fifteen optional members of
`AudioEngine` — including `getAnalyser?()` — and declares `capabilities.visualizer: false`. The
audio is not merely absent from the page; it is in another process, played by `AVAudioEngine`
scheduling `AVAudioFile` buffers. There is no Web Audio graph in the web view to analyse and no way
to make one. Either data flows app → page, or there is no embedded visualizer.

**The DSP is already built, already running, and already discarded.** `NativeAudioEngine`
installs a tap on `mainMixerNode` in `enableAnalysis()` (`NativeAudioEngine.swift:2165`), runs a
Hann-windowed FFT off the main actor in `NativeAudioAnalysisProcessor`, throttles to
`analysisMinInterval = 1.0/60.0`, and hands a `NativeAudioAnalysisFrame` to its delegate. The
delegate is `FamiliarPlayer.swift:1466`:

```swift
/// Analysis drives the visualizer, which ADR-0001 point 5 puts out of v1 scope.
nonisolated func audioEngineDidUpdateAnalysis(
    frequencyData: [UInt8],
    timeDomainData: [UInt8],
    metrics: NativeAudioAnalysisMetrics
) {}
```

An empty body. The tap is installed on every `play()`, the FFT runs at 60 Hz, the frame hops to the
main actor, and it is thrown away — because of the ADR point this one amends.

**The main-thread cost of this channel is therefore already being paid, into nothing.** Verified
2026-08-07, after [ADR-0041](ADR-0041-the-playhead-is-published-separately.md) made this the
question worth asking: `NativeAudioEngine.swift:2199` performs a `DispatchQueue.main.async` for
every emitted frame — roughly **57 times a second throughout playback** — carrying two `[UInt8]`
arrays and a thirteen-field struct to that empty function. This ADR does not add a 60 Hz main-thread
burden. It gives one that already exists a purpose, which is a materially better position than "a
visualizer would cost 60 hops a second" and is worth stating plainly, because ADR-0041's measurement
otherwise reads as an argument against this ADR.

**~57 Hz, not 60, and it is the hardware's number rather than ours.** `analysisMinInterval` is
`1.0/60.0`, but the guard is evaluated on tap callbacks, which arrive at 44100/256 ≈ 172 Hz. The
first callback at or past 16.67 ms is the third, so frames emit every ~17.4 ms ≈ 57.4 Hz — and a
48 kHz device gives a different number again. `NativeAudioAnalysisMetrics.cadenceHz` already carries
the measured rate in every frame, which is the right thing for the page to trust.

Exposing an FFT here is mostly a publishing problem. Two signal-processing problems come with it,
below.

**Both ends of the channel were built once before, for Capacitor, and ADR-0001 deleted the middle.**
`NativeAudioAnalysisMetrics` still carries an `asDictionary()` — a survival from
`FamiliarAudioPlugin.swift`, which marshalled exactly this across a JS boundary. On the web side,
`packages/frontend/src/player/audio/nativeAnalysisBuffers.ts` still exports
`setNativeAnalysisBuffers` / `clearNativeAnalysisBuffers` / `getNativeAnalysisBuffers`, and
`useAudioAnalyser.ts` still reads them, because iOS suspends `AudioContext` in the background. The
shape this ADR proposes is not new; it is the shape that worked, with a different transport.

**The existing contract is a pull, and that matters for the transport.** `useAudioAnalyser.ts` runs
one shared `requestAnimationFrame` loop that mutates a persistent object; visualizers call
`getAudioData()` synchronously inside R3F's `useFrame`. Nothing awaits anything per frame. Whatever
this ADR builds has to land in a buffer the page reads on its own schedule, or every visualizer in
`docs/VISUALIZER_API.md` has to change.

**Two mismatches have to be settled here rather than found later, and only one of them is
resolution.** Both were found on 2026-08-07 by reading the processor rather than the ADR.

*Resolution.* The native processor uses `fftSize = 256`, giving 128 bins. `WebAudioEngine` uses
`fftSize = 1024` — 512 bins. Feeding 128 bins into a detector tuned on 512 starves it.

*Smoothing, which is the half that was missed.* The same `WebAudioEngine.ts:92-96` comment gives two
reasons, not one: *"1024-pt FFT (512 bins) for finer bass/kick separation; **lower smoothing so
transients survive for the onset/beat detector (0.8 over-averaged the spectrum and starved
spectral-flux onset detection)**"* — and it sets `smoothingTimeConstant = 0.5` accordingly. The
native processor applies `frequencyFloats[i] = 0.8 * previous[i] + 0.2 * frequencyFloats[i]`
(`NativeAudioEngine.swift:349`): **exactly the value the web deliberately tuned away from.** Point 5
moves onset derivation to the page to keep one tuned implementation, and would then hand that
implementation a spectrum pre-smoothed at the setting it was tuned *against*. Matching
`WebAudioEngine` means matching both numbers or the fix is half a fix.

**And the frames are not a continuous spectrogram.** `NativeAudioAnalysisProcessor.accumulate`
evaluates its throttle **before** appending:

```swift
guard now - lastFrameAt >= minInterval else { return nil }
sampleBuffer.append(contentsOf: UnsafeBufferPointer(start: channelData, count: frameCount))
```

So a throttled callback discards its buffer entirely — **roughly two of every three buffers of audio
are never seen.** Each frame is a 256-sample window with ~740 samples unobserved before it, not a
window onto a continuous stream. That is harmless for a level meter and is *not* harmless for
spectral flux, which is defined as the frame-to-frame difference of consecutive spectra: the page's
detector would be differencing snapshots taken across gaps. This is independent of the smoothing
problem, undermines point 5 in the same way, and is invisible from the ADR's vantage point because
the frames currently go nowhere.

**And two native tests have never passed.** `NativeAudioAnalysisProcessorTests.swift:54` and `:75`
are unconditional skips — *"Band edges disagree with the fixture"* and *"Variance ordering does not
hold; not yet diagnosed"* — and CI never reported it because the iOS job ends
`| xcpretty || true`. The values in question are `bass`, `mid`, `treble` and `variance` on
`NativeAudioAnalysisMetrics`: the derived half of the frame, not the spectrum itself.

## Decision

1. **The visualizer is an embedded surface**, by ADR-0016 point 1 applied to the largest and
   joint-churniest screen in the web app. ADR-0001 point 5's "possibly permanently" is retired for
   the visualizer specifically. The rest of that point — ambient mode, the settings panels, library
   import, S3 backup — is untouched. [ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md)
   point 4 is amended in the same narrow way: its visualizer bullet gave "no native analogue and no
   management purpose" as the reasons, and the first of those has stopped being true — the analogue
   is the FFT quoted above, running on every track.

2. **The bridge gains a direction, not a message.** Page → app stays at exactly two intents and
   ADR-0020 point 2's cap is not weakened, because nothing is being added to it. App → page is a
   separate channel with its own contract, its own file and its own tests. Keeping them separate is
   what lets ADR-0020 point 3's bar go on meaning what it means.

3. **The channel is a coalesced push into a page-side buffer, and the page reads it on its own
   frame.** The native side calls `evaluateJavaScript` with the latest frame, fire-and-forget, and
   **never has more than one call in flight** — if a frame is ready while one is outstanding, the
   newer frame replaces it and the older is dropped. A visualizer rendering at 30 fps must not
   accumulate a queue of 60 Hz frames it will never draw.

   **Nothing to build this on exists today.** There is no buffering anywhere in the analysis path:
   each frame is an independent `DispatchQueue.main.async`, so a busy main queue delays every frame
   in order rather than dropping any. The coalescing described here is new machinery, not a
   configuration of something present.

   **And it trades directly against point 5.** Every dropped frame widens the gap the page's
   spectral flux is differenced across, on top of the gaps point 12 already has to close. Coalescing
   is right for the render loop and is a cost to the detector; the two must be designed together
   rather than each in isolation.

4. **The page-side landing point is `nativeAnalysisBuffers.ts`, unchanged.** The frame is written
   with `setNativeAnalysisBuffers`, `useAudioAnalyser` reads it, and `getAudioData()` keeps its
   current signature. Every visualizer in `docs/VISUALIZER_API.md` works without modification,
   which is most of what embedding is being bought for.

5. **The frame carries the spectrum, not the derived values.** `frequencyData` and
   `timeDomainData` cross; `bass`, `mid`, `treble`, `beat` and `onset` are derived on the page by
   `player/audio/analysisMetrics.ts` and the spectral-flux detector in `useAudioAnalyser`, which
   already exist and are already tuned. This deliberately routes around the two never-passing tests
   rather than depending on them, and it leaves **one** implementation of the band maths instead of
   two that are known to disagree.

6. **The native `fftSize` rises from 256 to 1024 and its smoothing falls from 0.8 to 0.5**, both
   matching `WebAudioEngine`, so the page's detector receives the spectrum it was tuned for.
   Anything less makes point 5 a downgrade dressed as reuse — and the smoothing is the half this
   ADR originally missed. `WebAudioEngine.ts`'s comment gives both numbers for both reasons, and
   0.8 is named there as the value that "starved spectral-flux onset detection". Shipping 1024 bins
   still smoothed at 0.8 would fix the resolution complaint and leave the detector starved by the
   thing the comment is actually about.

7. **Now-playing identity travels on the same channel**: track id, title, artist, album, artwork
   URL, duration, position, and an explicit `playing` flag. This is the part that plainly reverses
   ADR-0016 point 5's "never told what is playing", and it is reversed **for this surface only** —
   embedded Discover is not told, and does not ask.

8. **Lyrics do not travel on the channel.** `GET /api/v1/tracks/{track_id}/lyrics` is tagged
   `tracks`, is already generated, and returns the synced `lines` the `lyrics` visualizer wants.
   The page has the server URL and the profile ([ADR-0016](ADR-0016-embedded-web-surfaces-on-the-mac.md)
   point 6) and can fetch it itself. A channel that carries everything is a channel with no shape.

9. **The visualizer document declares `visualizer: true` while still constructing no
   `AudioContext`**, and the distinction is what makes this work. The page reads the buffer; it
   never asks the engine for an analyser. ADR-0017's guarantee holds exactly as written — a missed
   play path is inert rather than a second `AudioContext` — and this ADR adds nothing that could
   construct one.

   **Corrected 2026-08-07.** This point previously said the null engine was unchanged at
   `visualizer: false`. That does not work: `isVisualizerAvailable()` reads the *registered
   capability descriptor*, and `FullPlayer.tsx:260` gates on it — `!isVisualizerAvailable()` renders
   album art instead. A surface declaring `false` would never draw a visualizer at all. What keeps
   the guarantee is not the flag but the omission: `NullAudioEngine` omits all fifteen optional
   `AudioEngine` members including `getAnalyser`, and `getAudioAnalyser()` calls
   `existingEngine()?.getAnalyser?.()` — which never constructs. So the visualizer surface registers
   an engine that says it can show a visualizer and still cannot make or analyse a sound.
   `assertCapabilitiesMatch` requires the class-level capabilities and the registration to agree, so
   this is one coherent change rather than a flag flipped in one place.

10. **`disableAnalysis()` runs on `pause()`, so a paused visualizer receives no frames.** The last
    frame is held and `playing: false` is pushed once. Deciding this now is cheaper than
    diagnosing it later as a visualizer that looks frozen rather than paused.

11. **The surface needs its own marker, and the marker is the small part.**
    `EmbedIntent.surfaceMarker` is the single value `"embed"`, probed out of
    `<meta name="familiar-surface">` and compared by `==` in one place. A second embedded document
    must identify itself distinctly, or the probe that exists to catch a pre-`/embed` server
    answering from its SPA fallback cannot tell the two surfaces apart.

    **What a second surface actually touches**, inventoried 2026-08-07, because "its own marker"
    reads much cheaper than it is: `isEmbeddedSurface` and its five-assertion test; the `"embed"`
    path segment, which is an inline literal in `EmbeddedDiscoverView.swift` with no route constant;
    the copy in both failure states, which names Discover; a third entry in
    `packages/web/vite.config.ts` plus an `.html` and a `.tsx`; and the sentence in
    `packages/web/src/embed.tsx` asserting it is *"the only thing that boots the embedded page"*,
    which a second entry point falsifies and which must be rewritten rather than quietly broken.

    **The sharp one is the tests.** `EmbedNavigationPolicyTests` asserts against the **source text
    of `App/Shared/EmbeddedDiscoverView.swift`, located by file path** — because `swift test` cannot
    see the app target. A second view is not covered by them, and extracting the coordinator into a
    shared file so both surfaces use it makes those tests fail on the *path* rather than on the
    substance they exist to protect.

12. **The processor accumulates continuously instead of discarding throttled buffers.** Added
    2026-08-07. The throttle currently returns *before* appending, so ~2 of every 3 buffers are
    dropped and each frame is a window with ~740 unobserved samples in front of it. Point 5 hands
    onset detection to the page, and spectral flux is the difference between *consecutive* spectra —
    so the fix is to keep appending on every callback and throttle only the *emission*, leaving the
    ring of samples continuous.

    **This changes code inside `NativeAudioEngine`'s processing**, which
    [ADR-0015](ADR-0015-audio-effects-are-exposed-not-rebuilt.md) point 2 fenced off — *"If exposing
    an effect appears to require engine changes, that is a signal to stop and reconsider, not to
    proceed."* So it is named here rather than discovered during implementation, and the
    reconsideration is this: the alternative is deriving onsets natively instead, which means a
    second tuned detector in a second language — the duplication point 5 exists to avoid and the one
    [ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md) refused for ranking.
    Appending unconditionally is a few lines inside `NativeAudioAnalysisProcessor`, which is already
    `@unchecked Sendable` and already confined to the tap callback under
    [ADR-0024](ADR-0024-the-audio-engine-is-main-actor-except-where-it-cannot-be.md)'s exception, so
    it crosses no isolation boundary that is not already crossed. It adds no allocation the throttle
    was saving either — the discarded buffers were already copied into the tap's parameter before
    the guard ran.

13. **The frame shape is parsed and formatted in `FamiliarKit`, under test.** `swift test` cannot
    see `App/`, and a wire format is exactly the kind of decision that belongs in the package —
    the same reasoning that put `EmbedIntent.parse` there rather than in the message handler.

## Alternatives Considered

**Rebuild the visualizer natively in Metal or SceneKit.** Fully native, no web view, and the FFT is
already in the right process. Rejected on maintenance, for the reason ADR-0016 rejected a native
Discover: 3,985 lines across 22 files with 14 commits in six months is the most active surface in
the product, and a second implementation would have to change with it every time. It would also
strand the four existing visualizers and the three plugin repositories that target the web API.

**Have the page pull each frame with `WKScriptMessageHandlerWithReply`.** Genuinely attractive: the
page's `requestAnimationFrame` becomes the clock, so backpressure is automatic and a hidden page
asks for nothing. Rejected because it inverts a schedule that already exists — the engine throttles
the tap to 60 Hz and knows when a frame is ready — and it adds an asynchronous round trip per
rendered frame to fetch data that is already sitting in a buffer. `getAudioData()` is synchronous
inside `useFrame`; making it await would change the contract every visualizer is written against,
which is point 4's whole value.

**Push the derived metrics too, since `NativeAudioAnalysisMetrics` already computes them and even
has `asDictionary()`.** The cheapest possible framing, and it is what the Capacitor bridge did.
Rejected because the two skipped tests say the band edges and the variance are wrong, and shipping
them would put unverified numbers into the contract third-party visualizers are written against.
At 44.1 kHz with `fftSize` 256 the processor's "treble" begins around 11 kHz, which is not what
anyone drawing a treble bar means. Deriving on the page keeps one tuned implementation.

**Add a third message to the existing `familiar` handler instead of a second channel.** No new
plumbing, one contract to keep in step. Rejected because it conflates two things ADR-0020 was
careful to separate: a listener-initiated intent, of which there may be two, and a 60 Hz render
feed. It would also make ADR-0020 point 2's cap meaningless — "two messages" would come to include
one that fires sixty times a second — and the bar in point 3 would then have to be argued about
every future push as well as every future intent.

**Ship only the `lyrics` and `music-video` visualizers, which need metadata but no spectrum.** It
would need point 7 and not points 3–6, which is most of the work avoided. Rejected because the two
that need no FFT are the two least worth embedding a web view for, and the channel gets built the
first time anyone wants `reactive-terrain` — which at 1,311 lines is the default and the largest.

**Leave the visualizer web-only, as ADR-0001 point 5 said.** Still defensible: it is the one
feature in the product with no functional purpose, and the web app is a browser tab away. Rejected
because the phone and the Mac are now where the listening happens, the DSP is already running and
being discarded on every track, and "possibly permanently" was written as a scope boundary for v1
rather than as a finding.

## Consequences

- **Positive:** The four existing visualizers work on both Apple clients with no changes to any of
  them, because points 4 and 5 keep `getAudioData()` and its shape intact.
- **Positive:** An FFT that currently runs ~57 times a second and is discarded starts being used.
- **Positive:** The band maths and the onset detector stop existing in two places that disagree.
  Point 5 makes `analysisMetrics.ts` the single implementation for every client.
- **Positive:** Raising `fftSize` to 1024 *and* dropping smoothing to 0.5 fixes a mismatch that
  would otherwise have been discovered as "the beat detection is worse on the Mac" — and the
  smoothing half would have survived the resolution fix, so it would have been discovered twice.
- **Tradeoff:** **ADR-0016 point 5 is no longer true as written.** The bridge is one-way for
  Discover and two-way for the visualizer, and a rule stated in absolute terms now has an
  exception. Anyone reading ADR-0016 alone will get the wrong answer, which is why point 2
  separates the directions rather than blurring them.
- **Tradeoff:** A second embedded document, a second marker, a second entry point in
  `vite.config.ts`, and a second `serve_*` route registered before the SPA catch-all. ADR-0017
  already named the first of these as a cost; this doubles it.
- **Tradeoff:** The seam ADR-0016 called embedding's main risk now has a third contract across it,
  and like the other two nothing checks the TypeScript half against the Swift half at compile time.
- **Tradeoff:** point 12 changes `NativeAudioEngine`'s processing, which ADR-0015 point 2 said was
  a signal to stop and reconsider. The reconsideration is recorded there rather than skipped, and it
  is the one place this ADR spends its "no engine changes" credit — worth knowing before anything
  else in it is treated as licence to spend more.
- **Tradeoff, and smaller than it first read:** ~57 `evaluateJavaScript` calls a second is real
  main-thread work whenever the visualizer is on screen, on top of the render loop inside the web
  view. What it is *not* is a new 60 Hz hop: measured 2026-08-07, the app already performs a
  main-queue dispatch per frame at that rate into an empty delegate, so the added cost is the
  `evaluateJavaScript` call and the serialisation, not the hop. ADR-0041's finding — a **4 Hz**
  publisher saturating the main thread — reads as an argument against this ADR and on inspection is
  not one: that cost was unbounded SwiftUI invalidation, where this is a bounded call with a fixed
  payload. The yardstick worth holding it against is `MusicMapView`'s 0.83 ms/frame of dictionary
  building, which was measured and then removed as too expensive for a frame budget.
- **Tradeoff, found 2026-08-07:** the visualizer document needs more than a spectrum.
  `FullPlayer.tsx:276-283` hands `AudioVisualizer` a track, an artwork URL, lyrics, `isPlaying`,
  `currentTime` and `duration` — all from a player store the embedded document will not have. Point
  7 carries identity and point 8 sends the page to fetch its own lyrics, so the gap is the *clock*:
  `currentTime` advances continuously and the lyrics visualizer is built on it. Whether that rides
  the analysis channel, which already arrives ~57 times a second, or is derived page-side from a
  start time is unresolved here and is the first thing implementation will hit.
- **Follow-up:** The two skipped tests in `NativeAudioAnalysisProcessorTests` are now routed around
  rather than fixed. They still assert something about a processor this ADR depends on, and
  `testBrightFixtureDominatesTreble` in particular encodes a disagreement about where treble begins
  that someone should settle.
- **Follow-up:** `FullPlayer.tsx` decides what to draw from `isVisualizerAvailable()`. The native
  full-player has no equivalent decision yet, and where the visualizer is *reached from* on each
  platform is not settled here.
- **Follow-up:** With two embedded surfaces, `EmbeddedDiscoverView`'s host, coordinator, navigation
  policy and probe are no longer Discover-specific. Generalising them is implementation work, but
  the marker check in point 11 is the part that must not be generalised into a blanket allow.
