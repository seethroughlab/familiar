import AudioToolbox
import AVFoundation
import Foundation

// ============================================================================
// MARK: - FourCharCode Helper
// ============================================================================

private func fourCC(_ string: String) -> FourCharCode {
    var result: FourCharCode = 0
    for char in string.utf8.prefix(4) {
        result = (result << 8) | FourCharCode(char)
    }
    return result
}

// ============================================================================
// MARK: - Registration Helper
// ============================================================================

/// Call once at app launch to register all custom audio unit component descriptions.
func registerCustomAudioUnits() {
    AUAudioUnit.registerSubclass(
        ChorusAudioUnit.self,
        as: ChorusAudioUnit.componentDescription,
        name: "Familiar: Chorus",
        version: 1
    )
    AUAudioUnit.registerSubclass(
        StereoWidthAudioUnit.self,
        as: StereoWidthAudioUnit.componentDescription,
        name: "Familiar: StereoWidth",
        version: 1
    )
    AUAudioUnit.registerSubclass(
        TremoloAudioUnit.self,
        as: TremoloAudioUnit.componentDescription,
        name: "Familiar: Tremolo",
        version: 1
    )
    AUAudioUnit.registerSubclass(
        BitcrusherAudioUnit.self,
        as: BitcrusherAudioUnit.componentDescription,
        name: "Familiar: Bitcrusher",
        version: 1
    )
}

// ============================================================================
// MARK: - ChorusAudioUnit
// ============================================================================

/// Multi-voice chorus with LFO-modulated delay lines.
final class ChorusAudioUnit: AUAudioUnit {

    static let componentDescription = AudioComponentDescription(
        componentType: kAudioUnitType_Effect,
        componentSubType: FourCharCode("chor"),
        componentManufacturer: FourCharCode("Fmlr"),
        componentFlags: 0,
        componentFlagsMask: 0
    )

    // Parameters
    private let rateParam: AUParameter
    private let depthParam: AUParameter      // depth in ms
    private let mixParam: AUParameter
    private let voicesParam: AUParameter

    private var _parameterTree: AUParameterTree!
    override var parameterTree: AUParameterTree? {
        get { return _parameterTree }
        set { _parameterTree = newValue }
    }

    // Audio state
    private var sampleRate: Double = 44100
    private var channelCount: Int = 2

    // Delay buffers — one per voice
    private static let maxVoices = 3
    private static let maxDelayMs: Double = 50   // max delay line length
    private var delayBuffers: [[Float]] = []      // [voice][sample]
    private var writeIndices: [Int] = [0, 0, 0]
    private var lfoPhases: [Double] = [0, 0, 0]

    // Base delays per voice (ms)
    private static let baseDelaysMs: [Double] = [25, 30, 35]

    // Input/output bus management
    private var _inputBusArray: AUAudioUnitBusArray!
    private var _outputBusArray: AUAudioUnitBusArray!
    private var inputBus: AUAudioUnitBus!
    private var outputBus: AUAudioUnitBus!

    override var inputBusses: AUAudioUnitBusArray { return _inputBusArray }
    override var outputBusses: AUAudioUnitBusArray { return _outputBusArray }

