import { vi } from 'vitest';
import type { Track } from '../../types';

export const createMockTrack = (id: string, title = 'Test Track'): Track => ({
  id,
  title,
  artist: 'Test Artist',
  album: 'Test Album',
  album_artist: null,
  album_type: 'album',
  track_number: 1,
  disc_number: 1,
  year: 2024,
  genre: 'Test',
  duration_seconds: 180,
  format: 'mp3',
  file_path: `/music/${id}.mp3`,
  analysis_version: 1,
});

export const mockConnectivityState = {
  offlineModeActive: false,
  offlineTrackIds: new Set<string>(),
};

/**
 * Standard mock setup for playerStore tests.
 * Call vi.mock() with these in your test file's top-level scope.
 */
export function setupStandardMocks() {
  vi.mock('../persistence', () => ({
    debouncedSavePlayerState: vi.fn(),
    loadPlayerState: vi.fn(() => Promise.resolve(null)),
    fetchTracksBatched: vi.fn(() => Promise.resolve([])),
    migrateOldPlayerState: vi.fn(() => Promise.resolve()),
  }));

  vi.mock('../audio/engineInstance', () => ({
    getEngine: () => ({ seek: vi.fn(), cancelCrossfade: vi.fn() }),
  }));

  vi.mock('../../stores/connectivityStore', () => ({
    useConnectivityStore: Object.assign(
      (selector: (state: typeof mockConnectivityState) => unknown) => selector(mockConnectivityState),
      { getState: () => mockConnectivityState }
    ),
  }));
}
