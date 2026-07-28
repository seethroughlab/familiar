/**
 * Tests for the radio controller (ADR-0005 parts 6-8).
 *
 * The controller holds cadence and insertion policy only — ranking is entirely
 * server-side, under the `RADIO` weight profile. So these cover *when* and *where* a
 * suggestion lands, and the cases where it should stay quiet.
 *
 * Staying quiet matters more than it sounds. This feature inserts tracks the listener did
 * not choose, into a queue they are already enjoying. Inserting something arbitrary
 * because the candidate pool was too small, or stacking duplicates, is worse than
 * inserting nothing at all.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const { mockGetSuggestions, mockGetOfflineNeighbours, mockResolveTrackIds, connectivityState } =
  vi.hoisted(() => ({
    mockGetSuggestions: vi.fn(),
    mockGetOfflineNeighbours: vi.fn(),
    mockResolveTrackIds: vi.fn(),
    connectivityState: { offlineModeActive: false, offlineTrackIds: new Set<string>() },
  }));

vi.mock('../../api/queue', () => ({ queueApi: { getSuggestions: mockGetSuggestions } }));
vi.mock('../../services/offlineManifestService', () => ({
  getOfflineNeighbours: mockGetOfflineNeighbours,
}));
vi.mock('../../services/playlistCache', () => ({
  resolveTrackIds: mockResolveTrackIds,
  // The real converter is trivial and its field mapping is what we want to exercise.
  cachedTrackToTrack: (c: { id: string; title: string }) => ({
    id: c.id, title: c.title, artist: null, album: null, album_artist: null,
    album_type: 'album', track_number: null, disc_number: null, year: null,
    genre: null, duration_seconds: null, format: null, file_path: '', analysis_version: 0,
  }),
}));
vi.mock('../../stores/connectivityStore', () => ({
  useConnectivityStore: Object.assign(
    (sel: (s: typeof connectivityState) => unknown) => sel(connectivityState),
    { getState: () => connectivityState }
  ),
}));

import { radioController, INSERT_EVERY_N_TRACKS, INSERT_OFFSET } from '../radio/radioController';
import { usePlayerStore } from '../playerStore';
import { useRadioStore } from '../../stores/radioStore';
import type { Track } from '../../types';

const track = (id: string, title = `Track ${id}`): Track => ({
  id, title, artist: 'A', album: 'Al', album_artist: null, album_type: 'album' as const,
  track_number: 1, disc_number: 1, year: 2024, genre: null, duration_seconds: 200,
  format: 'mp3', file_path: `/m/${id}.mp3`, analysis_version: 1,
});

const suggestion = (id: string, score = 0.9) => ({ track: track(id), score });

function seedQueue(ids: string[], index = 0) {
  usePlayerStore.setState({
    queue: ids.map((id, i) => ({ track: track(id), queueId: `q${i}` })),
    queueIndex: index,
    currentTrack: track(ids[index]),
  });
}

beforeEach(() => {
  mockGetSuggestions.mockReset();
  mockGetSuggestions.mockResolvedValue({ suggestions: [suggestion('s1')], pool_size: 50, pool_collapsed: false });
  mockGetOfflineNeighbours.mockReset();
  mockGetOfflineNeighbours.mockResolvedValue([]);
  mockResolveTrackIds.mockReset();
  mockResolveTrackIds.mockImplementation((ids: string[]) =>
    Promise.resolve(ids.map((id) => ({ id, title: `Track ${id}` })))
  );
  connectivityState.offlineModeActive = false;
  connectivityState.offlineTrackIds = new Set<string>();
  radioController.stop();
  useRadioStore.setState({ enabled: true });
  seedQueue(['a', 'b', 'c', 'd', 'e', 'f']);
});

describe('staying quiet', () => {
  it('does nothing while disabled', async () => {
    useRadioStore.setState({ enabled: false });
    await radioController.suggest();
    expect(mockGetSuggestions).not.toHaveBeenCalled();
  });

  it('does not insert when the candidate pool collapsed', async () => {
    // Too few candidates to rank meaningfully — inserting anyway would be arbitrary.
    mockGetSuggestions.mockResolvedValue({ suggestions: [], pool_size: 2, pool_collapsed: true });
    const before = usePlayerStore.getState().queue.length;

    await radioController.suggest();

    expect(usePlayerStore.getState().queue.length).toBe(before);
  });

  it('never asks the server while offline', async () => {
    connectivityState.offlineModeActive = true;
    await radioController.suggest();
    expect(mockGetSuggestions).not.toHaveBeenCalled();
  });

  it('does not insert while offline when the manifest knows nothing', async () => {
    // No manifest yet, or a seed downloaded since the last refresh. A suggestion that
    // cannot stream is worse than no suggestion.
    connectivityState.offlineModeActive = true;
    mockGetOfflineNeighbours.mockResolvedValue([]);
    const before = usePlayerStore.getState().queue.length;

    await radioController.suggest();

    expect(usePlayerStore.getState().queue.length).toBe(before);
  });

  it('does not insert without a current track', async () => {
    usePlayerStore.setState({ currentTrack: null });
    await radioController.suggest();
    expect(mockGetSuggestions).not.toHaveBeenCalled();
  });

  it('swallows a failed request rather than surfacing it', async () => {
    // The listener did not ask for this; a visible error would be noise.
    mockGetSuggestions.mockRejectedValue(new Error('boom'));
    await expect(radioController.suggest()).resolves.toBeUndefined();
  });

  it('does not re-suggest a track it already inserted', async () => {
    await radioController.suggest();
    const afterFirst = usePlayerStore.getState().queue.length;

    mockGetSuggestions.mockResolvedValue({
      suggestions: [suggestion('s1')], pool_size: 50, pool_collapsed: false,
    });
    await radioController.suggest();

    expect(usePlayerStore.getState().queue.length).toBe(afterFirst);
  });

  it('skips a candidate already sitting in the upcoming queue', async () => {
    mockGetSuggestions.mockResolvedValue({
      suggestions: [suggestion('c'), suggestion('fresh')], pool_size: 50, pool_collapsed: false,
    });

    await radioController.suggest();

    const titles = usePlayerStore.getState().queue.map((i) => i.track.id);
    expect(titles.filter((t) => t === 'c')).toHaveLength(1); // not duplicated
    expect(titles).toContain('fresh');
  });
});

describe('insertion', () => {
  it('marks the inserted track as a suggestion', async () => {
    await radioController.suggest();

    const inserted = usePlayerStore.getState().queue.find((i) => i.track.id === 's1');
    expect(inserted?.suggested).toBe(true);
  });

  it('does not displace the listener’s very next track', async () => {
    // Landing at queueIndex+1 would read as the app overriding their choice.
    seedQueue(['a', 'b', 'c', 'd'], 1);

    await radioController.suggest();

    const q = usePlayerStore.getState().queue.map((i) => i.track.id);
    expect(q[2]).toBe('c');   // their next track, untouched
    expect(q[3]).toBe('s1');  // suggestion lands after it
  });

  it('sends recent tracks and artists so the server can avoid repeats', async () => {
    seedQueue(['a', 'b', 'c'], 2);

    await radioController.suggest();

    const body = mockGetSuggestions.mock.calls[0][0];
    expect(body.current_track_id).toBe('c');
    expect(body.recent_track_ids).toEqual(expect.arrayContaining(['a', 'b', 'c']));
    expect(body.profile).toBe('radio');
  });

  it('clamps the insert position to the end of a short queue', async () => {
    seedQueue(['a'], 0);
    await radioController.suggest();
    expect(usePlayerStore.getState().queue.map((i) => i.track.id)).toEqual(['a', 's1']);
  });
});

describe('shuffle', () => {
  // Found in use, not by these tests: with shuffle on, both playback and QueueView follow
  // shuffleOrder rather than the queue array. addToQueue appends to that order unless
  // given a position, so the suggestion landed last in play order — at index ~1719 of a
  // favourites queue. Invisible at the bottom of a virtualised list, and never reached.
  function seedShuffled(ids: string[], shuffleIndex: number) {
    seedQueue(ids, 0);
    usePlayerStore.setState({
      shuffle: true,
      shuffleOrder: ids.map((_, i) => i),
      shuffleIndex,
      currentTrack: track(ids[shuffleIndex]),
      queueIndex: shuffleIndex,
    });
  }

  it('places the suggestion just ahead in play order, not at the end', async () => {
    seedShuffled(['a', 'b', 'c', 'd', 'e', 'f'], 1);

    await radioController.suggest();

    const { queue, shuffleOrder } = usePlayerStore.getState();
    const playOrderIds = shuffleOrder.map((qi) => queue[qi]?.track.id);
    const position = playOrderIds.indexOf('s1');

    expect(position).toBeGreaterThan(-1);
    expect(position).toBeLessThan(shuffleOrder.length - 1); // not dumped at the end
    expect(position).toBe(1 + INSERT_OFFSET);
  });

  it('does not displace the next track in play order', async () => {
    seedShuffled(['a', 'b', 'c', 'd', 'e', 'f'], 1);
    const { queue: before, shuffleOrder: orderBefore } = usePlayerStore.getState();
    const nextUpId = before[orderBefore[2]].track.id;

    await radioController.suggest();

    const { queue, shuffleOrder } = usePlayerStore.getState();
    expect(queue[shuffleOrder[2]].track.id).toBe(nextUpId);
  });

  it('still inserts sensibly with shuffle off', async () => {
    seedQueue(['a', 'b', 'c', 'd'], 1);
    usePlayerStore.setState({ shuffle: false, shuffleOrder: [], shuffleIndex: -1 });

    await radioController.suggest();

    expect(usePlayerStore.getState().queue.map((i) => i.track.id)[3]).toBe('s1');
  });
});

describe('cadence', () => {
  it('waits N track changes before suggesting', async () => {
    radioController.start();
    seedQueue(['a', 'b', 'c', 'd', 'e', 'f'], 0);

    for (let i = 1; i < INSERT_EVERY_N_TRACKS; i++) {
      usePlayerStore.setState({ currentTrack: track(String(i)) });
    }
    await vi.waitFor(() => expect(mockGetSuggestions).not.toHaveBeenCalled());

    usePlayerStore.setState({ currentTrack: track('final') });
    await vi.waitFor(() => expect(mockGetSuggestions).toHaveBeenCalled());

    radioController.stop();
  });
});

describe('accepting and rejecting', () => {
  it('accepting clears the marker so the affordances go away', async () => {
    await radioController.suggest();
    const item = usePlayerStore.getState().queue.find((i) => i.track.id === 's1')!;

    usePlayerStore.getState().acceptSuggestion(item.queueId);

    const after = usePlayerStore.getState().queue.find((i) => i.track.id === 's1');
    expect(after?.suggested).toBe(false);
    expect(after).toBeDefined(); // kept, not removed
  });

  it('accepting a non-suggestion is a no-op', () => {
    seedQueue(['a', 'b']);
    const before = usePlayerStore.getState().queue;

    usePlayerStore.getState().acceptSuggestion('q0');

    expect(usePlayerStore.getState().queue).toEqual(before);
  });

  it('rejecting removes it from the queue', async () => {
    await radioController.suggest();
    const item = usePlayerStore.getState().queue.find((i) => i.track.id === 's1')!;

    usePlayerStore.getState().removeFromQueue(item.queueId);

    expect(usePlayerStore.getState().queue.find((i) => i.track.id === 's1')).toBeUndefined();
  });
});

/**
 * Offline radio (ADR-0006).
 *
 * The server generates a `radio` variant of the offline manifest and, until this, nothing
 * consumed it — radio simply went quiet in airplane mode. The ranking is still entirely
 * server-side: these assert that the client does lookup and ordering, never scoring, and
 * that it refuses to suggest a track whose audio is not actually on the device.
 */
