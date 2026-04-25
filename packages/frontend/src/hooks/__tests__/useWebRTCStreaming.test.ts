/* @vitest-environment jsdom */
/**
 * Tests for useWebRTCStreaming — focused on the audit findings:
 * L2 (handleOffer cleans up the prior PC + audio on renegotiation),
 * removePeer closes connections, and host-disabled signaling when no stream.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

// --- RTCPeerConnection fake ----------------------------------------------
class FakeRTCPeerConnection {
  static instances: FakeRTCPeerConnection[] = [];
  config: RTCConfiguration;
  closed = false;
  tracks: MediaStreamTrack[] = [];
  ontrack: ((e: { streams: MediaStream[] }) => void) | null = null;
  onicecandidate: ((e: { candidate: RTCIceCandidate | null }) => void) | null = null;
  onconnectionstatechange: (() => void) | null = null;
  connectionState: RTCPeerConnectionState = 'new';
  localDescription: RTCSessionDescriptionInit | null = null;

  constructor(config: RTCConfiguration) {
    this.config = config;
    FakeRTCPeerConnection.instances.push(this);
  }
  addTrack(track: MediaStreamTrack) {
    this.tracks.push(track);
  }
  async createOffer(): Promise<RTCSessionDescriptionInit> {
    return { type: 'offer', sdp: 'fake-offer' };
  }
  async createAnswer(): Promise<RTCSessionDescriptionInit> {
    return { type: 'answer', sdp: 'fake-answer' };
  }
  async setLocalDescription(desc: RTCSessionDescriptionInit) {
    this.localDescription = desc;
  }
  async setRemoteDescription() {
    /* noop */
  }
  async addIceCandidate() {
    /* noop */
  }
  restartIce() {
    /* noop */
  }
  close() {
    this.closed = true;
    this.connectionState = 'closed';
  }
}

// Stand-in for HTMLAudioElement that doesn't actually try to play.
class FakeAudio {
  static instances: FakeAudio[] = [];
  srcObject: MediaStream | null = null;
  autoplay = false;
  volume = 1;
  paused = false;
  constructor() {
    FakeAudio.instances.push(this);
  }
  play() {
    return Promise.resolve();
  }
  pause() {
    this.paused = true;
  }
}

const realRTC = globalThis.RTCPeerConnection;
const realRTCSession = globalThis.RTCSessionDescription;
const realRTCIce = globalThis.RTCIceCandidate;
const realAudio = globalThis.Audio;

beforeEach(() => {
  FakeRTCPeerConnection.instances = [];
  FakeAudio.instances = [];
  getEngineOutputStreamMock = vi.fn(() => fakeStream as MediaStream | null);
  (globalThis as unknown as { RTCPeerConnection: unknown }).RTCPeerConnection = FakeRTCPeerConnection;
  (globalThis as unknown as { RTCSessionDescription: unknown }).RTCSessionDescription = class {};
  (globalThis as unknown as { RTCIceCandidate: unknown }).RTCIceCandidate = class {};
  (globalThis as unknown as { Audio: unknown }).Audio = FakeAudio;
});
afterEach(() => {
  (globalThis as unknown as { RTCPeerConnection: unknown }).RTCPeerConnection = realRTC;
  (globalThis as unknown as { RTCSessionDescription: unknown }).RTCSessionDescription = realRTCSession;
  (globalThis as unknown as { RTCIceCandidate: unknown }).RTCIceCandidate = realRTCIce;
  (globalThis as unknown as { Audio: unknown }).Audio = realAudio;
  vi.clearAllMocks();
});

// --- engine output mock ---------------------------------------------------
const fakeStream = {
  getTracks: () => [{ kind: 'audio' } as unknown as MediaStreamTrack],
} as unknown as MediaStream;
let getEngineOutputStreamMock = vi.fn(() => fakeStream as MediaStream | null);
vi.mock('../../player/audio/engineInstance', () => ({
  getEngineOutputStream: () => getEngineOutputStreamMock(),
}));

import { useWebRTCStreaming } from '../useWebRTCStreaming';

function renderHostHook(onSendMessage: (m: object) => void = vi.fn()) {
  return renderHook(() =>
    useWebRTCStreaming({ isHost: true, sessionId: 'sess-1', iceServers: [], onSendMessage }),
  );
}

