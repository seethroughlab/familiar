import AVFoundation
import Foundation

/// Separate AVAudioEngine graph for ambient synth: 2 drone oscillators + 1 motif oscillator,
/// lowpass filter, reverb, delay. Independent from the FamiliarAudio playback graph.
/// Shares the system audio session.
class AmbientSynthEngine {
    private let audioEngine = AVAudioEngine()

    private let mixerNode = AVAudioMixerNode()
    private let reverbNode = AVAudioUnitReverb()
    private let delayNode = AVAudioUnitDelay()
    private let eqNode = AVAudioUnitEQ(numberOfBands: 1) // Used as lowpass

    // Oscillator state (accessed from audio render thread via closures)
    private var drone1Phase: Float = 0
    private var drone1Freq: Float = 0
    private var drone1Amp: Float = 0
    private var drone1TargetAmp: Float = 0

    private var drone2Phase: Float = 0
    private var drone2Freq: Float = 0
    private var drone2Amp: Float = 0
    private var drone2TargetAmp: Float = 0

    private var motifPhase: Float = 0
    private var motifFreq: Float = 0
    private var motifAmp: Float = 0
    private var motifTargetAmp: Float = 0

    private var isRunning = false
    private var sampleRate: Float = 44100

    // Public mix level parameters (set via configure/updateMix)
    var droneLevel: Float = 0.3
    var motifLevel: Float = 0.2
    var reverbMix: Float = 0.6

    func configure(
        droneVolume: Float,
        motifVolume: Float,
        reverbMix: Float,
        delayMix: Float,
        lowpassFreq: Float
    ) {
        self.droneLevel = droneVolume
        self.motifLevel = motifVolume
        self.reverbMix = reverbMix

        reverbNode.wetDryMix = reverbMix * 100
        reverbNode.loadFactoryPreset(.largeChamber)

        delayNode.wetDryMix = delayMix * 100
        delayNode.delayTime = 0.4
        delayNode.feedback = 30

        // Configure lowpass via EQ band
        if let band = eqNode.bands.first {
            band.filterType = .lowPass
            band.frequency = lowpassFreq
            band.bandwidth = 1.0
            band.bypass = false
        }

        setupEngineIfNeeded()
    }

    private func setupEngineIfNeeded() {
        guard !isRunning else { return }

        let format = AVAudioFormat(standardFormatWithSampleRate: 44100, channels: 1)!
        sampleRate = Float(format.sampleRate)

        // Create source nodes with render blocks
        let drone1Source = AVAudioSourceNode { [weak self] _, _, frameCount, audioBufferList -> OSStatus in
            guard let self = self else { return noErr }
            return self.renderOscillator(
                phase: &self.drone1Phase,
                freq: self.drone1Freq,
                amp: &self.drone1Amp,
                targetAmp: self.drone1TargetAmp,
                frameCount: frameCount,
                audioBufferList: audioBufferList,
                waveform: .sine
            )
        }

        let drone2Source = AVAudioSourceNode { [weak self] _, _, frameCount, audioBufferList -> OSStatus in
            guard let self = self else { return noErr }
            return self.renderOscillator(
                phase: &self.drone2Phase,
                freq: self.drone2Freq,
                amp: &self.drone2Amp,
                targetAmp: self.drone2TargetAmp,
                frameCount: frameCount,
                audioBufferList: audioBufferList,
                waveform: .triangle
            )
        }

        let motifSource = AVAudioSourceNode { [weak self] _, _, frameCount, audioBufferList -> OSStatus in
            guard let self = self else { return noErr }
            return self.renderOscillator(
                phase: &self.motifPhase,
                freq: self.motifFreq,
                amp: &self.motifAmp,
                targetAmp: self.motifTargetAmp,
                frameCount: frameCount,
                audioBufferList: audioBufferList,
                waveform: .sine
            )
        }

        audioEngine.attach(drone1Source)
        audioEngine.attach(drone2Source)
        audioEngine.attach(motifSource)
        audioEngine.attach(mixerNode)
        audioEngine.attach(reverbNode)
        audioEngine.attach(delayNode)
        audioEngine.attach(eqNode)

        let stereoFormat = AVAudioFormat(standardFormatWithSampleRate: 44100, channels: 2)!

        audioEngine.connect(drone1Source, to: mixerNode, format: format)
        audioEngine.connect(drone2Source, to: mixerNode, format: format)
        audioEngine.connect(motifSource, to: mixerNode, format: format)
        audioEngine.connect(mixerNode, to: eqNode, format: stereoFormat)
        audioEngine.connect(eqNode, to: reverbNode, format: stereoFormat)
        audioEngine.connect(reverbNode, to: delayNode, format: stereoFormat)
        audioEngine.connect(delayNode, to: audioEngine.mainMixerNode, format: stereoFormat)

        do {
            try audioEngine.start()
            isRunning = true
        } catch {
            print("[AmbientSynth] Failed to start engine: \(error)")
        }
    }

