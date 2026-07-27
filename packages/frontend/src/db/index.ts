/**
 * Dexie database for local device storage.
 *
 * Stores device profile info, chat history, and offline data.
 */
import Dexie, { type Table } from 'dexie';
import { createLogger } from '../utils/logger';

const log = createLogger('DB');

export interface DeviceProfile {
  id: 'device-profile'; // Single record with fixed ID
  profileId: string; // UUID from backend
  deviceId: string; // UUID for this device
  createdAt: Date;
}

// Chat types
export interface ChatToolCall {
  name: string;
  input: Record<string, unknown>;
  result?: Record<string, unknown>;
  status: 'running' | 'complete';
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: ChatToolCall[];
  timestamp: Date;
}

export interface ChatSession {
  id: string; // UUID
  profileId: string; // UUID from backend
  title: string; // Auto-generated from first user message
  messages: ChatMessage[];
  createdAt: Date;
  updatedAt: Date;
}

// PWA Offline types
export interface CachedTrack {
  id: string; // Track UUID
  title: string;
  artist: string;
  album: string;
  albumArtist: string | null;
  genre: string | null;
  year: number | null;
  durationSeconds: number | null;
  trackNumber: number | null;
  discNumber: number | null;
  cachedAt: Date;
}

export interface OfflineTrack {
  id: string; // Track UUID
  audio?: Blob; // Web/PWA path
  nativePath?: string; // Capacitor native file path
  sizeBytes?: number; // Native file size when blob is not stored
  cachedAt: Date;
}

export interface OfflineArtwork {
  hash: string; // Album hash (from computeAlbumHash)
  artwork: Blob;
  cachedAt: Date;
}

export interface PendingAction {
  id?: number; // Auto-increment
  profileId: string; // Profile that queued this action
  // NOTE: mirrored by `ActionType` in services/syncService.ts — keep both in step.
  // Adding a value needs no Dexie version bump: `type` is indexed, but an IndexedDB
  // index constrains the key path, not the value domain, and `payload` is unindexed.
  type: 'scrobble' | 'now_playing' | 'favorite_toggle' | 'listen_event';
  payload: unknown;
  createdAt: Date;
  retries: number;
}

// Cached profile for offline support
export interface CachedProfile {
  id: string;
  name: string;
  color: string | null;
  avatar_url: string | null;
  has_lastfm: boolean;
  cachedAt: Date;
}

// Cached playlist for offline support
export interface CachedPlaylist {
  id: string;
  name: string;
  description: string | null;
  is_auto_generated: boolean;
  generation_prompt: string | null;
  track_ids: string[];
  track_count: number;
  cachedAt: Date;
}

// Cached smart playlist for offline support
export interface CachedSmartPlaylist {
  id: string;
  name: string;
  description: string | null;
  rules: Array<{
    field: string;
    operator: string;
    value?: unknown;
  }>;
  match_mode: 'all' | 'any';
  order_by: string;
  order_direction: 'asc' | 'desc';
  max_tracks: number | null;
  track_ids: string[];
  cached_track_count: number;
  last_refreshed_at: string | null;
  cachedAt: Date;
}

// Cached favorites for offline support
export interface CachedFavorites {
  profileId: string;
  trackIds: string[];
  cachedAt: Date;
}

// Download queue persistence for iOS resilience
export interface PersistedDownloadJob {
  id: string; // Job ID (e.g., "playlist-123")
  type: 'playlist' | 'smart-playlist' | 'album';
  name: string;
  trackIds: string[];
  completedIds: string[];
  failedIds: string[];
  status: 'queued' | 'downloading' | 'paused' | 'completed' | 'failed';
  startedAt: Date;
  updatedAt: Date;
}

// Remote log entry for frontend-to-backend log shipping
export interface RemoteLogEntry {
  id?: number; // Auto-increment
  level: string;
  namespace: string;
  message: string; // Serialized args
  context: {
    url: string;
    userAgent: string;
    profileId: string | null;
  };
  createdAt: Date;
}

