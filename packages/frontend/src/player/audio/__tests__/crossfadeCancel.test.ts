/**
 * Regression test for a silent playback-killing bug in the crossfade path.
 *
 * `executeCrossfade` optimistically sets `loadedTrackId` to the next track, because a
 * crossfade normally completes. When it is cancelled instead — a media error on either
 * element rolls it back — the element still playing is the *current* one, but
 * `cancelCrossfade` used to leave `loadedTrackId` pointing at the next track.
 *
 * That desync is permanent and fatal. `useAudioEngine`'s 'ended' handler discards the
 * event whenever `engine.getLoadedTrackId() !== store.currentTrack.id`, so once the two
 * disagree the queue never advances again and playback dies with no error shown.
 *
 * Observed live: after a failed crossfade the logs showed
 * `ended ignored: queue already advanced {currentId: <rolled-back track>, loadedId: <next track>}`
 * on every subsequent track end.
 */
import { describe, expect, it } from 'vitest';
import { WebAudioEngine } from '../../../../../web/src/WebAudioEngine';

/** Minimal harness — cancelCrossfade only touches elements, gains and URL state. */
function makeEngineMidCrossfade() {
  const engine = new WebAudioEngine();
  const internals = engine as unknown as {
    elementA: HTMLAudioElement | null;
    elementB: HTMLAudioElement | null;
    currentIsA: boolean;
    crossfadeActive: boolean;
    loadedTrackId: string | null;
    preloadingTrackId: string | null;
  };

  const current = document.createElement('audio');
  current.setAttribute('data-track-id', 'current-track');
  const next = document.createElement('audio');
  next.setAttribute('data-track-id', 'next-track');

  internals.elementA = current;
  internals.elementB = next;
  internals.currentIsA = true;
  internals.crossfadeActive = true;
  // What executeCrossfade leaves behind: pointing at the track that has not taken over.
  internals.loadedTrackId = 'next-track';
  internals.preloadingTrackId = 'next-track';

  return { engine, internals };
}

describe('WebAudioEngine.cancelCrossfade', () => {
  it('restores loadedTrackId to the track that is actually playing', () => {
    const { engine } = makeEngineMidCrossfade();
    expect(engine.getLoadedTrackId()).toBe('next-track');

    engine.cancelCrossfade();

    // Must match the element still playing, or the 'ended' guard silently kills the queue.
    expect(engine.getLoadedTrackId()).toBe('current-track');
  });

  it('clears crossfade state so a later crossfade can run', () => {
    const { engine, internals } = makeEngineMidCrossfade();

    engine.cancelCrossfade();

    expect(engine.isCrossfading()).toBe(false);
    expect(internals.preloadingTrackId).toBeNull();
  });

  it('is a no-op when no crossfade is active', () => {
    const { engine, internals } = makeEngineMidCrossfade();
    internals.crossfadeActive = false;
    internals.loadedTrackId = 'something-else';

    engine.cancelCrossfade();

    // Nothing in flight to roll back — must not clobber the loaded track.
    expect(engine.getLoadedTrackId()).toBe('something-else');
  });

  it('handles a missing current element without throwing', () => {
    const { engine, internals } = makeEngineMidCrossfade();
    internals.elementA = null;

    expect(() => engine.cancelCrossfade()).not.toThrow();
    expect(engine.getLoadedTrackId()).toBeNull();
  });
});
