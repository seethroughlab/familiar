import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  installNowPlayingSink, getNowPlaying, subscribeToNowPlaying, resetNowPlayingForTests,
} from '../nowPlayingSink';

/**
 * ADR-0090's channel, from the page's side.
 *
 * The half that matters is point 5: **advisory**. A page that is never called must behave exactly
 * as it did before this existed, because the same bundle runs in the web app — which has no player
 * and will never call the sink — and inside an older build of the native app that does not know to.
 */
describe('the now-playing sink', () => {
  beforeEach(() => {
    resetNowPlayingForTests();
    installNowPlayingSink();
  });

  const send = (frame: unknown) =>
    (window as unknown as Record<string, (f: unknown) => void>).__familiarNowPlaying(frame);

  it('reports nothing playing until a host says otherwise', () => {
    resetNowPlayingForTests();
    // The web app's whole lifetime. No indicator, no error, no difference from before ADR-0090.
    expect(getNowPlaying()).toEqual({ trackId: null, playing: false });
  });

  it('takes the track and the transport from a frame', () => {
    send({ trackId: 'abc', playing: true });
    expect(getNowPlaying()).toEqual({ trackId: 'abc', playing: true });
  });

  it('notifies subscribers only when something actually changed', () => {
    const listener = vi.fn();
    subscribeToNowPlaying(listener);

    send({ trackId: 'abc', playing: true });
    send({ trackId: 'abc', playing: true });
    send({ trackId: 'abc', playing: true });

    // The native side sends on its own schedule and repeats itself. Publishing regardless would
    // re-render the Discover tree at the channel's rate for no reason.
    expect(listener).toHaveBeenCalledTimes(1);

    send({ trackId: 'abc', playing: false });
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it('treats a malformed frame as nothing playing rather than throwing', () => {
    send({ trackId: 'abc', playing: true });
    // A host sending rubbish must not take the surface down with it: this runs inside a WKWebView
    // where an exception is invisible.
    expect(() => send({ trackId: 42, playing: 'yes' })).not.toThrow();
    expect(getNowPlaying()).toEqual({ trackId: null, playing: false });
  });

  it('handles a track ending', () => {
    send({ trackId: 'abc', playing: true });
    send({ trackId: null, playing: false });
    expect(getNowPlaying()).toEqual({ trackId: null, playing: false });
  });
});
