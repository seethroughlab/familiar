import { useState, useEffect, useCallback, useRef } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { usePlayerStore } from '../stores/playerStore';
import { useAudioControls } from './useAudioControls';
import { useWebRTCStreaming } from './useWebRTCStreaming';
import { getProfile, getSelectedProfileId } from '../services/profileService';
import {
  createGeneratedFamiliar,
  loadStoredFamiliar,
  saveStoredFamiliar,
  sanitizeFamiliar,
  type FamiliarConfig,
  type SessionReaction,
  type SessionReactionKind,
} from '../services/listeningSessionFamiliars';
import { createLogger } from '../utils/logger';
import { showError } from '../stores/toastStore';

const log = createLogger('ListeningSession');

const PLAYBACK_BROADCAST_INTERVAL_MS = 1000;
const MAX_RECONNECT_ATTEMPTS = 10;
const PENDING_SEND_TIMEOUT_MS = 5000;
const PENDING_SEND_TICK_MS = 100;
const HANDSHAKE_TIMEOUT_MS = 12000;
const REACTION_RETENTION_MS = 4000;

/**
 * Public WebRTC signaling relay URL (familiar-sessions service).
 * Override at build time via VITE_SESSIONS_RELAY_URL.
 * Falls back to the same origin as the Familiar app — useful for local dev when
 * running familiar-sessions on the same host.
 */
const RELAY_URL: string =
  (import.meta.env?.VITE_SESSIONS_RELAY_URL as string | undefined) ?? '';

export interface SessionParticipant {
  user_id: string;
  username: string;
  role: 'host' | 'listener' | 'guest';
  familiar: FamiliarConfig;
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
  has_password: boolean;
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
  /** Display name shown to others. Falls back to the current profile's name. */
  username?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function normalizeParticipant(value: SessionParticipant): SessionParticipant {
  return {
    ...value,
    familiar: sanitizeFamiliar(value.familiar, value.username),
  };
}

function normalizeSession(value: SessionInfo): SessionInfo {
  return {
    ...value,
    participants: Array.isArray(value.participants)
      ? value.participants.map((participant) => normalizeParticipant(participant))
      : [],
  };
}

function buildWsUrl(): string {
  let base: string;
  if (RELAY_URL) {
    base = RELAY_URL.replace(/^http/, 'ws').replace(/\/$/, '');
  } else {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    base = `${proto}//${window.location.host}`;
  }
  return `${base}/api/v1/sessions/ws`;
}

/** Public guest URL the host can share. */
export function buildShareLink(code: string): string {
  const safe = encodeURIComponent(code);
  if (RELAY_URL) {
    return `${RELAY_URL.replace(/\/$/, '')}/listen/${safe}`;
  }
  return `${window.location.origin}/listen/${safe}`;
}

export function useListeningSession({ username }: UseListeningSessionOptions = {}) {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [isConnecting, setIsConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [reactions, setReactions] = useState<SessionReaction[]>([]);
  const [iceServers, setIceServers] = useState<IceServer[]>([]);
  const [myUserId, setMyUserId] = useState<string | null>(null);
  const [resolvedUsername, setResolvedUsername] = useState<string>(username ?? 'Anonymous');
  const [profileId, setProfileId] = useState<string | null>(null);
  const [myFamiliar, setMyFamiliar] = useState<FamiliarConfig>(() =>
    createGeneratedFamiliar(username ?? 'Anonymous'),
  );

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef<number>(0);
  const handshakeTimeoutRef = useRef<number | null>(null);
  const pendingSendTimeoutRef = useRef<number | null>(null);
  const lastBroadcastRef = useRef<number>(0);

  const { currentTrack, isPlaying, currentTime, setIsPlaying } = usePlayerStore(
    useShallow((s) => ({
      currentTrack: s.currentTrack,
      isPlaying: s.isPlaying,
      currentTime: s.currentTime,
      setIsPlaying: s.setIsPlaying,
    })),
  );
  const audioEngine = useAudioControls();

  // Resolve a display name from the local Familiar profile so listeners see something useful.
  // The relay doesn't care about profile id — only the username string.
  useEffect(() => {
    if (username) {
      setResolvedUsername(username);
      setMyFamiliar((prev) => sanitizeFamiliar(prev, username));
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const id = await getSelectedProfileId();
        if (cancelled) return;
        setProfileId(id ?? null);
        if (!id) return;
        const profile = await getProfile(id, { allowCache: true });
        if (cancelled || !profile) return;
        const nextName = profile.name || 'Anonymous';
        const storedFamiliar = loadStoredFamiliar(id);
        setResolvedUsername(nextName);
        setMyFamiliar(sanitizeFamiliar(storedFamiliar, nextName, profile.color));
      } catch {
        // fall back to default name
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [username]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      setReactions((prev) =>
        prev.filter((reaction) => Date.now() - reaction.timestamp.getTime() < REACTION_RETENTION_MS),
      );
    }, 1000);
    return () => {
      clearInterval(interval);
    };
  }, []);

  const send = useCallback((message: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    }
  }, []);

