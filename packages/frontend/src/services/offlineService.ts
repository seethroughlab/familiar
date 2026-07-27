/**
 * Offline service for managing track downloads and offline playback.
 */
import {
  db,
  type OfflineTrack,
  type OfflineArtwork,
  type CachedTrack,
  type PartialDownload,
} from '../db';
import { getApiUrl } from '../api/base';
import { computeAlbumHash } from '../utils/albumHash';
import { trackFetchError } from '../utils/apiErrorTracker';
import { createLogger } from '../utils/logger';
import { isNativeApp } from '../utils/platform';
import { DownloadThrottle } from './playbackGate';

const log = createLogger('Offline');

export type FilesystemProvider = {
  writeFile(options: { path: string; data: string; directory?: string; recursive?: boolean }): Promise<void>;
  deleteFile(options: { path: string; directory?: string }): Promise<void>;
  getUri(options: { path: string; directory?: string }): Promise<{ uri: string }>;
};

let _filesystemProvider: FilesystemProvider | null = null;

export function registerFilesystemProvider(provider: FilesystemProvider): void {
  _filesystemProvider = provider;
}

async function getCapacitorFilesystem(): Promise<FilesystemProvider | null> {
  return _filesystemProvider;
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result as string;
      resolve(dataUrl.split(',')[1]); // strip "data:...;base64," prefix
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

function nativeTrackPath(trackId: string): string {
  return `offline-tracks/${trackId}.bin`;
}

function notifyOfflineTracksUpdated(): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent('offline-tracks-updated'));
}

/**
 * Fetch and cache track metadata from the API.
 * This ensures downloaded tracks have their metadata available for display.
 */
async function ensureTrackMetadataCached(trackId: string): Promise<CachedTrack | null> {
  // Check if already cached
  const existing = await db.cachedTracks.get(trackId);
  if (existing) {
    return existing;
  }

  // Fetch metadata from API
  try {
    // eslint-disable-next-line no-restricted-globals -- Offline track metadata fetch before download
    const response = await fetch(getApiUrl(`/tracks/${trackId}`));
    if (!response.ok) {
      trackFetchError(`/tracks/${trackId}`, 'GET', response.status, 'offline-track-metadata');
      log.warn('Could not fetch track metadata:', trackId);
      return null;
    }

    const track = await response.json();
    const cachedTrack: CachedTrack = {
      id: track.id,
      title: track.title || '',
      artist: track.artist || '',
      album: track.album || '',
      albumArtist: track.album_artist || null,
      genre: track.genre || null,
      year: track.year || null,
      durationSeconds: track.duration_seconds || null,
      trackNumber: track.track_number || null,
      discNumber: track.disc_number || null,
      cachedAt: new Date(),
    };

    await db.cachedTracks.put(cachedTrack);
    log.info('Cached track metadata:', trackId);
    return cachedTrack;
  } catch (error) {
    log.warn('Failed to cache track metadata:', trackId, error);
    return null;
  }
}

/**
 * Progress callback type for download tracking.
 */
export type DownloadProgressCallback = (progress: {
  loaded: number;
  total: number;
  percentage: number;
}) => void;

/**
 * Check if a partial download exists for a track.
 */
export async function getPartialDownload(
  trackId: string
): Promise<PartialDownload | undefined> {
  return db.partialDownloads.get(trackId);
}

/**
 * Save partial download progress.
 */
async function savePartialProgress(
  trackId: string,
  bytesDownloaded: number,
  totalBytes: number,
  chunks: Blob[]
): Promise<void> {
  await db.partialDownloads.put({
    trackId,
    bytesDownloaded,
    totalBytes,
    chunks,
    updatedAt: new Date(),
  });
}

/**
 * Clear partial download after completion or failure.
 */
async function clearPartialDownload(trackId: string): Promise<void> {
  await db.partialDownloads.delete(trackId);
}

/**
 * Fetch, stream, and store a track's audio data.
 * Extracted into its own function so `blob` goes out of scope (and becomes
 * GC-eligible) before metadata/artwork work begins, preventing two-track
 * peak-memory overlap on iOS.
 */
