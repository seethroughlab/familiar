/* @vitest-environment jsdom */
/**
 * Tests for useListeningSession — focused on the message dispatch, lifecycle,
 * and bug regressions identified in the audit (B1, L1, L3, L5).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

// --- WebSocket fake -------------------------------------------------------
class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: FakeWebSocket[] = [];
  url: string;
  readyState: number = FakeWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];
  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
  }
  /* test helpers */
  triggerOpen() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }
  emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent);
  }
  emitRaw(raw: string) {
    this.onmessage?.({ data: raw } as MessageEvent);
  }
}

const realWebSocket = globalThis.WebSocket;
beforeEach(() => {
  FakeWebSocket.instances = [];
  (globalThis as unknown as { WebSocket: typeof FakeWebSocket }).WebSocket = FakeWebSocket;
});
afterEach(() => {
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = realWebSocket;
  vi.clearAllMocks();
});

// --- Mocks ----------------------------------------------------------------
vi.mock('../useWebRTCStreaming', () => ({
  useWebRTCStreaming: vi.fn(() => ({
    isStreaming: false,
    peers: [],
    connectedGuestCount: 0,
    handleSignalingMessage: vi.fn(),
    requestStream: vi.fn(),
    removePeer: vi.fn(),
    setGuestVolume: vi.fn(),
    hasGuestAudio: false,
    hostDisabled: false,
  })),
}));

vi.mock('../useAudioControls', () => ({
  useAudioControls: () => ({
    seek: vi.fn(),
    play: vi.fn(),
    pause: vi.fn(),
  }),
}));

vi.mock('../../services/profileService', () => ({
  getSelectedProfileId: vi.fn(() => Promise.resolve('profile-1')),
  getProfile: vi.fn(() => Promise.resolve({ id: 'profile-1', name: 'Tester' })),
}));

const showErrorMock = vi.fn();
vi.mock('../../stores/toastStore', () => ({
  showError: (...args: unknown[]) => showErrorMock(...args),
}));

import { useListeningSession, buildShareLink } from '../useListeningSession';

const SESSION = {
  id: 'sess-1',
  code: 'ABCDEF12',
  name: 'Test Session',
  host_id: 'user-host',
  participant_count: 1,
  participants: [
    {
      user_id: 'user-host',
      username: 'Host',
      role: 'host' as const,
      joined_at: '2026-01-01T00:00:00Z',
    },
  ],
  webrtc_enabled: true,
  has_password: false,
  playback_state: { track_id: null, is_playing: false, position_ms: 0 },
};

describe('buildShareLink', () => {
  it('URL-encodes the code segment', () => {
    expect(buildShareLink('A B/C')).toMatch(/A%20B%2FC$/);
  });
});

describe('useListeningSession — connect lifecycle', () => {
  it('opens a WebSocket and clears isConnecting on open', async () => {
    const { result } = renderHook(() => useListeningSession({ username: 'T' }));
    act(() => result.current.createSession('My Session'));
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(result.current.isConnecting).toBe(true);
    act(() => FakeWebSocket.instances[0].triggerOpen());
    expect(result.current.isConnecting).toBe(false);
  });

  it('sends the create payload once the WS opens (sendOnceConnected)', async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useListeningSession({ username: 'T' }));
    act(() => result.current.createSession('My Session', 'sekret'));
    const ws = FakeWebSocket.instances[0];
    expect(ws.sent).toEqual([]);
    act(() => {
      ws.triggerOpen();
      vi.advanceTimersByTime(150);
    });
    expect(ws.sent).toHaveLength(1);
    const payload = JSON.parse(ws.sent[0]);
    expect(payload).toMatchObject({ type: 'create', name: 'My Session', password: 'sekret' });
    vi.useRealTimers();
  });

  it('does NOT spawn a second WebSocket when called while CONNECTING (L3)', () => {
    const { result } = renderHook(() => useListeningSession({ username: 'T' }));
    act(() => result.current.createSession('A'));
    act(() => result.current.createSession('B'));
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it('surfaces an error and stops connecting if the WS handshake times out (L4)', () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useListeningSession({ username: 'T' }));
    act(() => result.current.createSession('My Session'));
    expect(result.current.isConnecting).toBe(true);
    act(() => {
      vi.advanceTimersByTime(13_000);
    });
    expect(result.current.isConnecting).toBe(false);
    expect(result.current.error).toMatch(/relay/i);
    expect(showErrorMock).toHaveBeenCalled();
    vi.useRealTimers();
  });

  it('times out a pending sendOnceConnected if WS never opens (L1)', () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useListeningSession({ username: 'T' }));
    act(() => result.current.createSession('My Session'));
    const ws = FakeWebSocket.instances[0];
    act(() => {
      vi.advanceTimersByTime(6_000);
    });
    expect(ws.sent).toEqual([]);
    expect(result.current.error).toMatch(/relay/i);
    vi.useRealTimers();
  });
});

