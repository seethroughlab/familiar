import XCTest
@testable import App

final class NativeAudioEngineRemoteCommandAvailabilityTests: XCTestCase {
    func testPreviousEnabledWhenCurrentTimeExceedsRestartThreshold() {
        let engine = NativeAudioEngine()
        XCTAssertTrue(engine.canGoPreviousForRemoteCommand(at: 4.0))
        XCTAssertFalse(engine.canGoPreviousForRemoteCommand(at: 2.0))
    }

    func testPreviousEnabledWhenPendingPreviousExists() {
        let engine = NativeAudioEngine()
        engine.setPendingPrevious(
            url: "https://example.com/prev.mp3",
            trackId: "prev-1",
            title: "Prev",
            artist: "Artist",
            album: "Album",
            artworkUrl: nil
        )

        XCTAssertTrue(engine.canGoPreviousForRemoteCommand(at: 0.0))
    }

    func testNextEnabledOnlyWhenPendingNextExists() {
        let engine = NativeAudioEngine()
        engine.setPendingNext(url: nil, trackId: nil, title: nil, artist: nil, album: nil, artworkUrl: nil)
        XCTAssertFalse(engine.canGoNextForRemoteCommand())

        engine.setPendingNext(
            url: "https://example.com/next.mp3",
            trackId: "next-1",
            title: "Next",
            artist: "Artist",
            album: "Album",
            artworkUrl: nil
        )
        XCTAssertTrue(engine.canGoNextForRemoteCommand())
    }
}
