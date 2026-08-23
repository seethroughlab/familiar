import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  registerPlaybackInterceptor,
  interceptPlayback,
  resetPlaybackInterceptorForTesting,
} from '../playbackInterceptor';
import type { Track } from '../../types';

/**
 * The seam that stops the embedded surface playing audio itself.
 *
 * Written against a real bug: `EmbedDiscover` wired the bridge to the `onPlayTrack` prop, and
 * `DiscoverTrackList` never calls it — it drives `usePlayerStore.setQueueByTrackId` directly. So a
 * track pressed in "Unheard in Your Library" posted no intent, set a local queue, and handed it to a
 * null audio engine. Correctly silent, and the row spun forever.
 *
 * A prop can be missed; the store is where every play path converges. These pin the part that
 * matters: it is inert unless something registers, and it never lets a start id escape the list.
 */
describe('playbackInterceptor', () => {
  const track = (id: string): Track =>
    ({ id, title: id, artist: 'A', album: 'B' }) as unknown as Track;

  beforeEach(() => resetPlaybackInterceptorForTesting());
  afterEach(() => resetPlaybackInterceptorForTesting());

  /**
   * The case that must never regress: the ordinary web app and the iOS app register nothing, and
   * a false here is what lets them keep playing their own audio.
   */
  it('is inert until something registers', () => {
    expect(interceptPlayback([track('a')], 'a')).toBe(false);
  });

  it('hands the whole context and the starting track to the host', () => {
    const seen: unknown[] = [];
    registerPlaybackInterceptor((intent) => {
      seen.push(intent);
      return true;
    });

    expect(interceptPlayback([track('a'), track('b'), track('c')], 'b')).toBe(true);
    expect(seen).toEqual([
      { tracks: [track('a'), track('b'), track('c')], startingAt: 'b' },
    ]);
  });

  /**
   * A start id outside the list would leave the native side choosing a cursor for a track it was
   * never given — the same defence the bridge and its Swift parser both already make.
   */
  it('falls back to the first track when the start is not in the list', () => {
    let got: string | undefined;
    registerPlaybackInterceptor(({ startingAt }) => {
      got = startingAt;
      return true;
    });

    interceptPlayback([track('a'), track('b')], 'nope');
    expect(got).toBe('a');

    interceptPlayback([track('a'), track('b')], undefined);
    expect(got).toBe('a');
  });

  /** Nothing to play is not a request; the host should never be asked about it. */
  it('does not bother the host with an empty queue', () => {
    const host = vi.fn(() => true);
    registerPlaybackInterceptor(host);

    expect(interceptPlayback([], 'a')).toBe(false);
    expect(host).not.toHaveBeenCalled();
  });

  /**
   * A host that declines leaves the app to play normally. Nothing does this today, but the return
   * value is the contract — if it were ignored, a host that could not deliver would silence
   * playback instead of falling back.
   */
  it('lets the app carry on when the host declines', () => {
    registerPlaybackInterceptor(() => false);
    expect(interceptPlayback([track('a')], 'a')).toBe(false);
  });
});
