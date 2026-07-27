import { useEffect, useRef } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { usePlayerStore } from '../stores/playerStore';
import { deliverListenEvent } from '../services/syncService';
import { createLogger } from '../utils/logger';
import type { AdvanceReason } from '../player/playbackStore';
import type { ListenContext, ListenStopReason } from '../api/profiles';
const log = createLogger('PlayTracking');

/** Reaching the scrobble threshold is what counts as a play. */
const MIN_PLAY_SECONDS = 30;
const MAX_PLAY_SECONDS = 4 * 60;

/**
 * Map the client's advance reason onto the backend's `StopReason` (ADR-0004).
 *
 * Returns null for advances the listener did not cause — offline queue rebuilds,
 * hydration, profile switches — which must emit nothing. Without this, every reconnect
 * would log a phantom skip.
 */
function toStopReason(reason: AdvanceReason): ListenStopReason | null {
  switch (reason) {
    case 'ended':
    case 'crossfade':
    case 'native-auto':
      return 'natural';
    case 'error':
      return 'error';
    case 'user':
      return 'user';
    case 'system':
      return null;
  }
}

/** Queue source types line up with the backend's PlayContext, apart from 'library'. */
function toContext(sourceType: string | undefined): ListenContext | undefined {
  if (!sourceType) return undefined;
  const known: ListenContext[] = [
    'library', 'album', 'playlist', 'artist', 'ephemeral', 'radio', 'ambient', 'other',
  ];
  return known.includes(sourceType as ListenContext) ? (sourceType as ListenContext) : 'other';
}

/**
 * Track listening and report it to the backend.
 *
 * Two things are recorded:
 *  - a **play**, on the Last.fm rule — ≥30s listened AND ≥min(half the track, 4 min).
 *    This bumps ProfilePlayHistory and is unchanged from before.
 *  - a **listening event** for every track the listener moves on from, including short
 *    skips, which previously produced no API call at all. This is the negative signal
 *    ADR-0005's radio needs, and it only accumulates in real time.
 *
 * The outcome is derived server-side from the stop reason plus completion ratio, so a
 * crossfade (which advances early, around 0.9) is not mistaken for a skip and a failed
 * load is never mistaken for dislike.
 */
export function usePlayTracking() {
  const { currentTrack, currentTime, duration, isPlaying } = usePlayerStore(
    useShallow((s) => ({ currentTrack: s.currentTrack, currentTime: s.currentTime, duration: s.duration, isPlaying: s.isPlaying }))
  );

  const recordedTrackRef = useRef<string | null>(null);
  const accumulatedTimeRef = useRef<number>(0);
  const lastTimeRef = useRef<number>(0);
  const lastTrackIdRef = useRef<string | null>(null);
  // The outgoing track's duration. By the time the reset effect runs, `duration` in the
  // render closure is already the NEW track's, so a completion ratio computed from it
  // would measure every track against the wrong length.
  const lastDurationRef = useRef<number>(0);
  const currentTrackIdRef = useRef<string | null>(null);

  // Store current track id in ref for cleanup function
  useEffect(() => {
    currentTrackIdRef.current = currentTrack?.id ?? null;
  }, [currentTrack?.id]);

  // Reset state when the track changes, and report what happened to the outgoing one
  useEffect(() => {
    const trackId = currentTrack?.id ?? null;
    const previousId = lastTrackIdRef.current;

    if (previousId && previousId !== trackId) {
      const playedSeconds = accumulatedTimeRef.current;
      const outgoingDuration = lastDurationRef.current;
      const alreadyRecorded = recordedTrackRef.current === previousId;

      // Read the reason from the store rather than the render closure — it is written in
      // the same setState as the track change, so it is current here.
      const { _advanceReason, queueSource } = usePlayerStore.getState();
      const stopReason = toStopReason(_advanceReason);
      const context = toContext(queueSource?.type);

      if (stopReason === null) {
        // A rebuild or profile switch — the listener did nothing to report.
        log.debug('advance not attributable to the listener, not reporting', { previousId });
      } else if (alreadyRecorded) {
        // Already counted as a play; nothing further to say about it.
        log.debug('outgoing track already recorded as a play', { previousId });
      } else if (playedSeconds >= MIN_PLAY_SECONDS) {
        // Partial play past the minimum but short of the scrobble threshold. Counts
        // toward the aggregate, exactly as it did before.
        void deliverListenEvent(
          previousId,
          'played',
          {
            track_duration: outgoingDuration || undefined,
            completion_ratio: outgoingDuration ? playedSeconds / outgoingDuration : undefined,
            context,
          },
          playedSeconds,
        );
      } else {
        // Under the play threshold. Previously this emitted nothing at all — a track
        // skipped at five seconds was invisible. The backend derives the outcome, so a
        // short track played in full still comes back `completed`.
        void deliverListenEvent(previousId, 'skipped', {
          played_seconds: playedSeconds,
          track_duration: outgoingDuration || undefined,
          context,
          reason: stopReason,
        });
      }

      recordedTrackRef.current = null;
      accumulatedTimeRef.current = 0;
      lastTimeRef.current = 0;
    }

    lastTrackIdRef.current = trackId;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only re-run on track change
  }, [currentTrack?.id]);

  // Track accumulated play time and record when threshold is met
  useEffect(() => {
    if (!currentTrack || !isPlaying || !duration) return;

    // Keep the outgoing duration current while this track is the one playing.
    lastDurationRef.current = duration;

    // Already recorded this track
    if (recordedTrackRef.current === currentTrack.id) return;

    // Update accumulated time (only count forward progress)
    if (currentTime > lastTimeRef.current) {
      accumulatedTimeRef.current += currentTime - lastTimeRef.current;
    } else if (currentTime < lastTimeRef.current) {
      // User seeked backward - don't subtract, just update reference
    }
    lastTimeRef.current = currentTime;

    const recordThreshold = Math.min(duration / 2, MAX_PLAY_SECONDS);

    if (accumulatedTimeRef.current < MIN_PLAY_SECONDS) return;

    if (accumulatedTimeRef.current >= recordThreshold) {
      recordedTrackRef.current = currentTrack.id;
      const played = accumulatedTimeRef.current;
      const { queueSource } = usePlayerStore.getState();

      deliverListenEvent(
        currentTrack.id,
        'played',
        {
          track_duration: duration,
          completion_ratio: duration ? played / duration : undefined,
          context: toContext(queueSource?.type),
        },
        played,
      ).catch((err) => {
        // Reset so we can retry on the next threshold check
        log.error('Failed to record play:', err);
        recordedTrackRef.current = null;
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Only re-run when track ID changes, not object reference
  }, [currentTrack?.id, currentTime, duration, isPlaying]);
}
