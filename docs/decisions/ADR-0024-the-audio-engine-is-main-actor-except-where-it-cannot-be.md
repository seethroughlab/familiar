# ADR-0024: The Audio Engine Is Main-Actor, Except Where It Cannot Be

Status: accepted

Date: 2026-08-04

Extends [ADR-0008](ADR-0008-the-apple-app-shell-is-a-committed-xcode-project.md).

## Context

`Package.swift` has said since the first commit that Swift 6 is deferred, and said why: the audio
engine "arrives exactly as it compiled in the Capacitor app" per ADR-0001 point 2, and Swift 6's
strict concurrency rejects it. It also said what should happen next — *"adopting Swift 6 concurrency
is its own piece of work, and wants its own ADR: the audio render thread has real isolation
requirements that `@MainActor`-by-default would get wrong."* This is that ADR.

**The premise this was queued on is wrong, and measurement is what showed it.** The work was carried
in the backlog as "the actor-isolation warnings in `LibraryView` are its leading edge", which framed
the app as the bulk of the job. It is not. Compiled with `-strict-concurrency=complete` on
2026-08-04:

| target | files | warnings |
|---|---|---|
| `FamiliarKit` — `NativeAudioEngine.swift` | 1 | **74** |
| `FamiliarKit` — everything else | 42 | 1 |
| `FamiliarAPI` | 2 | 2 |
| the app target (`App/`) | 50 | 5 |

*(The `FamiliarAPI` row was missing from this table when the ADR was written: the
first count was taken from an incremental build in which that target was not
recompiled. Corrected while carrying out point 5, which is when a stale figure
would otherwise have been mistaken for finished work.)*

`LibraryView` has **two**, both the same thing: a synchronous nonisolated context calling two
`@MainActor` statics. The other three are one `Any` that is not `Sendable` (`SmartPlaylistDraft`),
one static `[PartialKeyPath<TrackRowValue>: String]` (`TrackTable`, added by ADR-0021), and one
`WKNavigationDelegate` near-match in `EmbeddedDiscoverView` — which looks like the least interesting
of the five and is the most dangerous; see point 1. **Four real fixes across fifty files.** The
migration is one file.

**What that one file is.** `NativeAudioEngine.swift` is 1,967 lines, and it does not express
isolation in the type system. A plain `class`, not an actor and not `@MainActor`. Nineteen
`DispatchQueue.main` hops bounce completions back. One `installTap` closure runs on the **audio
render thread** with a 256-frame buffer — roughly 172 calls a second at 44.1kHz, each with a hard
deadline: it may not allocate, may not lock, and may not await. One `static var
waveshaperRegistered` records a process-wide AudioUnit registration.

The 74 warnings are that design seen through Swift 6's eyes: 36 non-`Sendable` captures in
`@Sendable` closures, 25 "sending risks causing data races", 6 captures in isolated closures, 3
implicit-capture conformances, the static, and one captured `var`. **They are not 74 bugs.** They
are one design reported once per site.

**This ADR's own first version got that design wrong, and the correction is the ADR.** It said "a
serial `stateQueue` guards engine state", and decided on that basis to make the queue an `actor`'s
`unownedExecutor` — compiler-checked isolation, identical runtime, no added hops. Reading all
fifteen uses of `stateQueue` before writing the code showed it guards no engine state at all. It
guards **four `UInt64` cancellation tokens** — `loadOperationToken`, `preloadOperationToken`,
`seekOperationToken`, `crossfadeOperationToken` — and every use either bumps one or compares one to
decide whether a late callback is stale. It is a cancellation lock, not a state lock. Adopting it as
the actor's executor would have moved the whole engine onto a queue that today carries four counter
bumps, which is a real change to where audio work runs and the exact opposite of the promise that
made it attractive.

**What the engine actually does is confine its state to the main thread.** `FamiliarPlayer` is
`@MainActor`, so all 29 call sites into the engine are already on main; and the off-main callbacks —
`URLSession`, `scheduleSegment`, the artwork fetch — hop to main *before* touching state. Verified at
four sites: the download completion at 811 assigns `tempFile` and `audioFile` inside
`DispatchQueue.main.async`, the seek completion at 981 does the same, and `applyFetchedArtwork`
computes off-main and then hops to mutate. The tokens need their own lock precisely *because* they
are the one thing read from off-main, before that hop.

