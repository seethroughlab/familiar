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
    func audioEngineRemoteNext(loadedTrackId: String?)
    func audioEngineRemotePrevious(nativeAction: String?, loadedTrackId: String?)
    func audioEngineRemoteSeek(time: Double)
}

class NativeAudioEngine {
    weak var delegate: NativeAudioEngineDelegate?

    private let engine = AVAudioEngine()
    private var playerNodes: [AVAudioPlayerNode] = [AVAudioPlayerNode(), AVAudioPlayerNode()]
    private var activePlayerIndex = 0
    private var playerNode: AVAudioPlayerNode { playerNodes[activePlayerIndex] }
    private var nextPlayerNode: AVAudioPlayerNode { playerNodes[1 - activePlayerIndex] }
    private let inputMixer = AVAudioMixerNode()
    private let eqNode: AVAudioUnitEQ
    private let reverbNode = AVAudioUnitReverb()
    private let delayNode = AVAudioUnitDelay()
    private let distortionNode = AVAudioUnitDistortion()

    // Additional built-in effect nodes
    private var compressorNode: AVAudioUnitEffect?
    private let filterNode: AVAudioUnitEQ          // 2-band: highpass + lowpass
    private let reverbPreDelayNode = AVAudioUnitDelay() // Pure delay before reverb for preDelay


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

    // Crossfade state
    private var nextAudioFile: AVAudioFile?
    private var nextTempFileURL: URL?
    private var nextTrackId: String?
    private var preloadingTrackId: String?
    private var nextDownloadTask: URLSessionDataTask?
    private var isCrossfadingFlag = false
    private var crossfadeTimer: Timer?
    private var nextNormalizationVolume: Float = 1.0

    // Now Playing metadata
    private var nowPlayingTitle: String?
    private var nowPlayingArtist: String?
    private var nowPlayingAlbum: String?
    private var nowPlayingArtwork: MPMediaItemArtwork?

    // Pending next/previous track info (pre-synced from JS for lock screen control)
    private var pendingNextUrl: String?
    private var pendingNextTrackId: String?
    private var pendingNextTitle: String?
    private var pendingNextArtist: String?
    private var pendingNextAlbum: String?
    private var pendingNextArtworkUrl: String?

    private var pendingPreviousUrl: String?
    private var pendingPreviousTrackId: String?
    private var pendingPreviousTitle: String?
    private var pendingPreviousArtist: String?
    private var pendingPreviousAlbum: String?
    private var pendingPreviousArtworkUrl: String?

    // FFT analysis
    private static let analysisFFTSize = 256
    private static let analysisBinCount = 128  // fftSize / 2
    private static let analysisLog2n = vDSP_Length(log2(Double(analysisFFTSize)))
    private var fftSetup: FFTSetup?
    private var previousFrequencyData: [Float]?
    private var isAnalysisEnabled = false
    private var lastAnalysisTime: CFAbsoluteTime = 0
    private static let analysisMinInterval: CFAbsoluteTime = 1.0 / 60.0  // ~60fps

    // Pre-allocated FFT work buffers (reused each frame to avoid per-frame allocations)
    private var fftWindow: [Float]?
    private var fftWindowedSamples: [Float]?
    private var fftRealPart: [Float]?
    private var fftImagPart: [Float]?
    private var fftMagnitudes: [Float]?
    private var fftSqrtMagnitudes: [Float]?
    private var fftFrequencyFloats: [Float]?
    private var fftFrequencyBytes: [UInt8]?
    private var fftTimeDomainBytes: [UInt8]?

    // MARK: - Initialization

