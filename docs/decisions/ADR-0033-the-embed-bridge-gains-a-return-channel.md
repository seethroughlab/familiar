# ADR-0033: The Embed Bridge Gains a Return Channel

Status: proposed

Date: 2026-08-06

Extends [ADR-0016](ADR-0016-embedded-web-surfaces-on-the-mac.md),
[ADR-0017](ADR-0017-the-embedded-surface-gets-a-null-audio-engine.md) and
[ADR-0020](ADR-0020-the-embedded-surface-can-ask-the-app-to-navigate.md).
Amends [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md) point 5 and
[ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md) point 4.

Implementation:
- **Nothing of the channel itself is built.** This ADR remains `proposed`: whether the visualizer is
  worth an embedded surface is undecided, and points 1–5 and 7–11 describe work not started.
- **Points 6 and 12 shipped early, on 2026-08-08, in `familiar-apple` #84**, driven by a different
  and much smaller feature: a 24-bar spectrum meter above the Mac's scrubber, drawn natively from
  these frames. It needed the same two fixes for the same reasons, so they landed there rather than
  waiting on a decision about the web visualizer.
- That is why the numbers in `## Context` changed. A consumer is the only thing that makes an
  analysis path measurable, and this ADR had been reasoning from arithmetic — **the 57.4 Hz cadence
  it previously stated as verified was wrong by a factor of six.** Points 6 and 12 were both
  right in direction and wrong in detail until something drew the frames.
- The meter needs no ADR of its own, on the precedent
  [ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md) set when it separated the Music Map
  from ADR-0001 point 5: *"'4,017 lines of three.js' is the visualizer, a different feature."* The
  3,985-line Three.js surface stays out of scope and remains this ADR's subject.
- **Four changes now sit inside the fence ADR-0015 point 2 put around
  `NativeAudioEngine`'s processing** — smoothing, `fftSize`, accumulation order, and the `cadenceHz`
  the last of those broke. Each is recorded where it was made and none can alter what anyone hears,
  the processor being a read-only tap. Accepting this ADR is what makes them a decision rather than
  a run of exceptions; that acceptance has not happened.

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

An empty body. The tap was installed on every `play()`, the FFT ran, the frame hopped to the main
actor, and it was thrown away — because of the ADR point this one amends. **That body is no longer
empty**: the Mac's transport gained a spectrum meter on 2026-08-08 (`familiar-apple` #84), which is
what turned several of the numbers below from estimates into measurements. See `Implementation`.

**The main-thread cost of this channel is therefore already being paid, into nothing.** Verified
2026-08-07, after [ADR-0041](ADR-0041-the-playhead-is-published-separately.md) made this the
question worth asking: `NativeAudioEngine.swift:2199` performs a `DispatchQueue.main.async` for
every emitted frame — **ten times a second throughout playback** — carrying two `[UInt8]` arrays and
a thirteen-field struct to that empty function. This ADR does not add a 60 Hz main-thread burden. It
gives one that already exists a purpose, which is a materially better position than "a visualizer
would cost 60 hops a second" and is worth stating plainly, because ADR-0041's measurement otherwise
reads as an argument against this ADR.

**10 Hz, and it is the platform's number rather than ours.**

**Corrected 2026-08-08, and this replaces a figure this ADR previously asserted as verified.** An
earlier revision of this section said "~57.4 Hz", derived by assuming tap callbacks arrive at
44100/256 ≈ 172 Hz and counting how many the `1.0/60.0` throttle would let through. That arithmetic
was sound and its premise was invented — nothing had ever measured the callback rate, because until
#84 nothing consumed the frames.

Measured two ways once something did. A probe on the delegate, on the running Mac app during real
playback:

    frames/s(observed)=10.0  cadenceHz mean=10.0 min=9.4 max=10.8  bins=512

and then a standalone `AVAudioEngine` playing silence, to find out why:

    requested  256 / 512 / 1024 / 2048 / 4096  ->  actual 4410  (10.0 Hz)
    mainMixerNode 4410 (10.0 Hz),  playerNode 4410 (10.0 Hz)

4410 frames is **exactly 0.1 seconds**. macOS clamps `installTap` to a 100 ms buffer for every
requested `bufferSize` and on every tappable node, so `analysisMinInterval` never binds and the
emission rate is the callback rate. **10 Hz is a platform floor**, not a tuning choice, and it is
the rate any consumer of this channel gets.

