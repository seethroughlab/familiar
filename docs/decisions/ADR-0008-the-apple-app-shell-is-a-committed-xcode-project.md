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

3. **One multiplatform application target**, not one per platform. This refines ADR-0001 point 1's
   "two targets" and does not reverse its intent: that point exists to say macOS and iOS are *not
   split*, and a single target is the strongest available form of that. Platform differences are
   expressed as SDK-conditional build settings — `CODE_SIGN_ENTITLEMENTS[sdk=iphoneos*]` for the
   CarPlay entitlement, hardened runtime for macOS — rather than as duplicated target
   configuration that has to be kept in step by hand.

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

- **Two application targets, one per platform.** Rejected for now, and the closest call here. It is
  the conventional shape and makes divergent capabilities obvious, which matters because CarPlay's
  scene manifest and entitlement are unforgiving. But it duplicates every build setting, and the
  failure mode of duplication is silent drift between platforms. SDK-conditional settings cover the
  divergence that actually exists. Revisit if the conditionals become harder to read than two
  targets would be — this is a refactor, not a one-way door.

- **Stay SwiftPM-only and defer the shell.** Rejected. It is what the repo does today, and it is
  why there is nothing to run. Every remaining v1 item is UI inside an application.

## Consequences

- **Positive:** cloning and opening the repo is one step, with no toolchain prerequisite beyond
  Xcode. What is reviewed is what is built.
- **Positive:** the churn and merge-conflict cost that motivates project generators is measured to
  be absent, not assumed away.
- **Positive:** one target means a platform difference has to be written down deliberately as a
  conditional, rather than arising from two configurations drifting.
- **Tradeoff:** `project.pbxproj` is still a generated-looking file under version control. Changes
  to *settings* remain awkward to review even though changes to *files* no longer appear. The
  mitigation is that settings change rarely.
- **Tradeoff:** synchronized groups require Xcode 16 or newer. That is not a real constraint at
  Xcode 26.5, but it does mean the project cannot be opened by a much older Xcode at all, rather
  than opening with warnings.
- **Tradeoff:** a single target makes per-platform capabilities less visible than two targets would.
  If CarPlay's requirements prove awkward under conditionals, decision point 3 is the thing to
  revisit first.
- **Follow-up:** app icons, launch assets and the bundle identifier still need deciding. The
  Capacitor app ships as `com.familiar.player`; whether the native app reuses that identifier —
  taking over the existing TestFlight record and its installed base — or takes a new one is a
  release-management decision that belongs with whoever holds the App Store Connect account.
- **Follow-up:** Swift 6 language mode remains deferred per the note in `Package.swift`. The app
  target should not adopt it ahead of `FamiliarKit`, or the two halves of the same build would sit
  in different concurrency models.
