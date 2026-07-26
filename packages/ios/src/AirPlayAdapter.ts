import type { AirPlayBridge } from '@familiar/frontend/src/player/audio/airPlayBridge';
import { FamiliarAudio } from './plugins/familiarAudio';

/** iOS implementation of the shared AirPlayBridge — presents the native system route picker. */
export class AirPlayAdapter implements AirPlayBridge {
  async showPicker(): Promise<void> {
    await FamiliarAudio.showAirPlayPicker();
  }
}
