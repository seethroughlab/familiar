/* @vitest-environment jsdom */
import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useAudioEngine } from '../../player/useAudioEngine';
import { usePlayerStore } from '../../player/playerStore';

type EngineEvent =
  | { type: 'ended' }
  | { type: 'error'; message: string; code?: string }
  | { type: 'remotePrevious'; nativeAction?: 'restart' }
  | { type: 'timeUpdate'; currentTime: number; duration: number };

function makeTrack(id: string) {
  return {
    id,
    title: `Track ${id}`,
    artist: 'Test Artist',
    album: 'Test Album',
    album_artist: null,
    album_type: 'album' as const,
    track_number: 1,
    disc_number: 1,
    year: 2024,
    genre: 'Test',
    duration_seconds: 120,
    format: 'mp3',
    file_path: `/music/${id}.mp3`,
    analysis_version: 1,
  };
}

const mockEngine = vi.hoisted(() => {
  const handlers = new Set<(event: EngineEvent) => void>();
  return {
    capabilities: { crossfade: true, visualizer: true, effects: 'native' as const },
    initialize: vi.fn(() => true),
    dispose: vi.fn(),
    load: vi.fn(async () => {}),
    play: vi.fn(async () => {}),
    pause: vi.fn(),
    seek: vi.fn(),
    stop: vi.fn(),
    setVolume: vi.fn(),
    setNormalizationGain: vi.fn(),
    getCurrentTime: vi.fn(() => 0),
    getDuration: vi.fn(() => 120),
    getLoadedTrackId: vi.fn(() => null),
    on: vi.fn((handler: (event: EngineEvent) => void) => {
      handlers.add(handler);
      return () => handlers.delete(handler);
    }),
    updateNowPlaying: vi.fn(),
    syncPendingTracks: vi.fn(),
    preloadNext: vi.fn(async () => false),
    setNextNormalizationGain: vi.fn(),
    executeCrossfade: vi.fn((_duration: number, onComplete: () => void) => onComplete()),
    cancelCrossfade: vi.fn(),
    isCrossfading: vi.fn(() => false),
    resolveTrackUrl: vi.fn(async (trackId: string) => ({ url: `/api/v1/tracks/${trackId}/stream`, isOffline: false })),
    getPreloadingTrackId: vi.fn(() => null),
    isNextReady: vi.fn(() => false),
    __emit(event: EngineEvent) {
      handlers.forEach((h) => h(event));
    },
    __reset() {
      handlers.clear();
      this.initialize.mockClear();
      this.dispose.mockClear();
      this.load.mockClear();
      this.play.mockClear();
      this.pause.mockClear();
      this.seek.mockClear();
      this.stop.mockClear();
      this.setVolume.mockClear();
      this.setNormalizationGain.mockClear();
      this.getLoadedTrackId.mockClear();
      this.updateNowPlaying.mockClear();
      this.syncPendingTracks.mockClear();
      this.preloadNext.mockClear();
      this.setNextNormalizationGain.mockClear();
      this.executeCrossfade.mockClear();
      this.cancelCrossfade.mockClear();
      this.resolveTrackUrl.mockClear();
      this.isCrossfading.mockClear();
      this.getPreloadingTrackId.mockClear();
      this.isNextReady.mockClear();
    },
  };
});

const mockConnectivityStore = vi.hoisted(() => {
  let state = {
    offlineModeActive: false,
    offlineTrackIds: new Set<string>(),
    noteStreamLoadFailure: vi.fn(),
    noteStreamLoadSuccess: vi.fn(),
    incrementCounter: vi.fn(),
    incrementCounterBy: vi.fn(),
    refreshOfflineTrackIds: vi.fn(async () => {}),
  };

  const store = ((selector?: (s: typeof state) => unknown) => selector ? selector(state) : state) as
    ((selector?: (s: typeof state) => unknown) => unknown) & {
      getState: () => typeof state;
      setState: (next: Partial<typeof state>) => void;
      __reset: () => void;
    };

  store.getState = () => state;
  store.setState = (next) => {
    state = { ...state, ...next };
  };
  store.__reset = () => {
    state = {
      offlineModeActive: false,
      offlineTrackIds: new Set<string>(),
      noteStreamLoadFailure: vi.fn(),
      noteStreamLoadSuccess: vi.fn(),
      incrementCounter: vi.fn(),
      incrementCounterBy: vi.fn(),
      refreshOfflineTrackIds: vi.fn(async () => {}),
    };
  };
  return store;
});