    override init(componentDescription: AudioComponentDescription,
                  options: AudioComponentInstantiationOptions = []) throws {
        // Create parameters
        rateParam = AUParameterTree.createParameter(
            withIdentifier: "rate", name: "Rate",
            address: 0, min: 0.1, max: 5, unit: .hertz,
            unitName: nil, flags: [.flag_IsReadable, .flag_IsWritable],
            valueStrings: nil, dependentParameters: nil)
        depthParam = AUParameterTree.createParameter(
            withIdentifier: "depth", name: "Depth",
            address: 1, min: 0, max: 10, unit: .milliseconds,
            unitName: nil, flags: [.flag_IsReadable, .flag_IsWritable],
            valueStrings: nil, dependentParameters: nil)
        mixParam = AUParameterTree.createParameter(
            withIdentifier: "mix", name: "Mix",
            address: 2, min: 0, max: 1, unit: .generic,
            unitName: nil, flags: [.flag_IsReadable, .flag_IsWritable],
            valueStrings: nil, dependentParameters: nil)
        voicesParam = AUParameterTree.createParameter(
            withIdentifier: "voices", name: "Voices",
            address: 3, min: 2, max: 3, unit: .generic,
            unitName: nil, flags: [.flag_IsReadable, .flag_IsWritable],
            valueStrings: nil, dependentParameters: nil)

        rateParam.value = 1.5
        depthParam.value = 3
        mixParam.value = 0.5
        voicesParam.value = 2

        try super.init(componentDescription: componentDescription, options: options)

        _parameterTree = AUParameterTree.createTree(withChildren: [rateParam, depthParam, mixParam, voicesParam])

        let defaultFormat = AVAudioFormat(standardFormatWithSampleRate: 44100, channels: 2)!
        inputBus = try AUAudioUnitBus(format: defaultFormat)
        outputBus = try AUAudioUnitBus(format: defaultFormat)
        _inputBusArray = AUAudioUnitBusArray(audioUnit: self, busType: .input, busses: [inputBus])
        _outputBusArray = AUAudioUnitBusArray(audioUnit: self, busType: .output, busses: [outputBus])

        maximumFramesToRender = 4096
    }

    override func allocateRenderResources() throws {
        try super.allocateRenderResources()

        let format = inputBus.format
        sampleRate = format.sampleRate
        channelCount = Int(format.channelCount)

        let maxDelaySamples = Int(ChorusAudioUnit.maxDelayMs * sampleRate / 1000) + 1
        delayBuffers = (0..<ChorusAudioUnit.maxVoices).map { _ in
            [Float](repeating: 0, count: maxDelaySamples)
        }
        writeIndices = [0, 0, 0]
        lfoPhases = [0, 0, 0]
    }

    override func deallocateRenderResources() {
        super.deallocateRenderResources()
        delayBuffers = []
    }

    override var internalRenderBlock: AUInternalRenderBlock {
        // Capture mutable state
        let rateParam = self.rateParam
        let depthParam = self.depthParam
        let mixParam = self.mixParam
        let voicesParam = self.voicesParam

        return { [unowned self]
            actionFlags, timestamp, frameCount, outputBusNumber,
            outputData, renderEvent, pullInputBlock in

            guard let pullInputBlock = pullInputBlock else {
                return kAudioUnitErr_NoConnection
            }

            var pullFlags = AudioUnitRenderActionFlags(rawValue: 0)
            let status = pullInputBlock(&pullFlags, timestamp, frameCount, 0, outputData)
            guard status == noErr else { return status }

            let rate = Double(rateParam.value)
            let depthMs = Double(depthParam.value)
            let mix = Float(mixParam.value)
            let numVoices = Int(voicesParam.value)
            let dry = 1.0 - mix

            let sr = self.sampleRate
            let bufLen = self.delayBuffers.isEmpty ? 0 : self.delayBuffers[0].count
            guard bufLen > 0 else { return noErr }

            let nFrames = Int(frameCount)

            for ch in 0..<min(Int(outputData.pointee.mNumberBuffers), self.channelCount) {
                let buf = outputData.pointee.mBuffers  // For stereo, access via tuple
                let ablBuffer: AudioBuffer
                if ch == 0 {
                    ablBuffer = outputData.pointee.mBuffers
                } else {
                    ablBuffer = UnsafeMutableAudioBufferListPointer(outputData)[ch]
                }
                guard let data = ablBuffer.mData?.assumingMemoryBound(to: Float.self) else { continue }

                for i in 0..<nFrames {
                    let inputSample = data[i]
                    var wetSample: Float = 0

                    for v in 0..<numVoices {
                        // LFO: sinusoidal modulation
                        let lfoValue = sin(self.lfoPhases[v] * 2.0 * Double.pi)
                        let delayMs = ChorusAudioUnit.baseDelaysMs[v] + depthMs * lfoValue
                        let delaySamples = max(1, delayMs * sr / 1000.0)

                        // Write current sample
                        self.delayBuffers[v][self.writeIndices[v]] = inputSample

                        // Read with linear interpolation
                        let readPos = Double(self.writeIndices[v]) - delaySamples
                        let readPosWrapped = readPos < 0 ? readPos + Double(bufLen) : readPos
                        let idx0 = Int(readPosWrapped) % bufLen
                        let idx1 = (idx0 + 1) % bufLen
                        let frac = Float(readPosWrapped - floor(readPosWrapped))
                        let delayed = self.delayBuffers[v][idx0] * (1 - frac) + self.delayBuffers[v][idx1] * frac

                        wetSample += delayed

                        // Advance write index (shared across channels — ok for chorus)
                        if ch == 0 {
                            self.lfoPhases[v] += rate / sr
                            if self.lfoPhases[v] > 1.0 { self.lfoPhases[v] -= 1.0 }
                            self.writeIndices[v] = (self.writeIndices[v] + 1) % bufLen
                        }
                    }

                    wetSample /= Float(numVoices)
                    data[i] = dry * inputSample + mix * wetSample
                }
            }

            return noErr
        }
    }
}

