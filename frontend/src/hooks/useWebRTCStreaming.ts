/**
 * WebRTC audio streaming hook for listening sessions.
 * Host captures audio and streams to guests via WebRTC.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useAudioEngine } from './useAudioEngine';
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
  const audioEngine = useAudioEngine();
  const [peers, setPeers] = useState<Map<string, PeerConnection>>(new Map());
  const [isStreaming, setIsStreaming] = useState(false);
  const [guestAudio, setGuestAudio] = useState<HTMLAudioElement | null>(null);

  // Refs for stable access in callbacks
  const peersRef = useRef<Map<string, PeerConnection>>(new Map());
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const guestConnectionRef = useRef<RTCPeerConnection | null>(null);

  // Create RTCPeerConnection configuration
  const rtcConfig: RTCConfiguration = useMemo(() => ({
    iceServers: iceServers.length > 0 ? iceServers : [
      { urls: 'stun:stun.l.google.com:19302' },
      { urls: 'stun:stun1.l.google.com:19302' },
    ],
  }), [iceServers]);

  // Get media stream from audio engine (host only)
  const getAudioStream = useCallback((): MediaStream | null => {
    if (mediaStreamRef.current) {
      return mediaStreamRef.current;
    }

    const audioContext = audioEngine.getContext();
    if (!audioContext) {
      log.error('No audio context available');
      return null;
    }

    // Create a media stream destination from the audio context
    const destination = audioContext.createMediaStreamDestination();

    // Get the audio engine's output node and connect it to the destination
    const outputNode = audioEngine.getOutputNode();
    if (outputNode) {
      outputNode.connect(destination);
    } else {
      log.warn('No output node available from audio engine');
      return null;
    }

    mediaStreamRef.current = destination.stream;
    return destination.stream;
  }, [audioEngine]);

  // Create a peer connection for a guest (host only)
  const createPeerConnection = useCallback((userId: string, peerId: string): RTCPeerConnection => {
    log.info(`Creating peer connection for guest ${userId} (${peerId})`);

    const pc = new RTCPeerConnection(rtcConfig);

    // Add audio track
    const stream = getAudioStream();
    if (stream) {
      stream.getTracks().forEach(track => {
        pc.addTrack(track, stream);
      });
    }

    // Handle ICE candidates
    pc.onicecandidate = (event) => {
      if (event.candidate) {
        onSendMessage({
          type: 'webrtc_ice',
          target_user_id: userId,
          candidate: event.candidate.toJSON(),
        });
      }
    };

    // Handle connection state changes
    pc.onconnectionstatechange = () => {
      log.info(`Peer ${userId} connection state: ${pc.connectionState}`);

      const peerData = peersRef.current.get(userId);
      if (peerData) {
        peerData.connected = pc.connectionState === 'connected';
        peersRef.current.set(userId, peerData);
        setPeers(new Map(peersRef.current));
      }

      if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
        // Try to reconnect
        pc.restartIce();
      }
    };

    return pc;
  }, [rtcConfig, getAudioStream, onSendMessage]);

  // Create offer for a guest (host only)
  const createOfferForGuest = useCallback(async (userId: string, peerId: string) => {
    if (!isHost) return;

    log.info(`Creating WebRTC offer for guest ${userId}`);

    const pc = createPeerConnection(userId, peerId);
    peersRef.current.set(userId, {
      peerId,
      userId,
      connection: pc,
      connected: false,
    });
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
  }, [isHost, createPeerConnection, onSendMessage]);

  // Handle incoming WebRTC answer (host only)
  const handleAnswer = useCallback(async (fromUserId: string, sdp: RTCSessionDescriptionInit) => {
    if (!isHost) return;

    const peer = peersRef.current.get(fromUserId);
    if (!peer) {
      log.warn(`No peer found for user ${fromUserId}`);
      return;
    }

    log.info(`Received WebRTC answer from ${fromUserId}`);

    try {
      await peer.connection.setRemoteDescription(new RTCSessionDescription(sdp));
    } catch (error) {
      log.error('Failed to set remote description:', error);
    }
  }, [isHost]);

  // Handle incoming ICE candidate (both host and guest)
  const handleIceCandidate = useCallback(async (fromUserId: string, candidate: RTCIceCandidateInit) => {
    let pc: RTCPeerConnection | null = null;

    if (isHost) {
      const peer = peersRef.current.get(fromUserId);
      pc = peer?.connection || null;
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
  }, [isHost]);

  // Handle incoming WebRTC offer (guest only)
  const handleOffer = useCallback(async (sdp: RTCSessionDescriptionInit) => {
    if (isHost) return;

    log.info('Received WebRTC offer from host');

    // Create peer connection for receiving
    const pc = new RTCPeerConnection(rtcConfig);
    guestConnectionRef.current = pc;

    // Handle incoming audio track
    pc.ontrack = (event) => {
      log.info('Received audio track from host');

      // Create audio element to play the stream
      const audio = new Audio();
      audio.srcObject = event.streams[0];
      audio.autoplay = true;
      audio.volume = 1;

      // Handle audio playback
      audio.play().catch(error => {
        log.error('Failed to play audio:', error);
        // May need user interaction to play
      });

      setGuestAudio(audio);
    };

    // Handle ICE candidates
    pc.onicecandidate = (event) => {
      if (event.candidate) {
        onSendMessage({
          type: 'webrtc_ice',
          candidate: event.candidate.toJSON(),
        });
      }
    };

    // Handle connection state changes
    pc.onconnectionstatechange = () => {
      log.info(`Guest connection state: ${pc.connectionState}`);

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

      onSendMessage({
        type: 'webrtc_answer',
        sdp: pc.localDescription,
      });
    } catch (error) {
      log.error('Failed to handle offer:', error);
    }
  }, [isHost, rtcConfig, onSendMessage]);

  // Request WebRTC stream from host (guest only)
  const requestStream = useCallback(() => {
    if (isHost) return;

    log.info('Requesting WebRTC stream from host');
    onSendMessage({ type: 'webrtc_request' });
  }, [isHost, onSendMessage]);

  // Handle WebRTC signaling messages
  const handleSignalingMessage = useCallback((message: WebRTCMessage) => {
    switch (message.type) {
      case 'webrtc_create_offer':
        // Host should create offer for this guest
        if (isHost && message.target_user_id && message.peer_id) {
          createOfferForGuest(message.target_user_id, message.peer_id);
        }
        break;

      case 'webrtc_offer':
        // Guest received offer from host
        if (!isHost && message.sdp) {
          handleOffer(message.sdp);
        }
        break;

      case 'webrtc_answer':
        // Host received answer from guest
        if (isHost && message.from_user_id && message.sdp) {
          handleAnswer(message.from_user_id, message.sdp);
        }
        break;

      case 'webrtc_ice':
        // ICE candidate received
        if (message.from_user_id && message.candidate) {
          handleIceCandidate(message.from_user_id, message.candidate);
        }
        break;

      case 'guest_joined':
        // New guest joined, create offer (host only)
        if (isHost && message.target_user_id && message.peer_id) {
          // Wait a moment for the guest to set up
          setTimeout(() => {
            createOfferForGuest(message.target_user_id!, message.peer_id!);
          }, 500);
        }
        break;
    }
  }, [isHost, createOfferForGuest, handleOffer, handleAnswer, handleIceCandidate]);

  // Remove a peer connection (host only)
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

  // Cleanup on unmount or session end
  useEffect(() => {
    // Capture current ref values for cleanup
    const currentPeers = peersRef.current;
    return () => {
      // Close all peer connections
      currentPeers.forEach(peer => {
        peer.connection.close();
      });
      currentPeers.clear();
      setPeers(new Map());

      // Close guest connection
      if (guestConnectionRef.current) {
        guestConnectionRef.current.close();
        guestConnectionRef.current = null;
      }

      // Stop guest audio
      if (guestAudio) {
        guestAudio.pause();
        guestAudio.srcObject = null;
      }

      // Disconnect media stream
      if (mediaStreamRef.current) {
        mediaStreamRef.current.getTracks().forEach(track => track.stop());
        mediaStreamRef.current = null;
      }

      setIsStreaming(false);
    };
  }, [sessionId, guestAudio]);

  // Set volume for guest audio
  const setGuestVolume = useCallback((volume: number) => {
    if (guestAudio) {
      guestAudio.volume = Math.max(0, Math.min(1, volume));
    }
  }, [guestAudio]);

  return {
    isStreaming,
    peers: Array.from(peers.values()),
    connectedGuestCount: Array.from(peers.values()).filter(p => p.connected).length,
    handleSignalingMessage,
    requestStream,
    removePeer,
    setGuestVolume,
    hasGuestAudio: !!guestAudio,
  };
}
