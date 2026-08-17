/**
 * PrefetchService — downloads upcoming tracks ahead of playback.
 *
 * Subscribes to playerStore queue/index changes and downloads the next N tracks
 * in the background so they're already local when the engine needs them.
 *
 * Stores Blobs in memory and returns blob URLs.
 */
import { usePlayerStore } from '../player/playerStore';
import { useConnectivityStore } from '../stores/connectivityStore';
import { isTrackOffline } from './offlineService';
import { getApiUrl } from '../api/base';
import { createLogger } from '../utils/logger';

const log = createLogger('Prefetch');

const PREFETCH_COUNT = 3;

type PrefetchStatus = 'downloading' | 'ready' | 'failed';

interface PrefetchEntry {
  trackId: string;
  status: PrefetchStatus;
  blobUrl?: string;
  abortController?: AbortController;
  blob?: Blob; // hold reference to prevent GC on web
}

// A Capacitor Filesystem branch wrote prefetched audio to disk on iOS and handed back a
// `nativeUri`. The Capacitor app was deleted on 2026-08-11 (ADR-0001 point 6), so that path was
// unreachable; prefetching is a blob URL in an ordinary browser.

class PrefetchService {
  private cache = new Map<string, PrefetchEntry>();
  private unsubscribe: (() => void) | null = null;
  private downloadQueue: string[] = [];
  private isDownloading = false;
  // Which tracks an audio element may still be reading from. Neither is "upcoming", and
  // both must survive eviction — see `reconcile`.
  private currentTrackId: string | null = null;
  private previousTrackId: string | null = null;

  /**
   * Start the prefetch service — subscribes to playerStore changes.
   */
  start(): void {
    if (this.unsubscribe) return; // already started

    log.info('Prefetch service started');

    let prevQueueIndex = usePlayerStore.getState().queueIndex;
    let prevQueueLength = usePlayerStore.getState().queue.length;

    this.unsubscribe = usePlayerStore.subscribe(() => {
      const state = usePlayerStore.getState();
      const queueIndex = state.queueIndex;
      const queueLength = state.queue.length;
      if (queueIndex !== prevQueueIndex || queueLength !== prevQueueLength) {
        prevQueueIndex = queueIndex;
        prevQueueLength = queueLength;
        this.reconcile();
      }
    });

    // Initial reconcile
    this.reconcile();
  }

  /**
   * Stop the prefetch service — unsubscribes and cleans up all entries.
   */
  stop(): void {
    if (this.unsubscribe) {
      this.unsubscribe();
      this.unsubscribe = null;
    }
    this.evictAll();
    log.info('Prefetch service stopped');
  }

  /**
   * Get a prefetched URL for a track, if available.
   */
  getUrl(trackId: string): { url: string; isOffline: true } | null {
    const entry = this.cache.get(trackId);
    if (!entry || entry.status !== 'ready') return null;

    const url = entry.blobUrl;
    if (!url) return null;

    return { url, isOffline: true };
  }

  /**
   * Reconcile: compute upcoming track IDs, diff against cache,
   * start new downloads and evict stale entries.
   */
  private reconcile(): void {
    // No-op if offline mode is active (nothing to download)
    if (useConnectivityStore.getState().offlineModeActive) return;

    const upcomingIds = usePlayerStore.getState().getUpcomingTrackIds(PREFETCH_COUNT);

    // A track an audio element may still be reading from must never be evicted.
    //
    // `getUpcomingTrackIds` counts from step 1, so the current track is by definition
    // never "upcoming". The engine resolves its source through `getUrl()`
    // (`WebAudioEngine.resolveTrackUrl`), so evicting the current track revokes the very
    // blob URL the element is reading from, and that surfaces as
    // `PIPELINE_ERROR_READ: FFmpegDemuxer: data source error` (issue #13).
    //
    // The delay is what made this hard to see. `URL.revokeObjectURL` does not abort a
    // read already in flight; it only breaks *subsequent* fetches. A short track that
    // buffered fully before the advance plays through fine, while a large one dies
    // part-way when the element next reaches for data — so it looked intermittent and
    // size-dependent, and it always followed a track change.
    //
    // The previous track is retained too: during a crossfade both elements read at once,
    // and the instant the queue advances the outgoing track is neither current nor
    // upcoming. Evicting it revokes a source still fading out — the "Crossfade failed,
    // rolling back" case. Tracking advances *before* the retention set is built, so on
    // the reconcile following a change `previousTrackId` is the track just stepped off.
    const currentTrackId = usePlayerStore.getState().currentTrack?.id ?? null;
    if (currentTrackId !== this.currentTrackId) {
      this.previousTrackId = this.currentTrackId;
      this.currentTrackId = currentTrackId;
    }

    const retained = new Set(upcomingIds);
    if (this.currentTrackId) retained.add(this.currentTrackId);
    if (this.previousTrackId) retained.add(this.previousTrackId);

    // Evict entries that are neither being read nor coming up
    for (const [trackId, entry] of this.cache) {
      if (!retained.has(trackId)) {
        this.evict(trackId, entry);
      }
    }

    // Cancel any queued downloads not in the upcoming list
    this.downloadQueue = this.downloadQueue.filter(id => upcomingIds.includes(id));

    // Queue downloads for new upcoming tracks (in priority order: N+1, N+2, N+3)
    const newDownloads: string[] = [];
    for (const trackId of upcomingIds) {
      if (!this.cache.has(trackId)) {
        newDownloads.push(trackId);
      }
    }

    if (newDownloads.length > 0) {
      // Replace queue with new priority order
      this.downloadQueue = [
        ...newDownloads,
        ...this.downloadQueue.filter(id => !newDownloads.includes(id)),
      ];
      this.processQueue();
    }
  }

