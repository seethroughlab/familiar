// AirPlay bridge — registration pattern (mirrors createEngine / ambientSynthBridge).
// The shared @familiar/frontend package must not import @capacitor directly; the iOS package
// registers a concrete implementation at boot. On web, no bridge is registered and the AirPlay
// button hides itself.

export interface AirPlayBridge {
  /** Present the iOS system AirPlay route picker so the user can route output to an AirPlay/WiiM device. */
  showPicker(): Promise<void>;
}

let _bridge: AirPlayBridge | null = null;

export function registerAirPlayBridge(bridge: AirPlayBridge): void {
  _bridge = bridge;
}

export function getAirPlayBridge(): AirPlayBridge | null {
  return _bridge;
}