`NativeAudioAnalysisMetrics.cadenceHz` carries the measured rate in every frame and is the right
thing for the page to trust — which is the lesson here restated: the number was available all along
and the ADR preferred a derivation.

**The purpose is a plugin ecosystem, and the plugin surface is already built and empty.** Recorded
2026-08-07, because it is the rationale for this ADR and it was missing: the visualizer is the one
place in Familiar where someone outside this repository can add something, and the scaffolding for
that shipped long ago. `docs/VISUALIZER_API.md` is **575 lines** with Registration, Guidelines,
Performance Tips and Contributing sections; `visualizers/_template/` holds an `ExampleVisualizer.tsx`
and its own README; `VisualizerMeta` carries an `author` field commented *"for community
visualizers"*. And `visualizers/community/` has contained nothing but `.gitkeep` since it was created
on 2026-04-20.

**A correction, per rule 4.** This ADR's Alternatives section claimed a native rebuild would strand
*"the three plugin repositories that target the web API"*. There are none — not in this
organisation, not referenced anywhere in the docs. `community/` is empty and the four visualizers in
the picker are all first-party. The sentence is fixed below; the ambition it described is real and
unrealised, which is a different and more useful thing to record.

**Which reframes what embedding buys.** A visualizer author writes Three.js against
`getAudioData()`. Today that runs in a browser tab — and the browser tab is not where this product
is used any more: ADR-0001 moved listening to the native clients and ADR-0013 left the web app as a
management surface. So the reward for writing one is that it runs in the place nobody listens.
Embedding is what makes a third-party visualizer appear on the Mac and the phone **without its
author writing a line of Swift**, which is the only version of this that a person outside the repo
would spend an evening on. Points 4 and 5 are what deliver that: the contract they preserve is not
an internal convenience, it is the thing being offered to other people.

The two occurrences of the phrase *"from Web Audio API"* — `VISUALIZER_API.md:156` and
`types.ts:27` — are the only promise in that contract a push source falsifies. Neither states a bin
count and neither names `AnalyserNode`, so the fix is two sentences, not a versioned API change.

**The frames arrive ~80 ms after their audio was heard, and that is not the same problem as the
rate.** Measured 2026-08-08, because "10 Hz" alone does not say whether a buffer is about to be
played or has just finished playing, and the two lead to opposite designs:

    tap block runs  +81.7 ms  after the buffer's own audio timestamp  (76.1-86.9, n=20)
    outputNode.presentationLatency = 1.3 ms
    sampleTime step = 4410 frames

Output latency is negligible, so the handoff is the whole story. A buffer **straddles now**: by the
time the block runs, roughly its first 80 ms has already left the speakers and only its last ~20 ms
is still ahead. This is the cost of a tap being non-realtime — the block runs on an ordinary
dispatch queue, where allocating and locking are safe, and 100 ms of chunking is what pays for that.

Two consequences fall straight out. Anything that *replays* the buffer over the following 100 ms
doubles the lag rather than fixing it. And a detector reading these frames reports an onset up to
80 ms after it was audible — invisible for a level meter, which is why the native spectrum meter
looks correct, and past the ~45 ms threshold at which audio-visual desync becomes noticeable for
anything that flashes on a beat.

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

So a throttled callback discarded its buffer entirely. **Corrected 2026-08-08:** this ADR first
described that as "roughly two of every three buffers", which followed from the invented 172 Hz.
With callbacks at 10 Hz the throttle never fires at all — and the real loss was worse and in a
different place. Each 4410-frame buffer was appended whole and then a *single* 1024-sample window
taken from it, so **under a quarter of the audio was analysed**: the last 23 ms of every 100 ms. A
transient landing anywhere else was never seen.

