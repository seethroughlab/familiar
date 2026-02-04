import { useState, useEffect, useCallback, useRef } from 'react';
import { usePlayerStore } from '../stores/playerStore';
import { useAudioEngine } from './useAudioEngine';
import { useWebRTCStreaming } from './useWebRTCStreaming';

export interface SessionParticipant {
  user_id: string;
  username: string;
  role: 'host' | 'listener' | 'guest';
  joined_at: string;
  webrtc_connected?: boolean;
}

export interface IceServer {
  urls: string;
  username?: string;
  credential?: string;
}

export interface SessionInfo {
  id: string;
  code: string;
  name: string;
  host_id: string;
  participant_count: number;
  participants: SessionParticipant[];
  webrtc_enabled: boolean;
  playback_state: {
    track_id: string | null;
    is_playing: boolean;
    position_ms: number;
  };
}

export interface ChatMessage {
  user_id: string;
  username: string;
  message: string;
  timestamp: Date;
}

interface UseListeningSessionOptions {
  userId: string;
  username: string;
}

export function useListeningSession({ userId, username }: UseListeningSessionOptions) {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [isConnecting, setIsConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [iceServers, setIceServers] = useState<IceServer[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef<number>(0);
  const maxReconnectAttempts = 10;

  const { setIsPlaying, currentTrack, isPlaying, currentTime } = usePlayerStore();
  const audioEngine = useAudioEngine();

  // Send message helper (defined early for WebRTC hook)
  const send = useCallback((message: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    }
  }, []);

  // WebRTC streaming
  const isHost = session?.host_id === userId;
  const webrtc = useWebRTCStreaming({
    isHost,
    sessionId: session?.id || null,
    iceServers,
    onSendMessage: send,
  });

  // Get WebSocket URL
  const getWsUrl = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.hostname;
    const port = window.location.port === '3000' ? '8000' : window.location.port;
    return `${protocol}//${host}:${port}/api/v1/sessions/ws`;
  }, []);

  // Ref to store WebRTC handler (to avoid circular dependency)
  const webrtcHandlerRef = useRef(webrtc.handleSignalingMessage);
  webrtcHandlerRef.current = webrtc.handleSignalingMessage;

  // Handle incoming messages
  const handleMessage = useCallback((event: MessageEvent) => {
    const data = JSON.parse(event.data);

    switch (data.type) {
      case 'session_created':
        setSession(data.session);
        setError(null);
        break;

      case 'session_joined':
        setSession(data.session);
        setError(null);
        // Store ICE servers if provided
        if (data.ice_servers) {
          setIceServers(data.ice_servers);
        }
        break;

      case 'user_joined':
        setSession(prev => {
          if (!prev) return prev;
          return {
            ...prev,
            participant_count: data.participant_count,
            participants: [
              ...prev.participants,
              data.user,
            ],
          };
        });
        break;

      case 'user_left':
        setSession(prev => {
          if (!prev) return prev;
          return {
            ...prev,
            participant_count: data.participant_count,
            participants: prev.participants.filter(p => p.user_id !== data.user_id),
          };
        });
        // Clean up WebRTC connection for this user
        webrtc.removePeer(data.user_id);
        break;

      case 'playback_update':
        // Sync playback from host
        if (data.track_id && data.track_id !== currentTrack?.id) {
          // Track changed - need to load it
          // This will be handled by the player store
        }
        if (data.is_playing !== undefined) {
          setIsPlaying(data.is_playing);
        }
        if (data.position_ms !== undefined) {
          audioEngine.seek(data.position_ms / 1000);
        }
        break;

      case 'sync_response':
        // Initial sync when joining
        if (data.is_playing !== undefined) {
          setIsPlaying(data.is_playing);
        }
        if (data.position_ms !== undefined) {
          audioEngine.seek(data.position_ms / 1000);
        }
        break;

      case 'chat':
        setChatMessages(prev => [
          ...prev,
          {
            user_id: data.user_id,
            username: data.username,
            message: data.message,
            timestamp: new Date(),
          },
        ]);
        break;

      case 'left':
        setSession(null);
        setChatMessages([]);
        break;

      case 'error':
        setError(data.message);
        break;

      // WebRTC signaling messages
      case 'guest_joined':
      case 'webrtc_create_offer':
      case 'webrtc_offer':
      case 'webrtc_answer':
      case 'webrtc_ice':
      case 'webrtc_state_changed':
        webrtcHandlerRef.current(data);
        break;
    }
  }, [currentTrack?.id, setIsPlaying, audioEngine, webrtc]);

  // Connect WebSocket
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    setIsConnecting(true);
    const ws = new WebSocket(getWsUrl());

    ws.onopen = () => {
      setIsConnecting(false);
      setError(null);
      // Reset reconnect attempts on successful connection
      reconnectAttemptsRef.current = 0;
    };

    ws.onmessage = handleMessage;

    ws.onerror = () => {
      setError('Connection error');
      setIsConnecting(false);
    };

    ws.onclose = () => {
      setIsConnecting(false);
      wsRef.current = null;

      // Auto-reconnect if in session with exponential backoff
      if (session) {
        reconnectAttemptsRef.current += 1;

        if (reconnectAttemptsRef.current > maxReconnectAttempts) {
          setError('Connection lost. Please try rejoining the session.');
          return;
        }

        // Exponential backoff: 3s, 6s, 12s, 24s, 48s, max 60s
        const delay = Math.min(3000 * Math.pow(2, reconnectAttemptsRef.current - 1), 60000);
        console.log(`[Session] Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current}/${maxReconnectAttempts})`);

        reconnectTimeoutRef.current = window.setTimeout(() => {
          connect();
        }, delay);
      }
    };

    wsRef.current = ws;
  }, [getWsUrl, handleMessage, session]);

  // Create a new session
  const createSession = useCallback((name: string = 'Listening Session') => {
    connect();

    // Wait for connection then send create message
    const checkAndSend = () => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        send({
          type: 'create',
          name,
          user_id: userId,
          username,
        });
      } else {
        setTimeout(checkAndSend, 100);
      }
    };
    checkAndSend();
  }, [connect, send, userId, username]);

  // Join an existing session
  const joinSession = useCallback((code: string) => {
    connect();

    const checkAndSend = () => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        send({
          type: 'join',
          code,
          user_id: userId,
          username,
        });
      } else {
        setTimeout(checkAndSend, 100);
      }
    };
    checkAndSend();
  }, [connect, send, userId, username]);

  // Leave current session
  const leaveSession = useCallback(() => {
    send({ type: 'leave' });
    wsRef.current?.close();
    wsRef.current = null;
    setSession(null);
    setChatMessages([]);
  }, [send]);

  // Send playback update (host only)
  const sendPlaybackUpdate = useCallback((
    trackId: string | null,
    isPlaying: boolean,
    positionMs: number,
  ) => {
    if (!session || session.host_id !== userId) return;

    send({
      type: 'playback',
      track_id: trackId,
      is_playing: isPlaying,
      position_ms: positionMs,
    });
  }, [session, userId, send]);

  // Send chat message
  const sendChatMessage = useCallback((message: string) => {
    send({
      type: 'chat',
      message,
    });
  }, [send]);

  // Request sync from host
  const requestSync = useCallback(() => {
    send({ type: 'sync_request' });
  }, [send]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      wsRef.current?.close();
    };
  }, []);

  // Auto-send playback updates when host plays/pauses/seeks
  useEffect(() => {
    if (!session || session.host_id !== userId) return;

    sendPlaybackUpdate(
      currentTrack?.id || null,
      isPlaying,
      Math.floor(currentTime * 1000),
    );
  }, [session, userId, currentTrack?.id, isPlaying, currentTime, sendPlaybackUpdate]);

  return {
    session,
    isConnecting,
    error,
    chatMessages,
    isHost: session?.host_id === userId,
    createSession,
    joinSession,
    leaveSession,
    sendPlaybackUpdate,
    sendChatMessage,
    requestSync,
    // WebRTC streaming
    webrtc: {
      isStreaming: webrtc.isStreaming,
      connectedGuestCount: webrtc.connectedGuestCount,
      peers: webrtc.peers,
      requestStream: webrtc.requestStream,
      hasGuestAudio: webrtc.hasGuestAudio,
      setGuestVolume: webrtc.setGuestVolume,
    },
  };
}
