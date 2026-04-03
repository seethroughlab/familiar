import XCTest
@testable import App

final class NativeAudioAnalysisProcessorTests: XCTestCase {
    private func sineWave(
        frequency: Double,
        sampleRate: Double = 44_100,
        count: Int = NativeAudioAnalysisProcessor.fftSize,
        amplitude: Double = 0.9
    ) -> [Float] {
        (0..<count).map { index in
            let phase = 2.0 * Double.pi * frequency * Double(index) / sampleRate
            return Float(sin(phase) * amplitude)
        }
    }

    private func mix(_ waves: [([Float], Double)]) -> [Float] {
        guard let count = waves.first?.0.count else { return [] }
        var output = [Float](repeating: 0, count: count)
        for (samples, gain) in waves {
            for index in 0..<count {
                output[index] += samples[index] * Float(gain)
            }
        }
        return output.map { max(-1.0, min(1.0, $0)) }
    }

    func testKickLikeFixtureDominatesBass() {
        let processor = NativeAudioAnalysisProcessor()
        let kick = mix([
            (sineWave(frequency: 70), 1.0),
            (sineWave(frequency: 140), 0.45),
        ])

        let frame = processor.process(samples: kick, now: 1.0)

        XCTAssertNotNil(frame)
        XCTAssertGreaterThan(frame?.metrics.bass ?? 0, frame?.metrics.mid ?? 0)
        XCTAssertGreaterThan(frame?.metrics.bass ?? 0, frame?.metrics.treble ?? 0)
        XCTAssertGreaterThan(frame?.metrics.variance ?? 0, 0.0001)
    }

    func testBrightFixtureDominatesTreble() {
        let processor = NativeAudioAnalysisProcessor()
        let bright = mix([
            (sineWave(frequency: 4_000), 1.0),
            (sineWave(frequency: 6_500), 0.5),
        ])

        let frame = processor.process(samples: bright, now: 2.0)

        XCTAssertNotNil(frame)
        XCTAssertGreaterThan(frame?.metrics.treble ?? 0, frame?.metrics.bass ?? 0)
        XCTAssertGreaterThan(frame?.metrics.treble ?? 0, frame?.metrics.mid ?? 0)
        XCTAssertGreaterThan(frame?.metrics.strongestBinValue ?? 0, 0.1)
    }

    func testPadFixtureIsLessVariantThanKickFixture() {
        let kickProcessor = NativeAudioAnalysisProcessor()
        let padProcessor = NativeAudioAnalysisProcessor()

        let kick = mix([
            (sineWave(frequency: 70), 1.0),
            (sineWave(frequency: 140), 0.45),
        ])
        let pad = mix([
            (sineWave(frequency: 220, amplitude: 0.35), 1.0),
            (sineWave(frequency: 330, amplitude: 0.25), 1.0),
            (sineWave(frequency: 440, amplitude: 0.2), 1.0),
        ])

        let kickFrame = kickProcessor.process(samples: kick, now: 3.0)
        let padFrame = padProcessor.process(samples: pad, now: 3.0)

        XCTAssertNotNil(kickFrame)
        XCTAssertNotNil(padFrame)
        XCTAssertGreaterThan(kickFrame?.metrics.variance ?? 0, padFrame?.metrics.variance ?? 0)
        XCTAssertGreaterThan(padFrame?.metrics.mid ?? 0, padFrame?.metrics.bass ?? 0)
    }
}
