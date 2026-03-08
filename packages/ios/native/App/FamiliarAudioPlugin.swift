import Capacitor
import Foundation

@objc(FamiliarAudioPlugin)
public class FamiliarAudioPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "FamiliarAudioPlugin"
    public let jsName = "FamiliarAudio"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "load", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "loadLocal", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "play", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "pause", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "resume", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "seek", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stop", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setVolume", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "getCurrentTime", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "getDuration", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "getIsPlaying", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setEQ", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setReverb", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setDelay", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setDistortion", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setCompressor", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setFilter", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setMasterBypass", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setNowPlayingInfo", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setPendingTrackInfo", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "preloadNext", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "preloadNextLocal", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "isNextReady", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "getPreloadingTrackId", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "isCrossfading", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "executeCrossfade", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "cancelCrossfade", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setNextNormalizationVolume", returnType: CAPPluginReturnPromise),
    ]

    private lazy var audioEngine: NativeAudioEngine = {
        let engine = NativeAudioEngine()
        engine.delegate = self
        return engine
    }()

    // MARK: - Playback

    @objc func load(_ call: CAPPluginCall) {
        guard let url = call.getString("url"),
              let trackId = call.getString("trackId") else {
            call.reject("Missing url or trackId")
            return
        }

        audioEngine.load(url: url, trackId: trackId) { error in
            if let error = error {
                call.reject("Failed to load: \(error.localizedDescription)")
            } else {
                call.resolve()
            }
        }
    }

    @objc func loadLocal(_ call: CAPPluginCall) {
        guard let path = call.getString("path"),
              let trackId = call.getString("trackId") else {
            call.reject("Missing path or trackId")
            return
        }

        audioEngine.loadLocal(path: path, trackId: trackId) { error in
            if let error = error {
                call.reject("Failed to load local file: \(error.localizedDescription)")
            } else {
                call.resolve()
            }
        }
    }

    @objc func play(_ call: CAPPluginCall) {
        audioEngine.play()
        call.resolve()
    }

    @objc func pause(_ call: CAPPluginCall) {
        audioEngine.pause()
        call.resolve()
    }

    @objc func resume(_ call: CAPPluginCall) {
        audioEngine.resume()
        call.resolve()
    }

    @objc func seek(_ call: CAPPluginCall) {
        let time = call.getDouble("time") ?? 0
        audioEngine.seek(time: time)
        call.resolve()
    }

    @objc func stop(_ call: CAPPluginCall) {
        audioEngine.stop()
        call.resolve()
    }

    @objc func setVolume(_ call: CAPPluginCall) {
        let vol = call.getFloat("volume") ?? 1.0
        audioEngine.setVolume(vol)
        call.resolve()
    }

    @objc func getCurrentTime(_ call: CAPPluginCall) {
        call.resolve(["currentTime": audioEngine.getCurrentTime()])
    }

    @objc func getDuration(_ call: CAPPluginCall) {
        call.resolve(["duration": audioEngine.getDuration()])
    }

    @objc func getIsPlaying(_ call: CAPPluginCall) {
        call.resolve(["isPlaying": audioEngine.getIsPlaying()])
    }

    // MARK: - Effects

    @objc func setEQ(_ call: CAPPluginCall) {
        let lowGain = call.getFloat("lowGain") ?? 0
        let midGain = call.getFloat("midGain") ?? 0
        let highGain = call.getFloat("highGain") ?? 0
        let lowFreq = call.getFloat("lowFreq")
        let midFreq = call.getFloat("midFreq")
        let highFreq = call.getFloat("highFreq")
        let enabled = call.getBool("enabled") ?? true
        audioEngine.setEQ(lowGain: lowGain, midGain: midGain, highGain: highGain,
                          lowFreq: lowFreq, midFreq: midFreq, highFreq: highFreq,
                          enabled: enabled)
        call.resolve()
    }

    @objc func setReverb(_ call: CAPPluginCall) {
        let preset = call.getString("preset") ?? "medium-room"
        let wetDryMix = call.getFloat("wetDryMix") ?? 0
        let enabled = call.getBool("enabled") ?? false
        let preDelay = call.getFloat("preDelay") ?? 0
        audioEngine.setReverb(preset: preset, wetDryMix: wetDryMix, enabled: enabled, preDelay: preDelay)
        call.resolve()
    }

    @objc func setDelay(_ call: CAPPluginCall) {
        let time = call.getDouble("time") ?? 0.3
        let feedback = call.getFloat("feedback") ?? 0
        let wetDryMix = call.getFloat("wetDryMix") ?? 0
        let enabled = call.getBool("enabled") ?? false
        let pingPong = call.getBool("pingPong") ?? false
        audioEngine.setDelay(time: time, feedback: feedback, wetDryMix: wetDryMix, enabled: enabled, pingPong: pingPong)
        call.resolve()
    }

    @objc func setDistortion(_ call: CAPPluginCall) {
        let preset = call.getString("preset") ?? "warm"
        let wetDryMix = call.getFloat("wetDryMix") ?? 0
        let enabled = call.getBool("enabled") ?? false
        let drive = call.getFloat("drive") ?? 1
        audioEngine.setDistortion(preset: preset, wetDryMix: wetDryMix, enabled: enabled, drive: drive)
        call.resolve()
    }

    @objc func setCompressor(_ call: CAPPluginCall) {
        let threshold = call.getFloat("threshold") ?? -24
        let ratio = call.getFloat("ratio") ?? 4
        let attack = call.getFloat("attack") ?? 0.003
        let release = call.getFloat("release") ?? 0.25
        let knee = call.getFloat("knee") ?? 30
        let makeupGain = call.getFloat("makeupGain") ?? 0
        let enabled = call.getBool("enabled") ?? false
        audioEngine.setCompressor(threshold: threshold, ratio: ratio, attack: attack,
                                  release: release, knee: knee, makeupGain: makeupGain, enabled: enabled)
        call.resolve()
    }

    @objc func setFilter(_ call: CAPPluginCall) {
        let highpassFreq = call.getFloat("highpassFreq") ?? 20
        let lowpassFreq = call.getFloat("lowpassFreq") ?? 20000
        let highpassQ = call.getFloat("highpassQ") ?? 0.7
        let lowpassQ = call.getFloat("lowpassQ") ?? 0.7
        let enabled = call.getBool("enabled") ?? false
        audioEngine.setFilter(highpassFreq: highpassFreq, lowpassFreq: lowpassFreq,
                              highpassQ: highpassQ, lowpassQ: lowpassQ, enabled: enabled)
        call.resolve()
    }


    @objc func setMasterBypass(_ call: CAPPluginCall) {
        let bypassed = call.getBool("bypassed") ?? false
        audioEngine.setMasterBypass(bypassed)
        call.resolve()
    }

    // MARK: - Now Playing

    @objc func setNowPlayingInfo(_ call: CAPPluginCall) {
        let title = call.getString("title")
        let artist = call.getString("artist")
        let album = call.getString("album")
        let artworkUrl = call.getString("artworkUrl")
        audioEngine.updateNowPlayingInfo(title: title, artist: artist, album: album)
        audioEngine.updateNowPlayingArtwork(url: artworkUrl)
        call.resolve()
    }

    @objc func setPendingTrackInfo(_ call: CAPPluginCall) {
        let nextUrl = call.getString("nextUrl")
        let nextTrackId = call.getString("nextTrackId")
        let nextTitle = call.getString("nextTitle")
        let nextArtist = call.getString("nextArtist")
        let nextAlbum = call.getString("nextAlbum")
        let nextArtworkUrl = call.getString("nextArtworkUrl")
        audioEngine.setPendingNext(
            url: nextUrl, trackId: nextTrackId,
            title: nextTitle, artist: nextArtist,
            album: nextAlbum, artworkUrl: nextArtworkUrl
        )

        let prevUrl = call.getString("prevUrl")
        let prevTrackId = call.getString("prevTrackId")
        let prevTitle = call.getString("prevTitle")
        let prevArtist = call.getString("prevArtist")
        let prevAlbum = call.getString("prevAlbum")
        let prevArtworkUrl = call.getString("prevArtworkUrl")
        audioEngine.setPendingPrevious(
            url: prevUrl, trackId: prevTrackId,
            title: prevTitle, artist: prevArtist,
            album: prevAlbum, artworkUrl: prevArtworkUrl
        )

        call.resolve()
    }

    // MARK: - Crossfade

    @objc func preloadNext(_ call: CAPPluginCall) {
        guard let url = call.getString("url"),
              let trackId = call.getString("trackId") else {
            call.reject("Missing url or trackId")
            return
        }
        audioEngine.preloadNext(url: url, trackId: trackId) { success, state, reason in
            call.resolve([
                "success": success,
                "state": preloadStateName(state),
                "reason": reason as Any,
            ])
        }
    }

    @objc func preloadNextLocal(_ call: CAPPluginCall) {
        guard let path = call.getString("path"),
              let trackId = call.getString("trackId") else {
            call.reject("Missing path or trackId")
            return
        }
        audioEngine.preloadNextLocal(path: path, trackId: trackId) { success, state, reason in
            call.resolve([
                "success": success,
                "state": preloadStateName(state),
                "reason": reason as Any,
            ])
        }
    }

    @objc func isNextReady(_ call: CAPPluginCall) {
        call.resolve(["ready": audioEngine.isNextReady()])
    }

    @objc func getPreloadingTrackId(_ call: CAPPluginCall) {
        let trackId = audioEngine.getPreloadingTrackId()
        if let trackId = trackId {
            call.resolve(["trackId": trackId])
        } else {
            call.resolve(["trackId": NSNull()])
        }
    }

    @objc func isCrossfading(_ call: CAPPluginCall) {
        call.resolve(["crossfading": audioEngine.isCrossfading()])
    }

    @objc func executeCrossfade(_ call: CAPPluginCall) {
        let duration = call.getDouble("duration") ?? 2.0
        audioEngine.executeCrossfade(duration: duration) { success, reason in
            call.resolve([
                "success": success,
                "reason": reason as Any,
            ])
        }
    }

    @objc func cancelCrossfade(_ call: CAPPluginCall) {
        audioEngine.cancelCrossfade()
        call.resolve()
    }

    @objc func setNextNormalizationVolume(_ call: CAPPluginCall) {
        let volume = call.getFloat("volume") ?? 1.0
        audioEngine.setNextNormalizationVolume(volume)
        call.resolve()
    }
}

