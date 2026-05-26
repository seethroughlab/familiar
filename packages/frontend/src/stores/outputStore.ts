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
    // If switching to a network output and a track is currently playing, start it
    if (id) {
      const { currentTrack, isPlaying } = usePlayerStore.getState();
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

// Mirror player state changes to the active network output.
// playerStore is a facade — subscribe takes () => void; we snapshot prev state manually.
let _prevTrackId: string | null = null;
let _prevIsPlaying = false;

usePlayerStore.subscribe(() => {
  const { activeOutputId } = useOutputStore.getState();
  if (!activeOutputId) return;

  const { currentTrack, isPlaying } = usePlayerStore.getState();
  const trackId = currentTrack?.id ?? null;
  const trackChanged = trackId !== _prevTrackId;
  const playingChanged = isPlaying !== _prevIsPlaying;

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

  _prevTrackId = trackId;
  _prevIsPlaying = isPlaying;
});
