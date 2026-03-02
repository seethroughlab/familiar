import Accelerate
import AVFoundation
import Foundation
import MediaPlayer

protocol NativeAudioEngineDelegate: AnyObject {
    func audioEngineDidFinishPlaying()
    func audioEngineDidUpdateTime(currentTime: Double, duration: Double)
    func audioEngineDidUpdateAnalysis(frequencyData: [UInt8], timeDomainData: [UInt8])
    func audioEngineDidEncounterError(message: String)
    func audioEngineRemotePlay()
    func audioEngineRemotePause()
    func audioEngineRemoteNext()
    func audioEngineRemotePrevious()
    func audioEngineRemoteSeek(time: Double)
}

class NativeAudioEngine {
    weak var delegate: NativeAudioEngineDelegate?

    private let engine = AVAudioEngine()
    private let playerNode = AVAudioPlayerNode()
    private let eqNode: AVAudioUnitEQ
    private let reverbNode = AVAudioUnitReverb()
    private let delayNode = AVAudioUnitDelay()
    private let distortionNode = AVAudioUnitDistortion()

    private var audioFile: AVAudioFile?
    private var tempFileURL: URL?
    private var currentTrackId: String?
    private var isPlayerScheduled = false
    private var startFramePosition: AVAudioFramePosition = 0
    private var pauseFramePosition: AVAudioFramePosition = 0
    private var isPaused = false

    private var volume: Float = 1.0
    private var masterBypassed = false

    private var timeUpdateTimer: Timer?
    private var downloadTask: URLSessionDataTask?

    // Now Playing metadata
    private var nowPlayingTitle: String?
    private var nowPlayingArtist: String?
    private var nowPlayingAlbum: String?
    private var nowPlayingArtwork: MPMediaItemArtwork?

    // FFT analysis
    private static let analysisFFTSize = 256
    private static let analysisBinCount = 128  // fftSize / 2
    private static let analysisLog2n = vDSP_Length(log2(Double(analysisFFTSize)))
    private var fftSetup: FFTSetup?
    private var previousFrequencyData: [Float]?
    private var isAnalysisEnabled = false
    private var lastAnalysisTime: CFAbsoluteTime = 0
    private static let analysisMinInterval: CFAbsoluteTime = 1.0 / 30.0  // ~30fps

    // MARK: - Initialization

    init() {
        eqNode = AVAudioUnitEQ(numberOfBands: 3)
        setupEQBands()
        setupAudioGraph()
        setupRemoteCommands()
    }

    private func setupEQBands() {
        // Band 0: Low shelf at 250 Hz
        let lowBand = eqNode.bands[0]
        lowBand.filterType = .lowShelf
        lowBand.frequency = 250
        lowBand.gain = 0
        lowBand.bypass = false

        // Band 1: Parametric mid at 1000 Hz
        let midBand = eqNode.bands[1]
        midBand.filterType = .parametric
        midBand.frequency = 1000
        midBand.bandwidth = 1.0
        midBand.gain = 0
        midBand.bypass = false

        // Band 2: High shelf at 4000 Hz
        let highBand = eqNode.bands[2]
        highBand.filterType = .highShelf
        highBand.frequency = 4000
        highBand.gain = 0
        highBand.bypass = false
    }

    private func setupAudioGraph() {
        engine.attach(playerNode)
        engine.attach(eqNode)
        engine.attach(reverbNode)
        engine.attach(delayNode)
        engine.attach(distortionNode)

        // Default effect states
        reverbNode.wetDryMix = 0
        delayNode.wetDryMix = 0
        distortionNode.wetDryMix = 0

        // Chain: playerNode → EQ → reverb → delay → distortion → mainMixer → output
        let format = engine.mainMixerNode.outputFormat(forBus: 0)
        engine.connect(playerNode, to: eqNode, format: format)
        engine.connect(eqNode, to: reverbNode, format: format)
        engine.connect(reverbNode, to: delayNode, format: format)
        engine.connect(delayNode, to: distortionNode, format: format)
        engine.connect(distortionNode, to: engine.mainMixerNode, format: format)

        setupInterruptionHandling()
    }

