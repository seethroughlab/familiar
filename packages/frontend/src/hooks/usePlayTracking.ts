import { useEffect, useRef } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { usePlayerStore } from '../stores/playerStore';
import { playTrackingApi } from '../api';
import { createLogger } from '../utils/logger';
import { isExternalTrack } from '../types';

const log = createLogger('PlayTracking');

/**
 * Hook for tracking local play history.
 *
 * Records plays to the backend when:
 * - Track has been played for at least 30 seconds
 * - AND either 50% of the track has been played OR 4 minutes have passed
 *
 * This follows the same rules as Last.fm scrobbling.
 */
export function usePlayTracking() {
  const { currentTrack, currentTime, duration, isPlaying } = usePlayerStore(
    useShallow((s) => ({ currentTrack: s.currentTrack, currentTime: s.currentTime, duration: s.duration, isPlaying: s.isPlaying }))
  );

  const recordedTrackRef = useRef<string | null>(null);
  const accumulatedTimeRef = useRef<number>(0);
  const lastTimeRef = useRef<number>(0);
  const lastTrackIdRef = useRef<string | null>(null);
  const currentTrackIdRef = useRef<string | null>(null);
  const lastTrackExternalRef = useRef<boolean>(false);

  // Store current track id in ref for cleanup function
  useEffect(() => {
    currentTrackIdRef.current = currentTrack?.id ?? null;
  }, [currentTrack?.id]);

  // Reset state when track changes
  useEffect(() => {
    const trackId = currentTrack?.id ?? null;

    // If track changed, record partial play from previous track if applicable
    if (lastTrackIdRef.current && lastTrackIdRef.current !== trackId) {
      // If we haven't recorded the previous track but have significant time, record it
      if (
        !lastTrackExternalRef.current &&
        recordedTrackRef.current !== lastTrackIdRef.current &&
        accumulatedTimeRef.current >= 30
      ) {
        const prevTrackId = lastTrackIdRef.current;
        const prevAccumulatedTime = accumulatedTimeRef.current;
        playTrackingApi.recordPlay(prevTrackId, prevAccumulatedTime).catch(() => {
          // Ignore errors for partial plays
        });
      }

      // Reset for new track
      recordedTrackRef.current = null;
      accumulatedTimeRef.current = 0;
      lastTimeRef.current = 0;
    }

    lastTrackIdRef.current = trackId;
    lastTrackExternalRef.current = isExternalTrack(currentTrack);
  }, [currentTrack?.id]);

  // Track accumulated play time and record when threshold is met
  useEffect(() => {
    if (!currentTrack || !isPlaying || !duration) return;

    // External tracks use preview URLs and have no entry in the tracks table
    if (isExternalTrack(currentTrack)) return;

    // Already recorded this track
    if (recordedTrackRef.current === currentTrack.id) return;

    // Update accumulated time (only count forward progress)
    if (currentTime > lastTimeRef.current) {
      accumulatedTimeRef.current += currentTime - lastTimeRef.current;
    } else if (currentTime < lastTimeRef.current) {
      // User seeked backward - don't subtract, just update reference
    }
    lastTimeRef.current = currentTime;

    // Calculate thresholds
    const halfDuration = duration / 2;
    const fourMinutes = 4 * 60;
    const recordThreshold = Math.min(halfDuration, fourMinutes);

    // Must have played at least 30 seconds
    if (accumulatedTimeRef.current < 30) return;

    // Check if we've reached the record threshold
    if (accumulatedTimeRef.current >= recordThreshold) {
      recordedTrackRef.current = currentTrack.id;

      // Record the play with duration
      playTrackingApi.recordPlay(currentTrack.id, accumulatedTimeRef.current).catch((err) => {
        // Reset so we can retry on next threshold check
        log.error('Failed to record play:', err);
        recordedTrackRef.current = null;
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Only re-run when track ID changes, not object reference
  }, [currentTrack?.id, currentTime, duration, isPlaying]);
}
