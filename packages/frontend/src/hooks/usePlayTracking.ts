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

/**
 * The share of the track that was heard, or undefined when the duration is unknown.
 *
 * Clamped, because the two figures come from different places: played time is accumulated
 * from the engine's clock while the duration is track metadata, and a track that loops or
 * whose tag understates its length can produce more played seconds than the track is long.
 * The server clamps too, but sending 1.1 makes every stored figure a question about which
 * end did the clamping — and the native client (`PlaybackReport.completionRatio`) has
 * always clamped, so this is the two clients agreeing rather than a new rule.
 */
function completionRatio(playedSeconds: number, durationSeconds: number): number | undefined {
  if (!durationSeconds) return undefined;
  return Math.min(Math.max(playedSeconds / durationSeconds, 0), 1);
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
 *  - a **play**, once ≥30s has been listened to. This bumps ProfilePlayHistory.
 *  - a **listening event** for every track the listener moves on from, including short
 *    skips, which previously produced no API call at all. This is the negative signal
 *    ADR-0005's radio needs, and it only accumulates in real time.
 *
 * The outcome is derived server-side from the stop reason plus completion ratio, so a
 * crossfade (which advances early, around 0.9) is not mistaken for a skip and a failed
 * load is never mistaken for dislike.
 *
 * **Reported when the track is done with, not partway through — and that is the whole
 * point.** This used to deliver the play the moment listening crossed
 * `min(duration / 2, 4 min)`, sending `completion_ratio` as measured *at that instant*.
 * Nothing ever revised it, so every web play landed with a ratio of almost exactly 0.5
 * whether the listener heard half the track or all of it. Measured on the live database
 * on 2026-08-01: **289 of 357 completed events sat in the 0.5–0.6 bucket**, against native
 * client rows correctly reading 0.95–1.00. Completion is the taste signal ADR-0005 ranks
 * on, and a constant carries none — so a month of "accumulating data" would have been a
 * month of noise.
 *
 * Nothing changes about *which* plays count. The early delivery only decided *when*: a
 * play short of the half mark but past 30s was already reported on track change, by the
 * same rule that now reports all of them. The Last.fm half/4-minute threshold turned out
 * to gate nothing, which is why it is gone rather than merely moved.
 */
export function usePlayTracking() {
  const { currentTrack, currentTime, duration, isPlaying } = usePlayerStore(
    useShallow((s) => ({ currentTrack: s.currentTrack, currentTime: s.currentTime, duration: s.duration, isPlaying: s.isPlaying }))
  );

  const recordedTrackRef = useRef<string | null>(null);
  const accumulatedTimeRef = useRef<number>(0);
  const lastTimeRef = useRef<number>(0);
  const lastTrackIdRef = useRef<string | null>(null);
  // The outgoing track's duration, taken from track metadata rather than the engine.
  // The store's `duration` cannot be trusted for this: it belongs to whatever the engine
  // last loaded, so it is the PREVIOUS track's value whenever the current one fails to
  // load — which is exactly when an errored event is about to be reported.
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
        // A play, reported now that the final figure is known. Marked as recorded for the
        // same reason the threshold delivery used to be: so a crossfade rollback cannot
        // report the same listen twice.
        recordedTrackRef.current = previousId;
        void deliverListenEvent(
          previousId,
          'played',
          {
            track_duration: outgoingDuration || undefined,
            completion_ratio: completionRatio(playedSeconds, outgoingDuration),
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

      // Deliberately NOT clearing recordedTrackRef here.
      //
      // A failed crossfade rolls the queue back to the track that was just playing
      // (useAudioEngine's error handler → setQueueByTrackId). Clearing on every change
      // meant the returned-to track crossed its threshold a second time and was
      // recorded twice — observed as play_count 2 and total_play_seconds 110.8 for a
      // single listen of a 75-second track. It also wrote a duplicate PlayEvent, biasing
      // the taste signal toward whichever tracks happen to fail a crossfade.
      //
      // Instead the accumulate effect clears it once a *different* track has genuinely
      // been listened to, so a real replay later still records while a rollback cannot.
      accumulatedTimeRef.current = 0;
      lastTimeRef.current = 0;
    }

    // Track metadata is authoritative and always corresponds to this track.
    if (previousId !== trackId) {
      lastDurationRef.current = currentTrack?.duration_seconds ?? 0;
    }

    lastTrackIdRef.current = trackId;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only re-run on track change
  }, [currentTrack?.id]);

  // Track accumulated play time and record when threshold is met
  useEffect(() => {
    if (!currentTrack || !isPlaying || !duration) return;

    // Already recorded this track
    if (recordedTrackRef.current === currentTrack.id) return;

    // Update accumulated time (only count forward progress)
    if (currentTime > lastTimeRef.current) {
      accumulatedTimeRef.current += currentTime - lastTimeRef.current;
    } else if (currentTime < lastTimeRef.current) {
      // User seeked backward - don't subtract, just update reference
    }
    lastTimeRef.current = currentTime;

    // A different track has now been genuinely listened to, so the previously recorded
    // one is free to be recorded again if the listener returns to it. Held until this
    // point so that a crossfade rollback — which spends no real time on the intervening
    // track — cannot re-record what it just left.
    if (
      recordedTrackRef.current !== null
      && recordedTrackRef.current !== currentTrack.id
      && accumulatedTimeRef.current >= MIN_PLAY_SECONDS
    ) {
      recordedTrackRef.current = null;
    }

    // Nothing is delivered here. The play is reported when the track is done with, where
    // the completion ratio is final — see this hook's own note on why.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Only re-run when track ID changes, not object reference
  }, [currentTrack?.id, currentTime, duration, isPlaying]);

  // Report the track in progress if the page goes away before it is finished with.
  //
  // The cost of reporting at the end rather than partway through: closing the tab mid-track
  // used to still count the play, because it had already been sent at the halfway mark.
  // This restores that without restoring the frozen ratio — the figures here are whatever
  // has actually been heard.
  //
  // Best effort, and honestly so. `pagehide` gives the request a chance to leave and the
  // IndexedDB fallback a chance to catch it, but a browser tearing the page down owes
  // neither of them anything. `visibilitychange` is the one that actually fires on mobile,
  // where tabs are discarded without warning; marking the track recorded keeps a later
  // track change from reporting the same listen twice if the page survives after all.
  useEffect(() => {
    const flush = () => {
      const trackId = currentTrackIdRef.current;
      const playedSeconds = accumulatedTimeRef.current;
      if (!trackId || playedSeconds < MIN_PLAY_SECONDS) return;
      if (recordedTrackRef.current === trackId) return;

      const outgoingDuration = lastDurationRef.current;
      const { queueSource } = usePlayerStore.getState();
      recordedTrackRef.current = trackId;

      void deliverListenEvent(
        trackId,
        'played',
        {
          track_duration: outgoingDuration || undefined,
          completion_ratio: completionRatio(playedSeconds, outgoingDuration),
          context: toContext(queueSource?.type),
        },
        playedSeconds,
      );
    };

    const onVisibilityChange = () => {
      if (document.visibilityState === 'hidden') flush();
    };

    window.addEventListener('pagehide', flush);
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      window.removeEventListener('pagehide', flush);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, []);
}