That is survivable for a level meter and is *not* survivable for spectral flux, which is defined as
the frame-to-frame difference of consecutive spectra: the page's detector would be differencing
snapshots taken across gaps. It is independent of the smoothing problem and undermines point 5 in
the same way. It was invisible from this ADR's original vantage point precisely because the frames
went nowhere — which is the argument for landing a consumer early, and is what happened.

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
   accumulate a queue of frames it will never draw.

   **Cheaper than it reads, now the rate is known.** At the measured 10 Hz a 30 fps page is *three*
   redraws per frame, not the other way round, so coalescing will almost never have anything to
   drop. It stays in the design because a stalled main thread is the case it exists for, not the
   steady state.

   **Nothing to build this on exists today.** There is no buffering anywhere in the analysis path:
   each frame is an independent `DispatchQueue.main.async`, so a busy main queue delays every frame
   in order rather than dropping any. The coalescing described here is new machinery, not a
   configuration of something present.

   **And it trades directly against point 5.** Every dropped frame widens the gap the page's
   spectral flux is differenced across, on top of the gaps point 12 already has to close. Coalescing
   is right for the render loop and is a cost to the detector; the two must be designed together
   rather than each in isolation.

4. **The page-side landing point is `nativeAnalysisBuffers.ts`, and `getAudioData()` keeps its
   current signature.** The newest sub-frame is written with `setNativeAnalysisBuffers` and
   `getAudioData()` returns what it always has, so every visualizer in `docs/VISUALIZER_API.md`
   works without modification — which is most of what embedding is being bought for.

   **`useAudioAnalyser` itself does change**, and the distinction matters: it is shared
   infrastructure, not a visualizer. Point 5's sequence has to reach the flux detector, so the
   native branch of `analyseLoop` gains a path that runs flux across the four sub-frames it was
   handed rather than differencing whatever `getAudioData()` last returned. Nothing above that line
   notices.

5. **The frame carries the spectrum, not the derived values — as a sequence of four, not one.**

   **Amended 2026-08-08.** As first written this point assumed the page could difference consecutive
   frames the way it does under Web Audio. It cannot: `analyseLoop` computes spectral flux per
   `requestAnimationFrame`, and at 10 Hz five of every six passes would see identical bytes. The
   `FLUX_EMA_ALPHA = 0.1` baseline would learn from ~50 zeroes a second, collapse, and fire on
   essentially every arriving buffer — a detector reporting buffer arrivals rather than beats,
   clamped to 9/s by `ONSET_REFRACTORY_MS = 110`.

   The fix is that **10 Hz is a delivery rate, not an analysis limit**. Each buffer holds 4410
   *continuous* samples, so onset resolution is set by the hop, which is ours to choose. At a 1024
   hop that is four windows per buffer, **23 ms resolution, ~43 Hz** — the same order as the
   `hop_length = 512` this repo's own `librosa.onset.onset_strength` uses in
   `backend/app/services/analysis.py`. The four windows are already computed for point 12; this
   point stops collapsing them.

   So the original intent survives intact — one tuned implementation, on the page — and it survives
   *because* the sequence crosses rather than a single spectrum.

   The two rules that follow from carrying a sequence are points 14 and 15.

   **The frame carries the spectrum, not the derived values.** `frequencyData` and
   `timeDomainData` cross; `bass`, `mid`, `treble`, `beat` and `onset` are derived on the page by
   `player/audio/analysisMetrics.ts` and the spectral-flux detector in `useAudioAnalyser`, which
   already exist and are already tuned. This deliberately routes around the two never-passing tests
   rather than depending on them, and it leaves **one** implementation of the band maths instead of
   two that are known to disagree.

6. **The native `fftSize` rises from 256 to 1024 and its smoothing falls from 0.8 to 0.5**, both
   matching `WebAudioEngine`, so the page's detector receives the spectrum it was tuned for.
   **Both shipped on 2026-08-08 ahead of this ADR** — see `Implementation`; the native meter needed
   them for the same reasons, and 256 turned out to be worse than "lower resolution": its first bin
   begins at 172 Hz, above the kick drum, so there was no bass in the data at all.
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

12. **The processor analyses every window of every buffer instead of one window per callback.**
    Added 2026-08-07, corrected and shipped 2026-08-08.

    As first written this point said the throttle returned before appending and dropped ~2 of every
    3 buffers. The append order was indeed wrong and is fixed; but with callbacks at 10 Hz the
    throttle never fires, and the real loss was that a single 1024-sample window was taken from each
    4410-frame buffer — **under a quarter of the audio**, the last 23 ms of every 100 ms. Point 5
    hands onset detection to the page, and spectral flux is the difference between *consecutive*
    spectra, so a detector fed this is differencing across gaps three times wider than the windows.

    The processor now appends on every callback, throttles only the emission, and folds **every**
    complete window in the buffer, keeping the loudest value per bin so a transient anywhere is
    carried. Given the 100 ms floor this is the only place the temporal detail can come from.

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

