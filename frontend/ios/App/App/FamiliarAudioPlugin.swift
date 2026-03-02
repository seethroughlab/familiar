import Capacitor
import Foundation

@objc(FamiliarAudioPlugin)
public class FamiliarAudioPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "FamiliarAudioPlugin"
    public let jsName = "FamiliarAudio"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "load", returnType: CAPPluginReturnPromise),
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
        CAPPluginMethod(name: "setMasterBypass", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setNowPlayingInfo", returnType: CAPPluginReturnPromise),
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
        audioEngine.setEQ(lowGain: lowGain, midGain: midGain, highGain: highGain,
                          lowFreq: lowFreq, midFreq: midFreq, highFreq: highFreq)
        call.resolve()
    }

    @objc func setReverb(_ call: CAPPluginCall) {
        let preset = call.getString("preset") ?? "medium-room"
        let wetDryMix = call.getFloat("wetDryMix") ?? 0
        let enabled = call.getBool("enabled") ?? false
        audioEngine.setReverb(preset: preset, wetDryMix: wetDryMix, enabled: enabled)
        call.resolve()
    }

    @objc func setDelay(_ call: CAPPluginCall) {
        let time = call.getDouble("time") ?? 0.3
        let feedback = call.getFloat("feedback") ?? 0
        let wetDryMix = call.getFloat("wetDryMix") ?? 0
        let enabled = call.getBool("enabled") ?? false
        audioEngine.setDelay(time: time, feedback: feedback, wetDryMix: wetDryMix, enabled: enabled)
        call.resolve()
    }

    @objc func setDistortion(_ call: CAPPluginCall) {
        let preset = call.getString("preset") ?? "warm"
        let wetDryMix = call.getFloat("wetDryMix") ?? 0
        let enabled = call.getBool("enabled") ?? false
        audioEngine.setDistortion(preset: preset, wetDryMix: wetDryMix, enabled: enabled)
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

    func audioEngineDidEncounterError(message: String) {
        notifyListeners("error", data: ["message": message])
    }

    func audioEngineRemotePlay() {
        notifyListeners("remotePlay", data: [:])
    }

    func audioEngineRemotePause() {
        notifyListeners("remotePause", data: [:])
    }

    func audioEngineRemoteNext() {
        notifyListeners("remoteNext", data: [:])
    }

    func audioEngineRemotePrevious() {
        notifyListeners("remotePrevious", data: [:])
    }

    func audioEngineRemoteSeek(time: Double) {
        notifyListeners("remoteSeek", data: ["time": time])
    }

    func audioEngineDidUpdateAnalysis(frequencyData: [UInt8], timeDomainData: [UInt8]) {
        notifyListeners("audioAnalysis", data: [
            "frequencyData": frequencyData.map { Int($0) },
            "timeDomainData": timeDomainData.map { Int($0) },
        ])
    }
}