describe('offline', () => {
  beforeEach(() => {
    connectivityState.offlineModeActive = true;
    connectivityState.offlineTrackIds = new Set(['n1', 'n2', 'n3']);
  });

  it('suggests from the manifest instead of going quiet', async () => {
    mockGetOfflineNeighbours.mockResolvedValue([{ trackId: 'n1', score: 0.88 }]);

    await radioController.suggest();

    expect(usePlayerStore.getState().queue.some((i) => i.track.id === 'n1')).toBe(true);
    expect(mockGetSuggestions).not.toHaveBeenCalled();
  });

  it('asks for the radio variant, not ambient', async () => {
    // Weight profile is what makes a suggestion radio-shaped rather than ambient-shaped.
    mockGetOfflineNeighbours.mockResolvedValue([{ trackId: 'n1', score: 0.8 }]);

    await radioController.suggest();

    expect(mockGetOfflineNeighbours).toHaveBeenCalledWith(
      'a',
      expect.objectContaining({ profile: 'radio', filterPreset: 'all' })
    );
  });

  it('preserves the manifest order rather than re-ranking', async () => {
    // There is no scorer on this client, so "best" can only mean "first as sent".
    mockGetOfflineNeighbours.mockResolvedValue([
      { trackId: 'n2', score: 0.4 },
      { trackId: 'n1', score: 0.9 },
    ]);

    await radioController.suggest();

    expect(usePlayerStore.getState().queue.some((i) => i.track.id === 'n2')).toBe(true);
    expect(usePlayerStore.getState().queue.some((i) => i.track.id === 'n1')).toBe(false);
  });

  it('refuses a neighbour whose audio is not downloaded', async () => {
    // The manifest goes stale when a track is removed. Suggesting metadata-only tracks is
    // the exact bug ADR-0006 flagged in offlineScoring (cachedTracks vs offlineTracks),
    // and addToQueue would silently drop it anyway.
    connectivityState.offlineTrackIds = new Set(['n2']);
    mockGetOfflineNeighbours.mockResolvedValue([
      { trackId: 'n1', score: 0.9 },
      { trackId: 'n2', score: 0.5 },
    ]);

    await radioController.suggest();

    const queue = usePlayerStore.getState().queue;
    expect(queue.some((i) => i.track.id === 'n1')).toBe(false);
    expect(queue.some((i) => i.track.id === 'n2')).toBe(true);
  });

  it('stays quiet when nothing in the manifest is downloaded', async () => {
    connectivityState.offlineTrackIds = new Set<string>();
    mockGetOfflineNeighbours.mockResolvedValue([{ trackId: 'n1', score: 0.9 }]);
    const before = usePlayerStore.getState().queue.length;

    await radioController.suggest();

    expect(usePlayerStore.getState().queue.length).toBe(before);
    // Nothing playable, so no point resolving metadata for it.
    expect(mockResolveTrackIds).not.toHaveBeenCalled();
  });

  it('marks an offline suggestion the same as an online one', async () => {
    mockGetOfflineNeighbours.mockResolvedValue([{ trackId: 'n1', score: 0.88 }]);

    await radioController.suggest();

    const item = usePlayerStore.getState().queue.find((i) => i.track.id === 'n1');
    expect(item?.suggested).toBe(true);
  });

  it('passes recent tracks so the manifest lookup can skip them', async () => {
    seedQueue(['a', 'b', 'c'], 2);
    mockGetOfflineNeighbours.mockResolvedValue([{ trackId: 'n1', score: 0.9 }]);

    await radioController.suggest();

    const opts = mockGetOfflineNeighbours.mock.calls[0][1];
    expect(opts.recentTrackIds).toEqual(expect.arrayContaining(['a', 'b', 'c']));
  });
});