// MARK: - NativeAudioEngineDelegate

extension FamiliarAudioPlugin: NativeAudioEngineDelegate {
    func audioEngineDidFinishPlaying() {
        notifyListeners("ended", data: [:])
    }

    func audioEngineDidUpdateTime(currentTime: Double, duration: Double) {
        notifyListeners("timeUpdate", data: [
            "currentTime": currentTime,
            "duration": duration,
        ])
    }

    func audioEngineDidEncounterError(message: String, category: NativeAudioEngine.NativeAudioErrorCategory) {
        notifyListeners("error", data: [
            "message": message,
            "category": category.rawValue,
        ])
    }

    func audioEngineRemotePlay() {
        notifyListeners("remotePlay", data: [:])
    }

    func audioEngineRemotePause() {
        notifyListeners("remotePause", data: [:])
    }

    func audioEngineRemoteNext(loadedTrackId: String?) {
        var data: [String: Any] = [:]
        if let trackId = loadedTrackId { data["loadedTrackId"] = trackId }
        notifyListeners("remoteNext", data: data)
    }

    func audioEngineRemotePrevious(nativeAction: String?, loadedTrackId: String?) {
        var data: [String: Any] = [:]
        if let action = nativeAction { data["nativeAction"] = action }
        if let trackId = loadedTrackId { data["loadedTrackId"] = trackId }
        notifyListeners("remotePrevious", data: data)
    }

    func audioEngineRemoteSeek(time: Double) {
        notifyListeners("remoteSeek", data: ["time": time])
    }

    func audioEngineDidUpdateAnalysis(frequencyData: [UInt8], timeDomainData: [UInt8]) {
        notifyListeners("audioAnalysis", data: [
            "frequencyData": frequencyData,
            "timeDomainData": timeDomainData,
        ])
    }
}

private func preloadStateName(_ state: NativeAudioEngine.PreloadState) -> String {
    switch state {
    case .idle:
        return "idle"
    case .preloading:
        return "preloading"
    case .ready:
        return "ready"
    case .failed:
        return "failed"
    }
}
