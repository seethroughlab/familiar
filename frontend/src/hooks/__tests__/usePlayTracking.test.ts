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
  fetchTracksBatched: vi.fn(() => Promise.resolve([])),
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
    file_path: `/music/${id}.mp3`,
    title: 'Test Track',
    artist: 'Test Artist',
    album: 'Test Album',
    album_artist: null,
    album_type: 'album' as const,
    track_number: null,
    disc_number: null,
    year: null,
    genre: null,
    duration_seconds: 180,
    format: 'mp3',
    analysis_version: 1,
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
