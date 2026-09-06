# ADR-0110: A Level Is a Loudness, and a Session Answers the System

Status: proposed

Date: 2026-09-06

Amends point 5 of
[ADR-0109](ADR-0109-ambient-is-an-instrument-the-app-plays.md), whose principle stands and whose
implementation of it did not go far enough. Re-affirms point 9 rather than reversing it. Extends
[ADR-0107](ADR-0107-ambient-is-a-destination-that-plays.md) point 5, which gave the process's one
now-playing entry to the primary engine.

Implementation:
- **Written after the code, which is the fourth time in this feature's life.** ADR-0109's own
  Implementation note records the third and calls doing it again "worth saying plainly rather than
  quietly". Saying it plainly a fourth time: every point below was built and measured on
  `familiar-apple` branch `worktree-ambient-synthesiser` before this file existed. The pattern is
  not an accident of scheduling — it is what happens when the only way to find out whether a
  decision was right is to listen to it, and it is the honest cost of a feature whose defects are
  inaudible to its test suite.
- 1,358 Swift tests pass. Both targets build. **Nobody has heard an hour of it**, and **no
  `AVAudioSession` path in point 2 has executed anywhere at all** — the tests drive a fake on
  macOS, and a TestFlight build will be the first time that code runs.

## Context

ADR-0109 rebuilt the synth and said what it was for. Four rounds of listening since have found that
two of its claims were incomplete rather than wrong, and both in the same direction: they named the
right principle and stopped one step short of it.

**The melody had stopped being a melody**, and that was a repair rather than a decision, so it is
not a point below — but it is why the listening happened. One commit had replaced a deterministic
motif with the composer of ADR-0109 point 2, and `fill` stretched every phrase to span 85% of the
intermission *whatever its note count*: twelve slots across twenty-seven seconds, sounding notes
about four apart. Past roughly a second and a half between onsets the ear stops grouping notes into
a line. The notes were fine; the tempo was an outcome of the clock.

Fixing that exposed the two things that are decisions.

## Decision

### 1. A level is matched on loudness, and RMS is not loudness

ADR-0109 point 5 says "loudness is what a listener compares, so loudness is what a level must be set
on", and then measures RMS. **The principle is right and RMS is energy.** The ear is far more
sensitive between 2 and 5 kHz than at the extremes, and spread spectral content recruits more of the
basilar membrane than a couple of partials do, so two signals of identical RMS are routinely not
equally loud.

Levels are therefore matched on the **K-weighting of ITU-R BS.1770** — the basis of LUFS, and what
every broadcaster levels against. `KWeighting` carries the standard's analog parameters and designs
its two biquads at the rate it is handed, because the graph renders at 44.1 kHz and the standard
tabulates 48; pasting the table would leave both corners about 9% high.

**What the weighting found was not what the listening report said.** The complaint was that the
cathedral organ was much too loud. Under RMS it measured *below* target. K-weighted, the outlier was
`keys`, at **0.0142 against everything else's 0.041 to 0.047** — nearly three times quieter than the
shelf it was supposedly matched to, because a `cutoffMultiplier` of 2 over a string damped at 0.998
puts almost all of its output below where the ear is listening. An organ intermission following a
keys intermission was the loud one. **Neither instrument was individually wrong; the spread was**,
and the organ sat at the top of it. All sixteen registrations now land at 0.030 ± 0.0003.

Three things follow that are worth stating as rules, in the shape point 5 states its own:

- **A measurement that is nearly right is worse than an obviously wrong one**, because it passes.
  Peak was visibly the wrong quantity and lasted one round; RMS was plausible and survived three,
  reporting a 2.9× loudness spread as balanced.
- **Pin a standard against its published values, not against itself.** The first implementation of
  the weighting used the audio EQ cookbook's shelf and high-pass, which are wrong here by about 4%
  on every coefficient. It produced entirely plausible numbers and failed the standard's table on
  the first run.
- **Derive gains after the voice count, not before.** With fewer melody slots a Karplus–Strong
  string is re-excited while still ringing, so `keys` measured 0.0300 at twelve slots and 0.0242 at
  twenty. Calibration depends on polyphony, which is not obvious and cost a round.

A consequence accepted rather than fixed: matching `keys` by gain alone leaves it carrying about
four times the RMS energy of anything else, nearly all of it low. Opening its filter fivefold
recovers 20% and changes what the instrument is, because the energy is in the fundamental rather
than above the corner. It is left as it is, and the thing that would change the answer is a small
speaker, which rolls off exactly where this voice lives.

### 2. A session answers whatever owns the audio, and on iOS something does

ADR-0107 built ambient on a second `AVAudioEngine` and noted that macOS has no `AVAudioSession`.
That is true and it is why the feature has always worked there: two engines simply both open the
default output. It is also why the client half has been Mac-only, with the reason recorded in three
places and never acted on.

**A session is the one thing this app expects to play for an hour**, which makes it the one thing
most exposed to a system that can take the audio away: a call, an alarm, a headphone lead, the media
server restarting. `AmbientSynthEngine` is a bare `AVAudioEngine` and heard about none of it.