describe('useListeningSession — message dispatch', () => {
  it('drops malformed JSON without crashing (B1)', () => {
    const { result } = renderHook(() => useListeningSession({ username: 'T' }));
    act(() => result.current.createSession('S'));
    const ws = FakeWebSocket.instances[0];
    act(() => ws.triggerOpen());
    expect(() => act(() => ws.emitRaw('{not json'))).not.toThrow();
    expect(result.current.session).toBeNull();
  });

  it('drops messages with a missing or non-string type', () => {
    const { result } = renderHook(() => useListeningSession({ username: 'T' }));
    act(() => result.current.createSession('S'));
    const ws = FakeWebSocket.instances[0];
    act(() => ws.triggerOpen());
    act(() => ws.emit({ no_type: 'here' }));
    act(() => ws.emit({ type: 42 }));
    expect(result.current.session).toBeNull();
  });

  it('drops session_created with no session field (L5)', () => {
    const { result } = renderHook(() => useListeningSession({ username: 'T' }));
    act(() => result.current.createSession('S'));
    const ws = FakeWebSocket.instances[0];
    act(() => ws.triggerOpen());
    act(() => ws.emit({ type: 'session_created', your_user_id: 'u' }));
    expect(result.current.session).toBeNull();
  });

  it('handles session_created and exposes isHost when ids match', () => {
    const { result } = renderHook(() => useListeningSession({ username: 'T' }));
    act(() => result.current.createSession('S'));
    const ws = FakeWebSocket.instances[0];
    act(() => ws.triggerOpen());
    act(() =>
      ws.emit({
        type: 'session_created',
        session: SESSION,
        your_user_id: 'user-host',
        ice_servers: [{ urls: 'stun:stun.example' }],
      }),
    );
    expect(result.current.session?.code).toBe('ABCDEF12');
    expect(result.current.isHost).toBe(true);
    expect(result.current.iceServers).toHaveLength(1);
  });

  it('appends a participant on user_joined and removes on user_left', () => {
    const { result } = renderHook(() => useListeningSession({ username: 'T' }));
    act(() => result.current.createSession('S'));
    const ws = FakeWebSocket.instances[0];
    act(() => ws.triggerOpen());
    act(() =>
      ws.emit({
        type: 'session_created',
        session: SESSION,
        your_user_id: 'user-host',
      }),
    );
    act(() =>
      ws.emit({
        type: 'user_joined',
        user: {
          user_id: 'guest-1',
          username: 'Guest',
          role: 'guest',
          joined_at: '2026-01-01T00:00:01Z',
        },
        participant_count: 2,
      }),
    );
    expect(result.current.session?.participant_count).toBe(2);
    expect(result.current.session?.participants).toHaveLength(2);

    act(() =>
      ws.emit({
        type: 'user_left',
        user_id: 'guest-1',
        participant_count: 1,
      }),
    );
    expect(result.current.session?.participant_count).toBe(1);
    expect(result.current.session?.participants).toHaveLength(1);
  });

  it('appends chat messages with all required fields and ignores partial chat payloads', () => {
    const { result } = renderHook(() => useListeningSession({ username: 'T' }));
    act(() => result.current.createSession('S'));
    const ws = FakeWebSocket.instances[0];
    act(() => ws.triggerOpen());
    act(() => ws.emit({ type: 'chat', user_id: 'g', username: 'Guest', message: 'hi' }));
    act(() => ws.emit({ type: 'chat', user_id: 'g' /* no username/message */ }));
    expect(result.current.chatMessages).toHaveLength(1);
    expect(result.current.chatMessages[0].message).toBe('hi');
  });

  it('routes server errors to setError and showError', () => {
    const { result } = renderHook(() => useListeningSession({ username: 'T' }));
    act(() => result.current.createSession('S'));
    const ws = FakeWebSocket.instances[0];
    act(() => ws.triggerOpen());
    act(() => ws.emit({ type: 'error', message: 'Bad code' }));
    expect(result.current.error).toBe('Bad code');
    expect(showErrorMock).toHaveBeenCalledWith('Session error', expect.objectContaining({ description: 'Bad code' }));
  });
});

describe('useListeningSession — leaveSession + cleanup', () => {
  it('cancels a pending sendOnceConnected timer when leaveSession is called', () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useListeningSession({ username: 'T' }));
    act(() => result.current.createSession('S'));
    act(() => result.current.leaveSession());
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    // Should not have errored out via the pending-send timeout path
    expect(result.current.error).toBeNull();
    vi.useRealTimers();
  });

  it('sends leave on unmount when the WS is open', async () => {
    const { result, unmount } = renderHook(() => useListeningSession({ username: 'T' }));
    act(() => result.current.createSession('S'));
    const ws = FakeWebSocket.instances[0];
    act(() => ws.triggerOpen());
    await waitFor(() => expect(ws.sent.length).toBeGreaterThan(0));
    const sentBefore = ws.sent.length;
    unmount();
    expect(ws.sent.length).toBe(sentBefore + 1);
    expect(JSON.parse(ws.sent[ws.sent.length - 1])).toEqual({ type: 'leave' });
  });
});
