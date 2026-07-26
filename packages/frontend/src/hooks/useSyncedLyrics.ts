/**
 * Fetch a track's synced lyrics for the lyrics visualizer.
 *
 * Race-safe across track changes: when the track id changes we clear the old
 * lyrics immediately (so a previous track's lyrics never linger on screen) and
 * ignore any in-flight response from a prior track. This prevents two bugs when
 * skipping quickly between tracks:
 *   - stale lyrics lingering / "not keeping up" with the current track, and
 *   - a late, out-of-order response overwriting good lyrics (e.g. flipping a
 *     loaded song back to the "no synced lyrics" fallback).
 *
 * Only synced lyrics (with timing) are surfaced; plain/unsynced results become
 * null so the visualizer shows its fallback.
 */
import { useEffect, useState } from 'react';
import { tracksApi, type LyricLine } from '../api';

export function useSyncedLyrics(trackId: string | null | undefined): LyricLine[] | null {
  const [lyrics, setLyrics] = useState<LyricLine[] | null>(null);

  useEffect(() => {
    // Clear first so the previous track's lyrics don't show against a new track.
    setLyrics(null);
    if (!trackId) return;

    let ignore = false;
    tracksApi
      .getLyrics(trackId)
      .then((response) => {
        if (ignore) return;
        setLyrics(response.synced && response.lines.length > 0 ? response.lines : null);
      })
      .catch(() => {
        if (!ignore) setLyrics(null);
      });

    // Invalidate this request if the track changes (or the component unmounts)
    // before it resolves — only the latest track's response is applied.
    return () => {
      ignore = true;
    };
  }, [trackId]);

  return lyrics;
}
