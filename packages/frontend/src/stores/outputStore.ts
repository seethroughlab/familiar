import { create } from 'zustand';
import { outputsApi, type Output, getAbsoluteStreamUrl } from '../api/outputs';
import { usePlayerStore } from '../player/playerStore';

interface OutputStore {
  outputs: Output[];
  activeOutputId: string | null;  // null = browser (This Device)
  isDiscovering: boolean;

  setOutputs(outputs: Output[]): void;
  setActive(id: string | null): void;
  setDiscovering(v: boolean): void;
  fetchOutputs(): Promise<void>;
  discover(): Promise<void>;
}

export const useOutputStore = create<OutputStore>((set, get) => ({
  outputs: [],
  activeOutputId: null,
  isDiscovering: false,

  setOutputs: (outputs) => set({ outputs }),

  setActive: (id) => {
    const prev = get().activeOutputId;
    set({ activeOutputId: id });
    // Stop the previous network output when switching away
    if (prev && prev !== id) {
      outputsApi.stop(prev).catch(() => {});
    }
    // If switching to a network output, make the slider authoritative immediately and,
    // if a track is currently playing, start it on the device.
    if (id) {
      const { currentTrack, isPlaying, volume } = usePlayerStore.getState();
      outputsApi.setVolume(id, toDeviceVolume(volume)).catch(() => {});
      if (currentTrack && isPlaying) {
        const url = getAbsoluteStreamUrl(currentTrack.id);
        outputsApi.play(id, url, currentTrack.id).catch(() => {});
      }
    }
  },

  setDiscovering: (v) => set({ isDiscovering: v }),

  fetchOutputs: async () => {
    const outputs = await outputsApi.list();
    set({ outputs });
    // If activeOutputId was set but the output no longer exists, reset to browser
    const { activeOutputId } = get();
    if (activeOutputId && !outputs.find((o) => o.id === activeOutputId)) {
      set({ activeOutputId: null });
    }
  },

  discover: async () => {
    set({ isDiscovering: true });
    try {
      await outputsApi.discoverAll();
      // Refresh the full list after discovery
      const outputs = await outputsApi.list();
      set({ outputs });
    } catch {
      // Discovery errors are non-fatal
    } finally {
      set({ isDiscovering: false });
    }
  },
}));

/** Player volume is 0–1; network devices (UPnP RenderingControl, Sonos, …) want 0–100. */
function toDeviceVolume(volume: number): number {
  return Math.round(Math.max(0, Math.min(1, volume)) * 100);
}

// Mirror player state changes to the active network output.
// playerStore is a facade — subscribe takes () => void; we snapshot prev state manually.
let _prevTrackId: string | null = null;
let _prevIsPlaying = false;
let _prevVolume = usePlayerStore.getState().volume;

// Slider drags fire many changes per second — debounce the device call so we send one
// SetVolume after the user settles instead of flooding the speaker with requests.
let _volumeTimer: ReturnType<typeof setTimeout> | null = null;
function pushVolumeToDevice(outputId: string, volume: number) {
  if (_volumeTimer) clearTimeout(_volumeTimer);
  _volumeTimer = setTimeout(() => {
    _volumeTimer = null;
    outputsApi.setVolume(outputId, toDeviceVolume(volume)).catch(() => {});
  }, 150);
}

usePlayerStore.subscribe(() => {
  const { activeOutputId } = useOutputStore.getState();
  if (!activeOutputId) return;

  const { currentTrack, isPlaying, volume } = usePlayerStore.getState();
  const trackId = currentTrack?.id ?? null;
  const trackChanged = trackId !== _prevTrackId;
  const playingChanged = isPlaying !== _prevIsPlaying;
  const volumeChanged = volume !== _prevVolume;

  if (trackChanged && currentTrack && isPlaying) {
    const url = getAbsoluteStreamUrl(currentTrack.id);
    outputsApi.play(activeOutputId, url, currentTrack.id).catch(() => {});
  } else if (playingChanged && !trackChanged) {
    if (isPlaying) {
      outputsApi.resume(activeOutputId).catch(() => {});
    } else {
      outputsApi.pause(activeOutputId).catch(() => {});
    }
  }

  // The volume slider controls the active network device (WiiM/Sonos/UPnP).
  if (volumeChanged) {
    pushVolumeToDevice(activeOutputId, volume);
  }

  _prevTrackId = trackId;
  _prevIsPlaying = isPlaying;
  _prevVolume = volume;
});
