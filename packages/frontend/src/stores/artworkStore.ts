/**
 * Artwork Store - Reactive state management for album artwork.
 *
 * Handles artwork request queueing, status polling, and reactive updates.
 * Components use this store to display artwork with automatic loading states.
 */
import { create } from 'zustand';
import { getApiUrl } from '../api/base';
import { artworkApi } from '../api/metadata';
import { createLogger } from '../utils/logger';

const log = createLogger('Artwork');

// Artwork status for each album
type ArtworkStatus = 'unknown' | 'checking' | 'pending' | 'ready' | 'missing';

interface ArtworkAlbum {
  artist: string;
  album: string;
  trackId?: string;
  hash?: string;
}

interface ArtworkState {
  // Map of "artist::album" -> status
  status: Map<string, ArtworkStatus>;

  // Map of "artist::album" -> computed hash
  hashes: Map<string, string>;

  // Set of hashes currently being polled (pending downloads)
  pendingHashes: Set<string>;

  // Polling state
  isPolling: boolean;
  pollIntervalId: ReturnType<typeof setInterval> | null;

  // Actions
  requestArtwork: (albums: ArtworkAlbum[]) => Promise<void>;
  getStatus: (artist: string, album: string) => ArtworkStatus;
  getHash: (artist: string, album: string) => string | undefined;
  getArtworkUrl: (artist: string, album: string, size: 'thumb' | 'full') => string | null;

  // Internal polling methods
  startPolling: () => void;
  stopPolling: () => void;
}

// Polling configuration
const POLL_INTERVAL_MS = 2000;

// Helper to create cache key
function cacheKey(artist: string, album: string): string {
  return `${artist || 'Unknown'}::${album || 'Unknown'}`;
}

export const useArtworkStore = create<ArtworkState>((set, get) => ({
  status: new Map(),
  hashes: new Map(),
  pendingHashes: new Set(),
  isPolling: false,
  pollIntervalId: null,

  requestArtwork: async (albums: ArtworkAlbum[]) => {
    if (albums.length === 0) return;

    const state = get();
    const newAlbums: ArtworkAlbum[] = [];

    // Filter to only albums we haven't seen yet
    for (const album of albums) {
      const key = cacheKey(album.artist, album.album);
      if (!state.status.has(key)) {
        newAlbums.push(album);
        // Mark as checking immediately
        state.status.set(key, 'checking');
      }
    }

    if (newAlbums.length === 0) return;

    // Update state to show checking status
    set({ status: new Map(state.status) });

    try {
      // Ask the server. **It tells us the key; we no longer guess it.**
      //
      // This used to compute the key locally with a JavaScript reimplementation of the
      // backend's `normalize_for_matching` and of SHA-256, kept in sync by hand — and
      // when the two disagreed the album fell through to `missing` and rendered blank,
      // silently. Since ADR-0052 the key is an `Album.id`, which no amount of hashing in
      // a browser could produce.
      const data = await artworkApi.queueBatch(
        newAlbums.map((a) => ({
          artist: a.artist,
          album: a.album,
          track_id: a.trackId,
        })),
      );

      const newHashes = new Map(get().hashes);
      const newStatus = new Map(get().status);
      const newPending = new Set(get().pendingHashes);

      for (const result of data.results ?? []) {
        const key = cacheKey(result.artist ?? '', result.album ?? '');
        newHashes.set(key, result.album_key);

        if (result.status === 'queued' || result.status === 'pending') {
          newStatus.set(key, 'pending');
          newPending.add(result.album_key);
        } else if (result.status === 'exists') {
          newStatus.set(key, 'ready');
        } else if (result.status === 'duplicate') {
          // Another item in this same batch owns it; its own result decides the status.
          continue;
        } else {
          // 'skipped' — recently failed on the server, so polling would never resolve.
          newStatus.set(key, 'missing');
        }
      }

      // A server too old to send `results` leaves every requested album unresolved
      // rather than blank-with-no-explanation.
      if (!data.results) {
        for (const album of newAlbums) {
          newStatus.set(cacheKey(album.artist, album.album), 'missing');
        }
      }

      set({ hashes: newHashes });

      set({
        status: newStatus,
        pendingHashes: newPending,
      });

      // Start polling if we have pending items
      if (newPending.size > 0) {
        get().startPolling();
      }
    } catch (error) {
      log.error('Failed to request artwork:', error);
      // Mark all as missing on error
      const newStatus = new Map(get().status);
      for (const album of newAlbums) {
        const key = cacheKey(album.artist, album.album);
        newStatus.set(key, 'missing');
      }
      set({ status: newStatus });
    }
  },

  getStatus: (artist: string, album: string): ArtworkStatus => {
    const key = cacheKey(artist, album);
    return get().status.get(key) || 'unknown';
  },

  getHash: (artist: string, album: string): string | undefined => {
    const key = cacheKey(artist, album);
    return get().hashes.get(key);
  },

  getArtworkUrl: (artist: string, album: string, size: 'thumb' | 'full'): string | null => {
    const hash = get().getHash(artist, album);
    if (!hash) return null;
    const status = get().getStatus(artist, album);
    if (status !== 'ready') return null;
    return getApiUrl(`/artwork/${hash}/${size}`);
  },

  // Internal: start polling for pending artwork
  startPolling: () => {
    const state = get();
    if (state.isPolling) return;

    const pollIntervalId = setInterval(async () => {
      const { pendingHashes, hashes, status } = get();

      if (pendingHashes.size === 0) {
        // Nothing pending, stop polling
        get().stopPolling();
        return;
      }

      try {
        const data = await artworkApi.statusBatch(Array.from(pendingHashes));

        // Update status for each hash
        const newStatus = new Map(status);
        const newPending = new Set(pendingHashes);
        const failedSet = new Set(data.failed || []);

        // Find which albums correspond to which hashes
        for (const [key, hash] of hashes.entries()) {
          if (pendingHashes.has(hash)) {
            const exists = data.status[hash];
            if (exists) {
              newStatus.set(key, 'ready');
              newPending.delete(hash);
            } else if (failedSet.has(hash)) {
              // Fetch failed - mark as missing and stop polling for it
              newStatus.set(key, 'missing');
              newPending.delete(hash);
            }
            // If not exists and not failed, keep as pending (still downloading)
          }
        }

        set({
          status: newStatus,
          pendingHashes: newPending,
        });

        // Stop polling if nothing pending
        if (newPending.size === 0) {
          get().stopPolling();
        }
      } catch (error) {
        log.error('Failed to poll artwork status:', error);
      }
    }, POLL_INTERVAL_MS);

    set({ isPolling: true, pollIntervalId });
  },

  // Internal: stop polling
  stopPolling: () => {
    const { pollIntervalId } = get();
    if (pollIntervalId) {
      clearInterval(pollIntervalId);
    }
    set({ isPolling: false, pollIntervalId: null });
  },
}));
