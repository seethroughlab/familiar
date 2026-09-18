# ADR-0122: The Apple Client Has Explicit Module Boundaries

Status: accepted

Date: 2026-09-17

Extends [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md) and
[ADR-0008](ADR-0008-the-apple-app-shell-is-a-committed-xcode-project.md).

## Context

ADR-0001 chose one native codebase for macOS and iOS, with a shared Swift package holding the
audio engine and decisions worth testing. That boundary worked: `familiar-apple` now has 47,401
lines of Swift under `Sources/` and `App/`, 26,124 lines under its Swift test and UI-test trees,
and one shared implementation across both platforms.

The feature count has outgrown the package boundary without replacing it. `FamiliarKit` now owns
playback, the audio graph, downloads, caches, session persistence, casting, ambient composition and
synthesis, artwork, library routing, visualizers and display text. It exposes 172 public type-level
declarations. The app target holds SwiftUI beside API-backed stores and application wiring, but
`swift test` cannot import that target. Fifteen test files therefore read `App/Shared` or
`NativeAudioEngine.swift` as text — through `Tests/FamiliarKitTests/AppSource.swift` and
`EngineSource.swift` — to assert that wiring and implementation phrases remain present.
Those checks have caught real omissions, but they are not type-checked behavioral tests: a rename
can break one while a behavior change can preserve the string it expects.

The largest files show where ownership has accumulated: `NativeAudioEngine.swift` is 2,744 lines,
`FamiliarPlayer.swift` 2,259, `LibraryView.swift` 2,188 and `AmbientSynthEngine.swift` 2,116 as of
this decision. Length alone is not a defect, and splitting files alone would not create boundaries;
the architectural issue is that unrelated features can import one module and reach one public
surface.

This does not contradict ADR-0001's choice of one codebase. A package may contain several targets,
and both applications can still share all of them. Nor does it reverse ADR-0024: real-time audio
isolation stays where that decision puts it.

## Decision

1. **The Apple client adopts a small directed target graph inside its existing Swift package.** The
   intended responsibilities are:
   - `FamiliarDomain`: value types and pure decisions shared across features, with no UI, storage,
     network or audio-framework dependency.
   - `FamiliarPlayback`: `FamiliarPlayer`, the native audio engine, analysis and platform media
     integration.
   - `FamiliarStorage`: downloads, play cache, library cache and playback-session persistence.
   - `FamiliarAmbient`: ambient policy, composition, session control and synthesis.
   - `FamiliarAppCore`: API-backed repositories, application composition, stores and navigation
     policy that the app uses but SwiftUI does not own.

2. **Dependencies point inward.** Domain depends on nothing in this list. Playback, Storage and
   Ambient may depend on Domain but not on the app or on each other without a protocol owned by the
   consumer. AppCore composes those targets and `FamiliarAPI`. The Xcode app targets depend on
   AppCore and the feature modules to render SwiftUI and bridge platform lifecycle callbacks.
   `FamiliarAPI` remains generated and does not depend on any domain target.

3. **The target graph is a destination, not a flag-day move.** New code goes to its intended owner;
   existing code moves when a feature is changed or when a move removes a source-text test. An
   intermediate `FamiliarKit` facade may re-export or wrap moved APIs while call sites migrate.
   No target is created solely to shorten a file.

4. **Public means cross-target API.** Moving a declaration is not permission to expose every member.
   Each feature publishes the smallest surface AppCore or another feature needs; engine internals
   remain internal to Playback. Package access may be used for package-wide implementation details
   where Swift's access model makes it appropriate.

5. **Compiled tests follow ownership.** Pure decisions and feature behavior are tested in the target
   that owns them. AppCore gets a test target so application wiring, stores and navigation policy
   are exercised as Swift rather than searched as source text. Source-text tests remain only for
   properties the language and a behavior test genuinely cannot express, such as a real-time API
   call's exact callback option.

6. **SwiftUI stays thin but is not forced into a separate package target by this decision.** Shared
   views may remain in the committed Xcode project. Reusable UI becomes a target only when a real
   build or test boundary appears; “views should be small” is a refactoring rule, not an
   architectural dependency.

7. **File splitting follows responsibility after target ownership is known.** `FamiliarPlayer`,
   `NativeAudioEngine`, `LibraryView` and `AmbientSynthEngine` may first be split into same-target
   extensions and collaborators. The split must preserve ADR-0024's isolation and real-time rules;
   it is not an occasion to redesign the audio graph.

## Alternatives Considered

- **Keep one package target and organise it into folders.** This improves browsing but leaves every
  declaration in one dependency domain, every cross-feature reach legal, and app-core behavior
  outside compiled package tests. It addresses navigation without addressing ownership.

- **Create one target per feature or screen.** Rejected as premature fragmentation. Dozens of small
  targets would turn ordinary changes into manifest and dependency work before stable boundaries
  are known. The five targets above express runtime responsibilities, not the current sidebar.

- **Move only `App/Shared` into `FamiliarKit`.** That would make it test-visible but expand the
  existing catch-all module and couple pure policy to SwiftUI. AppCore separates testable
  application behavior without making the domain own the interface.

- **Split the largest files without changing targets.** Worth doing, but not an architectural
  answer. Four shorter files can still share all state and expose the same undifferentiated API.

- **Create a second repository for the package.** Rejected. The modules version and ship together,
  and ADR-0001's shared-client premise benefits from one atomic change across app and package.

## Consequences

- **Positive:** a newcomer can identify an owner and dependency direction before reading a feature's
  implementation.
- **Positive:** app stores and composition become available to ordinary compiled tests.
- **Positive:** unrelated features stop sharing a public namespace by default, reducing accidental
  coupling and making future extraction possible without requiring it now.
- **Tradeoff:** moving code across targets creates access-control work and temporary facade APIs
  without changing product behavior.
- **Tradeoff:** more targets increase package build-graph and manifest complexity.
- **Tradeoff:** migration will temporarily leave old and new organization side by side; the
  architecture map must distinguish destination from current state.
- **Follow-up:** add `familiar-apple/docs/ARCHITECTURE.md` with the target graph, ownership table,
  lifecycle flows and a first-change walkthrough once the first boundary lands.
- **Follow-up:** remove each source-text test only when an equivalent compiled test exists.
- **Follow-up:** `FamiliarAppCore` is the first boundary to land. ADR-0123's composition root and
  ADR-0124's repositories both live there, so neither can start until it exists; the other three
  feature targets can follow in any order.