// ============================================================================
// MARK: - StereoWidthAudioUnit
// ============================================================================

/// Mid/side stereo width control.
final class StereoWidthAudioUnit: AUAudioUnit {

    static let componentDescription = AudioComponentDescription(
        componentType: kAudioUnitType_Effect,
        componentSubType: FourCharCode("stwd"),
        componentManufacturer: FourCharCode("Fmlr"),
        componentFlags: 0,
        componentFlagsMask: 0
    )

    private let widthParam: AUParameter

    private var _parameterTree: AUParameterTree!
    override var parameterTree: AUParameterTree? {
        get { return _parameterTree }
        set { _parameterTree = newValue }
    }

    private var _inputBusArray: AUAudioUnitBusArray!
    private var _outputBusArray: AUAudioUnitBusArray!
    private var inputBus: AUAudioUnitBus!
    private var outputBus: AUAudioUnitBus!

    override var inputBusses: AUAudioUnitBusArray { return _inputBusArray }
    override var outputBusses: AUAudioUnitBusArray { return _outputBusArray }

    override init(componentDescription: AudioComponentDescription,
                  options: AudioComponentInstantiationOptions = []) throws {
        widthParam = AUParameterTree.createParameter(
            withIdentifier: "width", name: "Width",
            address: 0, min: 0, max: 2, unit: .generic,
            unitName: nil, flags: [.flag_IsReadable, .flag_IsWritable],
            valueStrings: nil, dependentParameters: nil)
        widthParam.value = 1.0

        try super.init(componentDescription: componentDescription, options: options)

        _parameterTree = AUParameterTree.createTree(withChildren: [widthParam])

        let defaultFormat = AVAudioFormat(standardFormatWithSampleRate: 44100, channels: 2)!
        inputBus = try AUAudioUnitBus(format: defaultFormat)
        outputBus = try AUAudioUnitBus(format: defaultFormat)
        _inputBusArray = AUAudioUnitBusArray(audioUnit: self, busType: .input, busses: [inputBus])
        _outputBusArray = AUAudioUnitBusArray(audioUnit: self, busType: .output, busses: [outputBus])

        maximumFramesToRender = 4096
    }

    override func allocateRenderResources() throws {
        try super.allocateRenderResources()
    }

    override func deallocateRenderResources() {
        super.deallocateRenderResources()
    }

