/**
 * Shared fixtures for player tests.
 *
 * Deliberately contains **no `vi.mock` calls**. Vitest hoists `vi.mock` to the top of the
 * module it appears in, even from inside a function body — so a helper module that merely
 * *defines* mocks registers them for every test file that imports anything from it, and
 * those hoisted mocks win over the importing file's own. This module previously exported
 * an unused `setupStandardMocks()` doing exactly that, which silently replaced
 * `../persistence` with inert spies in any test that imported `createMockTrack`. Tests
 * needing a controllable mock got the inert one and failed for reasons unrelated to what
 * they were testing.
 *
 * Each test file declares its own mocks, using `vi.hoisted()` for any spy the factory
 * dereferences at factory-call time.
 */
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

