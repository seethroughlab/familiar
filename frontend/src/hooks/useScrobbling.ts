import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useShallow } from 'zustand/react/shallow';
import { usePlayerStore } from '../stores/playerStore';
import { lastfmApi } from '../api/client';

/**
 * Hook for automatic Last.fm scrobbling.
 *
 * Scrobbling rules (per Last.fm guidelines):
 * - Track must have been played for at least 30 seconds
 * - Track must be scrobbled when either 50% complete OR 4 minutes have passed
 * - Each track should only be scrobbled once per play
 */
export function useScrobbling() {
  const { currentTrack, currentTime, duration, isPlaying } = usePlayerStore(
    useShallow((s) => ({ currentTrack: s.currentTrack, currentTime: s.currentTime, duration: s.duration, isPlaying: s.isPlaying }))
  );

  const scrobbledTrackRef = useRef<string | null>(null);
  const nowPlayingTrackRef = useRef<string | null>(null);
  const playStartTimeRef = useRef<number>(0);

  // Get Last.fm connection status
  const { data: status } = useQuery({
    queryKey: ['lastfm-status'],
    queryFn: lastfmApi.getStatus,
    staleTime: 1000 * 60 * 5, // 5 minutes
  });

  const isConnected = status?.connected ?? false;

  // Update "Now Playing" when track changes
  useEffect(() => {
    if (!isConnected || !currentTrack || !isPlaying) return;

    // Only update if this is a new track
    if (nowPlayingTrackRef.current === currentTrack.id) return;

    nowPlayingTrackRef.current = currentTrack.id;
    playStartTimeRef.current = Date.now();

    // Reset scrobble status for new track
    if (scrobbledTrackRef.current !== currentTrack.id) {
      scrobbledTrackRef.current = null;
    }

    // Send now playing update (fire and forget)
    lastfmApi.updateNowPlaying(currentTrack.id).catch(() => {
      // Ignore errors - now playing is best-effort
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Only re-run when track ID changes, not object reference
  }, [currentTrack?.id, isPlaying, isConnected]);

  // Handle scrobbling based on playback progress
  useEffect(() => {
    if (!isConnected || !currentTrack || !isPlaying || !duration) return;

    // Already scrobbled this track
    if (scrobbledTrackRef.current === currentTrack.id) return;

    // Calculate thresholds
    const halfDuration = duration / 2;
    const fourMinutes = 4 * 60;
    const scrobbleThreshold = Math.min(halfDuration, fourMinutes);

    // Must have played at least 30 seconds
    if (currentTime < 30) return;

    // Check if we've reached the scrobble threshold
    if (currentTime >= scrobbleThreshold) {
      scrobbledTrackRef.current = currentTrack.id;

      // Calculate timestamp (when playback started)
      const timestamp = Math.floor(playStartTimeRef.current / 1000);

      // Submit scrobble
      lastfmApi.scrobble(currentTrack.id, timestamp).catch(() => {
        // Reset so we can retry
        scrobbledTrackRef.current = null;
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Only re-run when track ID changes, not object reference
  }, [currentTrack?.id, currentTime, duration, isPlaying, isConnected]);

  // Reset when track changes
  useEffect(() => {
    return () => {
      // When unmounting or track changes, reset refs
      nowPlayingTrackRef.current = null;
    };
  }, [currentTrack?.id]);
}