That reverses the first version's other conclusion too. It rejected `@MainActor` because it "would
force the audio graph onto the main thread — a crossfade queued behind a frame of SwiftUI drawing."
**The audio graph is already on the main thread.** `@MainActor` does not move it there; it describes
where it has always been, and makes the compiler enforce a confinement that is currently a habit.

**One place does not follow the habit, and it is a real defect.** Inside the download callback at
line 786, `guard self.currentTrackId == trackId else { return }` reads mutable engine state off-main
and unsynchronised, unlike its siblings that hop first. It predates this work by a long way. It is
exactly the class of bug strict concurrency exists to surface, and the reason point 5 fixes it rather
than annotating around it.

**The risk in this work is not Swift 6.** Swift 6 is a compile-time checker; the binary behaves
identically. The risk is in *how* the 74 warnings get silenced. The reflexive fix for "captured a
non-`Sendable` value in a `@Sendable` closure" is to wrap the body in `Task { }` or
`DispatchQueue.main.async` — and inside a callback firing 172 times a second on a real-time thread,
that is an allocation and a thread hop per buffer. **That is what produces clicks and dropouts, and
it would be introduced by this migration rather than found by it.**

## Decision

1. **The `WKNavigationDelegate` signature is fixed first, and separately.** It is not a concurrency
   cleanup; it is a regression this work could otherwise cause. Under strict checking the compiler
   reports the candidate as `(WKWebView, WKNavigationAction, @escaping (WKNavigationActionPolicy)
   -> Void) -> ()` against a requirement whose handler is now `@MainActor @Sendable` — a *near*
   match, so the conformance may not be satisfied and the `@objc` entry point may not be registered.
   That method is what stops an external link navigating the embedded Discover surface to Bandcamp
   with no way back; it is what `familiar-apple` #52 shipped. **Moving it to an extension, as the
   compiler's own note suggests, silences the signal rather than fixing the cause.** Match the
   signature, and verify a purchase link still opens in the browser.

2. **The engine is declared `@MainActor`, because that is where it already runs.** This is a
   description, not a move: every call site is on main and every off-main callback hops to main
   before touching state. What changes is that the confinement stops being a habit maintained by
   nineteen hand-written hops and becomes a rule the compiler checks on every future edit. The point
   of the ADR is unchanged; only the mechanism is, and the mechanism that matched the code turned out
   to be the simpler one.

3. **The real-time path stays `nonisolated`, and says so.** The `installTap` closure and the analysis
   processor take no isolation, because there is none an audio thread can honour. They get a comment
   naming the three things they may not do — allocate, lock, await — because Swift 6 will not enforce
   that, and the next person to meet a concurrency warning there will otherwise reach for `Task { }`.
   The same applies to the off-main *computation* that precedes a hop: decoding artwork and reading a
   downloaded file are deliberately not on main, and only their results cross over.

4. **`stateQueue` stays, and keeps its four tokens.** It is not replaced by actor isolation, because
   the tokens are the one piece of state read from off-main — that is what they are for. A lock
   around four counters is the right shape for that and `@MainActor` cannot express it: a stale-check
   inside a callback must not have to hop to main to find out it is stale.

5. **The off-main read at line 786 is fixed, not annotated.** `guard self.currentTrackId == trackId`
   reads main-confined state from a `URLSession` callback. It is a real race that predates this work,
   and the migration's job is to remove it — by moving the check after the existing hop, or by giving
   it a token like every other cancellable operation here. Silencing it with `nonisolated(unsafe)`
   would convert a bug the compiler found into a bug the compiler has been told to ignore.

6. **`@unchecked Sendable` and `nonisolated(unsafe)` are exceptions with names, never the strategy.**
   Where something genuinely cannot be expressed — the process-wide AudioUnit registration is the
   known case — it is annotated individually, with a comment stating the invariant and what enforces
   it. A blanket `@unchecked` over 1,967 lines would clear the 74 warnings in an afternoon and opt
   the file out of checking permanently, which is the opposite of what this ADR is for.

7. **`-strict-concurrency=complete` becomes the gate before the language mode does.** The warning
   count is the migration's measure, so it is turned on and driven to zero while still a warning.
   Flipping the mode first turns a workable list into a build that does not compile.

8. **Swift 6 is adopted per target, package first, app second.** ADR-0008's follow-up already
   requires this — the app target must not adopt ahead of `FamiliarKit`, or the two halves of one
   build sit in different concurrency models. `swiftLanguageModes: [.v5]` in `Package.swift` and
   `SWIFT_VERSION = 5.0` in the six Xcode build configurations flip in that order.