    func startTransition(
        droneRootNote: Int,
        droneSecondNote: Int,
        droneAttackMs: Int,
        droneReleaseMs: Int,
        motifNotes: [Int],
        motifTimingsMs: [Int],
        motifNoteDurationMs: Int
    ) {
        setupEngineIfNeeded()

        // Set drone frequencies
        drone1Freq = midiToFreq(droneRootNote)
        drone2Freq = midiToFreq(droneSecondNote)

        // Ramp in drones
        drone1TargetAmp = droneLevel
        drone2TargetAmp = droneLevel * 0.7

        // Schedule motif notes
        for (i, note) in motifNotes.enumerated() {
            let timing = i < motifTimingsMs.count ? motifTimingsMs[i] : i * 1000
            let delay = Double(timing) / 1000.0

            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
                guard let self = self else { return }
                self.motifFreq = self.midiToFreq(note)
                self.motifTargetAmp = self.motifLevel
            }

            // Fade out motif note after duration
            let fadeOutDelay = delay + Double(motifNoteDurationMs) / 1000.0
            DispatchQueue.main.asyncAfter(deadline: .now() + fadeOutDelay) { [weak self] in
                self?.motifTargetAmp = 0
            }
        }

        // Schedule drone release
        let releaseSec = Double(droneReleaseMs) / 1000.0
        DispatchQueue.main.asyncAfter(deadline: .now() + releaseSec) { [weak self] in
            self?.drone1TargetAmp = 0
            self?.drone2TargetAmp = 0
        }
    }

    func stopImmediate() {
        drone1TargetAmp = 0
        drone1Amp = 0
        drone2TargetAmp = 0
        drone2Amp = 0
        motifTargetAmp = 0
        motifAmp = 0
    }

    func stopWithRelease(releaseMs: Int) {
        drone1TargetAmp = 0
        drone2TargetAmp = 0
        motifTargetAmp = 0
        // Amplitude will ramp down naturally via the render smoothing
    }

    // MARK: - Oscillator rendering

    private enum Waveform {
        case sine, triangle
    }

    private func renderOscillator(
        phase: inout Float,
        freq: Float,
        amp: inout Float,
        targetAmp: Float,
        frameCount: UInt32,
        audioBufferList: UnsafeMutablePointer<AudioBufferList>,
        waveform: Waveform
    ) -> OSStatus {
        let ablPointer = UnsafeMutableAudioBufferListPointer(audioBufferList)
        let buffer = ablPointer[0]
        let ptr = buffer.mData?.assumingMemoryBound(to: Float.self)

        let smoothingCoeff: Float = 0.0005 // Very slow for ambient smoothness

        for frame in 0..<Int(frameCount) {
            // Smooth volume transitions
            amp += (targetAmp - amp) * smoothingCoeff

            let sample: Float
            switch waveform {
            case .sine:
                sample = sin(phase * 2.0 * .pi) * amp
            case .triangle:
                let t = phase - floor(phase)
                sample = (2.0 * abs(2.0 * t - 1.0) - 1.0) * amp
            }

            ptr?[frame] = sample

            phase += freq / sampleRate
            if phase >= 1.0 { phase -= 1.0 }
        }

        return noErr
    }

    private func midiToFreq(_ note: Int) -> Float {
        return 440.0 * pow(2.0, Float(note - 69) / 12.0)
    }
}