  const isHost = !!session && myUserId !== null && session.host_id === myUserId;
  const webrtc = useWebRTCStreaming({
    isHost,
    sessionId: session?.id ?? null,
    iceServers,
    onSendMessage: send,
  });

  // Indirect refs so handleMessage isn't recreated every render (which would
  // cascade into a fresh `connect` callback and a fresh ws.onmessage closure).
  const webrtcRef = useRef(webrtc);
  webrtcRef.current = webrtc;
  const audioEngineRef = useRef(audioEngine);
  audioEngineRef.current = audioEngine;

  const handleMessage = useCallback(
    (event: MessageEvent) => {
      let data: unknown;
      try {
        data = JSON.parse(typeof event.data === 'string' ? event.data : '');
      } catch (err) {
        log.warn('Dropping malformed WS message', err);
        return;
      }
      if (!isRecord(data) || typeof data.type !== 'string') {
        log.warn('Dropping WS message with no type');
        return;
      }
      switch (data.type) {
        case 'session_created':
        case 'session_joined': {
          if (!isRecord(data.session)) {
            log.warn(`Dropping ${data.type} with missing session`);
            return;
          }
          setSession(normalizeSession(data.session as unknown as SessionInfo));
          if (typeof data.your_user_id === 'string') setMyUserId(data.your_user_id);
          if (Array.isArray(data.ice_servers)) setIceServers(data.ice_servers as IceServer[]);
          setError(null);
          break;
        }
        case 'user_joined': {
          if (!isRecord(data.user) || typeof data.participant_count !== 'number') return;
          const newUser = normalizeParticipant(data.user as unknown as SessionParticipant);
          const count = data.participant_count;
          setSession((prev) =>
            prev
              ? {
                  ...prev,
                  participant_count: count,
                  participants: [...prev.participants, newUser],
                }
              : prev,
          );
          break;
        }
        case 'user_updated': {
          if (!isRecord(data.user) || typeof data.user.user_id !== 'string') return;
          const updatedUser = normalizeParticipant(data.user as unknown as SessionParticipant);
          setSession((prev) =>
            prev
              ? {
                  ...prev,
                  participants: prev.participants.map((participant) =>
                    participant.user_id === updatedUser.user_id ? updatedUser : participant,
                  ),
                }
              : prev,
          );
          break;
        }
        case 'user_left': {
          if (typeof data.user_id !== 'string') return;
          const leftUserId = data.user_id;
          const count = typeof data.participant_count === 'number' ? data.participant_count : null;
          setSession((prev) =>
            prev
              ? {
                  ...prev,
                  participant_count: count ?? Math.max(0, prev.participant_count - 1),
                  participants: prev.participants.filter((p) => p.user_id !== leftUserId),
                }
              : prev,
          );
          webrtcRef.current.removePeer(leftUserId);
          break;
        }
        case 'playback_update':
        case 'sync_response': {
          if (typeof data.is_playing === 'boolean') setIsPlaying(data.is_playing);
          if (typeof data.position_ms === 'number') {
            audioEngineRef.current.seek(data.position_ms / 1000);
          }
          break;
        }
        case 'chat': {
          if (
            typeof data.user_id !== 'string' ||
            typeof data.username !== 'string' ||
            typeof data.message !== 'string'
          ) {
            return;
          }
          const msg: ChatMessage = {
            user_id: data.user_id,
            username: data.username,
            message: data.message,
            timestamp: new Date(),
          };
          setChatMessages((prev) => [...prev, msg]);
          break;
        }
        case 'left':
          setSession(null);
          setChatMessages([]);
          setReactions([]);
          break;
        case 'user_kicked':
          setError('You were removed from the session');
          showError('Removed from session', { description: 'The host removed you.' });
          setSession(null);
          setReactions([]);
          break;
        case 'error': {
          const message = typeof data.message === 'string' ? data.message : 'Session error';
          setError(message);
          showError('Session error', { description: message });
          break;
        }
        case 'user_reaction': {
          if (
            typeof data.user_id !== 'string' ||
            typeof data.kind !== 'string' ||
            !['cheer', 'pulse', 'wave', 'spark'].includes(data.kind)
          ) {
            return;
          }
          const reactionUserId = data.user_id;
          setReactions((prev) => [
            ...prev,
            {
              user_id: reactionUserId,
              username: typeof data.username === 'string' ? data.username : undefined,
              kind: data.kind as SessionReactionKind,
              timestamp: new Date(),
            },
          ].slice(-24));
          break;
        }
        case 'guest_joined':
        case 'webrtc_create_offer':
        case 'webrtc_offer':
        case 'webrtc_answer':
        case 'webrtc_ice':
        case 'webrtc_state_changed':
          webrtcRef.current.handleSignalingMessage(
            data as unknown as Parameters<typeof webrtc.handleSignalingMessage>[0],
          );
          break;
      }
    },
    // setIsPlaying is stable (zustand setter); webrtc/audioEngine accessed via refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [setIsPlaying],
  );