    override var internalRenderBlock: AUInternalRenderBlock {
        let widthParam = self.widthParam

        return {
            actionFlags, timestamp, frameCount, outputBusNumber,
            outputData, renderEvent, pullInputBlock in

            guard let pullInputBlock = pullInputBlock else {
                return kAudioUnitErr_NoConnection
            }

            var pullFlags = AudioUnitRenderActionFlags(rawValue: 0)
            let status = pullInputBlock(&pullFlags, timestamp, frameCount, 0, outputData)
            guard status == noErr else { return status }

            let width = widthParam.value
            let nFrames = Int(frameCount)

            // Need at least 2 channels for mid/side processing
            guard outputData.pointee.mNumberBuffers >= 2 else { return noErr }

            let buffers = UnsafeMutableAudioBufferListPointer(outputData)
            guard let leftData = buffers[0].mData?.assumingMemoryBound(to: Float.self),
                  let rightData = buffers[1].mData?.assumingMemoryBound(to: Float.self) else {
                return noErr
            }

            // M/S matrix: mid=(L+R)/2, side=(L-R)/2
            // L_out = mid + side*width, R_out = mid - side*width
            // At width=1: identity. At width=0: mono. At width=2: extra wide.
            for i in 0..<nFrames {
                let left = leftData[i]
                let right = rightData[i]
                let mid = (left + right) * 0.5
                let side = (left - right) * 0.5
                leftData[i] = mid + side * width
                rightData[i] = mid - side * width
            }

            return noErr
        }
    }
}

// ============================================================================
// MARK: - TremoloAudioUnit
// ============================================================================

/// LFO amplitude modulation with sine/triangle/square shapes.
final class TremoloAudioUnit: AUAudioUnit {

    static let componentDescription = AudioComponentDescription(
        componentType: kAudioUnitType_Effect,
        componentSubType: FourCharCode("trem"),
        componentManufacturer: FourCharCode("Fmlr"),
        componentFlags: 0,
        componentFlagsMask: 0
    )

    private let rateParam: AUParameter
    private let depthParam: AUParameter
    private let shapeParam: AUParameter  // 0=sine, 1=triangle, 2=square

    private var _parameterTree: AUParameterTree!
    override var parameterTree: AUParameterTree? {
        get { return _parameterTree }
        set { _parameterTree = newValue }
    }

    private var sampleRate: Double = 44100
    private var lfoPhase: Double = 0

    private var _inputBusArray: AUAudioUnitBusArray!
    private var _outputBusArray: AUAudioUnitBusArray!
    private var inputBus: AUAudioUnitBus!
    private var outputBus: AUAudioUnitBus!

    override var inputBusses: AUAudioUnitBusArray { return _inputBusArray }
    override var outputBusses: AUAudioUnitBusArray { return _outputBusArray }

    override init(componentDescription: AudioComponentDescription,
                  options: AudioComponentInstantiationOptions = []) throws {
        rateParam = AUParameterTree.createParameter(
            withIdentifier: "rate", name: "Rate",
            address: 0, min: 0.5, max: 20, unit: .hertz,
            unitName: nil, flags: [.flag_IsReadable, .flag_IsWritable],
            valueStrings: nil, dependentParameters: nil)
        depthParam = AUParameterTree.createParameter(
            withIdentifier: "depth", name: "Depth",
            address: 1, min: 0, max: 1, unit: .generic,
            unitName: nil, flags: [.flag_IsReadable, .flag_IsWritable],
            valueStrings: nil, dependentParameters: nil)
        shapeParam = AUParameterTree.createParameter(
            withIdentifier: "shape", name: "Shape",
            address: 2, min: 0, max: 2, unit: .generic,
            unitName: nil, flags: [.flag_IsReadable, .flag_IsWritable],
            valueStrings: nil, dependentParameters: nil)

        rateParam.value = 4
        depthParam.value = 0.5
        shapeParam.value = 0  // sine

        try super.init(componentDescription: componentDescription, options: options)

        _parameterTree = AUParameterTree.createTree(withChildren: [rateParam, depthParam, shapeParam])

        let defaultFormat = AVAudioFormat(standardFormatWithSampleRate: 44100, channels: 2)!
        inputBus = try AUAudioUnitBus(format: defaultFormat)
        outputBus = try AUAudioUnitBus(format: defaultFormat)
        _inputBusArray = AUAudioUnitBusArray(audioUnit: self, busType: .input, busses: [inputBus])
        _outputBusArray = AUAudioUnitBusArray(audioUnit: self, busType: .output, busses: [outputBus])

        maximumFramesToRender = 4096
    }

