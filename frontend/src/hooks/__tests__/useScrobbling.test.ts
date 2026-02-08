/**
 * Tests for useScrobbling hook - Last.fm scrobbling behavior.
 *
 * Scrobbling rules (per Last.fm guidelines):
 * - Send "now playing" when a new track starts
 * - Track must have been played for at least 30 seconds
 * - Track must be scrobbled when either 50% complete OR 4 minutes have passed
 * - Each track should only be scrobbled once per play
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { act } from 'react';
import { useScrobbling } from '../useScrobbling';
import { usePlayerStore } from '../../stores/playerStore';

// Mock the API client
vi.mock('../../api/client', () => ({
  lastfmApi: {
    getStatus: vi.fn(() => Promise.resolve({ connected: true, configured: true, username: 'testuser' })),
    updateNowPlaying: vi.fn(() => Promise.resolve({ status: 'ok', message: '' })),
    scrobble: vi.fn(() => Promise.resolve({ status: 'ok', message: '' })),
  },
}));

// Mock react-query
vi.mock('@tanstack/react-query', () => ({
  useQuery: vi.fn(({ queryFn: _queryFn }: { queryFn: () => unknown }) => ({
    data: { connected: true, configured: true, username: 'testuser' },
    isLoading: false,
    error: null,
  })),
}));

// Mock the persistence functions
vi.mock('../../services/playerPersistence', () => ({
  debouncedSavePlayerState: vi.fn(),
  loadPlayerState: vi.fn(() => Promise.resolve(null)),
  fetchTracksByIds: vi.fn(() => Promise.resolve([])),
  migrateOldPlayerState: vi.fn(() => Promise.resolve()),
}));

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
  duration_seconds: 300,
  format: 'mp3',
  analysis_version: 1,
});

describe('useScrobbling', () => {
  beforeEach(() => {
    usePlayerStore.setState({
      currentTrack: null,
      isPlaying: false,
      currentTime: 0,
      duration: 0,
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

  it('should send now-playing update when a new track starts', async () => {
    const { lastfmApi } = await import('../../api/client');
    const track = createMockTrack('track-1');

    renderHook(() => useScrobbling());

    act(() => {
      usePlayerStore.setState({
        currentTrack: track,
        isPlaying: true,
        duration: 300,
        currentTime: 0,
      });
    });

    await waitFor(() => {
      expect(lastfmApi.updateNowPlaying).toHaveBeenCalledWith('track-1');
    });
  });

  it('should not send now-playing when not playing', async () => {
    const { lastfmApi } = await import('../../api/client');
    const track = createMockTrack('track-1');

    renderHook(() => useScrobbling());

    act(() => {
      usePlayerStore.setState({
        currentTrack: track,
        isPlaying: false,
        duration: 300,
        currentTime: 0,
      });
    });

    await waitFor(() => {
      expect(lastfmApi.updateNowPlaying).not.toHaveBeenCalled();
    });
  });

  it('should not scrobble before 30 seconds of playback', async () => {
    const { lastfmApi } = await import('../../api/client');
    const track = createMockTrack('track-1');

    const { rerender } = renderHook(() => useScrobbling());

    act(() => {
      usePlayerStore.setState({
        currentTrack: track,
        isPlaying: true,
        duration: 60,
        currentTime: 0,
      });
    });

    rerender();

    // At 25 seconds, should not scrobble yet
    act(() => {
      usePlayerStore.setState({ currentTime: 25 });
    });

    rerender();

    await waitFor(() => {
      expect(lastfmApi.scrobble).not.toHaveBeenCalled();
    });
  });

  it('should scrobble at 50% of track duration', async () => {
    const { lastfmApi } = await import('../../api/client');
    const track = createMockTrack('track-2');

    const { rerender } = renderHook(() => useScrobbling());

    // Start playing a 120-second track
    act(() => {
      usePlayerStore.setState({
        currentTrack: track,
        isPlaying: true,
        duration: 120,
        currentTime: 0,
      });
    });

    rerender();

    // Jump to 60 seconds (50% of 120)
    act(() => {
      usePlayerStore.setState({ currentTime: 60 });
    });

    rerender();

    await waitFor(() => {
      expect(lastfmApi.scrobble).toHaveBeenCalledWith('track-2', expect.any(Number));
    });
  });

  it('should scrobble at 4 minutes for long tracks instead of 50%', async () => {
    const { lastfmApi } = await import('../../api/client');
    // 10-minute track: 50% = 300s, 4min = 240s, so scrobble at 240s
    const track = createMockTrack('track-long');

    const { rerender } = renderHook(() => useScrobbling());

    act(() => {
      usePlayerStore.setState({
        currentTrack: track,
        isPlaying: true,
        duration: 600,
        currentTime: 0,
      });
    });

    rerender();

    // Jump to 240 seconds (4 minutes)
    act(() => {
      usePlayerStore.setState({ currentTime: 240 });
    });

    rerender();

    await waitFor(() => {
      expect(lastfmApi.scrobble).toHaveBeenCalledWith('track-long', expect.any(Number));
    });
  });

  it('should not double-scrobble the same track', async () => {
    const { lastfmApi } = await import('../../api/client');
    const track = createMockTrack('track-3');

    const { rerender } = renderHook(() => useScrobbling());

    act(() => {
      usePlayerStore.setState({
        currentTrack: track,
        isPlaying: true,
        duration: 120,
        currentTime: 0,
      });
    });

    rerender();

    // First scrobble point
    act(() => {
      usePlayerStore.setState({ currentTime: 60 });
    });

    rerender();

    await waitFor(() => {
      expect(lastfmApi.scrobble).toHaveBeenCalledTimes(1);
    });

    // Continue playing past scrobble point
    act(() => {
      usePlayerStore.setState({ currentTime: 100 });
    });

    rerender();

    // Should still only have 1 scrobble call
    await waitFor(() => {
      expect(lastfmApi.scrobble).toHaveBeenCalledTimes(1);
    });
  });

  it('should not scrobble when paused', async () => {
    const { lastfmApi } = await import('../../api/client');
    const track = createMockTrack('track-4');

    const { rerender } = renderHook(() => useScrobbling());

    act(() => {
      usePlayerStore.setState({
        currentTrack: track,
        isPlaying: true,
        duration: 120,
        currentTime: 0,
      });
    });

    rerender();

    // Pause
    act(() => {
      usePlayerStore.setState({ isPlaying: false });
    });

    // Jump past threshold while paused
    act(() => {
      usePlayerStore.setState({ currentTime: 100 });
    });

    rerender();

    await waitFor(() => {
      expect(lastfmApi.scrobble).not.toHaveBeenCalled();
    });
  });

  it('should not scrobble when no duration is set', async () => {
    const { lastfmApi } = await import('../../api/client');
    const track = createMockTrack('track-5');

    const { rerender } = renderHook(() => useScrobbling());

    act(() => {
      usePlayerStore.setState({
        currentTrack: track,
        isPlaying: true,
        duration: 0,
        currentTime: 60,
      });
    });

    rerender();

    await waitFor(() => {
      expect(lastfmApi.scrobble).not.toHaveBeenCalled();
    });
  });

  it('should send now-playing only once per track', async () => {
    const { lastfmApi } = await import('../../api/client');
    const track = createMockTrack('track-6');

    const { rerender } = renderHook(() => useScrobbling());

    act(() => {
      usePlayerStore.setState({
        currentTrack: track,
        isPlaying: true,
        duration: 300,
        currentTime: 0,
      });
    });

    rerender();

    // Update time without changing track
    act(() => {
      usePlayerStore.setState({ currentTime: 30 });
    });

    rerender();

    await waitFor(() => {
      expect(lastfmApi.updateNowPlaying).toHaveBeenCalledTimes(1);
    });
  });

  it('should not scrobble when Last.fm is not connected', async () => {
    const { lastfmApi } = await import('../../api/client');
    const { useQuery } = await import('@tanstack/react-query');

    vi.mocked(useQuery).mockReturnValue({
      data: { connected: false, configured: false, username: null },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useQuery>);

    const track = createMockTrack('track-7');

    const { rerender } = renderHook(() => useScrobbling());

    act(() => {
      usePlayerStore.setState({
        currentTrack: track,
        isPlaying: true,
        duration: 120,
        currentTime: 60,
      });
    });

    rerender();

    await waitFor(() => {
      expect(lastfmApi.scrobble).not.toHaveBeenCalled();
      expect(lastfmApi.updateNowPlaying).not.toHaveBeenCalled();
    });
  });
});