const mockTracksApi = vi.hoisted(() => ({
  getStreamUrl: vi.fn((id: string) => `/api/v1/tracks/${id}/stream`),
  getArtworkUrl: vi.fn((id: string) => `/api/v1/tracks/${id}/artwork`),
  getAlbumGain: vi.fn(async () => ({ album_gain_db: null, album_peak: null, track_count: 1 })),
  reportPlaybackError: vi.fn(async () => {}),
}));

vi.mock('../../player/audio/engineInstance', () => ({
  getEngine: () => mockEngine,
}));

vi.mock('../../stores/connectivityStore', () => ({
  useConnectivityStore: mockConnectivityStore,
}));

vi.mock('../../api', () => ({
  tracksApi: mockTracksApi,
}));

vi.mock('../../player/audioSettingsStore', () => ({
  useAudioSettingsStore: () => ({
    crossfadeDuration: 5,
    crossfadeEnabled: true,
    normalizationEnabled: false,
    normalizationMode: 'track',
    normalizationTargetLufs: -14,
    normalizationPreamp: 0,
    normalizationPreventClipping: true,
  }),
}));

vi.mock('../../player/persistence', () => ({
  debouncedSavePlayerState: vi.fn(),
  loadPlayerState: vi.fn(async () => null),
  fetchTracksBatched: vi.fn(async () => []),
  migrateOldPlayerState: vi.fn(async () => {}),
}));