async function downloadAndStoreAudio(
  trackId: string,
  partial: PartialDownload | undefined,
  onProgress: DownloadProgressCallback | undefined,
  fs: FilesystemProvider | null,
  throttle: DownloadThrottle,
  onThrottleChange?: (throttling: boolean) => void,
): Promise<void> {
  const resumeFrom = partial?.bytesDownloaded || 0;
  const existingChunks: Blob[] = partial?.chunks || [];

  // Build request headers for resume
  const headers: HeadersInit = {};
  if (resumeFrom > 0) {
    headers['Range'] = `bytes=${resumeFrom}-`;
    log.info('Resuming download from byte:', resumeFrom);
  }

  // Rolling inactivity timer: aborts if no data arrives for 30s.
  // Covers both the initial connection and the streaming phase (unlike a
  // one-shot timeout that fires after headers are received).
  const INACTIVITY_TIMEOUT = 30_000;
  const controller = new AbortController();
  let activityTimer: ReturnType<typeof setTimeout> | null = null;

  function resetActivityTimer() {
    if (activityTimer) clearTimeout(activityTimer);
    activityTimer = setTimeout(() => controller.abort(), INACTIVITY_TIMEOUT);
  }

  resetActivityTimer(); // covers the initial connection

  // Fetch the audio file with progress tracking
  log.info('Fetching track:', trackId, resumeFrom > 0 ? '(resuming)' : '');
  let response: Response;
  try {
    // eslint-disable-next-line no-restricted-globals -- Resumable download with Range headers and AbortController
    response = await fetch(getApiUrl(`/tracks/${trackId}/stream`), {
      headers,
      signal: controller.signal,
    });
    // Do NOT clear the timer here — it continues covering the streaming phase
  } catch (error) {
    if (activityTimer) clearTimeout(activityTimer);
    if (error instanceof Error && error.name === 'AbortError') {
      const message = 'Download timed out - no data received';
      log.error('Download inactivity timeout:', trackId);
      window.dispatchEvent(
        new CustomEvent('offline-download-error', {
          detail: { trackId, error: message },
        })
      );
      throw new Error(message);
    }
    const message = error instanceof Error ? error.message : 'Unknown error';
    window.dispatchEvent(
      new CustomEvent('offline-download-error', {
        detail: { trackId, error: message },
      })
    );
    throw error;
  }

  // Check for successful response (200 OK or 206 Partial Content)
  if (!response.ok && response.status !== 206) {
    if (activityTimer) clearTimeout(activityTimer);
    log.error('Fetch failed:', response.status, response.statusText);
    throw new Error(`Failed to download track: ${response.statusText}`);
  }

  // Determine total size
  let total: number;
  if (response.status === 206) {
    // Partial content - parse Content-Range header
    const contentRange = response.headers.get('content-range');
    if (contentRange) {
      // Format: "bytes 1000-1999/2000" or "bytes 1000-1999/*"
      const match = contentRange.match(/bytes \d+-\d+\/(\d+|\*)/);
      total = match && match[1] !== '*' ? parseInt(match[1], 10) : 0;
    } else {
      total = partial?.totalBytes || 0;
    }
    log.info('Resume response, total size:', total);
  } else {
    // Full response
    const contentLength = response.headers.get('content-length');
    total = contentLength ? parseInt(contentLength, 10) : 0;
    log.info('Full response, content-length:', total);
  }

  let blob: Blob; // scoped here — freed when this function returns
  const contentType = response.headers.get('content-type') || 'audio/mpeg';

  // Use streaming if available
  if (response.body) {
    const reader = response.body.getReader();
    const chunks: Blob[] = [...existingChunks];
    let loaded = resumeFrom;
    let chunksSinceLastSave = 0;
    const SAVE_INTERVAL = 10; // Save progress every 10 chunks (~640KB with 64KB chunks)

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        resetActivityTimer(); // keep the timer alive as long as data flows
        chunks.push(new Blob([value]));
        loaded += value.length;
        chunksSinceLastSave++;

        // Leave most of the link free while audio is playing. Paced per chunk rather
        // than only between tracks because one file can hold the connection for ~40s —
        // far longer than a track's buffer — which is how PIPELINE_ERROR_READ (#13)
        // happened. No-ops when nothing is playing.
        await throttle.pace();
        onThrottleChange?.(throttle.throttling);

        onProgress?.({
          loaded,
          total: total || loaded,
          percentage: total > 0 ? Math.round((loaded / total) * 100) : 0,
        });

        // Periodically save progress for resume (iOS resilience)
        if (chunksSinceLastSave >= SAVE_INTERVAL && total > 0) {
          await savePartialProgress(trackId, loaded, total, chunks);
          chunksSinceLastSave = 0;
        }
      }

      if (activityTimer) clearTimeout(activityTimer);
      blob = new Blob(chunks, { type: contentType });
      chunks.length = 0; // free constituent chunk Blobs before base64 encoding
    } catch (error) {
      if (activityTimer) clearTimeout(activityTimer);
      // Save progress before throwing so we can resume later
      if (chunks.length > existingChunks.length && total > 0) {
        log.info('Saving partial progress before error:', loaded, 'bytes');
        await savePartialProgress(trackId, loaded, total, chunks);
      }
      throw error;
    }
  } else {
    if (activityTimer) clearTimeout(activityTimer);
    blob = await response.blob();
    if (existingChunks.length > 0) {
      // Combine existing chunks with new data
      blob = new Blob([...existingChunks, blob], { type: contentType });
    }
  }

  if (fs) {
    const path = nativeTrackPath(trackId);
    log.info('Storing track in Capacitor filesystem:', trackId, path);
    try {
      await fs.writeFile({
        path,
        data: await blobToBase64(blob),
        directory: 'DATA',
        recursive: true,
      });
      await db.offlineTracks.put({
        id: trackId,
        nativePath: path,
        sizeBytes: blob.size,
        cachedAt: new Date(),
      });
      notifyOfflineTracksUpdated();
    } catch (error) {
      log.error('Failed to store native offline track:', trackId, error);
      throw error;
    }
  } else {
    // Web/PWA path: store blob in IndexedDB
    const offlineTrack: OfflineTrack = {
      id: trackId,
      audio: blob,
      sizeBytes: blob.size,
      cachedAt: new Date(),
    };

    log.info('Storing track in IndexedDB:', trackId, 'size:', blob.size);

    try {
      await db.offlineTracks.put(offlineTrack);
      notifyOfflineTracksUpdated();
    } catch (error) {
      // Handle quota exceeded error
      const isQuotaError =
        error instanceof DOMException &&
        (error.name === 'QuotaExceededError' ||
          error.code === 22 ||
          // Firefox
          error.name === 'NS_ERROR_DOM_QUOTA_REACHED');

      if (isQuotaError) {
        log.error('Storage quota exceeded:', trackId);
        // Dispatch event for UI to show "Storage full" message
        window.dispatchEvent(
          new CustomEvent('offline-storage-full', {
            detail: {
              trackId,
              blobSize: blob.size,
              message: 'Storage is full. Free up space by removing downloaded tracks.',
            },
          })
        );
        // Also clear partial download since we can't store the full track
        await clearPartialDownload(trackId);
        throw new Error('Storage quota exceeded. Free up space by removing downloaded tracks.');
      }
      throw error;
    }
  }
  // blob goes out of scope here — GC-eligible before metadata/artwork work begins
}