So the session becomes a collaborator with five meanings rather than a set of notifications —
`interrupted`, `resumable`, `ended`, `outputDeviceLost`, `servicesReset` — because the interruption
notification hides the question that actually matters, *may we start again*, inside an options
bitfield. A session answers them with the transport it already has: an interruption and a listener
pressing pause are the same event.

**A media-services reset ends the session rather than rebuilding it.** A reset takes the synth's
graph, its sampler nodes and the SoundFonts loaded into them, and `configure()` is written to build
that graph once, on a fresh engine, with every bank loaded *before* `engine.start()` — the ordering
that ADR-0109's `AVAudioUnitSampler` constraint makes load-bearing. Re-running it blind on a dead
engine is the least examined path in the file, reached only in a moment nobody can reproduce.
Stopping with a reason a listener can read is honest; starting again is one press.

**It goes behind a protocol because `swift test` runs on the host**, so an `#if os(iOS)` branch is
never compiled by the suite. Left as platform-conditional code this would have been the least
exercised part of the feature and the most likely to be wrong. That is a general rule and not a
detail of this file: *platform-conditional behaviour that matters is behaviour that needs an
interface*.

### 3. One transport, and this is a re-affirmation rather than a decision

ADR-0109 point 9 gave the transport to whatever is playing. Bringing ambient to a phone puts that
under real pressure — the phone's own bar, the lock screen, Control Centre and CarPlay are four
surfaces, and a "second transport for a second system" is the intuitive answer.

It stays one, and the reason is reachability rather than tidiness. The moments a listener needs the
control are the moments they are not looking at the app: a call, a car, a locked phone. Every one of
those routes through `FamiliarPlayer`, and none of them can be handed a second transport that lives
inside one pane. A control that is inert because it has nothing to act on is honest; a control that
is absent when it is needed is not.

The corollary is that a surface which does *not* know about sessions will lie about one rather than
merely omit them. The phone's `CompactNowPlayingBar` showed a paused queue's track beside a Play
glyph while a drone sounded, and its buttons worked the whole time — only the labels were wrong,
which is worse than a dead control, because a dead control tells you something.

## Alternatives Considered

**Give ambient its own transport and grey out the app's.** Genuinely considered, and it is what
ADR-0107 point 7 originally did. Rejected for the reason point 9 rejected it, which the phone makes
sharper rather than softer: a transport that only exists inside one pane cannot be reached from a
lock screen, a car or a headphone remote, which is where an hour-long session is actually
controlled.

**Turn the organ down.** The reported complaint, and it would have worked, for that instrument, on
that phrase, until the next dense timbre was added. It would also have left `keys` three times
quiet, which is what was actually wrong and what nobody reported because a quiet instrument does not
generate a complaint.

**Rebuild the graph after a media-services reset.** Rejected above. Worth restating as an
alternative because it is the more ambitious answer and would be right for a foreground music
player, where silence is the whole failure; for a generative layer, an explained stop costs a press.

**Write this ADR after the phone testing.** It would have recorded what was true rather than what
was intended, which is the better order. Rejected because the two decisions above are independent of
what a phone measures — the weighting is right or wrong on its own terms, and the session contract
does not change with a battery figure. The device results belong in Consequences, and they are not
in yet.

## Consequences

- **The calibration table is now a derived artefact and must be re-derived, not adjusted.** Sixteen
  registrations, four synthesised gains, and a documented order: voice count, then material, then
  gains. `AmbientInstrumentBalanceTests` prints the table under `MEASURE_PHRASES`.
- **Ambient mode is ready for iOS behind everything but a screen**, and the screen is deliberately
  not in this decision. What is missing is a list row and a view; what is present is the audio
  session, interruptions, route changes, media-services reset, the lock-screen entry and a phone
  transport that no longer misreports.
- **A TestFlight-reachable way to start a session exists and is scaffolding.** It is gated on the
  receipt rather than a build flag — App Store builds carry a `receipt`, TestFlight a
  `sandboxReceipt` — because a gate you have to remember to switch off before an archive is a gate
  that eventually ships. It comes out with the screen.
- **The default harmony moved from 0.25 to 0.6 and fifths now arrive from 0.25 rather than 0.5.** At
  the old default a listener heard a dyad on one note in four and never a triad at all, so the
  chords the engine had voices for were unreachable from the pane. Melody voices went twelve to
  twenty to carry it.
- **Render cost has still not been measured since the bed grew**, which ADR-0109 also recorded, and
  is now more pressing: the phone is a different budget and a session is by nature long-running.
  This is the measurement that could say the iOS screen is not worth building.

## Follow-up

- **An hour of listening, on a phone, in TestFlight.** Whether the organ now sits right, whether 0.6
  harmony is the right amount, and whether `keys` survives a speaker that rolls off at 500 Hz.
- **CPU, memory and battery over that hour**, before the iOS screen rather than after it.
- **The iOS Ambient screen**, and then CarPlay, which wants the phone screen to exist first.
- `FILTER_PRESETS["instrumental"]` is still inert server-side and ambient still plays whatever the
  ranker hands it, including speech. ADR-0109 named this the largest outstanding defect in the
  feature and it remains untouched, in this repo rather than the client's.
