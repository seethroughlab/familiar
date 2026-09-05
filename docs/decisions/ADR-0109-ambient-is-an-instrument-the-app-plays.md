# ADR-0109: Ambient Is an Instrument the App Plays

Status: accepted

Date: 2026-09-04

Supersedes points 7, 10 and 12 of
[ADR-0107](ADR-0107-ambient-is-a-destination-that-plays.md). Extends
[ADR-0108](ADR-0108-ambient-composes-its-pool-rather-than-retrieving-it.md), whose Follow-up says
correcting ADR-0107 point 10 "needs its own ADR, since it is a claim about the client's aesthetic
rather than about ranking". This is that ADR, and it turned out to be about three things rather
than one.

Implementation:
- **Written after the code, which inverts the intended order and is the third time in this
  feature's life.** ADR-0108's Implementation note records the same failure and calls it out; doing
  it again a day later is worth saying plainly rather than quietly. Every point below was built and
  measured on `familiar-apple` branch `worktree-ambient-synthesiser` before this file existed.
  Reviewed and accepted 2026-09-05, on `familiar-apple#170`.
- 1,296 Swift tests pass. Both targets build. **Nobody has heard an hour of it**, which ADR-0107's
  Consequences already name as this feature's permanent condition.

## Context

ADR-0107 built the client half of ambient mode and got the architecture right: a second
`NativeAudioEngine`, decisions in `FamiliarKit`, a sidebar destination. What it got wrong is
everything about *what the synth is*, and it said so itself — point 10's "the aesthetic is preserved
exactly… nothing changes the synth's mix at runtime" was written, in its own words, "from reading
the March code".

Four rounds of listening have now contradicted it, and each was recorded only in a commit message:

1. Snippet volume became a slider, because 0.15 was inaudible on real speakers (`140a050a`).
2. The drone gained a swell, because it had **no modulation of any kind** (`f0eca36`).
3. ADR-0108 point 2 recorded both as making point 10 false, and changed nothing.
4. This work, which is the largest and is the reason the point cannot simply be amended.

The synth ADR-0107 ported was three oscillators. Two were sines — which have no harmonics at all —
and one a triangle whose partials fall off as 1/n². The melody was one bare sine with no envelope,
and `pickNotes` walked a fixed preference order, so **a given key produced the same notes forever**.
Of five listener controls, one reached the synth.

That is not an aesthetic to preserve. It is a sketch, and the ADR that froze it froze the wrong
thing.

## Decision

### The synth

1. **The drone has a mode.** `droneTarget` returned a root and a fifth, and a fifth is *modeless* —
   it states a pitch and omits the degree that decides major from minor. A third voice sounds the
   mode's characteristic degree an octave up (`AmbientMode.colourDegree`), and moving that degree
   between modes of the same parity is what "modulation" means here. The parity line is never
   crossed: a track arrives in a key the ranker chose partly *because* of that key, and turning its
   bed from minor to major underneath it is the bed disagreeing with the music.

2. **The melody composes rather than recites.** Six composer styles as distributions, a four-note
   motif transformed by retrograde / inversion / transposition, laid out AABA or ABAB, with a
   velocity arc, harmony thirds and triads, and a root-motion bass. Ported from `longwave`'s
   `core/composition/`, using its exact CDFs so the tuning is inherited rather than re-guessed.

3. **The bed is six voices in stereo, not three in mono.** Organ registration (octave, twelfth,
   fifteenth at falling levels), unison detune per voice, per-voice pan with φ-separated drift, and
   a pink/brown noise layer modulated in antiphase so the spectrum rocks rather than the level
   moving. **The registration is what makes the filter audible at all**: measured, the whole range
   of the brightness control moved the output by 0.5% against the old bed, because there was nothing
   above 700 Hz to remove.

4. **A Director walks the bed across the session.** Dwell, waypoint, smoothstep, dwell — longwave's
   state machine — over a hand-curated table of ranges deliberately narrower than the legal ones. It
   **multiplies** each track's own texture rather than replacing it, so a bright track's bed stays
   brighter than a dark one's however far the walk has gone.

