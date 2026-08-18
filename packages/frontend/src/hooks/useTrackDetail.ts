/**
 * Fetch a track's full detail — the shape that carries `features`.
 *
 * `VisualizerProps.features` is part of the documented visualizer contract (ADR-0034 point 6) and
 * until now nothing supplied it: `AudioVisualizer` defaults it to null and both call sites omitted
 * it, so `ReactiveTerrain` — the only visualizer that reads it — always took its fallbacks. This
 * hook is what makes that half of the API real (ADR-0064 point 9).
 *
 * **Why a fetch rather than the track already in hand.** `playerStore.currentTrack` comes from
 * `tracksApi.list`, which only populates `features` when the caller passes `include_features` —
 * and the only caller that does is the track-list browser, for its feature columns. So
 * `currentTrack.features` is usually undefined, and passing it would appear to work on exactly one
 * screen. `GET /tracks/{id}` always populates all fifteen fields when the track has been analysed.
 *
 * Race-safe across track changes, in the same shape as `useSyncedLyrics`: the previous track's
 * detail is cleared immediately so it cannot be read against a new track, and an in-flight response
 * from a prior track is ignored rather than applied late.
 *
 * A track that has never been analysed resolves with `features` absent, which is not an error —
 * callers get `null` features and visualizers use their own defaults.
 */
import { useEffect, useState } from 'react';
import { tracksApi } from '../api';
import type { Track } from '../types';

export function useTrackDetail(trackId: string | null | undefined): Track | null {
  const [track, setTrack] = useState<Track | null>(null);

  useEffect(() => {
    // Clear first so a previous track's analysis is never read against a new track.
    setTrack(null);
    if (!trackId) return;

    let ignore = false;
    tracksApi
      .get(trackId)
      .then((detail) => {
        if (!ignore) setTrack(detail);
      })
      .catch(() => {
        // Offline, or a track the server does not know. The visualizer falls back to what it has.
        if (!ignore) setTrack(null);
      });

    return () => {
      ignore = true;
    };
  }, [trackId]);

  return track;
}
