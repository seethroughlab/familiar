import { useEffect, useRef } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { usePlayerStore } from '../stores/playerStore';
import { playTrackingApi } from '../api/profiles';

/**
 * Tell the server when a track starts (ADR-0030).
 *
 * **This hook used to do the scrobbling itself**, implementing Last.fm's rules in the browser — a
 * 30-second floor, a scrobble at `min(duration / 2, 4 minutes)`, once per play, gated on a
 * connection-status query. All of that now lives on the server, which already receives
 * `played_seconds`, `track_duration` and `started_at` on every `/played` and `/skipped` from every
 * client. Leaving it here would scrobble each browser play twice.
 *
 * Moving it also fixed a case this could not see: Last.fm scrobbles at half a track, while
 * Familiar's `play_count` means the track reached its end. A track abandoned at 60% is a *skip* to
 * Familiar and a *scrobble* to Last.fm, and only the server sees both events.
 *
 * What is left is the one thing the server cannot infer. `/played` and `/skipped` both fire at the
 * *end* of a track, so nothing tells it what is playing right now — hence a start signal, sent once
 * per track. Fire-and-forget by design: a now-playing is a claim about the present, it expires in
 * minutes, and a retry would assert something that had already stopped being true.
 */
export function useScrobbling() {
  const { currentTrack, isPlaying } = usePlayerStore(
    useShallow((s) => ({ currentTrack: s.currentTrack, isPlaying: s.isPlaying }))
  );

  // So pausing and resuming the same track does not announce it twice.
  const announcedTrackRef = useRef<string | null>(null);

  useEffect(() => {
    if (!currentTrack || !isPlaying) return;
    if (announcedTrackRef.current === currentTrack.id) return;

    announcedTrackRef.current = currentTrack.id;
    playTrackingApi.recordStart(currentTrack.id).catch(() => {
      // Best-effort by design. Nothing downstream depends on this landing, and the durable record
      // of this track arrives later on /played or /skipped.
    });
  }, [currentTrack, isPlaying]);

  useEffect(() => {
    return () => {
      announcedTrackRef.current = null;
    };
  }, [currentTrack?.id]);
}