14. **The newest sub-frame is what gets drawn; the sequence is what gets analysed.** Added
    2026-08-08. Detection quality comes from the run of four, timing from the last of them — which
    the Context measurement puts within about ±12 ms of what is audible, where sub-frame 0 is 80 ms
    behind it. Drawing the sequence in order would animate 80 ms of the past every 100 ms. Drawing
    only the newest keeps the picture honest, and costs nothing, since the older three have already
    done their job by the time the flux is computed.

15. **Beat-locked effects are driven by a predicted grid, not by the flux.** Added 2026-08-08.
    Nothing above removes the 80 ms between an onset happening and this channel reporting it, so a
    reactive flash is late by construction on the native clients while the same visualizer is tight
    in a browser. A *predicted* grid is immune to input lag in a way a reactive detector is not.

    **A grid needs tempo and phase, and only tempo is stored.** Checked 2026-08-08 rather than
    assumed: `bpm` is persisted and is in `tracks.py`'s queryable allowlist, but the beat *positions*
    are not. `analysis.py:350-351` computes `beat_frames` and `beat_times` from a PLP curve and puts
    them in the shared dict at :366-367 — and nothing writes them to `features`, and there is no
    column. They are thrown away at the end of every analysis, which is the same shape of waste this
    ADR opened with.

    So this point costs one of two things, and the choice is deliberately left open because it is a
    backend decision rather than a bridge one: **derive phase on the page** from `bpm` plus the
    first flux onset, self-correcting and free but wrong until a beat has been heard; or **persist
    `beat_times`**, which is a migration and a few hundred floats per track, and which would also
    serve anything else that ever wants to line up with a beat. The flux stays for what it is good
    at either way: reacting to what a grid cannot predict.

    **This is the one point that changes a visualizer's own code**, and it is therefore the one to
    weigh against ADR-0016 point 1's whole premise. Points 4 and 5 exist so the four existing
    visualizers run unmodified; this says the beat-locked ones want a different clock on native. It
    is recorded here rather than left for whoever first notices the flashes are late.

## Alternatives Considered

**Rebuild the visualizer natively in Metal or SceneKit.** Fully native, no web view, and the FFT is
already in the right process. Rejected on maintenance, for the reason ADR-0016 rejected a native
Discover: 3,985 lines across 22 files with 14 commits in six months is the most active surface in
the product, and a second implementation would have to change with it every time. It would also
strand the four existing visualizers and the plugin API they are written against — see the
Context note on what that API is worth, and on the claim this sentence used to make.

**Have the page pull each frame with `WKScriptMessageHandlerWithReply`.** Genuinely attractive: the
page's `requestAnimationFrame` becomes the clock, so backpressure is automatic and a hidden page
asks for nothing. Rejected because it inverts a schedule that already exists — the engine throttles
the tap and knows when a frame is ready — and it adds an asynchronous round trip per
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
careful to separate: a listener-initiated intent, of which there may be two, and a continuous
render feed. It would also make ADR-0020 point 2's cap meaningless — "two messages" would come to include
one that fires continuously for as long as a track plays — and the bar in point 3 would then have to be argued about
every future push as well as every future intent.

**Replay the four sub-frames over the following 100 ms, so they are drawn in time.** The obvious
way to turn a 10 Hz delivery into 43 Hz motion, and it was the leading candidate until the arrival
time was measured. Rejected on that measurement: the block runs **81.7 ms after** the buffer's own
audio timestamp, so the buffer straddles now rather than sitting ahead of it and every sub-frame is
already due on arrival. Replaying them would add a second 100 ms on top of the 80 ms already spent —
lag of up to 180 ms in exchange for smoothness that point 14 gets for free by interpolating toward
the newest.

**Derive onsets natively and send the events.** Precise timing, tiny payload, and the analysis could
run at any hop we like. Rejected for what point 5 and
[ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md) both exist to prevent: a second
tuned detector, in a second language, drifting from the one the four existing visualizers are
written against. It also would not help — the 80 ms is the handoff, not the analysis, so a natively
detected onset arrives just as late.