    override func allocateRenderResources() throws {
        try super.allocateRenderResources()
        sampleRate = inputBus.format.sampleRate
        lfoPhase = 0
    }

    override func deallocateRenderResources() {
        super.deallocateRenderResources()
    }

    override var internalRenderBlock: AUInternalRenderBlock {
        let rateParam = self.rateParam
        let depthParam = self.depthParam
        let shapeParam = self.shapeParam

        return { [unowned self]
            actionFlags, timestamp, frameCount, outputBusNumber,
            outputData, renderEvent, pullInputBlock in

            guard let pullInputBlock = pullInputBlock else {
                return kAudioUnitErr_NoConnection
            }

            var pullFlags = AudioUnitRenderActionFlags(rawValue: 0)
            let status = pullInputBlock(&pullFlags, timestamp, frameCount, 0, outputData)
            guard status == noErr else { return status }

            let rate = Double(rateParam.value)
            let depth = Float(depthParam.value)
            let shape = Int(shapeParam.value)
            let sr = self.sampleRate
            let nFrames = Int(frameCount)
            let phaseInc = rate / sr

            let numBuffers = Int(outputData.pointee.mNumberBuffers)
            let buffers = UnsafeMutableAudioBufferListPointer(outputData)

            for i in 0..<nFrames {
                // Compute LFO value [0, 1]
                let phase = self.lfoPhase
                var lfo: Float
                switch shape {
                case 1:  // triangle
                    lfo = phase < 0.5 ? Float(phase * 2) : Float(2 - phase * 2)
                case 2:  // square
                    lfo = phase < 0.5 ? 1.0 : 0.0
                default: // sine
                    lfo = Float(sin(phase * 2.0 * Double.pi) * 0.5 + 0.5)
                }

                // Gain modulation: 1.0 at peak, (1-depth) at trough
                let gain = 1.0 - depth * (1.0 - lfo)

                for ch in 0..<numBuffers {
                    guard let data = buffers[ch].mData?.assumingMemoryBound(to: Float.self) else { continue }
                    data[i] *= gain
                }

                self.lfoPhase += phaseInc
                if self.lfoPhase >= 1.0 { self.lfoPhase -= 1.0 }
            }

            return noErr
        }
    }
}

// ============================================================================
// MARK: - BitcrusherAudioUnit
// ============================================================================

/// Bit depth reduction + sample rate reduction.
final class BitcrusherAudioUnit: AUAudioUnit {

    static let componentDescription = AudioComponentDescription(
        componentType: kAudioUnitType_Effect,
        componentSubType: FourCharCode("btcr"),
        componentManufacturer: FourCharCode("Fmlr"),
        componentFlags: 0,
        componentFlagsMask: 0
    )

    private let bitsParam: AUParameter
    private let srReductionParam: AUParameter
    private let mixParam: AUParameter

    private var _parameterTree: AUParameterTree!
    override var parameterTree: AUParameterTree? {
        get { return _parameterTree }
        set { _parameterTree = newValue }
    }

    private var holdCounters: [Int] = []
    private var holdSamples: [Float] = []

    private var _inputBusArray: AUAudioUnitBusArray!
    private var _outputBusArray: AUAudioUnitBusArray!
    private var inputBus: AUAudioUnitBus!
    private var outputBus: AUAudioUnitBus!

    override var inputBusses: AUAudioUnitBusArray { return _inputBusArray }
    override var outputBusses: AUAudioUnitBusArray { return _outputBusArray }