5. **Levels are measured on a phrase, never chosen and never on one note.** Every layer is rendered
   offline through the real graph and pinned by `AmbientInstrumentBalanceTests`. This is not
   diligence for its own sake: uncalibrated, the eight instruments measured **68× apart** and the
   melody peaked at 0.014 against a drone at 0.384 — inaudible — while every correctness test
   passed. A balance problem is invisible to assertions about correctness.

   **"On a phrase" is the half this point originally got wrong**, and it is worth more than the
   rest of the point. The first calibration levelled a single note at A4 to a peak of 0.20, which
   passed everywhere and left the sampled instruments at roughly a *third* of the synthesised ones
   in loudness — 0.0167 RMS for the cathedral organ against 0.0596 for the bell. The cause is
   structural: a synthesised voice ends in `dx / (1 + |dx|)` and a sampler is an `AVAudioUnit` that
   never passes through it, so four notes sum quite differently in the two paths. One note cannot
   show that, and neither can peak — loudness is what a listener compares, so loudness is what a
   level must be set on. The same error one layer down had the guitar's four registrations levelled
   note-by-note and still 0.035 to 0.060 apart across a phrase, because a registration's decay
   decides how much of it is still sounding when the next note arrives.

   Two things follow that are worth stating as rules rather than as fixes. A test whose input the
   system cannot produce measures nothing: an attempt to bound headroom by striking four notes at
   once at velocity 0.8 and holding them six seconds reported every sampled instrument clipping at
   1.35 to 2.38, and would have halved them all — on real phrases they peak at 0.138 to 0.294. And
   a suite that covers half the cases hides the other half: the level test covered only the four
   synthesised instruments, which is most of why an audible imbalance survived it.

   An `AUPeakLimiter` closes the last gap, because sampled instruments still peak around 0.5 where
   synthesised ones peak around 0.25 at equal loudness. It is a net, not a mix: it engages near
   full scale, and every calibration assertion passes unchanged with it in the graph.

### The listener

6. **Ten controls and six presets, not forty parameters.** Three of the controls are macros —
   Character, Motion, Space — each moving several synth values that only make sense together, for
   the reason `treatment(forLiveliness:)` already gives about distance. A preset is a full
   `AmbientSound` rather than a sparse overlay: with ten controls and a defaulted initialiser, a
   preset already names only what it changes.

7. **There is no randomise button**, as there is none in longwave. Random parameters sound bad;
   a random walk inside a tuned region sounds intentional, and that walk is point 4.

8. **A control that cannot be heard yet says so.** Space, Level, Character and Motion reach the bed
   at once; a mode, an instrument, a composer or a harmony can only apply when the next phrase is
   written, which may be a minute away. `AmbientController.pendingChanges` names which, and the
   surface marks them. Without this the two are indistinguishable from a control that is broken —
   which is how it read.

### The app

9. **The player hands its transport over rather than refusing it. This supersedes ADR-0107
   point 7.** That point had `FamiliarPlayer` refuse to start while a session ran, which made
   ambient a separate application: the space bar did nothing and the bar's buttons were greyed.
   Worse, `play(_:startingAt:)` never consulted the claim at all, so **a track started from the
   library sounded on top of the drone**. `FamiliarPlayer.AudioClaimant` replaces the two closures:
   a press reaches whatever is actually playing, skipping skips windows, and starting a track ends
   the session with its release. `FamiliarKit` still never learns what an ambient session is.

10. **Point 10 of ADR-0107 is withdrawn, not amended.** "Nothing changes the synth's mix at runtime"
    cannot be repaired by exceptions — the mix is now the listener's, the track's and the Director's,
    all at once. What survives of it is the intent: a session should sound like one continuous piece
    rather than a sequence of clips, and every decision above is measured against that.

11. **ADR-0107 point 12's real-time rules are kept exactly, and extended.** Render blocks are formed
    in a `nonisolated` context, capture pointers by value, and never allocate or lock. The voice
    array is flat POD behind one pointer. Karplus–Strong made the audio thread a *writer* for the
    first time, so note-on became a request the render thread fulfils — which makes the invariant
    stronger, not weaker: the writer sets parameters, never state.

## Alternatives Considered

**Amend ADR-0107 point 10 rather than supersede it.** Rejected: four contradictions in four days is
not a point needing a footnote, and the ADR's own justification for it ("the deleted
`AmbientSynthBridge` declared `updateMix` and never called it") argues against a synth nobody had
heard, not for the one that shipped.

**Use `AVAudioUnitSampler` for everything, and delete the hand-written voices.** Genuinely
considered, and the sampled instruments in point 3 are the half of it that was taken. Rejected as a
whole because the drone cannot use it: it glides continuously between arbitrary keys and carries
per-voice swell LFOs at hundredths of a hertz, and a sampler plays notes. Keeping both is two
architectures, which is the cost, and the recorded choir and organ are worth it.

**Leave the instrument as "one, or all of them".** Rejected after the code was written and heard,
which is why it is recorded here rather than in point 6: neither half of that choice is what a sound
usually wants. Cathedral had to take the plucked string and the FM bell along with its organs, or
give up variety and be one timbre for an hour. `instruments` is a set; one element is the old pinned
behaviour and every element is the old cycling behaviour, so it subsumes both rather than sitting
beside them.

**Let the listener choose which SoundFont preset each instrument uses.** Rejected on measurement,
and this is the sharpest constraint in the work. `AVAudioUnitSampler` **segfaults** rather than
erroring: loading a bank twice into one node crashes, attaching and loading while the engine runs
crashes, and loading a randomly-drawn four-of-twenty-nine combination crashed on **four of eight**
session seeds. One fixed set, loaded before `engine.start()`, survived every run. A listener-chosen
preset would be a listener-chosen crash.

