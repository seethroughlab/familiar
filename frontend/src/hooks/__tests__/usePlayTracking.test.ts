/**
 * Tests for usePlayTracking hook.
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { usePlayTracking } from '../usePlayTracking';
import { usePlayerStore } from '../../stores/playerStore';
import { playTrackingApi } from '../../api/client';

// Mock the API client
vi.mock('../../api/client', () => ({
  playTrackingApi: {
    recordPlay: vi.fn(() => Promise.resolve({ track_id: 'test-id', play_count: 1, total_play_seconds: 60 })),
  },
}));

// Mock the persistence functions
vi.mock('../../services/playerPersistence', () => ({
  debouncedSavePlayerState: vi.fn(),
  loadPlayerState: vi.fn(() => Promise.resolve(null)),
  fetchTracksByIds: vi.fn(() => Promise.resolve([])),
  migrateOldPlayerState: vi.fn(() => Promise.resolve()),
}));

describe('usePlayTracking', () => {
  beforeEach(() => {
    // Reset store to initial state before each test
    usePlayerStore.setState({
      currentTrack: null,
      isPlaying: false,
      currentTime: 0,
      duration: 180,
      volume: 0.5,
      shuffle: false,
      repeat: 'off',
      queue: [],
      queueIndex: -1,
      history: [],
      shuffleOrder: [],
      shuffleIndex: -1,
      crossfadeState: 'idle',
      nextTrackPreloaded: false,
      isHydrated: true,
    });
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  const createMockTrack = (id: string) => ({
    id,
    path: `/music/${id}.mp3`,
    title: 'Test Track',
    artist: 'Test Artist',
    album: 'Test Album',
    genre: null,
    year: null,
    track_number: null,
    disc_number: null,
    duration: 180,
    sample_rate: 44100,
    channels: 2,
    bitrate: 320,
    size_bytes: 1000000,
    mtime: '2024-01-01T00:00:00Z',
    features: null,
    embedding: null,
    analysis_version: 1,
    lyrics: null,
    art_path: null,
    play_count: 0,
    library_id: '1',
    album_artist: null,
    bpm: null,
  });

  it('should not record play when track has played less than 30 seconds', async () => {
    const track = createMockTrack('track-1');

    renderHook(() => usePlayTracking());

    // Start playing and jump to 25 seconds immediately
    act(() => {
      usePlayerStore.setState({
        currentTrack: track,
        isPlaying: true,
        duration: 180,
        currentTime: 25,
      });
    });

    // Give effects time to run
    await waitFor(() => {
      expect(playTrackingApi.recordPlay).not.toHaveBeenCalled();
    });
  });

  it('should record play when threshold is reached', async () => {
    const track = createMockTrack('track-2');

    const { rerender } = renderHook(() => usePlayTracking());

    // Start playing a 120-second track at time 0
    act(() => {
      usePlayerStore.setState({
        currentTrack: track,
        isPlaying: true,
        duration: 120,
        currentTime: 0,
      });
    });

    // Force a rerender to ensure hooks run
    rerender();

    // Now jump directly to past the threshold (60 seconds for 50% of 120)
    act(() => {
      usePlayerStore.setState({ currentTime: 65 });
    });

    rerender();

    // Give effects time to run
    await waitFor(() => {
      expect(playTrackingApi.recordPlay).toHaveBeenCalledWith('track-2', expect.any(Number));
    }, { timeout: 2000 });
  });

  it('should not record when paused', async () => {
    const track = createMockTrack('track-5');

    renderHook(() => usePlayTracking());

    // Start playing at time 25
    act(() => {
      usePlayerStore.setState({
        currentTrack: track,
        isPlaying: true,
        duration: 120,
        currentTime: 25,
      });
    });

    // Pause
    act(() => {
      usePlayerStore.setState({ isPlaying: false });
    });

    // Time jumps while paused
    act(() => {
      usePlayerStore.setState({ currentTime: 100 });
    });

    // Should not record while paused
    await waitFor(() => {
      expect(playTrackingApi.recordPlay).not.toHaveBeenCalled();
    });
  });
});
