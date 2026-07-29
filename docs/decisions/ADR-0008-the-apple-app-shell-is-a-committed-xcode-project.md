# ADR-0008: The Apple App Shell Is a Committed Xcode Project

Status: proposed
Date: 2026-07-28

Extends [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md)

## Context

ADR-0001 decided one repository, two platforms, sharing `FamiliarKit`. It did not say how the
application itself is built, and that gap is now the thing blocking progress.

`familiar-apple` today is a SwiftPM package and nothing more. `swift build` compiles `FamiliarKit`
and `FamiliarAPI`; `swift test` runs 19 tests, four of them against a live server. But there is no
application: no bundle, no `Info.plist`, no entitlements, no code signing, no scheme to run on a
device, no path to TestFlight. Every item in ADR-0001 point 4's v1 scope needs one, and SwiftPM
cannot produce it — `.executableTarget` yields a bare Mach-O, not a `.app`.

Verified on the development machine, which is also the self-hosted CI runner:

| Fact | Value |
|---|---|
| Xcode | 26.5 (build 17F42) |
| Swift | 6.3.2 |
| XcodeGen | 2.45.4, installed |
| Capacitor app's project | `packages/ios/native/App.xcodeproj`, 581 lines, `objectVersion = 60` |

The standing argument against committing an `.xcodeproj` is churn. `project.pbxproj` has
historically listed every source file against a generated UUID, so adding a file rewrites it, two
branches adding files conflict, and the conflict is in a format no reviewer can meaningfully read.
That argument drove a generation of projects onto XcodeGen and Tuist.

**That argument is now substantially weaker, and this ADR rests on having checked rather than
assumed it.** Xcode 16 introduced `PBXFileSystemSynchronizedRootGroup`: a folder whose membership is
the filesystem rather than a list. Apple ships template projects using it at `objectVersion = 77`.
A proof-of-concept — one multiplatform target, a synchronized group, a local SwiftPM dependency —
established three things:

1. It builds for **macOS and iOS Simulator from a single target**.
2. It links the local package and compiles its code.
3. Adding a new source file compiled it with **`project.pbxproj` byte-identical afterwards**.

Point 3 is the whole case. The churn the tooling exists to prevent no longer happens.

Two gotchas surfaced, recorded because both produce the same opaque `Multiple commands produce`
error and neither names its cause:

- An `Info.plist` **inside** the synchronized folder is copied as a resource and collides with the
  processed one. It must live outside.
- A synchronized folder whose name matches the product name collides with the executable on iOS,
  where the bundle is flat, but **not** on macOS, where it is under `Contents/`. So this failure
  appears on one platform only and looks platform-specific when it is not.

**A premise that investigation contradicted:** XcodeGen cannot emit synchronized groups. Its
`type: folder` produces a legacy blue-folder *resource* reference — in the proof-of-concept the
generated Sources phase was empty, so no application code would have compiled at all. The binary
does contain `PBXFileSystemSynchronizedRootGroup` symbols, but they belong to the XcodeProj library
it links for reading projects, which makes the capability look present from the outside. Choosing
XcodeGen to keep the project file small therefore does not deliver the property it would be chosen
for.

## Decision

1. **Commit `Familiar.xcodeproj`. No project generator**, and no XcodeGen or Tuist dependency.
   `git clone && open Familiar.xcodeproj` is the whole setup.

2. **Source folders are synchronized groups**, so the project file records targets, settings and
   schemes but never file membership. A pull request that adds a screen touches only Swift.

3. **Two application targets, one per platform**, as ADR-0001 point 1 says. They share
   `FamiliarKit`, `FamiliarAPI` and the SwiftUI layer; what differs is capability configuration,
   and that difference is made explicit rather than conditional.

   The deciding factor is CarPlay. It is in v1 scope (ADR-0001 point 4), and its requirements are
   unforgiving in a specific way: the scene manifest and the entitlement must both be present, and
   a partial configuration does not degrade — it black-screens the app on launch. That failure is
   worth being able to see in one place, attached to the target it belongs to, rather than
   assembled mentally from SDK-conditional settings scattered across a shared configuration.

   The cost is real and is accepted knowingly: every shared build setting exists twice, and the
   failure mode of duplication is silent drift between platforms rather than a build error.
   Decision point 5's per-platform CI builds are the mitigation — drift that changes behaviour
   shows up as a failing build on the platform that drifted.

