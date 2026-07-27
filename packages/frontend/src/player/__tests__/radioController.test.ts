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

const { mockGetSuggestions, connectivityState } = vi.hoisted(() => ({
  mockGetSuggestions: vi.fn(),
  connectivityState: { offlineModeActive: false, offlineTrackIds: new Set<string>() },
}));

vi.mock('../../api/queue', () => ({ queueApi: { getSuggestions: mockGetSuggestions } }));
vi.mock('../../stores/connectivityStore', () => ({
  useConnectivityStore: Object.assign(
    (sel: (s: typeof connectivityState) => unknown) => sel(connectivityState),
    { getState: () => connectivityState }
  ),
}));

import { radioController, INSERT_EVERY_N_TRACKS } from '../radio/radioController';
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
  connectivityState.offlineModeActive = false;
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

  it('does not insert while offline', async () => {
    // A suggestion that cannot stream is worse than no suggestion.
    connectivityState.offlineModeActive = true;
    await radioController.suggest();
    expect(mockGetSuggestions).not.toHaveBeenCalled();
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
