import XCTest

/// Guard against regression of the `.dataPlayedBack` fix.
///
/// AVAudioPlayerNode's `scheduleFile(_:at:completionHandler:)` and
/// `scheduleSegment(_:startingFrame:frameCount:at:completionHandler:)`
/// fire the completion handler with `.dataConsumed` semantics — i.e. when
/// audio data is *read from disk*, not when it finishes *playing*.
///
/// This causes the `ended` event to fire too early (or be silently dropped
/// during crossfade timing windows), leaving the app stuck after a track ends.
///
/// The fix is to always use the modern overload with
/// `completionCallbackType: .dataPlayedBack`. This test scans the source file
/// to ensure no one accidentally reintroduces the legacy API.
final class NativeAudioEngineSchedulingAPITests: XCTestCase {

    func testAllScheduleCallsUseDataPlayedBack() throws {
        // Locate NativeAudioEngine.swift relative to the test bundle
        let testFile = URL(fileURLWithPath: #file)
        let nativeDir = testFile
            .deletingLastPathComponent()  // AppTests/
            .deletingLastPathComponent()  // native/
            .appendingPathComponent("App")
            .appendingPathComponent("NativeAudioEngine.swift")

        let source = try String(contentsOf: nativeDir, encoding: .utf8)
        let lines = source.components(separatedBy: .newlines)

        var violations: [String] = []

        for (index, line) in lines.enumerated() {
            let trimmed = line.trimmingCharacters(in: .whitespaces)

            // Skip comments
            if trimmed.hasPrefix("//") || trimmed.hasPrefix("*") { continue }

            let isScheduleCall =
                line.contains(".scheduleFile(") || line.contains(".scheduleSegment(")

            if isScheduleCall && !line.contains("completionCallbackType:") {
                // Allow the wrapper method declaration: `private func scheduleFile(`
                // and internal calls like `self.scheduleFile(` which route through the wrapper
                let isFuncDecl = line.contains("func scheduleFile(")
                let isWrapperCall = line.contains("self.scheduleFile(")
                if !isFuncDecl && !isWrapperCall {
                    violations.append("Line \(index + 1): \(trimmed)")
                }
            }
        }

        XCTAssertTrue(
            violations.isEmpty,
            """
            Found AVAudioPlayerNode schedule calls without `completionCallbackType: .dataPlayedBack`.
            The legacy completion handler uses `.dataConsumed` semantics and fires before audio \
            finishes playing, which breaks auto-advance and crossfade.

            Violations:
            \(violations.joined(separator: "\n"))
            """
        )
    }
}
