/**
 * useArtworkPrefetch - Queue missing artwork for background download.
 *
 * Tracks which albums have been checked/queued to avoid duplicate requests.
 * Uses requestIdleCallback to avoid blocking UI during batch operations.
 */
import { useCallback, useRef, useEffect } from 'react';
import { artworkApi, type ArtworkQueueRequest } from '../api';
import { createLogger } from '../utils/logger';

const log = createLogger('ArtworkPrefetch');

// Global set of album keys we've already processed this session
// Persists across component unmounts to avoid re-checking
const processedAlbums = new Set<string>();

// Batch queue for collecting requests
const batchQueue: ArtworkQueueRequest[] = [];
let batchTimeout: ReturnType<typeof setTimeout> | number | null = null;

// Configuration
const BATCH_DELAY_MS = 500; // Wait this long to collect batch
const MAX_BATCH_SIZE = 20; // Max items per batch request

/**
 * Flush the batch queue - send all pending requests to the server.
 */
async function flushBatchQueue() {
  if (batchQueue.length === 0) return;

  const items = batchQueue.splice(0, MAX_BATCH_SIZE);

  try {
    await artworkApi.queueBatch(items);
  } catch (error) {
    // Silent failure - artwork prefetch is best-effort
    log.debug('Artwork prefetch batch failed:', error);
  }

  // If there are more items, schedule another flush
  if (batchQueue.length > 0) {
    scheduleBatchFlush();
  }
}

/**
 * Schedule a batch flush using requestIdleCallback if available.
 */
function scheduleBatchFlush() {
  if (batchTimeout !== null) return; // Already scheduled

  const callback = () => {
    batchTimeout = null;
    flushBatchQueue();
  };

  if (typeof window.requestIdleCallback === 'function') {
    batchTimeout = window.requestIdleCallback(callback, { timeout: BATCH_DELAY_MS * 2 });
  } else {
    batchTimeout = setTimeout(callback, BATCH_DELAY_MS);
  }
}

/**
 * Add an album to the batch queue for prefetching.
 */
function queueForPrefetch(artist: string, album: string, trackId?: string) {
  const key = `${artist}::${album}`;

  // Skip if already processed this session
  if (processedAlbums.has(key)) return;
  processedAlbums.add(key);

  // Add to batch queue
  batchQueue.push({
    artist,
    album,
    track_id: trackId,
  });

  // Schedule flush
  scheduleBatchFlush();
}

/**
 * Hook for prefetching artwork when albums come into view.
 *
 * Usage:
 * ```tsx
 * const prefetchArtwork = useArtworkPrefetch();
 *
 * // When an album becomes visible/focused:
 * prefetchArtwork(track.artist, track.album, track.id);
 * ```
 */
export function useArtworkPrefetch() {
  const prefetch = useCallback(
    (artist: string | null | undefined, album: string | null | undefined, trackId?: string) => {
      // Skip if missing required fields
      if (!artist || !album) return;

      queueForPrefetch(artist, album, trackId);
    },
    []
  );

  return prefetch;
}

/**
 * Hook for prefetching artwork for multiple albums at once.
 *
 * Useful for grid views where many albums become visible simultaneously.
 *
 * Usage:
 * ```tsx
 * const prefetchBatch = useArtworkPrefetchBatch();
 *
 * // When multiple albums become visible:
 * prefetchBatch(tracks.map(t => ({ artist: t.artist, album: t.album, trackId: t.id })));
 * ```
 */
export function useArtworkPrefetchBatch() {
  const prefetchBatch = useCallback(
    (
      items: Array<{
        artist: string | null | undefined;
        album: string | null | undefined;
        trackId?: string;
      }>
    ) => {
      for (const item of items) {
        if (item.artist && item.album) {
          queueForPrefetch(item.artist, item.album, item.trackId);
        }
      }
    },
    []
  );

  return prefetchBatch;
}

/**
 * Hook that returns a ref callback for intersection observer-based prefetching.
 *
 * Automatically prefetches artwork when the element enters the viewport.
 *
 * Usage:
 * ```tsx
 * const prefetchRef = useArtworkPrefetchOnVisible(track.artist, track.album, track.id);
 * return <div ref={prefetchRef}>...</div>;
 * ```
 */
export function useArtworkPrefetchOnVisible(
  artist: string | null | undefined,
  album: string | null | undefined,
  trackId?: string
) {
  const elementRef = useRef<HTMLElement | null>(null);
  const observerRef = useRef<IntersectionObserver | null>(null);
  const prefetchedRef = useRef(false);

  // Create observer on mount
  useEffect(() => {
    if (!artist || !album) return;

    const key = `${artist}::${album}`;
    if (processedAlbums.has(key)) {
      prefetchedRef.current = true;
      return;
    }

    observerRef.current = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry?.isIntersecting && !prefetchedRef.current) {
          prefetchedRef.current = true;
          queueForPrefetch(artist, album, trackId);
          // Disconnect after first intersection
          observerRef.current?.disconnect();
        }
      },
      {
        rootMargin: '100px', // Prefetch slightly before visible
        threshold: 0,
      }
    );

    if (elementRef.current) {
      observerRef.current.observe(elementRef.current);
    }

    return () => {
      observerRef.current?.disconnect();
    };
  }, [artist, album, trackId]);

  // Ref callback
  const setRef = useCallback((element: HTMLElement | null) => {
    elementRef.current = element;
    if (element && observerRef.current) {
      observerRef.current.observe(element);
    }
  }, []);

  return setRef;
}

/**
 * Reset the processed albums cache.
 * Useful for testing or after settings changes.
 */
export function resetArtworkPrefetchCache() {
  processedAlbums.clear();
}
