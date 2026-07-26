import { Airplay } from 'lucide-react';
import { isNativeApp } from '../../utils/platform';
import { getAirPlayBridge } from '../../player/audio/airPlayBridge';

/**
 * Native-only AirPlay button. Presents the iOS system route picker so the user can send the app's
 * audio output to an AirPlay 2 device (e.g. a WiiM) at the OS level — independent of the
 * backend-driven "Play To" outputs. Renders nothing on web, where no AirPlay bridge is registered.
 */
export function AirPlayButton() {
  if (!isNativeApp()) return null;

  const handleClick = async () => {
    const bridge = getAirPlayBridge();
    if (!bridge) return;
    try {
      await bridge.showPicker();
    } catch {
      // System picker unavailable — nothing actionable to surface.
    }
  };

  return (
    <button
      onClick={handleClick}
      className="p-2 rounded-full text-zinc-400 hover:text-white hover:bg-white/10 transition-colors"
      aria-label="AirPlay"
      title="AirPlay"
    >
      <Airplay className="w-5 h-5" />
    </button>
  );
}
