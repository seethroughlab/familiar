import { useEffect, useRef } from 'react';
import { usePlayerStore } from '../stores/playerStore';
import { tracksApi } from '../api';

/**
 * Hook for automatic metadata enrichment when a track plays.
 *
 * Triggers a fire-and-forget enrichment request when:
 * - A new track starts playing
 * - The track hasn't been enrichment-checked this session
 *
 * The backend checks if the track needs enrichment (missing metadata/artwork)
 * and fetches from MusicBrainz/AcoustID if needed.
 */
export function useMetadataEnrichment() {
  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const isPlaying = usePlayerStore((s) => s.isPlaying);

  // Track which tracks we've already requested enrichment for this session
  const enrichedTracksRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!currentTrack?.id || !isPlaying) return;

    // Only trigger once per track per session
    if (enrichedTracksRef.current.has(currentTrack.id)) return;
    enrichedTracksRef.current.add(currentTrack.id);

    // Fire-and-forget enrichment request
    tracksApi.enrich(currentTrack.id).catch(() => {
      // Ignore errors - enrichment is best-effort
      // Remove from set so we can retry if needed
      enrichedTracksRef.current.delete(currentTrack.id);
    });
  }, [currentTrack?.id, isPlaying]);
}