/**
 * Download a track for offline playback with optional progress tracking.
 * Supports resuming interrupted downloads using HTTP Range requests.
 * Also downloads album artwork if track metadata is available.
 */
export async function downloadTrackForOffline(
  trackId: string,
  onProgress?: DownloadProgressCallback,
  onThrottleChange?: (throttling: boolean) => void
): Promise<void> {
  // Paces this transfer against playback. Per-download, not shared.
  const throttle = new DownloadThrottle();

  // Check if already downloaded
  const existing = await db.offlineTracks.get(trackId);
  if (existing) {
    log.info('Track already exists in IndexedDB:', trackId);
    onProgress?.({ loaded: 1, total: 1, percentage: 100 });
    return;
  }

  const partial = await getPartialDownload(trackId);
  const fs = await getCapacitorFilesystem();

  // On native iOS, Filesystem plugin should always be available — fail fast
  if (!fs && isNativeApp()) {
    log.error('downloadTrack: Filesystem plugin unavailable on native app, aborting download for %s', trackId);
    throw new Error('Native filesystem unavailable — cannot download track');
  }

  await downloadAndStoreAudio(trackId, partial, onProgress, fs, throttle, onThrottleChange);
  // blob is now out of scope — GC-eligible before the steps below

  await clearPartialDownload(trackId);
  log.info('Track stored successfully:', trackId);

  // Ensure track metadata is cached for display in Downloads view
  const trackInfo = await ensureTrackMetadataCached(trackId);

  // Also download artwork if we have track metadata
  if (trackInfo?.artist && trackInfo?.album) {
    // Best-effort artwork download - don't fail if artwork unavailable
    try {
      await downloadArtworkForOffline(trackInfo.artist, trackInfo.album);
    } catch {
      // Artwork download failed, continue without it
    }
  }
}

/**
 * Get an offline track's audio blob.
 */
export async function getOfflineTrack(trackId: string): Promise<Blob | null> {
  const track = await db.offlineTracks.get(trackId);
  return track?.audio || null;
}

