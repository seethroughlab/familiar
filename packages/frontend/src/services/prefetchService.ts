/**
 * PrefetchService — downloads upcoming tracks ahead of playback.
 *
 * Subscribes to playerStore queue/index changes and downloads the next N tracks
 * in the background so they're already local when the engine needs them.
 *
 * Web: stores Blobs in memory, returns blob URLs.
 * iOS (Capacitor): writes to filesystem at prefetch-tracks/{trackId}.bin.
 */
import { usePlayerStore } from '../player/playerStore';
import { useConnectivityStore } from '../stores/connectivityStore';
import { isTrackOffline } from './offlineService';
import { DownloadThrottle } from './playbackGate';
import { getApiUrl } from '../api/base';
import { isNativeApp } from '../utils/platform';
import { createLogger } from '../utils/logger';

const log = createLogger('Prefetch');

const PREFETCH_COUNT = 3;

type PrefetchStatus = 'downloading' | 'ready' | 'failed';

interface PrefetchEntry {
  trackId: string;
  status: PrefetchStatus;
  blobUrl?: string;
  nativeUri?: string;
  abortController?: AbortController;
  blob?: Blob; // hold reference to prevent GC on web
}

type CapacitorFilesystemPlugin = {
  writeFile(options: { path: string; data: string; directory?: string; recursive?: boolean }): Promise<void>;
  deleteFile(options: { path: string; directory?: string }): Promise<void>;
  getUri(options: { path: string; directory?: string }): Promise<{ uri: string }>;
};

function nativePrefetchPath(trackId: string): string {
  return `prefetch-tracks/${trackId}.bin`;
}

async function getCapacitorFilesystem(): Promise<CapacitorFilesystemPlugin | null> {
  if (!isNativeApp()) return null;
  const cap = (window as unknown as { Capacitor?: { Plugins?: Record<string, unknown> } }).Capacitor;
  const fs = cap?.Plugins?.Filesystem as CapacitorFilesystemPlugin | undefined;
  return fs ?? null;
}

function toBase64(data: ArrayBuffer): string {
  const bytes = new Uint8Array(data);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

class PrefetchService {
  private cache = new Map<string, PrefetchEntry>();
  private unsubscribe: (() => void) | null = null;
  private downloadQueue: string[] = [];
  private isDownloading = false;

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

    const url = entry.blobUrl || entry.nativeUri;
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

    // Evict entries not in the upcoming list
    for (const [trackId, entry] of this.cache) {
      if (!upcomingIds.includes(trackId)) {
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
   * Read a response body while leaving bandwidth for the track that is playing.
   *
   * `response.arrayBuffer()` pulls the whole file as fast as the link allows, which is
   * how the prefetcher — the thing that exists to make playback smooth — became the
   * thing breaking it. Measured: 10-24 MB prefetches saturating a ~850 KB/s link while
   * the playing track needed 40 KB/s, producing PIPELINE_ERROR_READ and tracks that
   * ended a second after starting (issue #13).
   *
   * Chunked so `DownloadThrottle` can pace it, exactly as the offline download queue
   * does. Falls back to `arrayBuffer()` if the body isn't a readable stream.
   */
  private async readThrottled(response: Response, signal: AbortSignal): Promise<ArrayBuffer> {
    if (!response.body) return response.arrayBuffer();

    const reader = response.body.getReader();
    const throttle = new DownloadThrottle();
    const chunks: Uint8Array[] = [];
    let total = 0;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      total += value.length;
      // No-op when nothing is playing, so an idle device prefetches at full speed.
      await throttle.pace(signal);
      if (signal.aborted) {
        // Evicted mid-transfer. Release the connection rather than finishing a
        // download whose result is already going to be discarded.
        await reader.cancel().catch(() => {});
        throw new DOMException('Prefetch aborted', 'AbortError');
      }
    }

    const out = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) {
      out.set(chunk, offset);
      offset += chunk.length;
    }
    return out.buffer;
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

      const data = await this.readThrottled(response, abortController.signal);

      // Check if we were evicted during download. A throttled transfer takes longer,
      // which widens this window rather than narrowing it.
      if (!this.cache.has(trackId) || this.cache.get(trackId) !== entry) return;

      if (isNativeApp()) {
        // iOS: write to Capacitor filesystem
        const fs = await getCapacitorFilesystem();
        if (fs) {
          const base64 = toBase64(data);
          await fs.writeFile({
            path: nativePrefetchPath(trackId),
            data: base64,
            directory: 'CACHE',
            recursive: true,
          });
          const { uri } = await fs.getUri({
            path: nativePrefetchPath(trackId),
            directory: 'CACHE',
          });
          entry.nativeUri = uri;
        }
      } else {
        // Web: create blob URL
        const blob = new Blob([data], { type: response.headers.get('content-type') || 'audio/mpeg' });
        entry.blob = blob;
        entry.blobUrl = URL.createObjectURL(blob);
      }

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

    // Delete temp file (iOS) — fire and forget
    if (e.nativeUri) {
      getCapacitorFilesystem().then(fs => {
        fs?.deleteFile({ path: nativePrefetchPath(trackId), directory: 'CACHE' }).catch(() => {});
      }).catch(() => {});
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
  }
}

export const prefetchService = new PrefetchService();
