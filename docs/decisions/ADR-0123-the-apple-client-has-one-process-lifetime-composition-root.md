# ADR-0123: The Apple Client Has One Process-Lifetime Composition Root

Status: proposed

Date: 2026-09-17

Extends [ADR-0008](ADR-0008-the-apple-app-shell-is-a-committed-xcode-project.md) and
[ADR-0122](ADR-0122-the-apple-client-has-explicit-module-boundaries.md).

## Context

The Apple client has process-lifetime services whose ownership is already understood individually:
one player, one download stack, one radio controller, one ambient controller, one casting
controller, one command-channel subscription and one audio session. `FamiliarApp.swift` explains
why each must outlive a screen.

Their composition nevertheless happens in a `.task` attached to the `WindowGroup`'s root view. It
attaches effects and crossfade, installs persistence closures, supplies server-backed sources,
connects audio ownership, starts the playback-command client, registers a seek observer, begins
casting observation and prepares downloads. Configuration changes call part of that wiring again.

A SwiftUI task belongs to a view lifecycle, not to the process. A root view may be reconstructed,
a task may be cancelled and restarted, and a `WindowGroup` may create more than one hierarchy.
Some collaborators replace prior state and are accidentally idempotent; others register an
observer or start work. The seek-observer token created during launch is discarded
(`App/Shared/FamiliarApp.swift:256`, `_ = player.addSeekObserver { … }` as of this decision), so a
repeated attachment cannot remove the prior observer. Correctness therefore depends on lifecycle behavior
outside the types that require “exactly once” or “replace on configuration change.”

The existing comments are strong documentation of each wire, but they also demonstrate the
newcomer problem: the only architecture map is an executable block in a 490-line SwiftUI entry
point. Adding a service means knowing where in that block it belongs and which calls are safe to
repeat.

## Decision

1. **The Apple client has one explicit process-lifetime composition root**, named
   `FamiliarApplication`, owned by the SwiftUI `App`. It owns or is initialized with the process-wide
   services and is the only place that connects them to each other. The name says what it is — the
   process — and deliberately avoids "coordinator", which in iOS usage means a navigation flow, the one
   thing point 7 says this type must not become.

2. **The composition root exposes an idempotent `start()` operation.** Calling it more than once
   does not add another observer, subscription, timer or long-running task. It retains every
   registration token and cancellable it creates and releases or replaces them deliberately.

3. **Process startup and configuration binding are separate operations.** Stable wiring between
   process-owned services happens once. Server- and profile-dependent repositories are replaced
   when configuration identity changes. The replacement operation is idempotent for the same
   identity and may explicitly detach the old dependencies before installing new ones.

4. **SwiftUI lifecycle callbacks trigger the composition root but do not contain the wiring.** A view
   may call `start()`, report scene phase, or present its state. It does not register
   process-wide observers or assign collaborators directly. Platform delegates may enter the same
   composition root for callbacks that occur before any scene exists. There are three such entries
   today, and they are the cases where "the SwiftUI lifecycle triggers the composition root" is
   false — the platform triggers it: background `URLSession` events (ADR-0111 point 9), CarPlay
   scene attachment, and App Intents performed in the app (ADR-0121's stop button, a
   `LiveActivityIntent` the system constructs in whichever process it lands in). Each enters through
   the composition root's one static, not through a static of its own.

5. **Required collaborators are established through initialization where practical.** Runtime
   replaceable dependencies use named methods or grouped dependency values. A set of unrelated
   optional closure properties is not the composition API: an incompletely wired service should
   either be impossible to construct or explicitly use a null capability whose behavior is named.

6. **The composition root is testable without SwiftUI.** Tests cover repeated `start()`, a
   configuration transition, observer replacement and shutdown. Test doubles count registrations
   and starts, so “exactly once” is a behavior rather than a source-text assertion.

7. **This decision does not centralize feature policy.** Queue behavior stays in the player, radio
   cadence in the radio controller, ambient behavior in the ambient controller and download
   behavior in the download stack. `FamiliarApplication` says who talks to whom and for how long; it does
   not become another implementation of their rules.

## Alternatives Considered

- **Keep the root `.task` and add a Boolean guard.** This prevents the most visible duplicate start
  but leaves token ownership, configuration replacement and pre-scene callbacks distributed. A
  Boolean in a view also describes the current hierarchy, not necessarily the process.

- **Make every service attachment individually idempotent.** Useful as defense in depth, but it
  spreads composition semantics across every feature and still leaves no inspectable map of the
  running application. Services should defend themselves; one owner should still coordinate them.

- **Use a dependency-injection framework.** Rejected. The graph is explicit, finite and largely
  process-scoped. A small hand-written composition type gives compile-time visibility without a new
  runtime registration system.

- **Use global singletons for every process service.** `Downloads.shared` is justified by background
  relaunch behavior, but extending that shape would hide dependencies and make isolated tests
  harder. Process lifetime does not require global access — but process-lifetime *entry* does
  require exactly one static, because a background relaunch or an intent has nothing else to reach
  for. The composition root is that static; `Downloads.shared` becomes reachable through it rather
  than standing beside it as a peer, and ADR-0121's `DownloadActivityHooks.cancelAll` — an optional
  closure installed by the app delegate and nil in the extension, the exact shape point 5 rules
  out — is the first thing to fold in. In the extension process the intent still has to compile;
  there the capability is an explicit stub that says the intent is performed in the app, not an
  optional that happens to be nil.

- **Let each screen attach what it consumes.** Rejected because radio, playback, ambient, casting,
  CarPlay and command subscriptions intentionally survive navigation. Screen ownership would create
  duplicate controllers or behavior that disappears when its view does.

## Consequences

- **Positive:** process-wide work has one owner and explicit exactly-once semantics.
- **Positive:** opening another window or recreating the root view cannot silently multiply
  observers and subscriptions.
- **Positive:** the composition root becomes an executable architecture map and a natural first
  file for a newcomer learning application ownership.
- **Positive:** profile/server changes have a named replacement path rather than re-running an
  arbitrary subset of launch code.
- **Tradeoff:** `FamiliarApplication` becomes an important type and must resist accumulating feature
  policy.
- **Tradeoff:** some existing observable objects will need initializer or attachment APIs that make
  lifecycle and replacement explicit.
- **Follow-up:** document the flows for playback, casting, radio, ambient, downloads, CarPlay and
  command-channel ownership beside `FamiliarApplication` after it exists.

