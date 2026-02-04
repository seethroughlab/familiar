/**
 * Sync service for queuing actions when offline and syncing when back online.
 * All IndexedDB operations silently fail if IndexedDB isn't available (iOS private browsing).
 */
import { db, isIndexedDBAvailable, type PendingAction } from '../db';
import { getSelectedProfileId } from './profileService';
import { logger } from '../utils/logger';
import { showSuccess, showWarning } from '../stores/toastStore';

type ActionType = 'scrobble' | 'now_playing' | 'sync_spotify' | 'favorite_toggle';

/**
 * Queue an action to be performed when online.
 * Captures the current profile ID so actions go to the correct profile.
 */
export async function queueAction(
  type: ActionType,
  payload: unknown
): Promise<void> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) {
    console.warn('[SyncService] Cannot queue action - IndexedDB not available');
    return;
  }

  const profileId = await getSelectedProfileId();
  if (!profileId) {
    console.warn('Cannot queue action without a selected profile');
    return;
  }

  try {
    const action: PendingAction = {
      profileId,
      type,
      payload,
      createdAt: new Date(),
      retries: 0,
    };

    await db.pendingActions.add(action);
  } catch (error) {
    console.warn('[SyncService] Failed to queue action:', error);
  }
}

/**
 * Get the count of pending actions.
 */
export async function getPendingCount(): Promise<number> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return 0;

  try {
    return await db.pendingActions.count();
  } catch (error) {
    console.warn('[SyncService] Failed to get pending count:', error);
    return 0;
  }
}

/**
 * Get all pending actions.
 */
export async function getPendingActions(): Promise<PendingAction[]> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return [];

  try {
    return await db.pendingActions.orderBy('createdAt').toArray();
  } catch (error) {
    console.warn('[SyncService] Failed to get pending actions:', error);
    return [];
  }
}

/**
 * Process all pending actions.
 * Returns the number of successfully processed actions.
 */
export async function processPendingActions(): Promise<{
  processed: number;
  failed: number;
}> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return { processed: 0, failed: 0 };

  const actions = await getPendingActions();
  let processed = 0;
  let failed = 0;

  for (const action of actions) {
    try {
      await executeAction(action);
      try {
        await db.pendingActions.delete(action.id!);
      } catch (e) {
        console.warn('[SyncService] Failed to delete processed action:', e);
      }
      processed++;
    } catch (error) {
      console.error(`Failed to process action ${action.type}:`, error);

      try {
        // Increment retry count
        await db.pendingActions.update(action.id!, {
          retries: action.retries + 1,
        });

        // Remove if too many retries
        if (action.retries >= 3) {
          await db.pendingActions.delete(action.id!);
          failed++;
        }
      } catch (e) {
        console.warn('[SyncService] Failed to update action retries:', e);
      }
    }
  }

  return { processed, failed };
}

/**
 * Execute a single action.
 */
async function executeAction(action: PendingAction): Promise<void> {
  switch (action.type) {
    case 'scrobble':
      await executeScrobble(action.profileId, action.payload as ScrobblePayload);
      break;
    case 'now_playing':
      await executeNowPlaying(action.profileId, action.payload as NowPlayingPayload);
      break;
    case 'sync_spotify':
      await executeSyncSpotify(action.profileId);
      break;
    case 'favorite_toggle':
      await executeFavoriteToggle(action.profileId, action.payload as FavoriteTogglePayload);
      break;
    default:
      console.warn(`Unknown action type: ${action.type}`);
  }
}

interface ScrobblePayload {
  trackId: string;
  timestamp: string;
}

interface NowPlayingPayload {
  trackId: string;
}

interface FavoriteTogglePayload {
  trackId: string;
}

async function executeScrobble(profileId: string, payload: ScrobblePayload): Promise<void> {
  const response = await fetch('/api/v1/lastfm/scrobble', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Profile-ID': profileId,
    },
    body: JSON.stringify({
      track_id: payload.trackId,
      timestamp: payload.timestamp,
    }),
  });

  if (!response.ok) {
    throw new Error(`Scrobble failed: ${response.statusText}`);
  }
}

async function executeNowPlaying(profileId: string, payload: NowPlayingPayload): Promise<void> {
  const response = await fetch('/api/v1/lastfm/now-playing', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Profile-ID': profileId,
    },
    body: JSON.stringify({ track_id: payload.trackId }),
  });

  if (!response.ok) {
    throw new Error(`Now playing failed: ${response.statusText}`);
  }
}

async function executeSyncSpotify(profileId: string): Promise<void> {
  const response = await fetch('/api/v1/spotify/sync', {
    method: 'POST',
    headers: {
      'X-Profile-ID': profileId,
    },
  });

  if (!response.ok) {
    throw new Error(`Spotify sync failed: ${response.statusText}`);
  }
}

async function executeFavoriteToggle(profileId: string, payload: FavoriteTogglePayload): Promise<void> {
  const response = await fetch(`/api/v1/favorites/${payload.trackId}/toggle`, {
    method: 'POST',
    headers: {
      'X-Profile-ID': profileId,
    },
  });

  if (!response.ok) {
    throw new Error(`Favorite toggle failed: ${response.statusText}`);
  }
}

/**
 * Clear all pending actions.
 */
export async function clearPendingActions(): Promise<void> {
  const idbAvailable = await isIndexedDBAvailable();
  if (!idbAvailable) return;

  try {
    await db.pendingActions.clear();
  } catch (error) {
    console.warn('[SyncService] Failed to clear pending actions:', error);
  }
}

/**
 * Initialize online/offline listeners.
 * Call this once when the app starts.
 */
export function initSyncListeners(): () => void {
  const handleOnline = async () => {
    logger.log('Back online, processing pending actions...');
    const result = await processPendingActions();
    logger.log(`Processed ${result.processed} actions, ${result.failed} failed`);

    // Show toast for sync results if there were pending actions
    if (result.processed > 0 || result.failed > 0) {
      if (result.failed > 0) {
        showWarning(`Synced ${result.processed} actions, ${result.failed} failed`);
      } else {
        showSuccess(`Synced ${result.processed} pending actions`);
      }
    }
  };

  window.addEventListener('online', handleOnline);

  // Process any pending actions on startup if online
  if (navigator.onLine) {
    processPendingActions().catch(console.error);
  }

  // Return cleanup function
  return () => {
    window.removeEventListener('online', handleOnline);
  };
}
