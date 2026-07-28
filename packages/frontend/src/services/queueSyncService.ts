/**
 * Keeps the server's copy of the playback queue in step with this device (ADR-0003).
 *
 * The local replica is authoritative for playback: every mutation applies immediately and
 * nothing here can block it. This service only observes the result and pushes it, through
 * the same `pendingActions` outbox everything else uses, so an offline edit is delivered
 * on reconnect rather than lost.
 *
 * Three things are deliberately *not* done the obvious way:
 *
 * - **It does not hook `persistCombinedState`,** which is the single funnel every queue
 *   mutation already flows through and would be the natural seam. That funnel also fires
 *   on every `setCurrentTime` tick, throttled only to 500ms, so hanging sync off it would
 *   mean a request twice a second for the whole of playback. Structural changes and
 *   position changes get separate cadences instead.
 *
 * - **The reservoir is sent only when it changes.** For a full library it is ~26k UUIDs
 *   (~1 MB) and it changes only on `setLazyQueue`, `toggleShuffle` and a refill; every
 *   other write references it by hash.
 *
 * - **What is sent is always the *logical* queue**, never the offline-narrowed one. A
 *   device that uploaded its narrowed queue would overwrite every other device's copy
 *   with whatever it happened to have downloaded.
 */
import { useQueueStore } from '../player/queueStore';
import { usePlaybackStore } from '../player/playbackStore';
import { useConnectivityStore } from '../stores/connectivityStore';
import { useQueueSyncStore } from '../stores/queueSyncStore';
import { queueApi, type PlaybackSessionResponse, type PlaybackSessionWrite } from '../api/queue';
import { fetchTracksBatched } from '../player/persistence';
import { processPendingActions, queueAction, registerQueueSyncHandlers } from './syncService';
import { getSelectedProfileId } from './profileService';
import { createLogger } from '../utils/logger';

const log = createLogger('QueueSync');

/** Structural changes settle before being sent — a drag-reorder emits many in a row. */
const STRUCTURAL_DEBOUNCE_MS = 2_000;
/** Position is coarse on purpose: it only needs to be roughly right for a handoff. */
const POSITION_INTERVAL_MS = 15_000;

/**
 * Per-device opt-in, so the rollout can be staged before the native client depends on it
 * (ADR-0003 point 7). Read through a function rather than cached at module load, so
 * toggling it in Settings takes effect without a reload.
 */
export function isQueueSyncEnabled(): boolean {
  return useQueueSyncStore.getState().enabled;
}

/** What the server last told us it holds. Drives the version on the next write. */
let serverVersion = 0;
let serverUpdatedAt: string | null = null;
let serverReservoirHash: string | null = null;
/** Set when a write was rejected for naming a reservoir hash the server does not have. */
let mustResendReservoir = false;
/** The reservoir array last sent, compared by reference like the persistence layer does. */
let lastSentReservoir: string[] | null = null;

/**
 * A cheap signature of everything except position.
 *
 * Compared as a string rather than deep-equalling the queue: the point is to notice that
 * *something* structural moved, and building this on every store notification has to stay
 * cheaper than the sync it guards.
 */
function structuralSignature(): string {
  const q = useQueueStore.getState();
  const p = usePlaybackStore.getState();
  const logical = q.logicalTrackIds;
  const ids = logical ?? q.queue.map((item) => item.track.id);
  return [
    ids.length,
    ids.length > 0 ? ids[0] : '',
    ids.length > 0 ? ids[ids.length - 1] : '',
    logical ? q.logicalIndex : q.queueIndex,
    q.shuffleIndex,
    q.lazyQueueIndex,
    q.queueSource?.type ?? '',
    q.queueSource?.id ?? '',
    p.shuffle,
    p.repeat,
    p.consume,
  ].join('|');
}

/**
 * Build the write payload from the *logical* queue.
 *
 * While offline the store's `queue` is narrowed to downloaded tracks and `logicalTrackIds`
 * holds what it was; using the narrowed one here is the single worst thing this service
 * could do, so the choice is made in one place.
 */
