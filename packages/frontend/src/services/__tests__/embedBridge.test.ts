import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { isEmbedded, postPlayIntent, profileFromURL, BRIDGE_HANDLER, type PlayIntent } from '../embedBridge';

/**
 * The seam ADR-0016 names as the main risk of embedding: two clients that were independent now share
 * one message shape, and a change on this side can break the native app through it.
 *
 * So these pin the shape, and they pin the two failure modes that matter — inert in a browser, and
 * inert rather than throwing when the native side misbehaves. "Inert" is the correct failure here:
 * ADR-0017 puts a null audio engine underneath precisely so that nothing playing is the worst
 * outcome, rather than a second engine.
 */
describe('embedBridge', () => {
  let posted: unknown[];

  function installHandler(impl?: (message: unknown) => void) {
    posted = [];
    (window as unknown as Record<string, unknown>).webkit = {
      messageHandlers: {
        [BRIDGE_HANDLER]: {
          postMessage: impl ?? ((message: unknown) => posted.push(message)),
        },
      },
    };
  }

  beforeEach(() => {
    posted = [];
    delete (window as unknown as Record<string, unknown>).webkit;
  });

  afterEach(() => {
    delete (window as unknown as Record<string, unknown>).webkit;
    vi.restoreAllMocks();
  });

  it('is inert in an ordinary browser', () => {
    // This module lives in the shared package, so it is loaded by the web app and the iOS app too.
    // Posting into nothing must be a no-op, not a crash.
    expect(isEmbedded()).toBe(false);
    expect(postPlayIntent({ trackIds: ['a'], startingAt: 'a' })).toBe(false);
  });

  it('detects a native host and posts the agreed shape', () => {
    installHandler();
    expect(isEmbedded()).toBe(true);

    expect(postPlayIntent({ trackIds: ['a', 'b', 'c'], startingAt: 'b' })).toBe(true);
    expect(posted).toEqual([
      { type: 'play', trackIds: ['a', 'b', 'c'], startingAt: 'b' } satisfies PlayIntent,
    ]);
  });

  /**
   * A `startingAt` outside the list would leave the native side picking a cursor for a track it was
   * never given. The first track is the honest default.
   */
  it('falls back to the first track when startingAt is not in the list', () => {
    installHandler();
    postPlayIntent({ trackIds: ['a', 'b'], startingAt: 'zzz' });
    expect((posted[0] as PlayIntent).startingAt).toBe('a');
  });

  it('refuses to post an empty queue', () => {
    installHandler();
    expect(postPlayIntent({ trackIds: [], startingAt: 'a' })).toBe(false);
    expect(posted).toEqual([]);
  });

  /**
   * A throwing bridge is a native-side problem. Taking the page down with it would put a stack trace
   * inside a web view inside an app, which ADR-0016 calls the hardest place to read one.
   */
  it('survives a native handler that throws', () => {
    installHandler(() => {
      throw new Error('native side blew up');
    });
    expect(() => postPlayIntent({ trackIds: ['a'], startingAt: 'a' })).not.toThrow();
    expect(postPlayIntent({ trackIds: ['a'], startingAt: 'a' })).toBe(false);
  });

  it('treats a half-installed bridge as absent', () => {
    // The handler object exists but has no `postMessage` — what a partially wired native side looks
    // like, and it must read as "no bridge" rather than crashing on the call.
    (window as unknown as Record<string, unknown>).webkit = {
      messageHandlers: { [BRIDGE_HANDLER]: {} },
    };
    expect(isEmbedded()).toBe(false);
    expect(postPlayIntent({ trackIds: ['a'], startingAt: 'a' })).toBe(false);
  });
});

describe('profileFromURL', () => {
  it('reads the profile the native host passed', () => {
    expect(profileFromURL('?profile=abc123')).toBe('abc123');
    expect(profileFromURL('?other=1&profile=abc123&x=2')).toBe('abc123');
  });

  /**
   * Absent means no profile, never "fall back to storage" (ADR-0016 point 6). A `WKWebView` has its
   * own empty `localStorage`, so a fallback would either send nothing anyway or — worse, later —
   * send a previous listener's id, making the surface act as someone other than the window around
   * it.
   */
  it('returns null rather than guessing when nothing was passed', () => {
    expect(profileFromURL('')).toBeNull();
    expect(profileFromURL('?other=1')).toBeNull();
    expect(profileFromURL('?profile=')).toBeNull();
    expect(profileFromURL('?profile=%20%20')).toBeNull();
  });

  it('handles ids that need decoding', () => {
    expect(profileFromURL('?profile=a%20b')).toBe('a b');
  });
});