  const clearHandshakeTimeout = useCallback(() => {
    if (handshakeTimeoutRef.current !== null) {
      clearTimeout(handshakeTimeoutRef.current);
      handshakeTimeoutRef.current = null;
    }
  }, []);

  const clearPendingSend = useCallback(() => {
    if (pendingSendTimeoutRef.current !== null) {
      clearTimeout(pendingSendTimeoutRef.current);
      pendingSendTimeoutRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    const existing = wsRef.current;
    if (existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)) {
      return;
    }
    setIsConnecting(true);

    const ws = new WebSocket(buildWsUrl());

    handshakeTimeoutRef.current = window.setTimeout(() => {
      if (ws.readyState !== WebSocket.OPEN) {
        log.warn('WS handshake timed out');
        ws.close();
        setIsConnecting(false);
        setError('Could not reach the session relay.');
        showError('Could not reach the session relay', {
          description: 'Check your connection and try again.',
        });
      }
    }, HANDSHAKE_TIMEOUT_MS);

    ws.onopen = () => {
      clearHandshakeTimeout();
      setIsConnecting(false);
      setError(null);
      reconnectAttemptsRef.current = 0;
    };

    ws.onmessage = handleMessage;

    ws.onerror = () => {
      setError('Connection error');
      showError('Session connection error');
      setIsConnecting(false);
    };

    ws.onclose = () => {
      clearHandshakeTimeout();
      setIsConnecting(false);
      wsRef.current = null;

      if (session) {
        reconnectAttemptsRef.current += 1;
        if (reconnectAttemptsRef.current > MAX_RECONNECT_ATTEMPTS) {
          setError('Connection lost. Please try rejoining the session.');
          showError('Lost connection to the session', {
            description: 'Please rejoin to continue.',
          });
          return;
        }
        const delay = Math.min(3000 * 2 ** (reconnectAttemptsRef.current - 1), 60000);
        log.info(
          `Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current}/${MAX_RECONNECT_ATTEMPTS})`,
        );
        reconnectTimeoutRef.current = window.setTimeout(connect, delay);
      }
    };

    wsRef.current = ws;
  }, [handleMessage, session, clearHandshakeTimeout]);

