# ADR-0024: The Audio Engine's Queue Becomes Its Executor

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
| the app target (`App/`) | 50 | 5 |

`LibraryView` has **two**, both the same thing: a synchronous nonisolated context calling two
`@MainActor` statics. The other three are one `Any` that is not `Sendable` (`SmartPlaylistDraft`),
one static `[PartialKeyPath<TrackRowValue>: String]` (`TrackTable`, added by ADR-0021), and one
`WKNavigationDelegate` near-match in `EmbeddedDiscoverView` — which looks like the least interesting
of the five and is the most dangerous; see point 1. **Four real fixes across fifty files.** The
migration is one file.

**What that one file is.** `NativeAudioEngine.swift` is 1,967 lines, and it does not express
isolation in the type system — it expresses it with queue discipline. A plain `class`, not an actor
and not `@MainActor`. A serial `stateQueue` guards engine state. Nineteen `DispatchQueue.main` hops
bounce completions back. One `installTap` closure runs on the **audio render thread** with a
256-frame buffer — roughly 172 calls a second at 44.1kHz, each with a hard deadline: it may not
allocate, may not lock, and may not await. One `static var waveshaperRegistered` records a
process-wide AudioUnit registration.

The 74 warnings are that design seen through Swift 6's eyes: 36 non-`Sendable` captures in
`@Sendable` closures, 25 "sending risks causing data races", 6 captures in isolated closures, 3
implicit-capture conformances, the static, and one captured `var`. **They are not 74 bugs.** They
are one design — manual isolation — reported once per site.

**The premise ADR-0008 deferred on has also expired, and that is what makes this ADR different from
the one it would have been a month ago.** The right tool for "I have a serial queue and I want the
compiler to understand it" is a custom actor executor: an `actor` whose `unownedExecutor` *is* the
existing `DispatchSerialQueue`, so isolation becomes compiler-checked while the runtime behaviour
stays exactly what ships today — the same queue, the same serialisation, no added hops.
`DispatchSerialQueue`'s conformance to `SerialExecutor` is **macOS 14 / iOS 17**. When ADR-0008
deferred this, the floors were macOS 13 and iOS 15, so the tool did not exist and a blanket
`@unchecked Sendable` would have been the only answer available. ADR-0021 raised macOS to 14.4 and
ADR-0023 raised iOS to 17 for reasons of their own; a side effect is that the correct answer is now
in reach. Verified 2026-08-04: the pattern type-checks under `-swift-version 6` at
`arm64-apple-macos14.4` and `arm64-apple-ios17.0`, and fails at `ios15.0` with exactly the
availability errors that would have blocked it.

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

2. **The engine's state becomes an `actor` whose executor is the existing serial queue.** Not a new
   queue and not a new threading model: `stateQueue` becomes the actor's `unownedExecutor`, so every
   isolated member runs exactly where it runs today, in the same order, and the compiler can finally
   see why that is safe. This is the point of the ADR — the isolation stops being a convention held
   in one person's head and becomes a property checked on every future edit.

3. **The real-time path stays outside the actor, `nonisolated`, and says so.** The `installTap`
   closure and the analysis processor take no actor isolation, because there is none an audio thread
   can honour. They get a comment naming the three things they may not do — allocate, lock, await —
   because Swift 6 will not enforce that, and the next person to meet a concurrency warning there
   will otherwise reach for `Task { }`.

4. **`@unchecked Sendable` is an exception with a name, never the strategy.** Where something
   genuinely cannot be expressed — the process-wide AudioUnit registration is the known case — it is
   annotated individually, with a comment stating the invariant and what enforces it. A blanket
   `@unchecked` over 1,967 lines would clear the 74 warnings in an afternoon and opt the file out of
   checking permanently, which is the opposite of what this ADR is for.

5. **`-strict-concurrency=complete` becomes the gate before the language mode does.** The warning
   count is the migration's measure, so it is turned on and driven to zero while still a warning.
   Flipping the mode first turns a workable list into a build that does not compile.

6. **Swift 6 is adopted per target, package first, app second.** ADR-0008's follow-up already
   requires this — the app target must not adopt ahead of `FamiliarKit`, or the two halves of one
   build sit in different concurrency models. `swiftLanguageModes: [.v5]` in `Package.swift` and
   `SWIFT_VERSION = 5.0` in the six Xcode build configurations flip in that order.

7. **The engine is staged, and playback is verified by ear between stages.** No stage is "the engine
   migration". The suite does not cover audio output — `swift test` has no speakers — so each stage
   ends with a real listen: play, pause, seek, skip, crossfade, and an effects change while playing.
   A stage that cannot be verified that way is too big.

## Alternatives Considered

**A blanket `@unchecked Sendable` on the engine class.** This was the first proposal in this ADR's
own drafting, and it is the pragmatic answer: two annotations, 74 warnings gone, the file untouched
and still correct. Rejected on the instruction that the long-term answer is wanted and there is no
rush. It trades a permanent opt-out for an afternoon — the compiler stops asking about the one file
most likely to be got wrong, and a later change that breaks the queue discipline gets no warning at
all. Point 4 keeps it available where it is genuinely the only option.

**Make the engine an ordinary `actor`.** The model Swift 6 is built around. Rejected in that form
because a default actor executor is a *different runtime*: work moves to the cooperative thread
pool, so the careful serialisation the engine has today would be replaced by something with the same
shape and different timing. Point 2 keeps the actor and rejects only the default executor.

**Annotate the engine `@MainActor`.** The one-line change that silences the file. Rejected because
it forces the audio graph onto the main thread — a crossfade queued behind a frame of SwiftUI
drawing — and mis-states the render tap's isolation. It compiles, runs, and is wrong in a way that
shows up as glitches under UI load, the hardest kind of defect to attribute.

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
- **Positive:** no runtime change is intended. Point 2's whole purpose is that the queue keeps doing
  what it does and the compiler simply learns about it — which is also what makes point 7's
  listening test a real check rather than a formality.
- **Tradeoff:** **29 call sites in `FamiliarPlayer` gain `await`.** That is the price, and it is an
  honest one: actor isolation is checkable precisely because crossing it is visible. It is one file,
  and `FamiliarPlayer` is the engine's only substantial caller.
- **Tradeoff:** custom executors are a less-travelled corner of Swift. The pattern is small and
  verified at both floors, but its diagnostics are unfamiliar when they go wrong.
- **Tradeoff:** point 7 makes this several PRs over some weeks rather than one change. That is the
  instruction rather than an accident.
- **Follow-up:** whether `FamiliarPlayer` should own the isolation boundary explicitly once the
  engine is an actor, rather than inheriting it from `ObservableObject`. Not needed for the flip.
- **Follow-up:** the off-host `.other` navigation case in `EmbeddedDiscoverView`. The rule is that
  external links open in the browser; the current condition allows any `.other` navigation — which
  covers server redirects and some JavaScript navigation — to stay in the embed. Noticed while
  reading point 1's method, not observed in use.