    init() {
        eqNode = AVAudioUnitEQ(numberOfBands: 3)
        filterNode = AVAudioUnitEQ(numberOfBands: 2)
        setupEQBands()
        setupFilterBands()
        setupCompressorNode()
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

    private func setupFilterBands() {
        // Band 0: Highpass
        let hpBand = filterNode.bands[0]
        hpBand.filterType = .highPass
        hpBand.frequency = 20
        hpBand.bandwidth = 0.7
        hpBand.bypass = false

        // Band 1: Lowpass
        let lpBand = filterNode.bands[1]
        lpBand.filterType = .lowPass
        lpBand.frequency = 20000
        lpBand.bandwidth = 0.7
        lpBand.bypass = false

        // Start bypassed
        filterNode.bypass = true
    }

    private func setupCompressorNode() {
        let desc = AudioComponentDescription(
            componentType: kAudioUnitType_Effect,
            componentSubType: kAudioUnitSubType_DynamicsProcessor,
            componentManufacturer: kAudioUnitManufacturer_Apple,
            componentFlags: 0,
            componentFlagsMask: 0
        )
        compressorNode = AVAudioUnitEffect(audioComponentDescription: desc)
        compressorNode?.bypass = true
    }


    private func setupAudioGraph() {
        engine.attach(playerNodes[0])
        engine.attach(playerNodes[1])
        engine.attach(inputMixer)
        engine.attach(eqNode)
        if let comp = compressorNode { engine.attach(comp) }
        engine.attach(distortionNode)
        engine.attach(filterNode)
        engine.attach(delayNode)
        engine.attach(reverbPreDelayNode)
        engine.attach(reverbNode)

        // Default effect states
        reverbNode.wetDryMix = 0
        delayNode.wetDryMix = 0
        distortionNode.wetDryMix = 0
        reverbPreDelayNode.bypass = true     // start bypassed — its lowPassCutoff filters even at 0ms delay
        reverbPreDelayNode.wetDryMix = 100  // pure pass-through
        reverbPreDelayNode.feedback = 0
        reverbPreDelayNode.delayTime = 0
        reverbPreDelayNode.lowPassCutoff = 20000

        // Connect initial chain
        let format = engine.mainMixerNode.outputFormat(forBus: 0)
        connectChain(format: format)

        setupInterruptionHandling()
    }

    /// Build the ordered effect chain and connect nodes sequentially.
    /// Chain order: playerNodes[0,1] → inputMixer → EQ → Compressor → Distortion → Filter → Delay → preDelay → Reverb → mainMixer
    private func connectChain(format: AVAudioFormat) {
        engine.connect(playerNodes[0], to: inputMixer, format: format)
        engine.connect(playerNodes[1], to: inputMixer, format: format)

        var chain: [AVAudioNode] = [inputMixer, eqNode]
        if let comp = compressorNode { chain.append(comp) }
        chain.append(distortionNode)
        chain.append(filterNode)
        chain.append(delayNode)
        chain.append(reverbPreDelayNode)
        chain.append(reverbNode)
        chain.append(engine.mainMixerNode)

        for i in 0..<(chain.count - 1) {
            engine.connect(chain[i], to: chain[i + 1], format: format)
        }
    }

    /// Disconnect all effect node outputs before reconnecting.
    private func disconnectAllEffectNodes() {
        let nodes: [AVAudioNode?] = [
            playerNodes[0], playerNodes[1], inputMixer,
            eqNode, compressorNode, distortionNode, filterNode,
            delayNode, reverbPreDelayNode, reverbNode,
        ]
        for node in nodes {
            if let node = node {
                engine.disconnectNodeOutput(node)
            }
        }
    }

    /// Rebuild the signal chain with a given format (called on track load and custom node readiness).
    private func reconnectChain(format: AVAudioFormat) {
        disconnectAllEffectNodes()
        connectChain(format: format)
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

        // Clean up previous temp file before starting a new download
        cleanupTempFile()

        // Download audio to temp file (AVAudioPlayerNode requires local files).
        // We defer the file extension decision until we know the MIME type from the HTTP response.
        let tempDir = NSTemporaryDirectory()
        let tempBaseName = "familiar_audio_\(trackId)"

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

            // Determine file extension from the HTTP response MIME type
            let mimeType = (response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Type")
            let fileExtension = NativeAudioEngine.extensionForMIME(mimeType)
            let tempPath = (tempDir as NSString).appendingPathComponent("\(tempBaseName).\(fileExtension)")
            let tempURL = URL(fileURLWithPath: tempPath)
            self.tempFileURL = tempURL

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
        reconnectChain(format: processingFormat)

        let scheduledIndex = activePlayerIndex
        playerNode.scheduleFile(file, at: nil) { [weak self] in
            guard let self = self else { return }
            // This fires when the scheduled buffer/file finishes.
            // Check if we actually played to the end (vs being stopped/seeked).
            DispatchQueue.main.async {
                guard self.activePlayerIndex == scheduledIndex else { return }
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

        // Cancel any in-progress crossfade and preload
        crossfadeTimer?.invalidate()
        crossfadeTimer = nil
        isCrossfadingFlag = false
        playerNode.volume = 1.0

        nextDownloadTask?.cancel()
        nextDownloadTask = nil
        nextPlayerNode.stop()
        nextPlayerNode.volume = 1.0
        cleanupNextTempFile()
        nextTrackId = nil
        nextAudioFile = nil
        preloadingTrackId = nil
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
               lowFreq: Float? = nil, midFreq: Float? = nil, highFreq: Float? = nil,
               enabled: Bool = true) {
        if masterBypassed || !enabled {
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

    func setReverb(preset: String, wetDryMix: Float, enabled: Bool, preDelay: Float = 0) {
        if masterBypassed || !enabled {
            reverbNode.bypass = true
            reverbPreDelayNode.bypass = true
            return
        }
        reverbNode.bypass = false
        reverbPreDelayNode.bypass = false
        reverbPreDelayNode.delayTime = Double(preDelay) / 1000.0 // ms → seconds

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

    func setDelay(time: Double, feedback: Float, wetDryMix: Float, enabled: Bool, pingPong: Bool = false) {
        // pingPong: accepted but no-op on native (AVAudioUnitDelay is mono)
        if masterBypassed || !enabled {
            delayNode.bypass = true
            return
        }
        delayNode.bypass = false

        delayNode.delayTime = time
        delayNode.feedback = feedback * 100 // AVAudioUnitDelay uses -100 to 100
        delayNode.wetDryMix = wetDryMix * 100
    }

    // MARK: - Effects: Distortion (Saturation)

    func setDistortion(preset: String, wetDryMix: Float, enabled: Bool, drive: Float = 1) {
        if masterBypassed || !enabled {
            distortionNode.bypass = true
            return
        }
        distortionNode.bypass = false

        let avPreset = distortionPreset(from: preset)
        distortionNode.loadFactoryPreset(avPreset)
        distortionNode.wetDryMix = wetDryMix * 100
        // Map drive 1–5 → preGain 0–14 dB
        distortionNode.preGain = (drive - 1) * 3.5
    }

    private func distortionPreset(from name: String) -> AVAudioUnitDistortionPreset {
        switch name {
        case "warm": return .drumsBitBrush
        case "tape": return .speechCosmicInterference
        case "hard": return .drumsLoFi
        default: return .drumsBitBrush
        }
    }

    // MARK: - Effects: Compressor

    func setCompressor(threshold: Float, ratio: Float, attack: Float, release: Float,
                       knee: Float, makeupGain: Float, enabled: Bool) {
        guard let comp = compressorNode else { return }

        if masterBypassed || !enabled {
            comp.bypass = true
            return
        }

        comp.bypass = false
        let au = comp.audioUnit
        // kDynamicsProcessorParam_Threshold = 0
        AudioUnitSetParameter(au, 0, kAudioUnitScope_Global, 0, threshold, 0)
        // kDynamicsProcessorParam_HeadRoom = 1 (approximate knee)
        AudioUnitSetParameter(au, 1, kAudioUnitScope_Global, 0, knee, 0)
        // kDynamicsProcessorParam_ExpansionRatio = 2 — not used
        // kDynamicsProcessorParam_AttackTime = 4
        let clampedAttack = max(0.0001, min(0.2, attack))
        AudioUnitSetParameter(au, 4, kAudioUnitScope_Global, 0, clampedAttack, 0)
        // kDynamicsProcessorParam_ReleaseTime = 5
        AudioUnitSetParameter(au, 5, kAudioUnitScope_Global, 0, release, 0)
        // kDynamicsProcessorParam_MasterGain = 6
        AudioUnitSetParameter(au, 6, kAudioUnitScope_Global, 0, makeupGain, 0)
    }

    // MARK: - Effects: Filter

    func setFilter(highpassFreq: Float, lowpassFreq: Float,
                   highpassQ: Float, lowpassQ: Float, enabled: Bool) {
        if masterBypassed || !enabled {
            filterNode.bypass = true
            return
        }

        filterNode.bypass = false
        filterNode.bands[0].frequency = highpassFreq
        filterNode.bands[0].bandwidth = highpassQ
        filterNode.bands[1].frequency = lowpassFreq
        filterNode.bands[1].bandwidth = lowpassQ
    }

    // MARK: - Master Bypass

    func setMasterBypass(_ bypassed: Bool) {
        masterBypassed = bypassed
        if bypassed {
            eqNode.bypass = true
            compressorNode?.bypass = true
            filterNode.bypass = true
            reverbNode.bypass = true
            reverbPreDelayNode.bypass = true
            delayNode.bypass = true
            distortionNode.bypass = true
        }
    }

    // MARK: - Crossfade

    func preloadNext(url: String, trackId: String, completion: @escaping (Bool) -> Void) {
        // Already preloaded for this track — idempotent
        if nextTrackId == trackId {
            completion(true)
            return
        }
        // Already preloading this track — in-flight, report not ready yet
        if preloadingTrackId == trackId {
            completion(false)
            return
        }

        // Cancel any previous preload for a different track
        nextDownloadTask?.cancel()
        nextDownloadTask = nil
        nextPlayerNode.stop()
        cleanupNextTempFile()
        nextTrackId = nil
        nextAudioFile = nil

        preloadingTrackId = trackId

        guard let sourceURL = URL(string: url) else {
            preloadingTrackId = nil
            completion(false)
            return
        }

        let tempDir = NSTemporaryDirectory()
        let tempBaseName = "familiar_next_\(trackId)"

        let task = URLSession.shared.dataTask(with: sourceURL) { [weak self] data, response, error in
            guard let self = self else { return }
            guard self.preloadingTrackId == trackId else { return }

            if let error = error {
                if (error as NSError).code == NSURLErrorCancelled { return }
                DispatchQueue.main.async {
                    self.preloadingTrackId = nil
                    completion(false)
                }
                return
            }

            guard let data = data else {
                DispatchQueue.main.async {
                    self.preloadingTrackId = nil
                    completion(false)
                }
                return
            }

            let mimeType = (response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Type")
            let fileExtension = NativeAudioEngine.extensionForMIME(mimeType)
            let tempPath = (tempDir as NSString).appendingPathComponent("\(tempBaseName).\(fileExtension)")
            let tempURL = URL(fileURLWithPath: tempPath)

            do {
                try data.write(to: tempURL)
                let file = try AVAudioFile(forReading: tempURL)

                DispatchQueue.main.async {
                    guard self.preloadingTrackId == trackId else {
                        try? FileManager.default.removeItem(at: tempURL)
                        return
                    }
                    self.nextTempFileURL = tempURL
                    self.nextAudioFile = file
                    self.nextTrackId = trackId
                    self.preloadingTrackId = nil
                    completion(true)
                }
            } catch {
                DispatchQueue.main.async {
                    self.preloadingTrackId = nil
                    completion(false)
                }
            }
        }
        self.nextDownloadTask = task
        task.resume()
    }

    func isNextReady() -> Bool {
        return nextTrackId != nil
    }

    func getPreloadingTrackId() -> String? {
        return preloadingTrackId
    }

    func isCrossfading() -> Bool {
        return isCrossfadingFlag
    }

    func setNextNormalizationVolume(_ vol: Float) {
        nextNormalizationVolume = vol
    }

    func executeCrossfade(duration: Double, completion: @escaping () -> Void) {
        guard let nextFile = nextAudioFile, let nextId = nextTrackId else {
            completion()
            return
        }

        let capturedNextTrackId = nextId
        let capturedNextAudioFile = nextFile
        let capturedNextTempFileURL = nextTempFileURL

        isCrossfadingFlag = true

        // Stop nextPlayerNode (clears previous schedule), then re-schedule with the end-of-track handler
        nextPlayerNode.stop()
        let nextIndex = 1 - activePlayerIndex
        nextPlayerNode.scheduleFile(capturedNextAudioFile, at: nil) { [weak self] in
            guard let self = self else { return }
            DispatchQueue.main.async {
                guard self.activePlayerIndex == nextIndex else { return }
                if self.isPlayerScheduled && !self.isPaused {
                    self.isPlayerScheduled = false
                    self.stopTimeUpdates()
                    self.delegate?.audioEngineDidFinishPlaying()
                }
            }
        }

        nextPlayerNode.volume = 0.0

        if !engine.isRunning {
            try? engine.start()
        }
        nextPlayerNode.play()

        let startTime = Date()
        crossfadeTimer = Timer.scheduledTimer(withTimeInterval: 1.0 / 60.0, repeats: true) { [weak self] timer in
            guard let self = self else { timer.invalidate(); return }
            let elapsed = Date().timeIntervalSince(startTime)
            let progress = min(elapsed / duration, 1.0)

            self.playerNode.volume = 1.0 - Float(progress)
            self.nextPlayerNode.volume = self.nextNormalizationVolume * Float(progress)

            if progress >= 1.0 {
                self.finishCrossfade(
                    nextTrackId: capturedNextTrackId,
                    nextAudioFile: capturedNextAudioFile,
                    nextTempFileURL: capturedNextTempFileURL,
                    completion: completion
                )
            }
        }
    }

    private func finishCrossfade(
        nextTrackId: String,
        nextAudioFile: AVAudioFile,
        nextTempFileURL: URL?,
        completion: @escaping () -> Void
    ) {
        crossfadeTimer?.invalidate()
        crossfadeTimer = nil

        // Stop and reset the old current player (before index swap)
        playerNode.stop()
        playerNode.volume = 1.0

        // Swap — playerNode now points to the formerly-next player
        activePlayerIndex = 1 - activePlayerIndex

        // Update current track state
        currentTrackId = nextTrackId
        audioFile = nextAudioFile

        // Replace current temp file with the next track's file
        cleanupTempFile()
        tempFileURL = nextTempFileURL
        self.nextTempFileURL = nil  // already handed off above; prevent double-cleanup

        // Reset playback state for the new current track
        isPlayerScheduled = true
        isPaused = false
        startFramePosition = 0
        pauseFramePosition = 0

        // Clear next-track state
        self.nextTrackId = nil
        self.nextAudioFile = nil
        nextNormalizationVolume = 1.0
        isCrossfadingFlag = false

        startTimeUpdates()  // ensure timer is running for the new track
        completion()
    }

    func cancelCrossfade() {
        crossfadeTimer?.invalidate()
        crossfadeTimer = nil
        nextPlayerNode.stop()
        nextPlayerNode.volume = 1.0
        playerNode.volume = 1.0
        isCrossfadingFlag = false
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

    // MARK: - Pending Track Info (for lock screen next/previous)

    func setPendingNext(url: String?, trackId: String?, title: String?, artist: String?, album: String?, artworkUrl: String?) {
        pendingNextUrl = url
        pendingNextTrackId = trackId
        pendingNextTitle = title
        pendingNextArtist = artist
        pendingNextAlbum = album
        pendingNextArtworkUrl = artworkUrl
    }

    func setPendingPrevious(url: String?, trackId: String?, title: String?, artist: String?, album: String?, artworkUrl: String?) {
        pendingPreviousUrl = url
        pendingPreviousTrackId = trackId
        pendingPreviousTitle = title
        pendingPreviousArtist = artist
        pendingPreviousAlbum = album
        pendingPreviousArtworkUrl = artworkUrl
    }

    // MARK: - Now Playing

    private func setupRemoteCommands() {
        let commandCenter = MPRemoteCommandCenter.shared()

        commandCenter.playCommand.isEnabled = true
        commandCenter.playCommand.addTarget { [weak self] _ in
            guard let self = self else { return .commandFailed }
            self.play()
            self.delegate?.audioEngineRemotePlay()
            return .success
        }

        commandCenter.pauseCommand.isEnabled = true
        commandCenter.pauseCommand.addTarget { [weak self] _ in
            guard let self = self else { return .commandFailed }
            self.pause()
            self.delegate?.audioEngineRemotePause()
            return .success
        }

        commandCenter.nextTrackCommand.isEnabled = true
        commandCenter.nextTrackCommand.addTarget { [weak self] _ in
            guard let self = self else { return .commandFailed }

            if let url = self.pendingNextUrl, let trackId = self.pendingNextTrackId {
                // Load and play natively — no JS needed
                let title = self.pendingNextTitle
                let artist = self.pendingNextArtist
                let album = self.pendingNextAlbum
                let artworkUrl = self.pendingNextArtworkUrl

                // Clear pending info before async load
                self.setPendingNext(url: nil, trackId: nil, title: nil, artist: nil, album: nil, artworkUrl: nil)

                self.load(url: url, trackId: trackId) { [weak self] error in
                    guard let self = self, error == nil else {
                        // Load failed — fall through to JS
                        self?.delegate?.audioEngineRemoteNext(loadedTrackId: nil)
                        return
                    }
                    self.play()
                    self.updateNowPlayingInfo(title: title, artist: artist, album: album)
                    self.updateNowPlayingArtwork(url: artworkUrl)
                    self.delegate?.audioEngineRemoteNext(loadedTrackId: trackId)
                }
            } else {
                self.delegate?.audioEngineRemoteNext(loadedTrackId: nil)
            }

            return .success
        }

        commandCenter.previousTrackCommand.isEnabled = true
        commandCenter.previousTrackCommand.addTarget { [weak self] _ in
            guard let self = self else { return .commandFailed }

            // If more than 3 seconds in, restart the current track
            if self.getCurrentTime() > 3 {
                self.seek(time: 0)
                self.syncNowPlaying()
                self.delegate?.audioEngineRemotePrevious(nativeAction: "restart", loadedTrackId: nil)
                return .success
            }

            if let url = self.pendingPreviousUrl, let trackId = self.pendingPreviousTrackId {
                // Load and play natively — no JS needed
                let title = self.pendingPreviousTitle
                let artist = self.pendingPreviousArtist
                let album = self.pendingPreviousAlbum
                let artworkUrl = self.pendingPreviousArtworkUrl

                // Clear pending info before async load
                self.setPendingPrevious(url: nil, trackId: nil, title: nil, artist: nil, album: nil, artworkUrl: nil)

                self.load(url: url, trackId: trackId) { [weak self] error in
                    guard let self = self, error == nil else {
                        self?.delegate?.audioEngineRemotePrevious(nativeAction: nil, loadedTrackId: nil)
                        return
                    }
                    self.play()
                    self.updateNowPlayingInfo(title: title, artist: artist, album: album)
                    self.updateNowPlayingArtwork(url: artworkUrl)
                    self.delegate?.audioEngineRemotePrevious(nativeAction: nil, loadedTrackId: trackId)
                }
            } else {
                self.delegate?.audioEngineRemotePrevious(nativeAction: nil, loadedTrackId: nil)
            }

            return .success
        }

        commandCenter.changePlaybackPositionCommand.isEnabled = true
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
        let halfSize = fftSize / 2
        let mixer = engine.mainMixerNode
        let format = mixer.outputFormat(forBus: 0)

        // Pre-allocate all work buffers once (reused every frame)
        var window = [Float](repeating: 0, count: fftSize)
        vDSP_hann_window(&window, vDSP_Length(fftSize), Int32(vDSP_HANN_NORM))
        fftWindow = window
        fftWindowedSamples = [Float](repeating: 0, count: fftSize)
        fftRealPart = [Float](repeating: 0, count: halfSize)
        fftImagPart = [Float](repeating: 0, count: halfSize)
        fftMagnitudes = [Float](repeating: 0, count: halfSize)
        fftSqrtMagnitudes = [Float](repeating: 0, count: halfSize)
        fftFrequencyFloats = [Float](repeating: 0, count: binCount)
        fftFrequencyBytes = [UInt8](repeating: 0, count: binCount)
        fftTimeDomainBytes = [UInt8](repeating: 128, count: binCount)

        // Buffer to accumulate samples across tap callbacks
        var sampleBuffer = [Float]()
        sampleBuffer.reserveCapacity(fftSize)

        mixer.installTap(onBus: 0, bufferSize: AVAudioFrameCount(fftSize), format: format) {
            [weak self] buffer, _ in
            guard let self = self, self.isAnalysisEnabled, let fftSetup = self.fftSetup,
                  var windowedSamples = self.fftWindowedSamples,
                  let window = self.fftWindow,
                  var realPart = self.fftRealPart,
                  var imagPart = self.fftImagPart,
                  var magnitudes = self.fftMagnitudes,
                  var sqrtMagnitudes = self.fftSqrtMagnitudes,
                  var frequencyFloats = self.fftFrequencyFloats,
                  var frequencyBytes = self.fftFrequencyBytes,
                  var timeDomainBytes = self.fftTimeDomainBytes else { return }

            // Throttle to ~60fps
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
            for i in 0..<binCount {
                let clamped = max(-1.0, min(1.0, samples[i]))
                timeDomainBytes[i] = UInt8(clamped * 127.0 + 128.0)
            }

            // --- FFT: apply window, compute magnitudes, convert to dB, scale to bytes ---
            vDSP_vmul(samples, 1, window, 1, &windowedSamples, 1, vDSP_Length(fftSize))

            // Pack into split complex format for FFT
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
            vDSP_zvmags(&splitComplex, 1, &magnitudes, 1, vDSP_Length(halfSize))

            // Square root to get actual magnitudes
            var count = Int32(halfSize)
            vvsqrtf(&sqrtMagnitudes, magnitudes, &count)

            // Scale by 1/fftSize
            var scale = 1.0 / Float(fftSize)
            vDSP_vsmul(sqrtMagnitudes, 1, &scale, &sqrtMagnitudes, 1, vDSP_Length(halfSize))

            // Convert to dB: 20 * log10(magnitude), clamp to [minDecibels, maxDecibels]
            let minDecibels: Float = -100
            let maxDecibels: Float = -30
            let rangeDecibels = maxDecibels - minDecibels

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

        // Release work buffers
        fftWindow = nil
        fftWindowedSamples = nil
        fftRealPart = nil
        fftImagPart = nil
        fftMagnitudes = nil
        fftSqrtMagnitudes = nil
        fftFrequencyFloats = nil
        fftFrequencyBytes = nil
        fftTimeDomainBytes = nil
    }

    // MARK: - MIME → Extension

    private static func extensionForMIME(_ mime: String?) -> String {
        switch mime?.lowercased() {
        case "audio/mpeg":  return "mp3"
        case "audio/flac":  return "flac"
        case "audio/mp4":   return "m4a"
        case "audio/aac":   return "m4a"
        case "audio/wav", "audio/x-wav":  return "wav"
        case "audio/aiff", "audio/x-aiff": return "aif"
        default:            return "mp3"
        }
    }

    // MARK: - Cleanup

    private func cleanupTempFile() {
        if let url = tempFileURL {
            try? FileManager.default.removeItem(at: url)
            tempFileURL = nil
        }
    }

    private func cleanupNextTempFile() {
        if let url = nextTempFileURL {
            try? FileManager.default.removeItem(at: url)
            nextTempFileURL = nil
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
