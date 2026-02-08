/**
 * Guest listener page - allows unauthenticated users to join
 * a listening session and receive audio via WebRTC.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { Radio, Volume2, VolumeX, Users, Music2, Loader2 } from 'lucide-react';

import { createLogger } from '../../utils/logger';

const log = createLogger('GuestListener');

interface SessionInfo {
  id: string;
  code: string;
  name: string;
  host_id: string;
  participant_count: number;
  webrtc_enabled: boolean;
  playback_state: {
    track_id: string | null;
    is_playing: boolean;
    position_ms: number;
  };
}

interface IceServer {
  urls: string;
  username?: string;
  credential?: string;
}

interface TrackInfo {
  title: string;
  artist: string;
  album?: string;
}

export function GuestListener() {
  const [code, setCode] = useState('');
  const [guestName, setGuestName] = useState('');
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [isConnecting, setIsConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [volume, setVolume] = useState(1);
  const [isMuted, setIsMuted] = useState(false);
  const [isReceivingAudio, setIsReceivingAudio] = useState(false);
  const [currentTrack, setCurrentTrack] = useState<TrackInfo | null>(null);
  const [iceServers, setIceServers] = useState<IceServer[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const peerConnectionRef = useRef<RTCPeerConnection | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const userIdRef = useRef<string | null>(null);
  const reconnectAttemptsRef = useRef<number>(0);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const maxReconnectAttempts = 10;

  // Get WebSocket URL
  const getWsUrl = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.hostname;
    const port = window.location.port === '3000' ? '8000' : window.location.port;
    return `${protocol}//${host}:${port}/api/v1/sessions/ws`;
  }, []);

  // Send WebSocket message
  const send = useCallback((message: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    }
  }, []);

  // Handle WebRTC offer from host
  const handleOffer = useCallback(async (sdp: RTCSessionDescriptionInit) => {
    log.info('Received WebRTC offer from host');

    const rtcConfig: RTCConfiguration = {
      iceServers: iceServers.length > 0 ? iceServers : [
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' },
      ],
    };

    const pc = new RTCPeerConnection(rtcConfig);
    peerConnectionRef.current = pc;

    // Handle incoming audio track
    pc.ontrack = (event) => {
      log.info('Received audio track from host');
      setIsReceivingAudio(true);

      if (!audioRef.current) {
        audioRef.current = new Audio();
        audioRef.current.autoplay = true;
      }

      audioRef.current.srcObject = event.streams[0];
      audioRef.current.volume = isMuted ? 0 : volume;
      audioRef.current.play().catch(log.error);
    };

    // Handle ICE candidates
    pc.onicecandidate = (event) => {
      if (event.candidate) {
        send({
          type: 'webrtc_ice',
          candidate: event.candidate.toJSON(),
        });
      }
    };

    // Handle connection state
    pc.onconnectionstatechange = () => {
      log.info(`WebRTC connection state: ${pc.connectionState}`);
      if (pc.connectionState === 'connected') {
        send({ type: 'webrtc_connected', connected: true });
      } else if (pc.connectionState === 'disconnected' || pc.connectionState === 'failed') {
        setIsReceivingAudio(false);
        send({ type: 'webrtc_connected', connected: false });
      }
    };

    try {
      await pc.setRemoteDescription(new RTCSessionDescription(sdp));
      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);

      send({
        type: 'webrtc_answer',
        sdp: pc.localDescription,
      });
    } catch (err) {
      log.error('Failed to handle WebRTC offer:', err);
      setError('Failed to establish audio connection');
    }
  }, [iceServers, volume, isMuted, send]);

  // Handle ICE candidate from host
  const handleIceCandidate = useCallback(async (candidate: RTCIceCandidateInit) => {
    if (peerConnectionRef.current) {
      try {
        await peerConnectionRef.current.addIceCandidate(new RTCIceCandidate(candidate));
      } catch (err) {
        log.error('Failed to add ICE candidate:', err);
      }
    }
  }, []);

  // Cleanup connections
  const cleanup = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (peerConnectionRef.current) {
      peerConnectionRef.current.close();
      peerConnectionRef.current = null;
    }
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.srcObject = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsReceivingAudio(false);
    reconnectAttemptsRef.current = 0;
  }, []);

  // Handle WebSocket messages
  const handleMessage = useCallback((event: MessageEvent) => {
    const data = JSON.parse(event.data);

    switch (data.type) {
      case 'session_joined':
        setSession(data.session);
        userIdRef.current = data.your_user_id;
        if (data.ice_servers) {
          setIceServers(data.ice_servers);
        }
        setError(null);
        setIsConnecting(false);
        // Reset reconnect attempts on successful connection
        reconnectAttemptsRef.current = 0;

        // Request WebRTC stream
        setTimeout(() => {
          send({ type: 'webrtc_request' });
        }, 500);
        break;

      case 'webrtc_offer':
        if (data.sdp) {
          handleOffer(data.sdp);
        }
        break;

      case 'webrtc_ice':
        if (data.candidate) {
          handleIceCandidate(data.candidate);
        }
        break;

      case 'playback_update':
        // Track info is synced via WebRTC audio, but we can show what's playing
        if (data.track_id) {
          // Fetch track info
          fetch(`/api/v1/tracks/${data.track_id}`)
            .then(res => res.json())
            .then(track => {
              setCurrentTrack({
                title: track.title || 'Unknown',
                artist: track.artist || 'Unknown',
                album: track.album,
              });
            })
            .catch(() => {});
        }
        break;

      case 'user_left':
        if (data.reason === 'host_left') {
          setError('The host ended the session');
          setSession(null);
          cleanup();
        }
        break;

      case 'error':
        setError(data.message);
        setIsConnecting(false);
        break;
    }
  }, [handleOffer, handleIceCandidate, send, cleanup]);

  // Join session
  const joinSession = useCallback(() => {
    if (!code || !guestName) return;

    setIsConnecting(true);
    setError(null);

    const ws = new WebSocket(getWsUrl());

    ws.onopen = () => {
      ws.send(JSON.stringify({
        type: 'join_guest',
        code: code.toUpperCase(),
        guest_name: guestName,
      }));
    };

    ws.onmessage = handleMessage;

    ws.onerror = () => {
      setError('Connection error');
      setIsConnecting(false);
    };

    ws.onclose = () => {
      if (session) {
        reconnectAttemptsRef.current += 1;

        if (reconnectAttemptsRef.current > maxReconnectAttempts) {
          setError('Connection lost. Please try rejoining the session.');
          return;
        }

        // Exponential backoff: 3s, 6s, 12s, 24s, 48s, max 60s
        const delay = Math.min(3000 * Math.pow(2, reconnectAttemptsRef.current - 1), 60000);
        log.info(`Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current}/${maxReconnectAttempts})`);
        setError(`Connection lost. Reconnecting in ${Math.round(delay / 1000)}s...`);

        reconnectTimeoutRef.current = window.setTimeout(() => {
          joinSession();
        }, delay);
      }
    };

    wsRef.current = ws;
  }, [code, guestName, getWsUrl, handleMessage, session]);

  // Leave session
  const leaveSession = useCallback(() => {
    send({ type: 'leave' });
    cleanup();
    setSession(null);
    setCurrentTrack(null);
  }, [send, cleanup]);

  // Update volume
  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.volume = isMuted ? 0 : volume;
    }
  }, [volume, isMuted]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      cleanup();
    };
  }, [cleanup]);

  // Not in session - show join form
  if (!session) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-zinc-900 to-black flex items-center justify-center p-4">
        <div className="bg-zinc-800/50 rounded-xl border border-zinc-700 p-8 max-w-md w-full">
          <div className="text-center mb-8">
            <Radio className="w-16 h-16 mx-auto mb-4 text-green-500" />
            <h1 className="text-2xl font-bold text-white">Join Listening Session</h1>
            <p className="text-zinc-400 mt-2">
              Listen along with a friend without needing an account
            </p>
          </div>

          <div className="space-y-4">
            <div>
              <label className="block text-sm text-zinc-400 mb-1">Your Name</label>
              <input
                type="text"
                value={guestName}
                onChange={(e) => setGuestName(e.target.value)}
                placeholder="Enter your name"
                className="w-full px-4 py-3 bg-zinc-700 border border-zinc-600 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-green-500"
              />
            </div>

            <div>
              <label className="block text-sm text-zinc-400 mb-1">Session Code</label>
              <input
                type="text"
                value={code}
                onChange={(e) => setCode(e.target.value.toUpperCase())}
                placeholder="Enter 6-digit code"
                maxLength={6}
                className="w-full px-4 py-3 bg-zinc-700 border border-zinc-600 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-green-500 text-center text-2xl tracking-widest font-mono"
              />
            </div>

            {error && (
              <div className="bg-red-500/10 border border-red-500/50 text-red-400 px-4 py-3 rounded-lg text-sm">
                {error}
              </div>
            )}

            <button
              onClick={joinSession}
              disabled={!code || !guestName || isConnecting}
              className="w-full px-4 py-3 bg-green-600 hover:bg-green-500 disabled:bg-zinc-700 disabled:text-zinc-500 rounded-lg font-medium transition-colors flex items-center justify-center gap-2"
            >
              {isConnecting ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  Connecting...
                </>
              ) : (
                <>
                  <Radio className="w-5 h-5" />
                  Join Session
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // In session - show player
  return (
    <div className="min-h-screen bg-gradient-to-b from-zinc-900 to-black flex flex-col">
      {/* Header */}
      <header className="p-4 border-b border-zinc-800">
        <div className="flex items-center justify-between max-w-2xl mx-auto">
          <div className="flex items-center gap-3">
            <Radio className="w-6 h-6 text-green-500" />
            <div>
              <h1 className="font-semibold">{session.name}</h1>
              <div className="text-sm text-zinc-400 flex items-center gap-2">
                <Users className="w-4 h-4" />
                {session.participant_count} listeners
              </div>
            </div>
          </div>
          <button
            onClick={leaveSession}
            className="px-4 py-2 text-sm text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-lg transition-colors"
          >
            Leave
          </button>
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 flex items-center justify-center p-8">
        <div className="text-center max-w-md">
          {/* Now playing */}
          <div className="mb-8">
            <div className="w-48 h-48 mx-auto mb-6 bg-zinc-800 rounded-xl flex items-center justify-center">
              {currentTrack ? (
                <img
                  src={session.playback_state.track_id
                    ? `/api/v1/tracks/${session.playback_state.track_id}/artwork`
                    : undefined}
                  alt=""
                  className="w-full h-full object-cover rounded-xl"
                  onError={(e) => {
                    e.currentTarget.style.display = 'none';
                    e.currentTarget.nextElementSibling?.classList.remove('hidden');
                  }}
                />
              ) : null}
              <Music2 className={`w-16 h-16 text-zinc-600 ${currentTrack ? 'hidden' : ''}`} />
            </div>

            {currentTrack ? (
              <div>
                <h2 className="text-xl font-semibold">{currentTrack.title}</h2>
                <p className="text-zinc-400">{currentTrack.artist}</p>
                {currentTrack.album && (
                  <p className="text-sm text-zinc-500">{currentTrack.album}</p>
                )}
              </div>
            ) : (
              <div className="text-zinc-400">
                {isReceivingAudio ? 'Now playing...' : 'Waiting for audio...'}
              </div>
            )}
          </div>

          {/* Connection status */}
          <div className={`inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm ${
            isReceivingAudio
              ? 'bg-green-500/20 text-green-400'
              : 'bg-yellow-500/20 text-yellow-400'
          }`}>
            <span className={`w-2 h-2 rounded-full ${
              isReceivingAudio ? 'bg-green-500' : 'bg-yellow-500 animate-pulse'
            }`} />
            {isReceivingAudio ? 'Connected' : 'Connecting...'}
          </div>

          {/* Volume control */}
          <div className="mt-8 flex items-center justify-center gap-4">
            <button
              onClick={() => setIsMuted(!isMuted)}
              className="p-2 text-zinc-400 hover:text-white transition-colors"
            >
              {isMuted ? <VolumeX className="w-6 h-6" /> : <Volume2 className="w-6 h-6" />}
            </button>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={volume}
              onChange={(e) => setVolume(parseFloat(e.target.value))}
              className="w-32 accent-green-500"
            />
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="p-4 text-center text-sm text-zinc-500">
        Listening as <span className="text-white">{guestName}</span> | Code: <span className="font-mono">{session.code}</span>
      </footer>
    </div>
  );
}
