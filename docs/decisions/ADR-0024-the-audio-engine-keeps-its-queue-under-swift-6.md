# ADR-0024: The Audio Engine Keeps Its Queue Under Swift 6

Status: proposed

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
of the five and is the most dangerous; see the first follow-up. **Four real fixes across fifty
files.** The migration is one file.

**What that one file is.** `NativeAudioEngine.swift` is 1,967 lines, and it does not express
isolation in the type system — it expresses it with queue discipline. A plain `class`, not an actor
and not `@MainActor`. A serial `stateQueue` guards engine state. Nineteen `DispatchQueue.main` hops
bounce completions back. One `installTap` closure runs on the **audio render thread**, which is
real-time: it may not allocate, may not lock, and may not await. One `static var
waveshaperRegistered` records a process-wide AudioUnit registration.

The 74 warnings are that design seen through Swift 6's eyes: 36 non-`Sendable` captures in
`@Sendable` closures, 25 "sending risks causing data races", 6 captures in isolated closures, 3
implicit-capture conformances, the static, and one captured `var`. **They are not 74 bugs.** They
are one design — manual isolation — reported once per site.

**The trap this ADR exists to avoid.** The obvious way to silence 74 warnings is to annotate the
engine `@MainActor`. It compiles. It is also wrong: the render tap would inherit main-actor
isolation it cannot honour, and every `AVAudioEngine` call — `prepare`, `start`, `scheduleFile` —
would be forced onto the main thread, where an audio graph rebuild during a crossfade competes with
drawing. ADR-0016's map and ADR-0021's tables both put work where the data is; this is the same rule
about threads.

## Decision

1. **The audio engine keeps manual, queue-based isolation.** It is not made an actor and not made
   `@MainActor`. `stateQueue` remains the mechanism that serialises engine state; the render tap
   remains free of any isolation the audio thread cannot honour.

2. **That isolation is declared rather than implied.** `NativeAudioEngine` becomes
   `@unchecked Sendable`, and the static becomes `nonisolated(unsafe)`. Both are assertions the
   compiler cannot check, so each carries a comment naming the discipline that makes it true and the
   queue that enforces it. An unexplained `@unchecked` is a silenced warning; an explained one is a
   documented invariant.

3. **Swift 6 is adopted per target, package first, app second.** ADR-0008's follow-up already
   requires this — the app target must not adopt ahead of `FamiliarKit`, or the two halves of one
   build sit in different concurrency models. `swiftLanguageModes: [.v5]` in `Package.swift` and
   `SWIFT_VERSION = 5.0` in the six Xcode build configurations flip in that order, not together.

4. **The four real fixes land before the flip, under Swift 5.** They are correct in either mode and
   they are not the interesting part; landing them separately keeps the engine's diff readable
   rather than buried among unrelated annotations.

5. **`-strict-concurrency=complete` becomes the gate before the language mode does.** The warning
   surface is what the migration is measured against, so it is turned on and driven to zero while
   still a warning. Flipping the mode first turns a measurable list into a build that does not
   compile, which is the same list with no way to work through it incrementally.

6. **The render tap's real-time constraints are stated in code, not inferred.** The `installTap`
   closure gets a comment saying what it may not do — allocate, lock, await — because Swift 6 will
   not enforce that and the next person to touch it will otherwise reach for `Task { }`.

## Alternatives Considered

**Make the engine an `actor`.** The model Swift 6 is built around, and it would delete the queue.
Rejected because `AVAudioEngine` is a synchronous C-backed API and the render tap cannot `await`:
every call site would need `await`, the tap would need `nonisolated` and lose actor protection
anyway, and the result is the same manual discipline with async ceremony on top. The queue is not a
workaround for missing actors; it is the correct tool for a real-time graph.

**Annotate the engine `@MainActor`.** The one-line change that silences the file. Rejected for the
reason in the Context: it forces the audio graph onto the main thread and mis-states the render
tap's isolation. It would compile, run, and be wrong in a way that shows up as audio glitches under
UI load — the hardest kind of defect to attribute.

**Split the engine into its own SwiftPM target that stays `.v5`.** Genuinely appealing: the other 42
files adopt Swift 6 immediately, and the engine is quarantined behind a module boundary. `package`
visibility means it need not become `public`. Rejected because the boundary would exist only to
carry a compiler setting — it draws a permanent architectural line to express a temporary state, and
the thing being quarantined is one file that this ADR is about finishing rather than isolating.

**Leave Swift 5 mode indefinitely.** Defensible: the app ships, the engine works, and 74 warnings
nobody sees cost nothing. Rejected because the rest of the codebase is already clean — 42 of 43
package files and 46 of 50 app files — so the cost of adopting is one file's worth of work, and the
benefit is that every *future* file is checked. Deferring is cheap exactly once and gets more
expensive with every file added.

**Adopt Swift 6 in the app target first, since it is nearly clean.** Tempting given four fixes.
Rejected by ADR-0008's follow-up, and the reason still holds: `FamiliarKit` types crossing into a
Swift 6 app target would be checked under rules the module itself does not follow, producing
diagnostics at the call site for a cause in the library.

## Consequences

- **Positive:** every file written after the flip is concurrency-checked, which is the whole point.
  The codebase is already 88 of 93 files clean, so this buys checking for the future rather than
  paying off the past.
- **Positive:** the engine's isolation stops being folklore. The discipline that makes it correct is
  currently readable only by tracing nineteen `DispatchQueue.main` hops; point 2 makes it a
  declaration with a reason attached.
- **Tradeoff:** `@unchecked Sendable` is an assertion, not a proof. The compiler will stop asking
  about the engine, which means a future change that breaks the queue discipline gets no warning.
  Point 2's comments are the only guard, and comments are not enforcement.
- **Tradeoff:** two concurrency models coexist for the duration of point 3's staging. Bounded, and
  the alternative is a single change touching both halves at once.
- **Follow-up:** whether `FamiliarPlayer` — the engine's public wrapper, already `@MainActor`-shaped
  by `ObservableObject` — should own the boundary explicitly rather than inheriting it. Not needed
  for the flip, and worth its own look once the engine is annotated.
- **Follow-up, and the one to do first:** the `WKNavigationDelegate` near-match in
  `EmbeddedDiscoverView` is **a regression this flip could cause**, not a pre-existing bug. Today the
  method matches and runs. Under `-strict-concurrency=complete` the compiler reports the candidate as
  `(WKWebView, WKNavigationAction, @escaping (WKNavigationActionPolicy) -> Void) -> ()` against a
  requirement whose handler is now `@MainActor @Sendable` — a *near* match, which means the
  conformance may not be satisfied and the `@objc` entry point may not be registered. That method is
  what keeps an external link from navigating the embed itself to Bandcamp with no way back; it is
  the fix `familiar-apple` #52 shipped. Silencing it by moving the method to an extension, as the
  compiler's own note suggests, would hide exactly the thing worth knowing. Match the signature
  instead, and verify a purchase link still opens in the browser before the mode flips.
