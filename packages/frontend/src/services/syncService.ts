/**
 * Sync service for queuing actions when offline and syncing when back online.
 * All IndexedDB operations silently fail if IndexedDB isn't available (iOS private browsing).
 */
import { db, isIndexedDBAvailable, type PendingAction } from '../db';
import { lastfmApi } from '../api/integrations';
import { favoritesApi, playTrackingApi } from '../api/profiles';
import type { ListenEventBody } from '../api/profiles';
import { useConnectivityStore } from '../stores/connectivityStore';
import { getSelectedProfileId } from './profileService';
import { createLogger } from '../utils/logger';
const log = createLogger('SyncService');

// Mirrored by `PendingAction.type` in ../db — keep both in step.
type ActionType = 'scrobble' | 'now_playing' | 'favorite_toggle' | 'listen_event';

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
    log.warn('Cannot queue action - IndexedDB not available');
    return;
  }

  const profileId = await getSelectedProfileId();
  if (!profileId) {
    log.warn('Cannot queue action without a selected profile');
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
    log.warn('Failed to queue action:', error);
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
    log.warn('Failed to get pending count:', error);
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
    log.warn('Failed to get pending actions:', error);
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
        log.warn('Failed to delete processed action:', e);
      }
      processed++;
    } catch (error) {
      log.error(`Failed to process action ${action.type}:`, error);

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
        log.warn('Failed to update action retries:', e);
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
    case 'favorite_toggle':
      await executeFavoriteToggle(action.profileId, action.payload as FavoriteTogglePayload);
      break;
    case 'listen_event':
      await executeListenEvent(action.profileId, action.payload as ListenEventPayload);
      break;
    default:
      log.warn(`Unknown action type: ${action.type}`);
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

/** A listening event that could not be delivered when it happened (ADR-0004). */
interface ListenEventPayload {
  trackId: string;
  kind: 'played' | 'skipped' | 'rejected';
  body: ListenEventBody;
  /** Only meaningful for `played`, which also bumps the play aggregate. */
  durationSeconds?: number;
}

async function executeScrobble(_profileId: string, payload: ScrobblePayload): Promise<void> {
  await lastfmApi.scrobble(payload.trackId, parseInt(payload.timestamp));
}

async function executeNowPlaying(_profileId: string, payload: NowPlayingPayload): Promise<void> {
  await lastfmApi.updateNowPlaying(payload.trackId);
}

async function executeFavoriteToggle(_profileId: string, payload: FavoriteTogglePayload): Promise<void> {
  await favoritesApi.toggle(payload.trackId);
}

async function executeListenEvent(_profileId: string, payload: ListenEventPayload): Promise<void> {
  const { trackId, kind, body } = payload;
  if (kind === 'played') {
    await playTrackingApi.recordPlay(trackId, payload.durationSeconds, {
      track_duration: body.track_duration,
      completion_ratio: body.completion_ratio,
      context: body.context,
      source_track_id: body.source_track_id,
    });
    return;
  }
  if (kind === 'rejected') {
    await playTrackingApi.recordRejection(trackId, body);
    return;
  }
  await playTrackingApi.recordSkip(trackId, body);
}

/**
 * Send a listening event, falling back to the outbox if it cannot be delivered.
 *
 * Unlike `useFavorites`, which only pre-checks `isOffline`, this also queues on a failed
 * request. A 500 or a connection dropped mid-flight would otherwise discard taste data
 * silently — and offline listening, where skipping is most frequent, is exactly when
 * delivery is least reliable (ADR-0004 point 7).
 *
 * Never throws: a failed listening event must not disturb playback.
 */
export async function deliverListenEvent(
  trackId: string,
  kind: 'played' | 'skipped' | 'rejected',
  body: ListenEventBody = {},
  durationSeconds?: number,
): Promise<void> {
  const payload: ListenEventPayload = { trackId, kind, body, durationSeconds };

  // Already offline — skip the request that is certain to fail.
  if (useConnectivityStore.getState().offlineModeActive) {
    await queueAction('listen_event', payload);
    return;
  }

  try {
    await executeListenEvent('', payload);
  } catch (error) {
    log.warn('Listening event failed, queueing for retry:', error);
    await queueAction('listen_event', payload);
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
    log.warn('Failed to clear pending actions:', error);
  }
}

/**
 * Initialize online/offline listeners.
 * Call this once when the app starts.
 */
export interface SyncNotifications {
  onSuccess: (msg: string) => void;
  onWarning: (msg: string) => void;
}

export function initSyncListeners(notify?: SyncNotifications): () => void {
  const handleOnline = async () => {
    log.info('Back online, processing pending actions...');
    const result = await processPendingActions();
    log.info(`Processed ${result.processed} actions, ${result.failed} failed`);

    // Show toast for sync results if there were pending actions
    if (result.processed > 0 || result.failed > 0) {
      if (result.failed > 0) {
        notify?.onWarning(`Synced ${result.processed} actions, ${result.failed} failed`);
      } else {
        notify?.onSuccess(`Synced ${result.processed} pending actions`);
      }
    }
  };

  window.addEventListener('online', handleOnline);

  // Process any pending actions on startup if online
  if (useConnectivityStore.getState().browserOnline) {
    processPendingActions().catch(log.error);
  }

  // Return cleanup function
  return () => {
    window.removeEventListener('online', handleOnline);
  };
}
