import XCTest
import MediaPlayer
@testable import App

final class NativeAudioEngineRemoteCommandAvailabilityTests: XCTestCase {
    func testNextAndPreviousAreAlwaysEnabled() {
        // Both commands are always enabled regardless of pending track state.
        // Handlers fall back to JS (remoteNext/remotePrevious events) when no pre-synced track is available.
        _ = NativeAudioEngine()
        let commandCenter = MPRemoteCommandCenter.shared()
        XCTAssertTrue(commandCenter.nextTrackCommand.isEnabled)
        XCTAssertTrue(commandCenter.previousTrackCommand.isEnabled)
    }
}