async function buildPayload(): Promise<PlaybackSessionWrite> {
  const q = useQueueStore.getState();
  const p = usePlaybackStore.getState();

  const narrowed = q.logicalTrackIds !== null;
  const trackIds = q.logicalTrackIds ?? q.queue.map((item) => item.track.id);
  const cursor = narrowed ? q.logicalIndex : q.queueIndex;

  // Shuffle order indexes into the queue, so it is only meaningful alongside the queue it
  // was built for. While narrowed the two disagree, and sending it would scramble the
  // order on whichever device adopts it.
  const shuffleOrder = narrowed ? [] : q.shuffleOrder;
  const shuffleIndex = narrowed ? -1 : q.shuffleIndex;

  const reservoirChanged = q.lazyQueueIds !== lastSentReservoir || mustResendReservoir;

  return {
    track_ids: trackIds,
    cursor,
    shuffle_order: shuffleOrder,
    shuffle_index: shuffleIndex,
    shuffle: p.shuffle,
    repeat: p.repeat,
    consume: p.consume,
    queue_source: q.queueSource,
    // Omitted when unchanged — the server fills it in from `reservoir_hash`.
    reservoir_ids: reservoirChanged ? q.lazyQueueIds : undefined,
    reservoir_cursor: q.lazyQueueIndex,
    reservoir_hash: reservoirChanged ? undefined : serverReservoirHash,
    position_seconds: p.currentTime,
    version: serverVersion,
    updated_at: new Date().toISOString(),
  };
}

/** Queue a write. Coalesced by the outbox, so calling this often is cheap. */
async function pushSession(): Promise<void> {
  if (!isQueueSyncEnabled()) return;
  const profileId = await getSelectedProfileId();
  if (!profileId) return;

  const payload = await buildPayload();
  // Remember what this payload claims, so the next one can reference it by hash. The
  // outbox may coalesce this away before it is sent, which is fine: the replacement
  // carries the same reservoir.
  if (payload.reservoir_ids !== undefined) {
    lastSentReservoir = useQueueStore.getState().lazyQueueIds;
    mustResendReservoir = false;
  }

  await queueAction('queue_sync', payload);

  // Deliver immediately when online; otherwise it waits in the outbox for reconnect.
  if (!useConnectivityStore.getState().offlineModeActive) {
    processPendingActions().catch((error) => log.warn('Queue sync drain failed:', error));
  }
}

/**
 * Adopt a session the server holds, replacing whatever this device has.
 *
 * `reason: 'system'` matters: without it the queue store would report the track change as
 * a listener skip and ADR-0004 would log a phantom negative signal for whatever was
 * playing.
 */
async function adopt(session: PlaybackSessionResponse): Promise<void> {
  if (session.track_ids.length === 0) return;

  const tracks = await fetchTracksBatched(session.track_ids);
  if (tracks.length === 0) return;

  const store = useQueueStore.getState();
  const startIndex = Math.max(0, Math.min(session.cursor, tracks.length - 1));

  store.setQueue(tracks, startIndex, session.queue_source ?? undefined, {
    preservePlaybackState: true,
    reason: 'system',
  });
  if (session.reservoir_ids && session.reservoir_ids.length > 0) {
    useQueueStore.setState({
      lazyQueueIds: session.reservoir_ids,
      lazyQueueIndex: session.reservoir_cursor,
    });
  }
  usePlaybackStore.setState({
    shuffle: session.shuffle,
    repeat: session.repeat,
    consume: session.consume,
    currentTime: session.position_seconds,
    // The display alone is not enough: the element loads at 0 and the first `timeUpdate`
    // overwrites the number, so the position has to be applied to the engine once the
    // track is ready. `useAudioEngine` consumes this on `canplay`.
    _pendingSeekSeconds: session.position_seconds > 0 ? session.position_seconds : null,
  });
  if (session.shuffle_order.length > 0) {
    useQueueStore.setState({
      shuffleOrder: session.shuffle_order,
      shuffleIndex: session.shuffle_index,
    });
  }
  noteServerState(session);
  log.info('Adopted the server session', { tracks: tracks.length, version: session.version });
}

