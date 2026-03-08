# AppTests

This folder contains native lock-screen regression tests for `NativeAudioEngine`.

## Wire Target In Xcode

1. Open `/Users/jeff/Developer/familiar/packages/ios/native/App.xcodeproj`.
2. File -> New -> Target -> Unit Testing Bundle (`AppTests`).
3. Set host app target to `App`.
4. Add `NativeAudioEngineRemoteCommandAvailabilityTests.swift` to the new target.
5. Enable `@testable import App` by making sure target/module name is `App`.

## Current Test Focus

- Previous command enablement when `currentTime > 3`.
- Previous command enablement when pending previous exists.
- Next command enablement only when pending next exists.
- Follow-up: assert command state transitions after pending metadata clear on command execution.

## Suggested CLI Invocation

```bash
xcodebuild test \
  -project /Users/jeff/Developer/familiar/packages/ios/native/App.xcodeproj \
  -scheme App \
  -destination 'platform=iOS Simulator,name=iPhone 16'
```