export async function getOfflineTrackNativeUri(trackId: string): Promise<string | null> {
  const track = await db.offlineTracks.get(trackId);
  if (!track?.nativePath) {
    log.debug('getOfflineTrackNativeUri: no nativePath for %s', trackId);
    return null;
  }
  const fs = await getCapacitorFilesystem();
  if (!fs) {
    log.warn('getOfflineTrackNativeUri: no filesystem plugin for %s', trackId);
    return null;
  }
  try {
    const { uri } = await fs.getUri({ path: track.nativePath, directory: 'DATA' });
    return uri;
  } catch (e) {
    log.warn('getOfflineTrackNativeUri: getUri failed for %s path=%s', trackId, track.nativePath, e);
    return null;
  }
}

/**
 * Check if a track is available offline.
 */
export async function isTrackOffline(trackId: string): Promise<boolean> {
  const count = await db.offlineTracks.where('id').equals(trackId).count();
  return count > 0;
}

/**
 * Remove a track from offline storage.
 */
export async function removeOfflineTrack(trackId: string): Promise<void> {
  const track = await db.offlineTracks.get(trackId);
  if (track?.nativePath) {
    const fs = await getCapacitorFilesystem();
    if (fs) {
      try {
        await fs.deleteFile({ path: track.nativePath, directory: 'DATA' });
      } catch {
        // best-effort
      }
    }
  }
  await db.offlineTracks.delete(trackId);
  notifyOfflineTracksUpdated();
}

/**
 * Download artwork for an album for offline use.
 * Returns the hash if successful, null if artwork unavailable.
 */
export async function downloadArtworkForOffline(
  artist: string,
  album: string
): Promise<string | null> {
  const hash = await computeAlbumHash(artist, album);

  // Check if already downloaded
  const existing = await db.offlineArtwork.get(hash);
  if (existing) {
    return hash;
  }

  // Try to fetch thumb size (smaller, sufficient for offline)
  // eslint-disable-next-line no-restricted-globals -- Offline artwork blob storage
  const response = await fetch(getApiUrl(`/artwork/${hash}/thumb`));
  if (!response.ok) {
    trackFetchError(`/artwork/${hash}/thumb`, 'GET', response.status, 'offline-artwork');
    return null;
  }

  const blob = await response.blob();

  // Store in IndexedDB
  const offlineArtwork: OfflineArtwork = {
    hash,
    artwork: blob,
    cachedAt: new Date(),
  };

  await db.offlineArtwork.put(offlineArtwork);
  return hash;
}

/**
 * Get offline artwork blob by hash.
 */
export async function getOfflineArtwork(hash: string): Promise<Blob | null> {
  const artwork = await db.offlineArtwork.get(hash);
  return artwork?.artwork || null;
}

/**
 * Get offline artwork by artist/album.
 */
export async function getOfflineArtworkByAlbum(
  artist: string,
  album: string
): Promise<Blob | null> {
  const hash = await computeAlbumHash(artist, album);
  return getOfflineArtwork(hash);
}

/**
 * Check if artwork is available offline.
 */
export async function isArtworkOffline(hash: string): Promise<boolean> {
  const count = await db.offlineArtwork.where('hash').equals(hash).count();
  return count > 0;
}

/**
 * Create an object URL for offline artwork.
 */
export function createOfflineArtworkUrl(blob: Blob): string {
  return URL.createObjectURL(blob);
}

/**
 * Get all offline track IDs.
 */
export async function getOfflineTrackIds(): Promise<string[]> {
  const tracks = await db.offlineTracks.toArray();
  return tracks.map((t) => t.id);
}

/**
 * Get storage usage for offline tracks and artwork.
 */
export async function getOfflineStorageUsage(): Promise<{
  count: number;
  sizeBytes: number;
  sizeFormatted: string;
  artworkCount: number;
  artworkSizeBytes: number;
}> {
  const tracks = await db.offlineTracks.toArray();
  const artwork = await db.offlineArtwork.toArray();

  const trackSizeBytes = tracks.reduce((total, track) => total + (track.audio?.size ?? track.sizeBytes ?? 0), 0);
  const artworkSizeBytes = artwork.reduce((total, art) => total + art.artwork.size, 0);

  return {
    count: tracks.length,
    sizeBytes: trackSizeBytes + artworkSizeBytes,
    sizeFormatted: formatBytes(trackSizeBytes + artworkSizeBytes),
    artworkCount: artwork.length,
    artworkSizeBytes,
  };
}