  /**
   * Process the download queue sequentially (one at a time).
   */
  private async processQueue(): Promise<void> {
    if (this.isDownloading) return;
    this.isDownloading = true;

    try {
      while (this.downloadQueue.length > 0) {
        const trackId = this.downloadQueue.shift()!;

        // Skip if already cached or evicted during wait
        if (this.cache.has(trackId)) continue;

        // Skip if offline mode activated while processing
        if (useConnectivityStore.getState().offlineModeActive) break;

        // Skip if track is already downloaded for offline use
        try {
          const offline = await isTrackOffline(trackId);
          if (offline) {
            log.debug('Skipping prefetch for offline track %s', trackId);
            continue;
          }
        } catch {
          // If offline check fails, proceed with prefetch
        }

        await this.downloadTrack(trackId);
      }
    } finally {
      this.isDownloading = false;
    }
  }


  /**
   * Download a single track to the prefetch cache.
   */
  private async downloadTrack(trackId: string): Promise<void> {
    const abortController = new AbortController();
    const entry: PrefetchEntry = { trackId, status: 'downloading', abortController };
    this.cache.set(trackId, entry);

    try {
      const url = getApiUrl(`/tracks/${trackId}/stream`);
      // eslint-disable-next-line no-restricted-globals -- Prefetch with AbortController for eviction during download
      const response = await fetch(url, { signal: abortController.signal });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.arrayBuffer();

      // Check if we were evicted during download
      if (!this.cache.has(trackId) || this.cache.get(trackId) !== entry) return;

      const blob = new Blob([data], { type: response.headers.get('content-type') || 'audio/mpeg' });
      entry.blob = blob;
      entry.blobUrl = URL.createObjectURL(blob);

      entry.status = 'ready';
      entry.abortController = undefined;
      log.debug('Prefetched track %s (%.1f MB)', trackId, data.byteLength / (1024 * 1024));
    } catch (e: unknown) {
      if ((e as Error).name === 'AbortError') {
        // Expected when evicted during download
        return;
      }
      log.warn('Prefetch failed for track %s: %s', trackId, (e as Error).message);
      entry.status = 'failed';
      entry.abortController = undefined;
    }
  }

  /**
   * Evict a single entry from the cache.
   */
  private evict(trackId: string, entry?: PrefetchEntry): void {
    const e = entry || this.cache.get(trackId);
    if (!e) return;

    // Abort in-flight download
    if (e.abortController) {
      e.abortController.abort();
    }

    // Revoke blob URL (web)
    if (e.blobUrl) {
      URL.revokeObjectURL(e.blobUrl);
    }

    this.cache.delete(trackId);
  }

  /**
   * Evict all entries.
   */
  private evictAll(): void {
    for (const [trackId, entry] of this.cache) {
      this.evict(trackId, entry);
    }
    this.cache.clear();
    this.downloadQueue = [];
    // Nothing is playing once everything is evicted; stale retention would otherwise
    // keep the next session's first reconcile from clearing a dead entry.
    this.currentTrackId = null;
    this.previousTrackId = null;
  }
}

export const prefetchService = new PrefetchService();