**Ship only the `lyrics` and `music-video` visualizers, which need metadata but no spectrum.** It
would need point 7 and not points 3–6, which is most of the work avoided. Rejected because the two
that need no FFT are the two least worth embedding a web view for, and the channel gets built the
first time anyone wants `reactive-terrain` — which at 1,311 lines is the default and the largest.

**Leave the visualizer web-only, as ADR-0001 point 5 said.** The case for it, which this ADR
previously made in its own voice: the visualizer plays nothing, finds nothing and manages nothing,
and the web app is a browser tab away. **That framing is wrong and is corrected here rather than
left standing** — it measures the visualizer as a playback feature, and it is not one. It is the
product's only extension point, the one thing a stranger can contribute without touching the
backend, the LLM or the audio engine; and it is the part that makes the app enjoyable rather than
merely useful, which is not nothing in a music player. Rejected because leaving it web-only leaves
that extension point pointed at the surface ADR-0013 reduced to management, so the plugin API stays
what it is today — 575 lines of documentation, a template, and an empty `community/` directory.
Also because the phone and the Mac are now where the listening happens, the DSP is already running
and being discarded on every track, and "possibly permanently" was written as a scope boundary for
v1 rather than as a finding.

## Consequences

- **Positive:** The four existing visualizers work on both Apple clients with no changes to any of
  them, because points 4 and 5 keep `getAudioData()` and its shape intact.
- **Positive, and the reason to do this at all:** the plugin API stops pointing at a surface
  nobody listens on. A Three.js visualizer written against `getAudioData()` would run on the Mac and
  the phone with no Swift and no change by its author, which is the first time contributing one has
  been worth an evening. Whether anyone takes it up is not something this ADR can promise — but
  today the offer is one the product cannot keep, and after this it is one it can.
- **Positive:** An FFT that ran ten times a second and was discarded is already being used, by the
  native meter #84 added; this puts the same frames to a second purpose rather than starting one.
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
- **Tradeoff, and much smaller than it first read:** **ten** `evaluateJavaScript` calls a second is
  real main-thread work whenever the visualizer is on screen, on top of the render loop inside the
  web view. Not sixty, and not the ~57 an earlier revision of this ADR assumed — see the Context
  note on the 100 ms tap floor. Nor is it a new hop: the app already performs a main-queue dispatch
  per frame at that rate, so the added cost is the `evaluateJavaScript` call and the serialisation. ADR-0041's finding — a **4 Hz**
  publisher saturating the main thread — reads as an argument against this ADR and on inspection is
  not one: that cost was unbounded SwiftUI invalidation, where this is a bounded call with a fixed
  payload. The yardstick worth holding it against is `MusicMapView`'s 0.83 ms/frame of dictionary
  building, which was measured and then removed as too expensive for a frame budget.
- **Tradeoff, found 2026-08-07:** the visualizer document needs more than a spectrum.
  `FullPlayer.tsx:276-283` hands `AudioVisualizer` a track, an artwork URL, lyrics, `isPlaying`,
  `currentTime` and `duration` — all from a player store the embedded document will not have. Point
  7 carries identity and point 8 sends the page to fetch its own lyrics, so the gap is the *clock*:
  `currentTime` advances continuously and the lyrics visualizer is built on it. Whether that rides
  the analysis channel or is derived page-side from a start time is unresolved here and is the first
  thing implementation will hit. The measured 10 Hz makes the second more likely: a clock that
  updates ten times a second is visibly steppy, and lyrics timing is exactly where that shows.
- **Tradeoff, measured 2026-08-08:** **beat-locked visuals are ~80 ms late on the native clients**
  and tight in a browser, because the tap hands its buffer over 81.7 ms after that audio played.
  Past the ~45 ms at which desync is noticeable. Point 15 is the answer and it is not a free one:
  it asks the page for a tempo grid it does not fetch today, and it is the only place this ADR
  changes a visualizer rather than carrying it unmodified.
- **Positive:** the detector gets a better input than it has in the browser in one respect — a
  23 ms hop is fixed and known, where `requestAnimationFrame` under Web Audio delivers whatever the
  frame rate happened to be, and drops frames under load.
- **Follow-up:** `beat_times` is computed on every analysed track and discarded (`analysis.py:351`,
  never written to `features`). Point 15 is the first thing that would want it. Deciding whether to
  persist it is a backend question and is not settled here.
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