  const sendOnceConnected = useCallback(
    (message: object) => {
      clearPendingSend();
      const startedAt = Date.now();
      const tick = () => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          pendingSendTimeoutRef.current = null;
          send(message);
          return;
        }
        if (Date.now() - startedAt >= PENDING_SEND_TIMEOUT_MS) {
          pendingSendTimeoutRef.current = null;
          log.warn('Timed out waiting for WS to open before sending', message);
          setError('Could not reach the session relay.');
          showError('Could not reach the session relay', {
            description: 'Check your connection and try again.',
          });
          return;
        }
        pendingSendTimeoutRef.current = window.setTimeout(tick, PENDING_SEND_TICK_MS);
      };
      tick();
    },
    [send, clearPendingSend],
  );

  const createSession = useCallback(
    (name: string = 'Listening Session', password?: string) => {
      connect();
      sendOnceConnected({ type: 'create', name, username: resolvedUsername, password, familiar: myFamiliar });
    },
    [connect, sendOnceConnected, resolvedUsername, myFamiliar],
  );

  const joinSession = useCallback(
    (code: string, password?: string) => {
      connect();
      sendOnceConnected({ type: 'join', code, username: resolvedUsername, password, familiar: myFamiliar });
    },
    [connect, sendOnceConnected, resolvedUsername, myFamiliar],
  );

  const leaveSession = useCallback(() => {
    clearPendingSend();
    if (reconnectTimeoutRef.current !== null) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    send({ type: 'leave' });
    wsRef.current?.close();
    wsRef.current = null;
    setSession(null);
    setChatMessages([]);
    setReactions([]);
  }, [send, clearPendingSend]);

  const kick = useCallback(
    (targetUserId: string) => {
      send({ type: 'kick', target_user_id: targetUserId });
    },
    [send],
  );

  const sendPlaybackUpdate = useCallback(
    (
      trackId: string | null,
      playing: boolean,
      positionMs: number,
      meta?: { title?: string; artist?: string; album?: string },
    ) => {
      if (!session || !isHost) return;
      const payload: Record<string, unknown> = {
        type: 'playback',
        track_id: trackId,
        is_playing: playing,
        position_ms: positionMs,
      };
      if (meta && (meta.title || meta.artist || meta.album)) {
        payload.track_meta = {
          ...(meta.title ? { title: meta.title } : {}),
          ...(meta.artist ? { artist: meta.artist } : {}),
          ...(meta.album ? { album: meta.album } : {}),
        };
      }
      send(payload);
    },
    [session, isHost, send],
  );

  const sendChatMessage = useCallback(
    (message: string) => {
      send({ type: 'chat', message });
    },
    [send],
  );

  const sendReaction = useCallback(
    (kind: SessionReactionKind) => {
      send({ type: 'reaction', kind });
    },
    [send],
  );

  const updateMySessionFamiliar = useCallback(
    (next: FamiliarConfig) => {
      const normalized = sanitizeFamiliar(next, resolvedUsername);
      setMyFamiliar(normalized);
      saveStoredFamiliar(profileId, normalized);
      if (myUserId) {
        setSession((prev) =>
          prev
            ? {
                ...prev,
                participants: prev.participants.map((participant) =>
                  participant.user_id === myUserId
                    ? { ...participant, familiar: normalized }
                    : participant,
                ),
              }
            : prev,
        );
      }
      if (session) {
        send({ type: 'update_familiar', familiar: normalized });
      }
    },
    [myUserId, profileId, resolvedUsername, send, session],
  );

  const requestSync = useCallback(() => {
    send({ type: 'sync_request' });
  }, [send]);

  useEffect(() => {
    return () => {
      clearHandshakeTimeout();
      clearPendingSend();
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      // Best-effort polite exit so the relay updates participant counts immediately;
      // close() alone leaves the relay to time us out.
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        try {
          wsRef.current.send(JSON.stringify({ type: 'leave' }));
        } catch {
          // socket might be in the middle of closing — ignore
        }
      }
      wsRef.current?.close();
    };
  }, [clearHandshakeTimeout, clearPendingSend]);

  // Throttled auto-broadcast (1 Hz). Backend additionally heartbeats at 5s.
  useEffect(() => {
    if (!session || !isHost) return;
    const now = Date.now();
    if (now - lastBroadcastRef.current < PLAYBACK_BROADCAST_INTERVAL_MS) return;
    lastBroadcastRef.current = now;
    const positionMs = Math.floor(currentTime * 1000);
    sendPlaybackUpdate(
      currentTrack?.id ?? null,
      isPlaying,
      positionMs,
      currentTrack
        ? {
            title: currentTrack.title ?? undefined,
            artist: currentTrack.artist ?? undefined,
            album: currentTrack.album ?? undefined,
          }
        : undefined,
    );
  }, [session, isHost, currentTrack, isPlaying, currentTime, sendPlaybackUpdate]);

  return {
    session,
    isConnecting,
    error,
    chatMessages,
    reactions,
    iceServers,
    isHost,
    myUserId,
    myFamiliar,
    createSession,
    joinSession,
    leaveSession,
    kick,
    sendPlaybackUpdate,
    sendChatMessage,
    sendReaction,
    updateMySessionFamiliar,
    requestSync,
    webrtc: {
      isStreaming: webrtc.isStreaming,
      connectedGuestCount: webrtc.connectedGuestCount,
      peers: webrtc.peers,
      requestStream: webrtc.requestStream,
      hasGuestAudio: webrtc.hasGuestAudio,
      setGuestVolume: webrtc.setGuestVolume,
      hostDisabled: webrtc.hostDisabled,
    },
  };
}
