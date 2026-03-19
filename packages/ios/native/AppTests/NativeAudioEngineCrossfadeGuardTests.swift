import XCTest

/// Guard against regression of the crossfade guard in scheduleFile and seek callbacks.
///
/// When crossfade is active, track A's end-of-track completion callbacks can fire
/// before the crossfade timer finishes (if crossfade duration exceeds the remaining
/// playback time). Without a guard for `isCrossfadingFlag`, the callback calls
/// handleTrackEnd() → stopInternal(), which kills the crossfade timer and corrupts
/// engine state — causing tracks to stop auto-advancing.
///
/// The seek() method replaces the scheduleFile callback with a scheduleSegment callback,
/// so BOTH must contain the `isCrossfadingFlag` guard.
///
/// This test scans NativeAudioEngine.swift to ensure both callbacks contain the guard.
final class NativeAudioEngineCrossfadeGuardTests: XCTestCase {

    func testScheduleFileCallbackGuardsCrossfadeFlag() throws {
        let testFile = URL(fileURLWithPath: #file)
        let engineFile = testFile
            .deletingLastPathComponent()  // AppTests/
            .deletingLastPathComponent()  // native/
            .appendingPathComponent("App")
            .appendingPathComponent("NativeAudioEngine.swift")

        let source = try String(contentsOf: engineFile, encoding: .utf8)
        let lines = source.components(separatedBy: .newlines)

        // Find the scheduleFile wrapper method (private func scheduleFile)
        // and verify its completion callback contains an isCrossfadingFlag guard
        var inScheduleFileMethod = false
        var braceDepth = 0
        var foundCrossfadeGuard = false
        var methodStartLine = 0

        for (index, line) in lines.enumerated() {
            if !inScheduleFileMethod && line.contains("private func scheduleFile(") {
                inScheduleFileMethod = true
                methodStartLine = index + 1
                // Count braces on the declaration line itself
                braceDepth = line.filter({ $0 == "{" }).count - line.filter({ $0 == "}" }).count
                continue
            }

            if inScheduleFileMethod {
                braceDepth += line.filter({ $0 == "{" }).count
                braceDepth -= line.filter({ $0 == "}" }).count

                if line.contains("isCrossfadingFlag") {
                    foundCrossfadeGuard = true
                }

                // Method body ended
                if braceDepth <= 0 {
                    break
                }
            }
        }

        XCTAssertTrue(
            inScheduleFileMethod,
            "Could not find `private func scheduleFile(` in NativeAudioEngine.swift"
        )

        XCTAssertTrue(
            foundCrossfadeGuard,
            """
            The scheduleFile() completion callback must guard against `isCrossfadingFlag`.
            Without this guard, track A's end-of-file callback fires during crossfade when \
            the crossfade duration exceeds remaining playback time, corrupting engine state \
            and causing tracks to stop auto-advancing.

            Add `guard !self.isCrossfadingFlag else { return }` to the DispatchQueue.main.async \
            block in the scheduleFile callback (around line \(methodStartLine)).
            """
        )
    }

    func testSeekCallbackGuardsCrossfadeFlag() throws {
        let testFile = URL(fileURLWithPath: #file)
        let engineFile = testFile
            .deletingLastPathComponent()  // AppTests/
            .deletingLastPathComponent()  // native/
            .appendingPathComponent("App")
            .appendingPathComponent("NativeAudioEngine.swift")

        let source = try String(contentsOf: engineFile, encoding: .utf8)
        let lines = source.components(separatedBy: .newlines)

        // Find the seek(time:) method and verify its scheduleSegment callback
        // contains an isCrossfadingFlag guard
        var inSeekMethod = false
        var braceDepth = 0
        var foundCrossfadeGuard = false
        var methodStartLine = 0

        for (index, line) in lines.enumerated() {
            if !inSeekMethod && line.contains("func seek(time:") {
                inSeekMethod = true
                methodStartLine = index + 1
                braceDepth = line.filter({ $0 == "{" }).count - line.filter({ $0 == "}" }).count
                continue
            }

            if inSeekMethod {
                braceDepth += line.filter({ $0 == "{" }).count
                braceDepth -= line.filter({ $0 == "}" }).count

                if line.contains("isCrossfadingFlag") {
                    foundCrossfadeGuard = true
                }

                if braceDepth <= 0 {
                    break
                }
            }
        }

        XCTAssertTrue(
            inSeekMethod,
            "Could not find `func seek(time:` in NativeAudioEngine.swift"
        )

        XCTAssertTrue(
            foundCrossfadeGuard,
            """
            The seek() scheduleSegment completion callback must guard against `isCrossfadingFlag`.
            After a seek, the original scheduleFile callback is dead (invalidated by seekOperationToken). \
            The scheduleSegment callback from seek() is the one that fires when the track ends, and it \
            must also check isCrossfadingFlag to prevent handleTrackEnd() from killing an active crossfade.

            Add `guard !self.isCrossfadingFlag else { return }` to the DispatchQueue.main.async \
            block in the seek scheduleSegment callback (around line \(methodStartLine)).
            """
        )
    }
}