// Track partial download progress for resume support
export interface PartialDownload {
  trackId: string;
  bytesDownloaded: number;
  totalBytes: number;
  chunks: Blob[]; // Stored chunks for resume
  updatedAt: Date;
}

// Player state persistence
export interface PersistedPlayerState {
  id: string; // Profile ID (was fixed 'player-state', now per-profile)
  volume: number;
  shuffle: boolean;
  repeat: 'off' | 'all' | 'one';
  queueTrackIds: string[]; // Just store track IDs, not full objects
  queueIndex: number;
  currentTrackId: string | null;
  shuffleOrder: number[]; // Randomized queue indices when shuffle is on
  shuffleIndex: number; // Current position in shuffleOrder (-1 when off)
  currentTime: number; // Playback position in seconds
  consume?: boolean; // Remove tracks from queue after playing
  updatedAt: Date;
}

// Track IndexedDB availability (can be disabled on iOS private browsing)
let indexedDBAvailable: boolean | null = null;

/**
 * Check if IndexedDB is available.
 * Returns false on iOS private browsing or when IndexedDB is disabled.
 */
export async function isIndexedDBAvailable(): Promise<boolean> {
  if (indexedDBAvailable !== null) {
    return indexedDBAvailable;
  }

  try {
    // Test if IndexedDB works (fails in private browsing on iOS)
    const testDB = indexedDB.open('__idb_test__');
    await new Promise<void>((resolve, reject) => {
      testDB.onerror = () => reject(new Error('IndexedDB not available'));
      testDB.onsuccess = () => {
        testDB.result.close();
        indexedDB.deleteDatabase('__idb_test__');
        resolve();
      };
      // Timeout for iOS which can hang instead of error
      setTimeout(() => reject(new Error('IndexedDB timeout')), 1000);
    });
    indexedDBAvailable = true;
    return true;
  } catch {
    log.warn('IndexedDB not available (private browsing or disabled)');
    indexedDBAvailable = false;
    return false;
  }
}

export class FamiliarDB extends Dexie {
  deviceProfile!: Table<DeviceProfile>;
  chatSessions!: Table<ChatSession>;
  cachedTracks!: Table<CachedTrack>;
  offlineTracks!: Table<OfflineTrack>;
  offlineArtwork!: Table<OfflineArtwork>;
  pendingActions!: Table<PendingAction>;
  playerState!: Table<PersistedPlayerState>;
  cachedProfiles!: Table<CachedProfile>;
  cachedPlaylists!: Table<CachedPlaylist>;
  cachedSmartPlaylists!: Table<CachedSmartPlaylist>;
  cachedFavorites!: Table<CachedFavorites>;
  downloadQueue!: Table<PersistedDownloadJob>;
  partialDownloads!: Table<PartialDownload>;
  remoteLogs!: Table<RemoteLogEntry>;