4. **`Info.plist` and entitlements live outside the synchronized folders**, in a `Support/`
   directory, for the collision reason above.

5. **CI builds the app, not just the package.** The existing `Build and Test` job on the
   self-hosted Mac runner gains an `xcodebuild` step per platform with `CODE_SIGNING_ALLOWED=NO`,
   so a project-file or settings mistake fails a build rather than being discovered at release
   time. Signing stays out of CI; it needs credentials CI does not have.

6. **The Capacitor project is not migrated.** `packages/ios/native/App.xcodeproj` stays where it is
   under ADR-0001 point 6's bug-fix-only freeze until the native app reaches parity, at which point
   it is deleted rather than converted.

## Alternatives Considered

- **XcodeGen from a `project.yml`.** Rejected on evidence rather than preference: it cannot generate
  the synchronized groups that make a committed project stable, so it would trade a real dependency
  for a benefit it does not provide. It also puts a `brew install` between cloning the repo and
  opening it, and the generated project must be gitignored, so what the user builds is never quite
  what is reviewed.

- **Tuist.** Rejected. Strictly more capable than XcodeGen — Swift manifests, caching, a module
  graph — and correspondingly heavier. Its value shows up across dozens of modules; this is one
  package and one app. It is not installed, so adopting it is a genuine new dependency for both the
  developer and the runner.

- **One multiplatform application target**, with `supportedDestinations: [iOS, macOS]` and platform
  differences expressed as SDK-conditional build settings. Rejected, and the closest call here —
  the proof-of-concept used exactly this shape and both platforms built, so it is known to work.
  It has the better story on shared settings: they exist once and cannot drift.

  Rejected because the divergence that matters is capabilities, not settings, and conditionals hide
  capabilities. `CODE_SIGN_ENTITLEMENTS[sdk=iphoneos*]` is a correct way to attach the CarPlay
  entitlement and a poor way to *notice* it is attached. Given that a partially-configured CarPlay
  app black-screens rather than degrading, legibility won over non-duplication. This is a refactor
  rather than a one-way door in either direction.

- **Stay SwiftPM-only and defer the shell.** Rejected. It is what the repo does today, and it is
  why there is nothing to run. Every remaining v1 item is UI inside an application.

## Consequences

- **Positive:** cloning and opening the repo is one step, with no toolchain prerequisite beyond
  Xcode. What is reviewed is what is built.
- **Positive:** the churn and merge-conflict cost that motivates project generators is measured to
  be absent, not assumed away.
- **Positive:** per-platform capabilities are visible where they apply. CarPlay's entitlement and
  scene manifest sit on the iOS target and nowhere else.
- **Tradeoff:** `project.pbxproj` is still a generated-looking file under version control. Changes
  to *settings* remain awkward to review even though changes to *files* no longer appear. The
  mitigation is that settings change rarely.
- **Tradeoff:** synchronized groups require Xcode 16 or newer. That is not a real constraint at
  Xcode 26.5, but it does mean the project cannot be opened by a much older Xcode at all, rather
  than opening with warnings.
- **Tradeoff:** every shared build setting exists twice, and two configurations drift silently
  rather than failing. Point 5's per-platform CI builds catch drift that changes behaviour; drift
  that does not — a stale comment, a diverged version string — will need noticing by eye. If the
  duplication becomes the larger problem, decision point 3 is the thing to revisit.
- **Follow-up:** app icons, launch assets and the bundle identifier still need deciding. The
  Capacitor app ships as `com.familiar.player`; whether the native app reuses that identifier —
  taking over the existing TestFlight record and its installed base — or takes a new one is a
  release-management decision that belongs with whoever holds the App Store Connect account.
- **Follow-up:** Swift 6 language mode remains deferred per the note in `Package.swift`. The app
  target should not adopt it ahead of `FamiliarKit`, or the two halves of the same build would sit
  in different concurrency models.