    override init(componentDescription: AudioComponentDescription,
                  options: AudioComponentInstantiationOptions = []) throws {
        bitsParam = AUParameterTree.createParameter(
            withIdentifier: "bits", name: "Bits",
            address: 0, min: 1, max: 16, unit: .generic,
            unitName: nil, flags: [.flag_IsReadable, .flag_IsWritable],
            valueStrings: nil, dependentParameters: nil)
        srReductionParam = AUParameterTree.createParameter(
            withIdentifier: "srReduction", name: "SR Reduction",
            address: 1, min: 1, max: 32, unit: .generic,
            unitName: nil, flags: [.flag_IsReadable, .flag_IsWritable],
            valueStrings: nil, dependentParameters: nil)
        mixParam = AUParameterTree.createParameter(
            withIdentifier: "mix", name: "Mix",
            address: 2, min: 0, max: 1, unit: .generic,
            unitName: nil, flags: [.flag_IsReadable, .flag_IsWritable],
            valueStrings: nil, dependentParameters: nil)

        bitsParam.value = 8
        srReductionParam.value = 4
        mixParam.value = 1

        try super.init(componentDescription: componentDescription, options: options)

        _parameterTree = AUParameterTree.createTree(withChildren: [bitsParam, srReductionParam, mixParam])

        let defaultFormat = AVAudioFormat(standardFormatWithSampleRate: 44100, channels: 2)!
        inputBus = try AUAudioUnitBus(format: defaultFormat)
        outputBus = try AUAudioUnitBus(format: defaultFormat)
        _inputBusArray = AUAudioUnitBusArray(audioUnit: self, busType: .input, busses: [inputBus])
        _outputBusArray = AUAudioUnitBusArray(audioUnit: self, busType: .output, busses: [outputBus])

        maximumFramesToRender = 4096
    }

    override func allocateRenderResources() throws {
        try super.allocateRenderResources()
        let channels = Int(inputBus.format.channelCount)
        holdCounters = [Int](repeating: 0, count: channels)
        holdSamples = [Float](repeating: 0, count: channels)
    }

    override func deallocateRenderResources() {
        super.deallocateRenderResources()
        holdCounters = []
        holdSamples = []
    }

    override var internalRenderBlock: AUInternalRenderBlock {
        let bitsParam = self.bitsParam
        let srReductionParam = self.srReductionParam
        let mixParam = self.mixParam

        return { [unowned self]
            actionFlags, timestamp, frameCount, outputBusNumber,
            outputData, renderEvent, pullInputBlock in

            guard let pullInputBlock = pullInputBlock else {
                return kAudioUnitErr_NoConnection
            }

            var pullFlags = AudioUnitRenderActionFlags(rawValue: 0)
            let status = pullInputBlock(&pullFlags, timestamp, frameCount, 0, outputData)
            guard status == noErr else { return status }

            let bits = bitsParam.value
            let srReduction = Int(srReductionParam.value)
            let mix = mixParam.value
            let dry = 1.0 - mix
            let nFrames = Int(frameCount)

            // Bit quantization step
            let step = powf(0.5, bits)

            let numBuffers = Int(outputData.pointee.mNumberBuffers)
            let buffers = UnsafeMutableAudioBufferListPointer(outputData)

            for ch in 0..<numBuffers {
                guard let data = buffers[ch].mData?.assumingMemoryBound(to: Float.self) else { continue }

                for i in 0..<nFrames {
                    let inputSample = data[i]

                    // Sample-and-hold: only update the held sample every `srReduction` samples
                    self.holdCounters[ch] += 1
                    if self.holdCounters[ch] >= srReduction {
                        self.holdCounters[ch] = 0
                        // Bit-reduce the sample
                        self.holdSamples[ch] = step * floorf(inputSample / step + 0.5)
                    }

                    data[i] = dry * inputSample + mix * self.holdSamples[ch]
                }
            }

            return noErr
        }
    }
}
