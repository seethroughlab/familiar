import Capacitor
import Foundation

@objc(FamiliarAmbientSynthPlugin)
public class FamiliarAmbientSynthPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "FamiliarAmbientSynthPlugin"
    public let jsName = "FamiliarAmbientSynth"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "configure", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "startDrone", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "glideDrone", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "playMotif", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stopImmediate", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stopWithRelease", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "updateMix", returnType: CAPPluginReturnPromise),
    ]

    private lazy var synthEngine = AmbientSynthEngine()

    @objc func configure(_ call: CAPPluginCall) {
        let droneVolume = call.getFloat("droneVolume") ?? 0.3
        let motifVolume = call.getFloat("motifVolume") ?? 0.2
        let reverbMix = call.getFloat("reverbMix") ?? 0.6
        let delayMix = call.getFloat("delayMix") ?? 0.3
        let lowpassFreq = call.getFloat("lowpassFreq") ?? 2000.0

        synthEngine.configure(
            droneVolume: droneVolume,
            motifVolume: motifVolume,
            reverbMix: reverbMix,
            delayMix: delayMix,
            lowpassFreq: lowpassFreq
        )
        call.resolve()
    }

    @objc func startDrone(_ call: CAPPluginCall) {
        let rootNote = call.getInt("rootNote") ?? 48
        let secondNote = call.getInt("secondNote") ?? 55
        synthEngine.startDrone(rootNote: rootNote, secondNote: secondNote)
        call.resolve()
    }

    @objc func glideDrone(_ call: CAPPluginCall) {
        let rootNote = call.getInt("rootNote") ?? 48
        let secondNote = call.getInt("secondNote") ?? 55
        let glideMs = call.getInt("glideMs") ?? 5000
        synthEngine.glideDrone(rootNote: rootNote, secondNote: secondNote, glideMs: glideMs)
        call.resolve()
    }

    @objc func playMotif(_ call: CAPPluginCall) {
        let motifNotes = call.getArray("motifNotes", Int.self) ?? []
        let motifTimings = call.getArray("motifTimingsMs", Int.self) ?? []
        let motifDuration = call.getInt("motifNoteDurationMs") ?? 2000
        synthEngine.playMotif(
            motifNotes: motifNotes,
            motifTimingsMs: motifTimings,
            motifNoteDurationMs: motifDuration
        )
        call.resolve()
    }

    @objc func stopImmediate(_ call: CAPPluginCall) {
        synthEngine.stopImmediate()
        call.resolve()
    }

    @objc func stopWithRelease(_ call: CAPPluginCall) {
        let releaseMs = call.getInt("releaseMs") ?? 2000
        synthEngine.stopWithRelease(releaseMs: releaseMs)
        call.resolve()
    }

    @objc func updateMix(_ call: CAPPluginCall) {
        if let droneVol = call.getFloat("droneVolume") {
            synthEngine.droneLevel = droneVol
        }
        if let motifVol = call.getFloat("motifVolume") {
            synthEngine.motifLevel = motifVol
        }
        if let reverb = call.getFloat("reverbMix") {
            synthEngine.reverbMix = reverb
        }
        call.resolve()
    }
}
