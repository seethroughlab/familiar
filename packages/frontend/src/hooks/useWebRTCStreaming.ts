/**
 * WebRTC audio streaming hook for listening sessions.
 * Host captures audio from the AudioEngine output and streams to guests.
 * Guests receive a single track from the host and play it through an HTMLAudioElement.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getEngineOutputStream } from '../player/audio/engineInstance';
import { createLogger } from '../utils/logger';

const log = createLogger('WebRTC');

interface PeerConnection {
  peerId: string;
  userId: string;
  connection: RTCPeerConnection;
  connected: boolean;
}

interface IceServer {
  urls: string;
  username?: string;
  credential?: string;
}

interface UseWebRTCStreamingOptions {
  isHost: boolean;
  sessionId: string | null;
  iceServers?: IceServer[];
  onSendMessage: (message: object) => void;
}

interface WebRTCMessage {
  type: string;
  sdp?: RTCSessionDescriptionInit;
  candidate?: RTCIceCandidateInit;
  target_user_id?: string;
  from_user_id?: string;
  peer_id?: string;
}

export function useWebRTCStreaming({
  isHost,
  sessionId,
  iceServers = [],
  onSendMessage,
}: UseWebRTCStreamingOptions) {
  const [peers, setPeers] = useState<Map<string, PeerConnection>>(new Map());
  const [isStreaming, setIsStreaming] = useState(false);
  const [guestAudio, setGuestAudio] = useState<HTMLAudioElement | null>(null);
  const [hostDisabled, setHostDisabled] = useState(false);

  const peersRef = useRef<Map<string, PeerConnection>>(new Map());
  const guestConnectionRef = useRef<RTCPeerConnection | null>(null);

  const rtcConfig: RTCConfiguration = useMemo(
    () => ({
      iceServers:
        iceServers.length > 0
          ? iceServers
          : [
              { urls: 'stun:stun.l.google.com:19302' },
              { urls: 'stun:stun1.l.google.com:19302' },
            ],
    }),
    [iceServers],
  );

  const getStream = useCallback((): MediaStream | null => {
    const stream = getEngineOutputStream();
    if (!stream) {
      log.warn('Engine output stream unavailable (host disabled or audio not running)');
      setHostDisabled(true);
      return null;
    }
    setHostDisabled(false);
    return stream;
  }, []);

  const createPeerConnection = useCallback(
    (userId: string, _peerId: string): RTCPeerConnection | null => {
      const stream = getStream();
      if (!stream) return null;

      log.info(`Creating peer connection for guest ${userId}`);
      const pc = new RTCPeerConnection(rtcConfig);

      stream.getTracks().forEach((track) => {
        pc.addTrack(track, stream);
      });

      pc.onicecandidate = (event) => {
        if (event.candidate) {
          onSendMessage({
            type: 'webrtc_ice',
            target_user_id: userId,
            candidate: event.candidate.toJSON(),
          });
        }
      };

      pc.onconnectionstatechange = () => {
        log.info(`Peer ${userId} connection state: ${pc.connectionState}`);
        const peerData = peersRef.current.get(userId);
        if (peerData) {
          peerData.connected = pc.connectionState === 'connected';
          peersRef.current.set(userId, peerData);
          setPeers(new Map(peersRef.current));
        }
        if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
          pc.restartIce();
        }
      };

      return pc;
    },
    [rtcConfig, getStream, onSendMessage],
  );

  const createOfferForGuest = useCallback(
    async (userId: string, peerId: string) => {
      if (!isHost) return;
      const pc = createPeerConnection(userId, peerId);
      if (!pc) return;

      peersRef.current.set(userId, { peerId, userId, connection: pc, connected: false });
      setPeers(new Map(peersRef.current));
      setIsStreaming(true);

      try {
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        onSendMessage({
          type: 'webrtc_offer',
          target_user_id: userId,
          sdp: pc.localDescription,
        });
      } catch (error) {
        log.error('Failed to create offer:', error);
      }
    },
    [isHost, createPeerConnection, onSendMessage],
  );

  const handleAnswer = useCallback(
    async (fromUserId: string, sdp: RTCSessionDescriptionInit) => {
      if (!isHost) return;
      const peer = peersRef.current.get(fromUserId);
      if (!peer) {
        log.warn(`No peer found for user ${fromUserId}`);
        return;
      }
      try {
        await peer.connection.setRemoteDescription(new RTCSessionDescription(sdp));
      } catch (error) {
        log.error('Failed to set remote description:', error);
      }
    },
    [isHost],
  );

  const handleIceCandidate = useCallback(
    async (fromUserId: string, candidate: RTCIceCandidateInit) => {
      let pc: RTCPeerConnection | null = null;
      if (isHost) {
        pc = peersRef.current.get(fromUserId)?.connection ?? null;
      } else {
        pc = guestConnectionRef.current;
      }
      if (!pc) {
        log.warn('No peer connection for ICE candidate');
        return;
      }
      try {
        await pc.addIceCandidate(new RTCIceCandidate(candidate));
      } catch (error) {
        log.error('Failed to add ICE candidate:', error);
      }
    },
    [isHost],
  );

  const handleOffer = useCallback(
    async (sdp: RTCSessionDescriptionInit) => {
      if (isHost) return;

      const pc = new RTCPeerConnection(rtcConfig);
      guestConnectionRef.current = pc;

      pc.ontrack = (event) => {
        log.info('Received audio track from host');
        const audio = new Audio();
        audio.srcObject = event.streams[0];
        audio.autoplay = true;
        audio.volume = 1;
        audio.play().catch((error) => {
          log.error('Failed to play audio:', error);
        });
        setGuestAudio(audio);
      };

      pc.onicecandidate = (event) => {
        if (event.candidate) {
          onSendMessage({ type: 'webrtc_ice', candidate: event.candidate.toJSON() });
        }
      };

      pc.onconnectionstatechange = () => {
        if (pc.connectionState === 'connected') {
          onSendMessage({ type: 'webrtc_connected', connected: true });
        } else if (pc.connectionState === 'disconnected' || pc.connectionState === 'failed') {
          onSendMessage({ type: 'webrtc_connected', connected: false });
        }
      };

      try {
        await pc.setRemoteDescription(new RTCSessionDescription(sdp));
        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        onSendMessage({ type: 'webrtc_answer', sdp: pc.localDescription });
      } catch (error) {
        log.error('Failed to handle offer:', error);
      }
    },
    [isHost, rtcConfig, onSendMessage],
  );

  const requestStream = useCallback(() => {
    if (isHost) return;
    onSendMessage({ type: 'webrtc_request' });
  }, [isHost, onSendMessage]);

  const handleSignalingMessage = useCallback(
    (message: WebRTCMessage) => {
      switch (message.type) {
        case 'webrtc_create_offer':
          if (isHost && message.target_user_id && message.peer_id) {
            void createOfferForGuest(message.target_user_id, message.peer_id);
          }
          break;
        case 'webrtc_offer':
          if (!isHost && message.sdp) {
            void handleOffer(message.sdp);
          }
          break;
        case 'webrtc_answer':
          if (isHost && message.from_user_id && message.sdp) {
            void handleAnswer(message.from_user_id, message.sdp);
          }
          break;
        case 'webrtc_ice':
          if (message.from_user_id && message.candidate) {
            void handleIceCandidate(message.from_user_id, message.candidate);
          }
          break;
        case 'guest_joined':
          if (isHost && message.target_user_id && message.peer_id) {
            const targetUserId = message.target_user_id;
            const peerId = message.peer_id;
            setTimeout(() => {
              void createOfferForGuest(targetUserId, peerId);
            }, 500);
          }
          break;
      }
    },
    [isHost, createOfferForGuest, handleOffer, handleAnswer, handleIceCandidate],
  );

  const removePeer = useCallback((userId: string) => {
    const peer = peersRef.current.get(userId);
    if (peer) {
      peer.connection.close();
      peersRef.current.delete(userId);
      setPeers(new Map(peersRef.current));
    }
    if (peersRef.current.size === 0) {
      setIsStreaming(false);
    }
  }, []);

  useEffect(() => {
    const currentPeers = peersRef.current;
    return () => {
      currentPeers.forEach((peer) => peer.connection.close());
      currentPeers.clear();
      setPeers(new Map());
      if (guestConnectionRef.current) {
        guestConnectionRef.current.close();
        guestConnectionRef.current = null;
      }
      if (guestAudio) {
        guestAudio.pause();
        guestAudio.srcObject = null;
      }
      setIsStreaming(false);
    };
  }, [sessionId, guestAudio]);

  const setGuestVolume = useCallback(
    (volume: number) => {
      if (guestAudio) {
        guestAudio.volume = Math.max(0, Math.min(1, volume));
      }
    },
    [guestAudio],
  );

  return {
    isStreaming,
    peers: Array.from(peers.values()),
    connectedGuestCount: Array.from(peers.values()).filter((p) => p.connected).length,
    handleSignalingMessage,
    requestStream,
    removePeer,
    setGuestVolume,
    hasGuestAudio: !!guestAudio,
    hostDisabled,
  };
}