9. **The engine is staged, and playback is verified by ear between stages.** No stage is "the engine
   migration". The suite does not cover audio output — `swift test` has no speakers — so each stage
   ends with a real listen: play, pause, seek, skip, crossfade, and an effects change while playing.
   A stage that cannot be verified that way is too big.

## Alternatives Considered

**An `actor` whose executor is the engine's existing serial queue.** This ADR's own first decision,
and on paper the ideal: compiler-checked isolation with the runtime unchanged, using a
`DispatchSerialQueue` as `unownedExecutor` — a pattern the floors now permit and which was verified
to type-check at `macos14.4` and `ios17.0`. Rejected once `stateQueue` was actually read: it guards
four cancellation counters, not engine state, so adopting it as the executor would move 1,967 lines
of audio work onto a queue that today carries four counter bumps. The promise that made it
attractive — same queue, same ordering, no added hops — was true only of the counters. **A correct
mechanism applied to a misread design is still the wrong answer.**

**A blanket `@unchecked Sendable` on the engine class.** The pragmatic answer: two annotations, 74
warnings gone, the file untouched and still correct. Rejected on the instruction that the long-term
answer is wanted and there is no rush. It trades a permanent opt-out for an afternoon — the compiler
stops asking about the one file most likely to be got wrong. Point 6 keeps it available where it is
genuinely the only option.

**Make the engine an ordinary `actor`.** The model Swift 6 is built around. Rejected because a
default actor executor is a *different runtime*: work moves to the cooperative thread pool, so the
main-thread confinement the engine has today would be replaced by something with the same shape and
different timing — and the 29 call sites in `FamiliarPlayer`, all of them already on the main actor,
would each gain an `await` for the privilege.

**Split the engine into its own SwiftPM target that stays `.v5`.** Genuinely appealing: the other 42
files adopt Swift 6 immediately and the engine is quarantined behind a module boundary, with
`package` visibility so nothing need become `public`. Rejected because the boundary would exist only
to carry a compiler setting — a permanent architectural line expressing a temporary state — and
because it would make the deferral comfortable enough to become permanent.

**Leave Swift 5 mode indefinitely.** Defensible: the app ships, the engine works, and 74 warnings
nobody sees cost nothing. Rejected because 88 of 93 files are already clean, so the cost is one
file's worth of careful work and the benefit applies to every file written afterwards. Deferring is
cheap exactly once, and gets dearer with each file added.

## Consequences

- **Positive:** the engine's isolation becomes a checked property rather than folklore. It is
  currently readable only by tracing nineteen `DispatchQueue.main` hops and trusting that every
  future edit traces them too.
- **Positive:** every file written after the flip is concurrency-checked. The codebase is already 88
  of 93 clean, so this buys checking for the future rather than paying off the past.
- **Positive:** no runtime change is intended, and this version has a much better claim to that than
  the first did. `@MainActor` names where the engine already runs; the first version's executor swap
  would have moved it. Point 9's listening test is still a real check rather than a formality.
- **Positive:** **the price the first version quoted is gone.** 29 `await`s in `FamiliarPlayer` were
  the cost of actor isolation; `FamiliarPlayer` is itself `@MainActor`, so main-actor to main-actor
  calls stay synchronous and no call site changes.
- **Positive:** a latent race gets fixed rather than documented — point 5's off-main read at line
  786, which nothing was looking for and no test would have found.
- **Tradeoff:** `@MainActor` makes main-thread confinement a rule rather than a habit, so the first
  person who legitimately wants background work inside the engine has to say so explicitly and
  arrange the hop. That is the intent, and it will read as friction the day it happens.
- **Tradeoff:** the engine keeps two isolation mechanisms — the main actor for state, `stateQueue`
  for the four tokens. Two is more than one, and point 4 exists because collapsing them would make a
  stale-check hop to main to discover it is stale.
- **Tradeoff:** point 9 makes this several PRs rather than one change. That is the instruction rather
  than an accident.
- **Follow-up:** the off-host `.other` navigation case in `EmbeddedDiscoverView`. The rule is that
  external links open in the browser; the current condition allows any `.other` navigation — which
  covers server redirects and some JavaScript navigation — to stay in the embed. Noticed while
  reading point 1's method, not observed in use.