function noteServerState(session: PlaybackSessionResponse): void {
  serverVersion = session.version;
  serverUpdatedAt = session.updated_at;
  serverReservoirHash = session.reservoir_hash ?? null;
}

/**
 * Reconcile with the server once, at startup.
 *
 * Hydration from IndexedDB has already happened by this point and is what the listener
 * sees; this only replaces it when the server's copy is genuinely newer, which is the
 * handoff case. A local queue that is newer is pushed up instead.
 */
export async function reconcileWithServer(): Promise<void> {
  if (!isQueueSyncEnabled()) return;
  if (useConnectivityStore.getState().offlineModeActive) return;

  try {
    const session = await queueApi.getSession();
    noteServerState(session);

    const localHasQueue = useQueueStore.getState().queue.length > 0;
    if (session.track_ids.length === 0) {
      if (localHasQueue) await pushSession();
      return;
    }
    if (!localHasQueue) {
      await adopt(session);
      return;
    }

    // Both sides have a queue. The server's own timestamp decides, matching the conflict
    // rule the server applies to writes.
    const localTime = lastLocalChange;
    if (localTime === null || new Date(session.updated_at) > localTime) {
      await adopt(session);
    } else {
      await pushSession();
    }
  } catch (error) {
    log.warn('Could not reconcile the queue with the server:', error);
  }
}

/** When this device last changed the queue, for the startup comparison above. */
let lastLocalChange: Date | null = null;

let started = false;

/**
 * Start observing. Idempotent, and safe to call when the flag is off — it simply does
 * nothing, so callers need no conditional.
 */
export function initQueueSync(): () => void {
  if (started || !isQueueSyncEnabled()) return () => {};
  started = true;

  registerQueueSyncHandlers({
    onSessionWritten: (session) => {
      noteServerState(session);
      if (session.superseded) {
        // This write lost a conflict: another device had a newer queue. Take theirs
        // rather than fighting over it — the losing queue is archived server-side.
        adopt(session).catch((error) => log.warn('Failed to adopt the winning session:', error));
      }
    },
    onReservoirRejected: () => {
      mustResendReservoir = true;
      lastSentReservoir = null;
      pushSession().catch((error) => log.warn('Reservoir resend failed:', error));
    },
  });

  let signature = structuralSignature();
  let structuralTimer: ReturnType<typeof setTimeout> | null = null;

  const onStoreChange = () => {
    const next = structuralSignature();
    // Position ticks dominate store notifications and are not in the signature, so this
    // is the guard that keeps a 500ms tick from becoming a request.
    if (next === signature) return;
    signature = next;
    lastLocalChange = new Date();

    if (structuralTimer) clearTimeout(structuralTimer);
    structuralTimer = setTimeout(() => {
      structuralTimer = null;
      pushSession().catch((error) => log.warn('Queue sync failed:', error));
    }, STRUCTURAL_DEBOUNCE_MS);
  };

  const unsubscribeQueue = useQueueStore.subscribe(onStoreChange);
  // playbackStore holds shuffle/repeat/consume, which are part of the queue's behaviour
  // even though they live in the other store.
  const unsubscribePlayback = usePlaybackStore.subscribe(onStoreChange);

  // Position on its own slow clock, and only while something is actually playing —
  // otherwise a paused tab would write every 15 seconds forever.
  const positionTimer = setInterval(() => {
    if (!usePlaybackStore.getState().isPlaying) return;
    pushSession().catch((error) => log.warn('Position sync failed:', error));
  }, POSITION_INTERVAL_MS);

  return () => {
    started = false;
    if (structuralTimer) clearTimeout(structuralTimer);
    clearInterval(positionTimer);
    unsubscribeQueue();
    unsubscribePlayback();
  };
}

/** Test seam: forget everything learned about the server. */
export function _resetQueueSyncState(): void {
  started = false;
  serverVersion = 0;
  serverUpdatedAt = null;
  serverReservoirHash = null;
  mustResendReservoir = false;
  lastSentReservoir = null;
  lastLocalChange = null;
}

/** Exposed for tests and diagnostics. */
export function _queueSyncState() {
  return { serverVersion, serverUpdatedAt, serverReservoirHash, mustResendReservoir };
}