  constructor() {
    super('FamiliarDB');

    this.version(1).stores({
      deviceProfile: 'id',
    });

    // Version 2: Add chat history
    this.version(2).stores({
      deviceProfile: 'id',
      chatSessions: 'id, profileId, updatedAt',
    });

    // Version 3: Add PWA offline support
    this.version(3).stores({
      deviceProfile: 'id',
      chatSessions: 'id, profileId, updatedAt',
      cachedTracks: 'id, artist, album, cachedAt',
      offlineTracks: 'id, cachedAt',
      pendingActions: '++id, type, createdAt',
    });

    // Version 4: Add player state persistence
    this.version(4).stores({
      deviceProfile: 'id',
      chatSessions: 'id, profileId, updatedAt',
      cachedTracks: 'id, artist, album, cachedAt',
      offlineTracks: 'id, cachedAt',
      pendingActions: '++id, type, createdAt',
      playerState: 'id',
    });

    // Version 5: Add profile context to pendingActions and playerState
    this.version(5).stores({
      deviceProfile: 'id',
      chatSessions: 'id, profileId, updatedAt',
      cachedTracks: 'id, artist, album, cachedAt',
      offlineTracks: 'id, cachedAt',
      pendingActions: '++id, profileId, type, createdAt',
      playerState: 'id', // id is now profileId
    });

    // Version 6: Add offline artwork storage
    this.version(6).stores({
      deviceProfile: 'id',
      chatSessions: 'id, profileId, updatedAt',
      cachedTracks: 'id, artist, album, cachedAt',
      offlineTracks: 'id, cachedAt',
      offlineArtwork: 'hash, cachedAt',
      pendingActions: '++id, profileId, type, createdAt',
      playerState: 'id',
    });

    // Version 7: Add cached profiles for offline support
    this.version(7).stores({
      deviceProfile: 'id',
      chatSessions: 'id, profileId, updatedAt',
      cachedTracks: 'id, artist, album, cachedAt',
      offlineTracks: 'id, cachedAt',
      offlineArtwork: 'hash, cachedAt',
      pendingActions: '++id, profileId, type, createdAt',
      playerState: 'id',
      cachedProfiles: 'id, cachedAt',
    });

    // Version 8: Add cached playlists, smart playlists, and favorites for offline support
    this.version(8).stores({
      deviceProfile: 'id',
      chatSessions: 'id, profileId, updatedAt',
      cachedTracks: 'id, artist, album, cachedAt',
      offlineTracks: 'id, cachedAt',
      offlineArtwork: 'hash, cachedAt',
      pendingActions: '++id, profileId, type, createdAt',
      playerState: 'id',
      cachedProfiles: 'id, cachedAt',
      cachedPlaylists: 'id, cachedAt',
      cachedSmartPlaylists: 'id, cachedAt',
      cachedFavorites: 'profileId, cachedAt',
    });

    // Version 9: Add download queue persistence and partial download tracking for iOS resilience
    this.version(9).stores({
      deviceProfile: 'id',
      chatSessions: 'id, profileId, updatedAt',
      cachedTracks: 'id, artist, album, cachedAt',
      offlineTracks: 'id, cachedAt',
      offlineArtwork: 'hash, cachedAt',
      pendingActions: '++id, profileId, type, createdAt',
      playerState: 'id',
      cachedProfiles: 'id, cachedAt',
      cachedPlaylists: 'id, cachedAt',
      cachedSmartPlaylists: 'id, cachedAt',
      cachedFavorites: 'profileId, cachedAt',
      downloadQueue: 'id, status, updatedAt',
      partialDownloads: 'trackId, updatedAt',
    });

    // Version 10: Add remote logs for frontend-to-backend log shipping
    this.version(10).stores({
      deviceProfile: 'id',
      chatSessions: 'id, profileId, updatedAt',
      cachedTracks: 'id, artist, album, cachedAt',
      offlineTracks: 'id, cachedAt',
      offlineArtwork: 'hash, cachedAt',
      pendingActions: '++id, profileId, type, createdAt',
      playerState: 'id',
      cachedProfiles: 'id, cachedAt',
      cachedPlaylists: 'id, cachedAt',
      cachedSmartPlaylists: 'id, cachedAt',
      cachedFavorites: 'profileId, cachedAt',
      downloadQueue: 'id, status, updatedAt',
      partialDownloads: 'trackId, updatedAt',
      remoteLogs: '++id, level, createdAt',
    });
  }
}

// Lazy singleton – defers Dexie/IndexedDB initialization until first access.
// On iOS (WKWebView) IndexedDB may not be ready at module evaluation time,
// so constructing FamiliarDB() eagerly causes a black screen on launch.
let _db: FamiliarDB | undefined;
export const db = new Proxy({} as FamiliarDB, {
  get(_target, prop, receiver) {
    if (!_db) _db = new FamiliarDB();
    return Reflect.get(_db, prop, receiver);
  },
  set(_target, prop, value) {
    if (!_db) _db = new FamiliarDB();
    return Reflect.set(_db, prop, value);
  },
});