    // MARK: - Audio Session Interruption Handling

    private func setupInterruptionHandling() {
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleInterruption),
            name: AVAudioSession.interruptionNotification,
            object: nil
        )
    }

    @objc private func handleInterruption(_ notification: Notification) {
        guard let userInfo = notification.userInfo,
              let typeValue = userInfo[AVAudioSessionInterruptionTypeKey] as? UInt,
              let type = AVAudioSession.InterruptionType(rawValue: typeValue) else {
            return
        }

        switch type {
        case .began:
            // Interruption began — system pauses audio automatically
            break
        case .ended:
            guard let optionsValue = userInfo[AVAudioSessionInterruptionOptionKey] as? UInt else {
                return
            }
            let options = AVAudioSession.InterruptionOptions(rawValue: optionsValue)
            if options.contains(.shouldResume) {
                do {
                    try engine.start()
                    if isPlayerScheduled && isPaused {
                        // Don't auto-resume — let JS side decide
                    }
                } catch {
                    delegate?.audioEngineDidEncounterError(message: "Failed to restart after interruption: \(error.localizedDescription)")
                }
            }
        @unknown default:
            break
        }
    }

    // MARK: - Playback

    func load(url: String, trackId: String, completion: @escaping (Error?) -> Void) {
        // Cancel any in-progress download
        downloadTask?.cancel()
        downloadTask = nil

        // Stop current playback
        stopInternal()

        currentTrackId = trackId

        guard let sourceURL = URL(string: url) else {
            completion(NSError(domain: "NativeAudioEngine", code: -1, userInfo: [NSLocalizedDescriptionKey: "Invalid URL"]))
            return
        }

        // Download audio to temp file (AVAudioPlayerNode requires local files)
        let tempDir = NSTemporaryDirectory()
        let fileExtension = sourceURL.pathExtension.isEmpty ? "mp3" : sourceURL.pathExtension
        let tempPath = (tempDir as NSString).appendingPathComponent("familiar_audio_\(trackId).\(fileExtension)")
        let tempURL = URL(fileURLWithPath: tempPath)

        // Clean up previous temp file
        cleanupTempFile()
        self.tempFileURL = tempURL

        let task = URLSession.shared.dataTask(with: sourceURL) { [weak self] data, response, error in
            guard let self = self else { return }

            // Check if this load was cancelled (new track started)
            guard self.currentTrackId == trackId else { return }

            if let error = error {
                if (error as NSError).code == NSURLErrorCancelled { return }
                DispatchQueue.main.async {
                    completion(error)
                }
                return
            }

            guard let data = data else {
                DispatchQueue.main.async {
                    completion(NSError(domain: "NativeAudioEngine", code: -2, userInfo: [NSLocalizedDescriptionKey: "No data received"]))
                }
                return
            }

            do {
                try data.write(to: tempURL)
                let file = try AVAudioFile(forReading: tempURL)
                self.audioFile = file

                DispatchQueue.main.async {
                    self.scheduleFile(file, completion: completion)
                }
            } catch {
                DispatchQueue.main.async {
                    completion(error)
                }
            }
        }
        self.downloadTask = task
        task.resume()
    }

    private func scheduleFile(_ file: AVAudioFile, completion: @escaping (Error?) -> Void) {
        // Reconnect with the file's processing format for correct sample rate / channel count
        let processingFormat = file.processingFormat

        engine.disconnectNodeOutput(playerNode)
        engine.disconnectNodeOutput(eqNode)
        engine.disconnectNodeOutput(reverbNode)
        engine.disconnectNodeOutput(delayNode)
        engine.disconnectNodeOutput(distortionNode)

        engine.connect(playerNode, to: eqNode, format: processingFormat)
        engine.connect(eqNode, to: reverbNode, format: processingFormat)
        engine.connect(reverbNode, to: delayNode, format: processingFormat)
        engine.connect(delayNode, to: distortionNode, format: processingFormat)
        engine.connect(distortionNode, to: engine.mainMixerNode, format: processingFormat)

        playerNode.scheduleFile(file, at: nil) { [weak self] in
            guard let self = self else { return }
            // This fires when the scheduled buffer/file finishes.
            // Check if we actually played to the end (vs being stopped/seeked).
            DispatchQueue.main.async {
                if self.isPlayerScheduled && !self.isPaused {
                    self.isPlayerScheduled = false
                    self.stopTimeUpdates()
                    self.delegate?.audioEngineDidFinishPlaying()
                }
            }
        }
        isPlayerScheduled = true
        isPaused = false
        startFramePosition = 0
        pauseFramePosition = 0

        do {
            if !engine.isRunning {
                try engine.start()
            }
            syncNowPlaying()
            completion(nil)
        } catch {
            completion(error)
        }
    }

    func play() {
        guard isPlayerScheduled else { return }

        do {
            if !engine.isRunning {
                try engine.start()
            }
            playerNode.play()
            isPaused = false
            engine.mainMixerNode.outputVolume = volume
            startTimeUpdates()
            enableAnalysis()
            syncNowPlaying()
        } catch {
            delegate?.audioEngineDidEncounterError(message: "Failed to start engine: \(error.localizedDescription)")
        }
    }

    func pause() {
        guard isPlayerScheduled else { return }
        // Capture current frame position before pausing
        if let nodeTime = playerNode.lastRenderTime,
           let playerTime = playerNode.playerTime(forNodeTime: nodeTime) {
            pauseFramePosition = playerTime.sampleTime
        }
        playerNode.pause()
        isPaused = true
        stopTimeUpdates()
        disableAnalysis()
        syncNowPlaying()
    }

    func resume() {
        play()
    }

    func stop() {
        stopInternal()
    }

    private func stopInternal() {
        stopTimeUpdates()
        disableAnalysis()
        playerNode.stop()
        isPlayerScheduled = false
        isPaused = false
        startFramePosition = 0
        pauseFramePosition = 0
    }

    func seek(time: Double) {
        guard let file = audioFile, isPlayerScheduled else { return }

        let sampleRate = file.processingFormat.sampleRate
        let totalFrames = file.length
        let targetFrame = AVAudioFramePosition(time * sampleRate)

        guard targetFrame >= 0 && targetFrame < totalFrames else { return }

        let wasPlaying = playerNode.isPlaying
        playerNode.stop()

        let remainingFrames = AVAudioFrameCount(totalFrames - targetFrame)
        playerNode.scheduleSegment(file, startingFrame: targetFrame, frameCount: remainingFrames, at: nil) { [weak self] in
            guard let self = self else { return }
            DispatchQueue.main.async {
                if self.isPlayerScheduled && !self.isPaused {
                    self.isPlayerScheduled = false
                    self.stopTimeUpdates()
                    self.delegate?.audioEngineDidFinishPlaying()
                }
            }
        }

        // Track offset so getCurrentTime computes correctly
        startFramePosition = targetFrame
        pauseFramePosition = 0

        if wasPlaying {
            playerNode.play()
        }
        syncNowPlaying()
    }

    func setVolume(_ vol: Float) {
        volume = max(0, min(1, vol))
        engine.mainMixerNode.outputVolume = volume
    }

    // MARK: - Time Info

    func getCurrentTime() -> Double {
        guard let file = audioFile else { return 0 }
        let sampleRate = file.processingFormat.sampleRate
        guard sampleRate > 0 else { return 0 }

        if isPaused {
            return Double(startFramePosition + pauseFramePosition) / sampleRate
        }

        guard let nodeTime = playerNode.lastRenderTime,
              let playerTime = playerNode.playerTime(forNodeTime: nodeTime) else {
            return Double(startFramePosition) / sampleRate
        }

        return Double(startFramePosition + playerTime.sampleTime) / sampleRate
    }

    func getDuration() -> Double {
        guard let file = audioFile else { return 0 }
        let sampleRate = file.processingFormat.sampleRate
        guard sampleRate > 0 else { return 0 }
        return Double(file.length) / sampleRate
    }

    func getIsPlaying() -> Bool {
        return playerNode.isPlaying
    }

    // MARK: - Effects: EQ

    func setEQ(lowGain: Float, midGain: Float, highGain: Float,
               lowFreq: Float? = nil, midFreq: Float? = nil, highFreq: Float? = nil) {
        if masterBypassed {
            eqNode.bypass = true
            return
        }

        eqNode.bypass = false
        eqNode.bands[0].gain = lowGain
        eqNode.bands[1].gain = midGain
        eqNode.bands[2].gain = highGain

        if let freq = lowFreq { eqNode.bands[0].frequency = freq }
        if let freq = midFreq { eqNode.bands[1].frequency = freq }
        if let freq = highFreq { eqNode.bands[2].frequency = freq }
    }

    // MARK: - Effects: Reverb

    func setReverb(preset: String, wetDryMix: Float, enabled: Bool) {
        if masterBypassed || !enabled {
            reverbNode.wetDryMix = 0
            return
        }

        let avPreset = reverbPreset(from: preset)
        reverbNode.loadFactoryPreset(avPreset)
        reverbNode.wetDryMix = wetDryMix * 100 // AVAudioUnitReverb uses 0-100
    }

    private func reverbPreset(from name: String) -> AVAudioUnitReverbPreset {
        switch name {
        case "small-room": return .smallRoom
        case "medium-room": return .mediumRoom
        case "large-hall": return .largeHall2
        case "plate": return .plate
        case "cathedral": return .cathedral
        default: return .mediumRoom
        }
    }

    // MARK: - Effects: Delay

    func setDelay(time: Double, feedback: Float, wetDryMix: Float, enabled: Bool) {
        if masterBypassed || !enabled {
            delayNode.wetDryMix = 0
            return
        }

        delayNode.delayTime = time
        delayNode.feedback = feedback * 100 // AVAudioUnitDelay uses -100 to 100
        delayNode.wetDryMix = wetDryMix * 100
    }

    // MARK: - Effects: Distortion (Saturation)

    func setDistortion(preset: String, wetDryMix: Float, enabled: Bool) {
        if masterBypassed || !enabled {
            distortionNode.wetDryMix = 0
            return
        }

        let avPreset = distortionPreset(from: preset)
        distortionNode.loadFactoryPreset(avPreset)
        distortionNode.wetDryMix = wetDryMix * 100
    }

    private func distortionPreset(from name: String) -> AVAudioUnitDistortionPreset {
        switch name {
        case "warm": return .drumsBitBrush
        case "tape": return .speechCosmicInterference
        case "hard": return .drumsLoFi
        default: return .drumsBitBrush
        }
    }

    // MARK: - Master Bypass

    func setMasterBypass(_ bypassed: Bool) {
        masterBypassed = bypassed
        if bypassed {
            eqNode.bypass = true
            reverbNode.wetDryMix = 0
            delayNode.wetDryMix = 0
            distortionNode.wetDryMix = 0
        }
    }

    // MARK: - Time Update Timer

    private func startTimeUpdates() {
        stopTimeUpdates()
        timeUpdateTimer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            let current = self.getCurrentTime()
            let duration = self.getDuration()
            self.delegate?.audioEngineDidUpdateTime(currentTime: current, duration: duration)
        }
    }

    private func stopTimeUpdates() {
        timeUpdateTimer?.invalidate()
        timeUpdateTimer = nil
    }

    // MARK: - Now Playing

    private func setupRemoteCommands() {
        let commandCenter = MPRemoteCommandCenter.shared()

        commandCenter.playCommand.addTarget { [weak self] _ in
            guard let self = self else { return .commandFailed }
            self.play()
            self.delegate?.audioEngineRemotePlay()
            return .success
        }

        commandCenter.pauseCommand.addTarget { [weak self] _ in
            guard let self = self else { return .commandFailed }
            self.pause()
            self.delegate?.audioEngineRemotePause()
            return .success
        }

        commandCenter.nextTrackCommand.addTarget { [weak self] _ in
            guard let self = self else { return .commandFailed }
            self.delegate?.audioEngineRemoteNext()
            return .success
        }

        commandCenter.previousTrackCommand.addTarget { [weak self] _ in
            guard let self = self else { return .commandFailed }
            self.delegate?.audioEngineRemotePrevious()
            return .success
        }

        commandCenter.changePlaybackPositionCommand.addTarget { [weak self] event in
            guard let self = self,
                  let positionEvent = event as? MPChangePlaybackPositionCommandEvent else {
                return .commandFailed
            }
            self.seek(time: positionEvent.positionTime)
            self.delegate?.audioEngineRemoteSeek(time: positionEvent.positionTime)
            return .success
        }
    }

    func updateNowPlayingInfo(title: String?, artist: String?, album: String?) {
        nowPlayingTitle = title
        nowPlayingArtist = artist
        nowPlayingAlbum = album
        syncNowPlaying()
    }

    func updateNowPlayingArtwork(url: String?) {
        guard let urlString = url, let imageURL = URL(string: urlString) else {
            nowPlayingArtwork = nil
            syncNowPlaying()
            return
        }

        URLSession.shared.dataTask(with: imageURL) { [weak self] data, _, _ in
            guard let self = self, let data = data, let image = UIImage(data: data) else { return }
            let artwork = MPMediaItemArtwork(boundsSize: image.size) { _ in image }
            DispatchQueue.main.async {
                self.nowPlayingArtwork = artwork
                self.syncNowPlaying()
            }
        }.resume()
    }

    private func syncNowPlaying() {
        var info = [String: Any]()
        if let title = nowPlayingTitle { info[MPMediaItemPropertyTitle] = title }
        if let artist = nowPlayingArtist { info[MPMediaItemPropertyArtist] = artist }
        if let album = nowPlayingAlbum { info[MPMediaItemPropertyAlbumTitle] = album }
        info[MPNowPlayingInfoPropertyElapsedPlaybackTime] = getCurrentTime()
        info[MPMediaItemPropertyPlaybackDuration] = getDuration()
        info[MPNowPlayingInfoPropertyPlaybackRate] = playerNode.isPlaying ? 1.0 : 0.0
        if let artwork = nowPlayingArtwork { info[MPMediaItemPropertyArtwork] = artwork }
        MPNowPlayingInfoCenter.default().nowPlayingInfo = info
    }

    // MARK: - FFT Analysis

    private func enableAnalysis() {
        guard !isAnalysisEnabled else { return }
        isAnalysisEnabled = true

        if fftSetup == nil {
            fftSetup = vDSP_create_fftsetup(NativeAudioEngine.analysisLog2n, FFTRadix(kFFTRadix2))
        }
        previousFrequencyData = nil

        let fftSize = NativeAudioEngine.analysisFFTSize
        let binCount = NativeAudioEngine.analysisBinCount
        let mixer = engine.mainMixerNode
        let format = mixer.outputFormat(forBus: 0)

        // Buffer to accumulate samples across tap callbacks
        var sampleBuffer = [Float]()
        sampleBuffer.reserveCapacity(fftSize)

        mixer.installTap(onBus: 0, bufferSize: AVAudioFrameCount(fftSize), format: format) {
            [weak self] buffer, _ in
            guard let self = self, self.isAnalysisEnabled, let fftSetup = self.fftSetup else { return }

            // Throttle to ~30fps
            let now = CFAbsoluteTimeGetCurrent()
            guard now - self.lastAnalysisTime >= NativeAudioEngine.analysisMinInterval else { return }

            guard let channelData = buffer.floatChannelData?[0] else { return }
            let frameCount = Int(buffer.frameLength)

            // Accumulate samples
            sampleBuffer.append(contentsOf: UnsafeBufferPointer(start: channelData, count: frameCount))

            guard sampleBuffer.count >= fftSize else { return }

            // Take exactly fftSize samples
            let samples = Array(sampleBuffer.prefix(fftSize))
            sampleBuffer.removeFirst(fftSize)

            self.lastAnalysisTime = now

            // --- Time domain: scale float [-1,1] → byte [0,255] centered at 128 ---
            var timeDomainBytes = [UInt8](repeating: 128, count: binCount)
            for i in 0..<binCount {
                let clamped = max(-1.0, min(1.0, samples[i]))
                timeDomainBytes[i] = UInt8(clamped * 127.0 + 128.0)
            }

            // --- FFT: apply window, compute magnitudes, convert to dB, scale to bytes ---
            var windowedSamples = samples

            // Apply Hanning window
            var window = [Float](repeating: 0, count: fftSize)
            vDSP_hann_window(&window, vDSP_Length(fftSize), Int32(vDSP_HANN_NORM))
            vDSP_vmul(samples, 1, window, 1, &windowedSamples, 1, vDSP_Length(fftSize))

            // Pack into split complex format for FFT
            let halfSize = fftSize / 2
            var realPart = [Float](repeating: 0, count: halfSize)
            var imagPart = [Float](repeating: 0, count: halfSize)

            windowedSamples.withUnsafeBufferPointer { ptr in
                ptr.baseAddress!.withMemoryRebound(to: DSPComplex.self, capacity: halfSize) { complexPtr in
                    var splitComplex = DSPSplitComplex(realp: &realPart, imagp: &imagPart)
                    vDSP_ctoz(complexPtr, 2, &splitComplex, 1, vDSP_Length(halfSize))
                }
            }

            // Forward FFT
            var splitComplex = DSPSplitComplex(realp: &realPart, imagp: &imagPart)
            vDSP_fft_zrip(fftSetup, &splitComplex, 1, NativeAudioEngine.analysisLog2n, FFTDirection(FFT_FORWARD))

            // Compute magnitudes
            var magnitudes = [Float](repeating: 0, count: halfSize)
            vDSP_zvmags(&splitComplex, 1, &magnitudes, 1, vDSP_Length(halfSize))

            // Square root to get actual magnitudes
            var sqrtMagnitudes = [Float](repeating: 0, count: halfSize)
            var count = Int32(halfSize)
            vvsqrtf(&sqrtMagnitudes, magnitudes, &count)

            // Scale by 1/fftSize
            var scale = 1.0 / Float(fftSize)
            vDSP_vsmul(sqrtMagnitudes, 1, &scale, &sqrtMagnitudes, 1, vDSP_Length(halfSize))

            // Convert to dB: 20 * log10(magnitude), clamp to [minDecibels, maxDecibels]
            let minDecibels: Float = -100
            let maxDecibels: Float = -30
            let rangeDecibels = maxDecibels - minDecibels

            var frequencyFloats = [Float](repeating: 0, count: binCount)
            for i in 0..<binCount {
                let mag = max(sqrtMagnitudes[i], 1e-20)  // avoid log(0)
                let dB = 20.0 * log10f(mag)
                let clamped = max(minDecibels, min(maxDecibels, dB))
                frequencyFloats[i] = (clamped - minDecibels) / rangeDecibels
            }

            // Smooth: 0.8 * previous + 0.2 * current (matching Web Audio smoothingTimeConstant)
            if let previous = self.previousFrequencyData {
                for i in 0..<binCount {
                    frequencyFloats[i] = 0.8 * previous[i] + 0.2 * frequencyFloats[i]
                }
            }
            self.previousFrequencyData = frequencyFloats

            // Scale to bytes [0, 255]
            var frequencyBytes = [UInt8](repeating: 0, count: binCount)
            for i in 0..<binCount {
                frequencyBytes[i] = UInt8(max(0, min(255, frequencyFloats[i] * 255.0)))
            }

            DispatchQueue.main.async { [weak self] in
                self?.delegate?.audioEngineDidUpdateAnalysis(
                    frequencyData: frequencyBytes,
                    timeDomainData: timeDomainBytes
                )
            }
        }
    }

    private func disableAnalysis() {
        guard isAnalysisEnabled else { return }
        isAnalysisEnabled = false
        engine.mainMixerNode.removeTap(onBus: 0)
    }

    // MARK: - Cleanup

    private func cleanupTempFile() {
        if let url = tempFileURL {
            try? FileManager.default.removeItem(at: url)
            tempFileURL = nil
        }
    }

    func cleanup() {
        stopInternal()
        downloadTask?.cancel()
        downloadTask = nil
        audioFile = nil
        cleanupTempFile()
        if let setup = fftSetup {
            vDSP_destroy_fftsetup(setup)
            fftSetup = nil
        }
        engine.stop()
        NotificationCenter.default.removeObserver(self)
    }

    deinit {
        cleanup()
    }
}
