/**
 * Native analysis buffer management.
 *
 * Shared module for native (iOS Capacitor) audio analysis data.
 * CapacitorEngine writes buffers here; useAudioAnalyser reads them.
 * Extracted to avoid CapacitorEngine importing from the hooks layer.
 */

let nativeFrequencyData: Uint8Array | null = null;
let nativeTimeDomainData: Uint8Array | null = null;

export function setNativeAnalysisBuffers(freq: Uint8Array, time: Uint8Array): void {
  nativeFrequencyData = freq;
  nativeTimeDomainData = time;
}

export function clearNativeAnalysisBuffers(): void {
  nativeFrequencyData = null;
  nativeTimeDomainData = null;
}

export function getNativeAnalysisBuffers(): { frequency: Uint8Array | null; timeDomain: Uint8Array | null } {
  return { frequency: nativeFrequencyData, timeDomain: nativeTimeDomainData };
}
