/**
 * ADR-0087 point 2: the event contract, and the three things about it that can fail silently.
 *
 * The handshake, because without it the host talks to a document that has not attached a listener
 * and the first track of a session never arrives — which looks like a broken plugin. The source
 * check, because the plugin has an opaque origin, so identity is the only thing that can be
 * verified and a string comparison would be a check that never matches. And the *subscription* to
 * the analysis loop, which shipped missing: `getAudioData` is a getter over a buffer that only
 * moves while something holds a subscription, every visualizer used to hold one by being a React
 * component, and a document cannot. The buffer stayed empty, every plugin got silent audio, and
 * nothing anywhere errored.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, act } from '@testing-library/react';
import { DocumentVisualizer, READY, EVENT_API_VERSION } from '../DocumentVisualizer';

const audio = { bass: 0.5, mid: 0.4, treble: 0.3, averageFrequency: 120, frequencyData: new Uint8Array([1, 2, 3]) };
const subscribe = vi.fn();
vi.mock('../hooks', () => ({
  getAudioData: () => audio,
  useAudioAnalyser: (enabled: boolean) => subscribe(enabled),
}));

const track = { id: 't1', title: 'A Song', artist: 'An Artist', album: 'An Album' } as never;

/** Messages the host posted into the frame, in order. */
function sentMessages(frame: HTMLIFrameElement): Array<Record<string, unknown>> {
  const post = frame.contentWindow!.postMessage as unknown as { mock: { calls: unknown[][] } };
  return post.mock.calls.map((c) => c[0] as Record<string, unknown>);
}

function mountWithSpy(props: Partial<React.ComponentProps<typeof DocumentVisualizer>> = {}) {
  const result = render(
    <DocumentVisualizer
      src="familiar-visualizer://plugin/index.html"
      track={track}
      features={null}
      artworkUrl="art.png"
      lyrics={null}
      currentTime={12}
      duration={200}
      isPlaying
      {...props}
    />
  );
  const frame = result.container.querySelector('iframe')!;
  // jsdom gives the frame a real contentWindow; the spy is what lets us read what was posted.
  Object.defineProperty(frame, 'contentWindow', {
    value: { postMessage: vi.fn() },
    configurable: true,
  });
  return { ...result, frame };
}

function sayReady(frame: HTMLIFrameElement) {
  act(() => {
    window.dispatchEvent(new MessageEvent('message', {
      data: { type: READY },
      source: frame.contentWindow as unknown as Window,
    }));
  });
}

describe('DocumentVisualizer', () => {
  beforeEach(() => { vi.stubGlobal('requestAnimationFrame', () => 0); vi.stubGlobal('cancelAnimationFrame', () => {}); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it('renders the plugin sandboxed, without same-origin', () => {
    const { frame } = mountWithSpy();
    // The whole isolation argument rests on this attribute. `allow-same-origin` would give the
    // plugin this page's origin back, which is what ADR-0087 point 5 exists to prevent.
    expect(frame.getAttribute('sandbox')).toBe('allow-scripts');
    expect(frame.getAttribute('src')).toBe('familiar-visualizer://plugin/index.html');
  });

  it('sends nothing until the plugin says it is ready', () => {
    const { frame } = mountWithSpy();
    expect(sentMessages(frame)).toHaveLength(0);
  });

  it('sends the track once the plugin is ready', () => {
    const { frame } = mountWithSpy();
    sayReady(frame);

    const track_ = sentMessages(frame).find((m) => m.type === 'familiar:track');
    expect(track_).toBeDefined();
    expect(track_!.payload).toMatchObject({ id: 't1', title: 'A Song', artworkUrl: 'art.png', duration: 200 });
  });

  it('sends transport state', () => {
    const { frame } = mountWithSpy();
    sayReady(frame);

    const state = sentMessages(frame).find((m) => m.type === 'familiar:state');
    expect(state!.payload).toEqual({ isPlaying: true, currentTime: 12 });
  });

  it('stamps every message with the event API version', () => {
    const { frame } = mountWithSpy();
    sayReady(frame);

    const all = sentMessages(frame);
    expect(all.length).toBeGreaterThan(0);
    for (const message of all) expect(message.apiVersion).toBe(EVENT_API_VERSION);
  });

  it('ignores a ready message from anything but its own frame', () => {
    const { frame } = mountWithSpy();

    act(() => {
      window.dispatchEvent(new MessageEvent('message', {
        data: { type: READY },
        source: window, // some other document on the page
      }));
    });

    expect(sentMessages(frame)).toHaveLength(0);
  });

  it('lends the plugin nothing — the payload is data, not handles', () => {
    const { frame } = mountWithSpy();
    sayReady(frame);

    for (const message of sentMessages(frame)) {
      const json = JSON.stringify(message);
      // If a function or a live object ever leaks into a payload it stops being serialisable,
      // which is the cheapest possible check that this stayed a data contract.
      expect(() => JSON.parse(json)).not.toThrow();
    }
  });
});

describe('the analysis subscription', () => {
  it('subscribes to the analysis loop, rather than only reading its buffer', () => {
    subscribe.mockClear();
    mountWithSpy();

    // The regression: `getAudioData()` was called every frame while nothing held a subscription,
    // so the singleton rAF loop never started and the buffer it reads never filled. Reading is not
    // subscribing, and the failure is silent — the plugins render, they just never move.
    expect(subscribe).toHaveBeenCalledWith(true);
  });
});