describe('useAudioEngine + playerStore integration parity', () => {
  beforeEach(() => {
    mockConnectivityStore.__reset();
    mockEngine.__reset();
    mockTracksApi.getStreamUrl.mockClear();
    mockTracksApi.getArtworkUrl.mockClear();
    mockTracksApi.getAlbumGain.mockClear();
    mockTracksApi.reportPlaybackError.mockClear();
    mockEngine.resolveTrackUrl.mockImplementation(async (trackId: string) => ({ url: `/api/v1/tracks/${trackId}/stream`, isOffline: false }));
    usePlayerStore.setState({
      currentTrack: null,
      isPlaying: false,
      currentTime: 0,
      duration: 0,
      volume: 1,
      shuffle: false,
      repeat: 'off',
      consume: false,
      queue: [],
      queueIndex: -1,
      history: [],
      shuffleOrder: [],
      shuffleIndex: -1,
      lazyQueueIds: null,
      lazyQueueIndex: -1,
      queueSource: null,
      crossfadeState: 'idle',
      nextTrackPreloaded: false,
      isLoadingAudio: false,
      isHydrated: true,
      isQueueHydrating: false,
    });
  });

  it('auto-advances exactly one track on ended event', async () => {
    const t1 = makeTrack('1');
    const t2 = makeTrack('2');
    const t3 = makeTrack('3');
    usePlayerStore.getState().setQueue([t1, t2, t3], 0);

    renderHook(() => useAudioEngine());

    usePlayerStore.setState({ isLoadingAudio: false });
    await act(async () => {
      mockEngine.__emit({ type: 'ended' });
    });

    const state = usePlayerStore.getState();
    expect(state.queueIndex).toBe(1);
    expect(state.currentTrack?.id).toBe('2');
  });

  it('applies previous-button restart semantics from native remotePrevious restart', async () => {
    const t1 = makeTrack('1');
    const t2 = makeTrack('2');
    usePlayerStore.getState().setQueue([t1, t2], 1);
    usePlayerStore.setState({ currentTime: 42 });

    renderHook(() => useAudioEngine());

    await act(async () => {
      mockEngine.__emit({ type: 'remotePrevious', nativeAction: 'restart' });
    });

    const state = usePlayerStore.getState();
    expect(state.queueIndex).toBe(1);
    expect(state.currentTrack?.id).toBe('2');
    expect(state.currentTime).toBe(0);
  });

  it('falls back to ended-based advance when preload/crossfade is not ready', async () => {
    const t1 = makeTrack('1');
    const t2 = makeTrack('2');
    usePlayerStore.getState().setQueue([t1, t2], 0);
    mockEngine.isNextReady.mockReturnValue(false);
    mockEngine.preloadNext.mockResolvedValue(false);

    renderHook(() => useAudioEngine());

    await act(async () => {
      mockEngine.__emit({ type: 'timeUpdate', currentTime: 95, duration: 100 });
    });

    expect(usePlayerStore.getState().queueIndex).toBe(0);
    expect(mockEngine.executeCrossfade).not.toHaveBeenCalled();

    await act(async () => {
      mockEngine.__emit({ type: 'ended' });
    });

    const state = usePlayerStore.getState();
    expect(state.queueIndex).toBe(1);
    expect(state.currentTrack?.id).toBe('2');
  });

  it('syncs pending next/previous tracks for native lock-screen controls', async () => {
    const t1 = makeTrack('1');
    const t2 = makeTrack('2');
    const t3 = makeTrack('3');
    usePlayerStore.getState().setQueue([t1, t2, t3], 1);
    usePlayerStore.setState({ history: [t1] });

    renderHook(() => useAudioEngine());

    await act(async () => {});

    expect(mockEngine.syncPendingTracks).toHaveBeenCalled();
    expect(mockEngine.syncPendingTracks).toHaveBeenLastCalledWith({
      next: expect.objectContaining({ trackId: '3' }),
      previous: expect.objectContaining({ trackId: '1' }),
    });
  });

  it('syncs pending tracks using resolver-backed local URLs while offline', async () => {
    const t1 = makeTrack('1');
    const t2 = makeTrack('2');
    const t3 = makeTrack('3');
    mockConnectivityStore.setState({
      offlineModeActive: true,
      offlineTrackIds: new Set(['1', '2', '3']),
    });
    mockEngine.resolveTrackUrl.mockImplementation(async (trackId: string) => ({
      url: `/local/${trackId}.m4a`,
      isOffline: true,
    }));
    usePlayerStore.getState().setQueue([t1, t2], 0);
    usePlayerStore.setState({ history: [t3] });

    renderHook(() => useAudioEngine());

    await act(async () => {});

    expect(mockEngine.syncPendingTracks).toHaveBeenCalled();
    expect(mockEngine.syncPendingTracks).toHaveBeenLastCalledWith({
      next: expect.objectContaining({ trackId: '2', url: '/local/2.m4a' }),
      previous: expect.objectContaining({ trackId: '3', url: '/local/3.m4a' }),
    });
    expect(mockTracksApi.getStreamUrl).not.toHaveBeenCalledWith('2');
    expect(mockTracksApi.getStreamUrl).not.toHaveBeenCalledWith('3');
    expect(mockConnectivityStore.getState().incrementCounterBy).toHaveBeenCalledWith('pending_sync_local_url_local', 2);
    expect(mockConnectivityStore.getState().incrementCounterBy).toHaveBeenCalledWith('pending_sync_local_url_total', 2);
  });

  it('increments remote command mismatch counter when pending resolution fails', async () => {
    const t1 = makeTrack('1');
    const t2 = makeTrack('2');
    usePlayerStore.getState().setQueue([t1, t2], 0);
    mockEngine.resolveTrackUrl.mockImplementation(async (trackId: string) => {
      if (trackId === '2') throw new Error('Failed to fetch');
      return { url: `/api/v1/tracks/${trackId}/stream`, isOffline: false };
    });

    renderHook(() => useAudioEngine());
    await act(async () => {});

    expect(mockConnectivityStore.getState().incrementCounter).toHaveBeenCalledWith('remote_command_enablement_mismatch');
  });

  it('re-syncs pending previous when history changes without currentTrack id change', async () => {
    const t1 = makeTrack('1');
    const t2 = makeTrack('2');
    const t3 = makeTrack('3');
    usePlayerStore.getState().setQueue([t1, t2, t3], 1);

    renderHook(() => useAudioEngine());
    await act(async () => {});

    const initialCalls = mockEngine.syncPendingTracks.mock.calls.length;
    expect(initialCalls).toBeGreaterThan(0);

    await act(async () => {
      usePlayerStore.setState({ history: [t1] });
    });

    expect(mockEngine.syncPendingTracks.mock.calls.length).toBeGreaterThan(initialCalls);
    expect(mockEngine.syncPendingTracks).toHaveBeenLastCalledWith({
      next: expect.objectContaining({ trackId: '3' }),
      previous: expect.objectContaining({ trackId: '1' }),
    });
  });

  it('re-syncs pending next when queue length changes without currentTrack id change', async () => {
    const t1 = makeTrack('1');
    const t2 = makeTrack('2');
    const t3 = makeTrack('3');
    usePlayerStore.getState().setQueue([t1, t2], 0);

    renderHook(() => useAudioEngine());
    await act(async () => {});

    const initialCalls = mockEngine.syncPendingTracks.mock.calls.length;
    expect(initialCalls).toBeGreaterThan(0);

    await act(async () => {
      usePlayerStore.getState().addToQueue(t3);
    });

    expect(mockEngine.syncPendingTracks.mock.calls.length).toBeGreaterThan(initialCalls);
    expect(mockEngine.syncPendingTracks).toHaveBeenLastCalledWith({
      next: expect.objectContaining({ trackId: '2' }),
      previous: null,
    });
  });

  it('sends null pending tracks at single-track boundary', async () => {
    const t1 = makeTrack('1');
    usePlayerStore.getState().setQueue([t1], 0);

    renderHook(() => useAudioEngine());
    await act(async () => {});

    expect(mockEngine.syncPendingTracks).toHaveBeenCalled();
    expect(mockEngine.syncPendingTracks).toHaveBeenLastCalledWith({
      next: null,
      previous: null,
    });
  });

  it('falls back to next downloaded track on network-unreachable load error', async () => {
    const t1 = makeTrack('1');
    const t2 = makeTrack('2');
    const t3 = makeTrack('3');
    mockConnectivityStore.setState({
      offlineTrackIds: new Set(['3']),
      refreshOfflineTrackIds: vi.fn(async () => {}),
    });
    mockEngine.resolveTrackUrl.mockImplementation(async (trackId: string) => {
      if (trackId === '1' || trackId === '2') throw new Error('Failed to fetch');
      return { url: `/api/v1/tracks/${trackId}/stream`, isOffline: false };
    });

    usePlayerStore.getState().setQueue([t1, t2, t3], 0);
    renderHook(() => useAudioEngine());

    await act(async () => {});

    const state = usePlayerStore.getState();
    expect(state.currentTrack?.id).toBe('3');
    expect(state.queueIndex).toBe(2);
    expect(mockConnectivityStore.getState().noteStreamLoadFailure).toHaveBeenCalled();
  });

  it('preload timeout fallback still advances on ended when next is not ready', async () => {
    const t1 = makeTrack('1');
    const t2 = makeTrack('2');
    usePlayerStore.getState().setQueue([t1, t2], 0);
    mockEngine.isNextReady.mockReturnValue(false);
    mockEngine.preloadNext.mockResolvedValue(false);

    renderHook(() => useAudioEngine());

    await act(async () => {
      mockEngine.__emit({ type: 'timeUpdate', currentTime: 96, duration: 100 });
      usePlayerStore.setState({ isLoadingAudio: false });
      mockEngine.__emit({ type: 'ended' });
    });

    expect(usePlayerStore.getState().currentTrack?.id).toBe('2');
  });

  it('does not attempt stream fallback for unavailable-offline track', async () => {
    const t1 = makeTrack('1');
    const t2 = makeTrack('2');
    mockConnectivityStore.setState({
      offlineModeActive: true,
      offlineTrackIds: new Set(['2']),
    });
    mockEngine.resolveTrackUrl.mockImplementation(async (trackId: string) => {
      if (trackId === '1') {
        const err = new Error('Track unavailable while offline') as Error & { code?: string };
        err.code = 'offline-unavailable';
        throw err;
      }
      return { url: `/local/${trackId}.mp3`, isOffline: true };
    });

    usePlayerStore.getState().setQueue([t1, t2], 0);
    renderHook(() => useAudioEngine());

    await act(async () => {});

    const state = usePlayerStore.getState();
    expect(state.currentTrack?.id).toBe('2');
    expect(mockEngine.resolveTrackUrl).toHaveBeenCalledWith('2');
  });
});