function renderGuestHook(onSendMessage: (m: object) => void = vi.fn()) {
  return renderHook(() =>
    useWebRTCStreaming({ isHost: false, sessionId: 'sess-1', iceServers: [], onSendMessage }),
  );
}

describe('useWebRTCStreaming — host', () => {
  it('creates a peer connection and sends an offer on webrtc_create_offer', async () => {
    const onSendMessage = vi.fn();
    const { result } = renderHostHook(onSendMessage);
    await act(async () => {
      result.current.handleSignalingMessage({
        type: 'webrtc_create_offer',
        target_user_id: 'guest-1',
        peer_id: 'p-1',
      } as Parameters<typeof result.current.handleSignalingMessage>[0]);
    });
    await waitFor(() => expect(FakeRTCPeerConnection.instances).toHaveLength(1));
    await waitFor(() =>
      expect(onSendMessage).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'webrtc_offer', target_user_id: 'guest-1' }),
      ),
    );
    expect(result.current.peers).toHaveLength(1);
    expect(result.current.isStreaming).toBe(true);
  });

  it('removePeer closes the connection and clears it from state', async () => {
    const { result } = renderHostHook();
    await act(async () => {
      result.current.handleSignalingMessage({
        type: 'webrtc_create_offer',
        target_user_id: 'guest-1',
        peer_id: 'p-1',
      } as Parameters<typeof result.current.handleSignalingMessage>[0]);
    });
    await waitFor(() => expect(result.current.peers).toHaveLength(1));
    const pc = FakeRTCPeerConnection.instances[0];
    act(() => result.current.removePeer('guest-1'));
    expect(pc.closed).toBe(true);
    expect(result.current.peers).toHaveLength(0);
  });

  it('marks hostDisabled when the engine has no output stream', async () => {
    getEngineOutputStreamMock = vi.fn(() => null);
    const { result } = renderHostHook();
    await act(async () => {
      result.current.handleSignalingMessage({
        type: 'webrtc_create_offer',
        target_user_id: 'guest-1',
        peer_id: 'p-1',
      } as Parameters<typeof result.current.handleSignalingMessage>[0]);
    });
    await waitFor(() => expect(result.current.hostDisabled).toBe(true));
    expect(FakeRTCPeerConnection.instances).toHaveLength(0);
  });
});

describe('useWebRTCStreaming — guest renegotiation (L2)', () => {
  it('closes the prior PC and pauses the prior audio when a new offer arrives', async () => {
    const { result } = renderGuestHook();
    const fakeOffer = { type: 'webrtc_offer', sdp: { type: 'offer', sdp: 'a' } };
    await act(async () => {
      result.current.handleSignalingMessage(
        fakeOffer as Parameters<typeof result.current.handleSignalingMessage>[0],
      );
    });
    await waitFor(() => expect(FakeRTCPeerConnection.instances).toHaveLength(1));
    const firstPc = FakeRTCPeerConnection.instances[0];

    // Simulate the host sending a track on the first PC so we get a guest audio element
    act(() => {
      firstPc.ontrack?.({ streams: [fakeStream] });
    });
    await waitFor(() => expect(FakeAudio.instances).toHaveLength(1));
    const firstAudio = FakeAudio.instances[0];

    // Renegotiation: second offer arrives
    await act(async () => {
      result.current.handleSignalingMessage({
        type: 'webrtc_offer',
        sdp: { type: 'offer', sdp: 'b' },
      } as Parameters<typeof result.current.handleSignalingMessage>[0]);
    });
    await waitFor(() => expect(FakeRTCPeerConnection.instances).toHaveLength(2));

    expect(firstPc.closed).toBe(true);
    expect(firstAudio.paused).toBe(true);
    expect(firstAudio.srcObject).toBeNull();
  });
});

describe('useWebRTCStreaming — unmount cleanup', () => {
  it('closes all open peer connections when the hook unmounts', async () => {
    const { result, unmount } = renderHostHook();
    await act(async () => {
      result.current.handleSignalingMessage({
        type: 'webrtc_create_offer',
        target_user_id: 'guest-1',
        peer_id: 'p-1',
      } as Parameters<typeof result.current.handleSignalingMessage>[0]);
    });
    await waitFor(() => expect(FakeRTCPeerConnection.instances).toHaveLength(1));
    const pc = FakeRTCPeerConnection.instances[0];
    unmount();
    expect(pc.closed).toBe(true);
  });
});
