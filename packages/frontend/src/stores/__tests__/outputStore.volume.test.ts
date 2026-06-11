/* @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Mock the outputs API so we can assert exactly what gets sent to the device.
vi.mock('../../api/outputs', () => ({
  outputsApi: {
    setVolume: vi.fn(async () => {}),
    play: vi.fn(async () => {}),
    pause: vi.fn(async () => {}),
    resume: vi.fn(async () => {}),
    stop: vi.fn(async () => {}),
    list: vi.fn(async () => []),
    discoverAll: vi.fn(async () => ({ sonos: [], upnp: [], airplay: [], chromecast: [] })),
  },
  getAbsoluteStreamUrl: (id: string) => `http://test/api/v1/tracks/${id}/stream`,
}));

import { outputsApi } from '../../api/outputs';
import { usePlayerStore } from '../../player/playerStore';
import { useOutputStore } from '../outputStore';

describe('outputStore — volume slider controls the active network device', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    useOutputStore.setState({ activeOutputId: null });
    usePlayerStore.setState({ volume: 1, currentTrack: null, isPlaying: false });
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it('does not touch the device when no network output is active', () => {
    usePlayerStore.setState({ volume: 0.5 });
    vi.advanceTimersByTime(500);
    expect(outputsApi.setVolume).not.toHaveBeenCalled();
  });

  it('pushes the current volume (0–1 → 0–100) when you switch to a network output', () => {
    useOutputStore.getState().setActive('wiim-1');
    expect(outputsApi.setVolume).toHaveBeenCalledWith('wiim-1', 100);
  });

  it('debounces slider drags and sends only the final 0–100 value', () => {
    useOutputStore.getState().setActive('wiim-1');
    vi.mocked(outputsApi.setVolume).mockClear();

    // Rapid drag — three changes in quick succession.
    usePlayerStore.setState({ volume: 0.4 });
    usePlayerStore.setState({ volume: 0.5 });
    usePlayerStore.setState({ volume: 0.55 });
    expect(outputsApi.setVolume).not.toHaveBeenCalled(); // still within the debounce window

    vi.advanceTimersByTime(150);
    expect(outputsApi.setVolume).toHaveBeenCalledTimes(1);
    expect(outputsApi.setVolume).toHaveBeenCalledWith('wiim-1', 55);
  });
});