/**
 * Clear all offline tracks and artwork.
 */
export async function clearAllOfflineTracks(): Promise<void> {
  const fs = await getCapacitorFilesystem();
  if (fs) {
    const tracks = await db.offlineTracks.toArray();
    await Promise.allSettled(
      tracks
        .filter((t) => !!t.nativePath)
        .map((t) => fs.deleteFile({ path: t.nativePath!, directory: 'DATA' }))
    );
  }
  await db.offlineTracks.clear();
  await db.offlineArtwork.clear();
  notifyOfflineTracksUpdated();
}

/**
 * Get a URL for playing an offline track.
 * Creates an object URL from the stored blob.
 */
export function createOfflineTrackUrl(blob: Blob): string {
  return URL.createObjectURL(blob);
}

/**
 * Revoke an offline track URL to free memory.
 */
export function revokeOfflineTrackUrl(url: string): void {
  URL.revokeObjectURL(url);
}

/**
 * Format bytes to human-readable string.
 */
export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 Bytes';

  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB'];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);

  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * Get storage quota information.
 */
export async function getStorageQuota(): Promise<{
  used: number;
  quota: number;
  usedFormatted: string;
  quotaFormatted: string;
  percentUsed: number;
} | null> {
  if (!navigator.storage?.estimate) {
    return null;
  }

  try {
    const estimate = await navigator.storage.estimate();
    const used = estimate.usage || 0;
    const quota = estimate.quota || 0;

    return {
      used,
      quota,
      usedFormatted: formatBytes(used),
      quotaFormatted: formatBytes(quota),
      percentUsed: quota > 0 ? Math.round((used / quota) * 100) : 0,
    };
  } catch {
    return null;
  }
}

/**
 * Get detailed info for all offline tracks including metadata from cache.
 */
export interface OfflineTrackInfo {
  id: string;
  title: string;
  artist: string;
  album: string;
  sizeBytes: number;
  sizeFormatted: string;
  cachedAt: Date;
}

export async function getOfflineTracksWithInfo(): Promise<OfflineTrackInfo[]> {
  const offlineTracks = await db.offlineTracks.toArray();
  const cachedTracks = await db.cachedTracks.toArray();

  // Create a map for fast lookup
  const trackInfoMap = new Map<string, CachedTrack>();
  cachedTracks.forEach((t) => trackInfoMap.set(t.id, t));

  // Find tracks missing metadata and try to fetch it (best-effort)
  const missingIds = offlineTracks
    .filter((t) => !trackInfoMap.has(t.id))
    .map((t) => t.id);

  if (missingIds.length > 0) {
    log.info('Fetching missing metadata for', missingIds.length, 'tracks');
    // Fetch metadata in parallel (limit concurrency to avoid overwhelming the API)
    const fetchPromises = missingIds.slice(0, 10).map(async (id) => {
      const info = await ensureTrackMetadataCached(id);
      if (info) {
        trackInfoMap.set(id, info);
      }
    });
    await Promise.allSettled(fetchPromises);
  }

  return offlineTracks.map((track) => {
    const info = trackInfoMap.get(track.id);
    const sizeBytes = track.audio?.size ?? track.sizeBytes ?? 0;
    return {
      id: track.id,
      title: info?.title || 'Unknown Title',
      artist: info?.artist || 'Unknown Artist',
      album: info?.album || 'Unknown Album',
      sizeBytes,
      sizeFormatted: formatBytes(sizeBytes),
      cachedAt: track.cachedAt,
    };
  });
}

/**
 * Download multiple tracks with overall progress.
 */
export async function downloadTracksForOffline(
  trackIds: string[],
  onProgress?: (progress: {
    currentTrack: number;
    totalTracks: number;
    currentTrackProgress: number;
    overallPercentage: number;
  }) => void
): Promise<{ succeeded: number; failed: number }> {
  let succeeded = 0;
  let failed = 0;

  for (let i = 0; i < trackIds.length; i++) {
    const trackId = trackIds[i];

    try {
      await downloadTrackForOffline(trackId, (progress) => {
        onProgress?.({
          currentTrack: i + 1,
          totalTracks: trackIds.length,
          currentTrackProgress: progress.percentage,
          overallPercentage: Math.round(
            ((i + progress.percentage / 100) / trackIds.length) * 100
          ),
        });
      });
      succeeded++;
    } catch (error) {
      log.error(`Failed to download track ${trackId}:`, error);
      failed++;
    }
  }

  return { succeeded, failed };
}
