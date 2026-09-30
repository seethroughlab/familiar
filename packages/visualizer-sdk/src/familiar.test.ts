/**
 * The bridge against the recorded protocol (ADR-0125 point 4).
 *
 * Driven through `handleMessage` with the fixtures every first-party visualizer is built against,
 * and once through a real `window` `MessageEvent` to prove the wiring.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { act, renderHook } from '@testing-library/react';

import * as events from './fixtures/events';
import { _reset, API_VERSION, announceReady, getAudioData, handleMessage, install, usePlaybackState, useTrack } from './familiar';

beforeEach(() => _reset());
afterEach(() => vi.restoreAllMocks());

describe('the recorded events', () => {
  it('an audio frame is read as the contract says', () => {
    handleMessage(events.audio);
    const a = getAudioData();
    expect(a.bass).toBe(0.8);
    expect(a.averageFrequency).toBe(120);
    expect(a.frequencyData).toBeInstanceOf(Uint8Array);
    expect(a.frequencyData.length).toBe(64);
    expect(a.frequencyData[1]).toBe(43);
  });

  it('beat and onset default when an older host omits them, and are read when a newer one sends them', () => {
    handleMessage(events.audio);
    expect(getAudioData()).toMatchObject({ beat: 0, onset: false });
    handleMessage(events.audioWithBeat);
    expect(getAudioData()).toMatchObject({ beat: 0.9, onset: true });
  });

  it('a message without apiVersion is a version-1 host', () => {
    handleMessage(events.audioWithoutVersion);
    expect(getAudioData().bass).toBe(0.8);
  });
});

describe('what a bridge must survive', () => {
  it('drops every malformed shape without throwing and keeps the last good frame', () => {
    handleMessage(events.audio);
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    for (const bad of Object.values(events.malformed)) {
      expect(() => handleMessage(bad)).not.toThrow();
    }
    // Garbage fields become zeros; a missing spectrum keeps the previous one rather than blanking.
    expect(getAudioData().frequencyData.length).toBe(64);
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it('a protocol version this bridge does not speak is ignored, and said once', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    handleMessage(events.audio);
    handleMessage(events.malformed.futureVersion);
    handleMessage(events.malformed.futureVersion);
    expect(getAudioData().bass).toBe(0.8);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn.mock.calls[0][0]).toMatch(`apiVersion 2, this document speaks ${API_VERSION}`);
  });

  it('a track can be cleared to null — that is the queue emptying, not a malformed message', () => {
    const { result } = renderHook(() => useTrack());
    act(() => handleMessage(events.track));
    expect(result.current?.title).toBe('A Song');
    act(() => handleMessage(events.trackCleared));
    expect(result.current).toBeNull();
    act(() => handleMessage(events.malformed.trackWithScalarPayload));
    expect(result.current).toBeNull();
  });

  it('a state hook sees each transport change and nothing from a malformed one', () => {
    const { result } = renderHook(() => usePlaybackState());
    act(() => handleMessage(events.state));
    expect(result.current).toEqual({ isPlaying: true, currentTime: 3 });
    act(() => handleMessage(events.malformed.stateWithoutPayload));
    expect(result.current).toEqual({ isPlaying: true, currentTime: 3 });
  });
});

describe('the window wiring', () => {
  it('a real MessageEvent reaches the bridge', () => {
    install();
    window.dispatchEvent(new MessageEvent('message', { data: events.audio }));
    expect(getAudioData().treble).toBe(0.3);
  });

  it('install is idempotent — importing the module attached the listener, and calling it again adds none', () => {
    const add = vi.spyOn(window, 'addEventListener');
    install();
    install();
    expect(add).not.toHaveBeenCalled();
  });

  it('announceReady posts the handshake with the protocol version, after installing', () => {
    const post = vi.spyOn(window.parent, 'postMessage').mockImplementation(() => {});
    vi.stubGlobal('requestAnimationFrame', () => 0);
    announceReady();
    expect(post).toHaveBeenCalledWith({ type: 'familiar:ready', apiVersion: API_VERSION }, '*');
    vi.unstubAllGlobals();
  });
});