**Schedule notes sample-accurately in the audio callback**, as longwave does. Rejected: longwave
needs it for a kick at 60 BPM, there is no kick on a grid here, the ADSR runs on the audio thread so
attacks are sample-exact regardless, and a lock-free ring would move every musical decision somewhere
no test can reach — against ADR-0107 point 14.

## Consequences

- **Positive.** The complaint that started this — "the drone gets a little too droney" — had three
  separate causes, and naming them is most of the value here: no spectrum, no modulation below the
  per-track level, and a melody that repeated exactly. Each is now measured rather than asserted.
- **Positive.** Point 9 makes ambient behave like the rest of the app. The space bar, the media keys
  and the transport buttons all reach it, and playing a track ends it instead of doubling it.
- **Tradeoff, weighed and taken.** 45 MB of SoundFonts in the repository, permanent in history.
  Both alternatives — LFS, and a post-install download — were put before the decision was made and
  both were declined as not worth the machinery at this size. This is settled rather than deferred,
  and the reason it is written down is that a repository's size is the kind of thing re-argued
  yearly by people who were not in the room. The guitar font carries 64 presets where 16 are
  curated and one is used, so the figure could fall a long way if it ever needs to.
- **Checked, and clear.** All four SoundFonts permit commercial distribution: the choir, the pipe
  organ and the drums are public domain, and the guitar is CC BY. Each was matched to its listing
  by **filename and byte size** rather than by a similar title, which was not pedantry — these
  fonts circulate in many edited versions under different terms, and the choir has a later
  revision (`KBH-Real-Choir-V2.5.sf2`) distributed as CC BY-NC-SA. Bundled is not that file, and
  upgrading it without re-checking would make the app non-distributable. See
  `Sources/FamiliarKit/Resources/SoundFonts/CREDITS.md`, which ships inside the bundle because an
  attribution requirement that lives only in a repository is not being met.
- **Follow-up, and the only obligation this feature creates.** The guitar is CC BY, so *Studio
  FG460s II Pro Guitar Pack* by Mitrofanis George Gemitros has to be credited somewhere a user can
  see — an acknowledgements screen or the store description. There is no such screen yet.
- **Residual risk, small and not zero.** The pipe organ is by its own metadata a merge, crediting
  five sources including one reed whose origin the author cannot name because their computer was
  wiped. A public-domain declaration by whoever assembled a merge does not clear the rights in what
  was merged. Recorded rather than resolved, because it cannot be resolved from here.
- **Tradeoff.** Sampled presets are fixed per build rather than per session or per phrase, which is
  two reductions from what was wanted, forced entirely by the crashes above. The ceiling appears to
  be about loading while running rather than node count — five nodes load fine before start — so it
  may be liftable.
- **Correction, found by listening after this record was drafted.** Two controls were coupled to
  settings they do not name. The intermission was a flat 25–40 s whatever the window length, so the
  Window control changed the *ratio* of music to bed rather than the pace — a fifth music at the
  short setting, nearly half at the long one. And the percussion roll fired once per seam, so the
  same "how often" bought roughly 40% fewer hits per hour at one end of the Window control than the
  other. Silence is now proportional and the roll is a rate per unit time. Both are the same defect:
  a control whose meaning depended on another control's value, with nothing saying so.
- **Correction.** Point 5 says levels are measured rather than chosen, and it did not go far enough.
  Three defects survived every test in this suite and were found only by a listener: percussion
  routed through the bed's swept lowpass (audible for a kick, deleted for a cymbal, then given 22×
  gain to compensate); `attack` dead on every plucked voice because note-on forced the envelope
  open; and a first attempt at measuring onset that timed the *reverb* rather than the note, and so
  passed against the voice that had just been reported as jarring. Measuring the right quantity is
  the hard half, and none of these were level problems.
- **Tradeoff.** The bed is twelve voices where it was three, and the render path is much larger.
  Measured at **0.55% of one core** in release for the densest texture before the bed rework; it
  should be re-measured now.
- **Follow-up.** `FILTER_PRESETS["instrumental"]` is still inert (ADR-0108 Context 5), and a session
  observed in real use played standup comedy and a radio play. Ambient plays whatever the ranker
  hands it, and nothing in the ranker can currently tell speech from music. This is the largest
  outstanding defect in the feature and it is server-side.
- **Follow-up.** The phone, still, per ADR-0107 point 3.
- **Follow-up.** This record was written after its implementation. That is now three ADRs in a row
  for this feature, and the pattern is the finding: work that is discovered by listening does not
  arrive in an order that suits writing it down first. If that is accepted, the rule should change;
  if it is not, something has to.
