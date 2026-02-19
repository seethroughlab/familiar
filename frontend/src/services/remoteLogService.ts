/**
 * Remote logging service -- captures frontend logs to IndexedDB and
 * periodically ships them to the backend for remote diagnosis.
 *
 * Key design decisions:
 * - captureLog() is synchronous (pushes to in-memory buffer) -- zero overhead on hot path
 * - Write flush (buffer → IDB) runs on a 1s timer
 * - Submit flush (IDB → backend) runs on a 30s timer
 * - Enabled by default; opt-out via localStorage.remoteLogging = 'false'
 * - Best-effort: all failures are silently swallowed
 */
import { db, isIndexedDBAvailable, type RemoteLogEntry } from '../db';
import { getSelectedProfileId } from './profileService';
import { setLogSink } from '../utils/logger';

const WRITE_INTERVAL = 1_000;   // Flush buffer to IDB every 1s
const SUBMIT_INTERVAL = 30_000; // Ship IDB entries to backend every 30s
const LOCAL_CAP = 5_000;        // Max entries in IDB before pruning
const SUBMIT_BATCH = 200;       // Max entries per backend POST
const MAX_MESSAGE_LEN = 2_000;  // Truncate serialized args

let buffer: RemoteLogEntry[] = [];
let writeTimer: ReturnType<typeof setInterval> | null = null;
let submitTimer: ReturnType<typeof setInterval> | null = null;
let initialized = false;
let cachedProfileId: string | null = null;

// ── Helpers ────────────────────────────────────────────────────────

function isEnabled(): boolean {
  try {
    return localStorage.getItem('remoteLogging') !== 'false';
  } catch {
    return true; // default enabled even if localStorage unavailable
  }
}

function serializeArg(arg: unknown): string {
  if (arg instanceof Error) {
    return `${arg.message}${arg.stack ? '\n' + arg.stack : ''}`;
  }
  if (typeof arg === 'object' && arg !== null) {
    try {
      const s = JSON.stringify(arg);
      return s.length > MAX_MESSAGE_LEN ? s.slice(0, MAX_MESSAGE_LEN) + '…' : s;
    } catch {
      return String(arg);
    }
  }
  return String(arg);
}

function serializeArgs(args: unknown[]): string {
  const msg = args.map(serializeArg).join(' ');
  return msg.length > MAX_MESSAGE_LEN ? msg.slice(0, MAX_MESSAGE_LEN) + '…' : msg;
}

// ── Public API ─────────────────────────────────────────────────────

/**
 * Capture a log entry into the in-memory buffer.
 * This is intentionally synchronous and cheap.
 */
export function captureLog(level: string, namespace: string, args: unknown[]): void {
  if (!isEnabled()) return;

  buffer.push({
    level,
    namespace,
    message: serializeArgs(args),
    context: {
      url: location.href,
      userAgent: navigator.userAgent,
      profileId: cachedProfileId,
    },
    createdAt: new Date(),
  });
}

/**
 * Flush in-memory buffer to IndexedDB.
 */
async function flushToIDB(): Promise<void> {
  if (buffer.length === 0) return;

  const available = await isIndexedDBAvailable();
  if (!available) {
    buffer = [];
    return;
  }

  const entries = buffer;
  buffer = [];

  try {
    await db.remoteLogs.bulkAdd(entries);

    // Prune if over local cap
    const count = await db.remoteLogs.count();
    if (count > LOCAL_CAP) {
      const excess = count - LOCAL_CAP;
      const oldest = await db.remoteLogs.orderBy('id').limit(excess).primaryKeys();
      await db.remoteLogs.bulkDelete(oldest);
    }
  } catch {
    // Best-effort: drop entries on failure
  }
}

/**
 * Submit IDB entries to the backend and delete on success.
 */
async function submitToBackend(): Promise<void> {
  const available = await isIndexedDBAvailable();
  if (!available) return;

  let entries: RemoteLogEntry[];
  try {
    entries = await db.remoteLogs.orderBy('createdAt').limit(SUBMIT_BATCH).toArray();
  } catch {
    return;
  }

  if (entries.length === 0) return;

  try {
    const payload = entries.map((e) => ({
      level: e.level,
      namespace: e.namespace,
      message: e.message,
      timestamp: e.createdAt.toISOString(),
      context: e.context,
    }));

    const res = await fetch('/api/v1/diagnostics/frontend-logs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ entries: payload }),
    });

    if (res.ok) {
      const ids = entries.map((e) => e.id!).filter(Boolean);
      await db.remoteLogs.bulkDelete(ids);
    }
  } catch {
    // Silent on failure -- best-effort
  }
}

/**
 * Force an immediate flush + submit cycle. Used by the Settings UI.
 */
export async function flushNow(): Promise<void> {
  await flushToIDB();
  await submitToBackend();
}

/**
 * Get count of pending (unsent) log entries in IDB.
 */
export async function getPendingCount(): Promise<number> {
  const available = await isIndexedDBAvailable();
  if (!available) return 0;
  try {
    return await db.remoteLogs.count();
  } catch {
    return 0;
  }
}

/**
 * Clear all local log entries from IDB.
 */
export async function clearLocalLogs(): Promise<void> {
  const available = await isIndexedDBAvailable();
  if (!available) return;
  try {
    await db.remoteLogs.clear();
  } catch {
    // Best-effort
  }
}

// Register as log sink so logger.ts doesn't need to import us (avoids circular dep)
setLogSink(captureLog);

// ── Initialization ─────────────────────────────────────────────────

/**
 * Initialize remote logging. Returns a cleanup function.
 */
export function initRemoteLogging(): () => void {
  if (initialized) return () => {};
  initialized = true;

  // Cache profile ID (refresh periodically)
  getSelectedProfileId().then((id) => { cachedProfileId = id; }).catch(() => {});

  // Write buffer to IDB on a timer
  writeTimer = setInterval(flushToIDB, WRITE_INTERVAL);

  // Submit IDB entries to backend on a timer
  submitTimer = setInterval(submitToBackend, SUBMIT_INTERVAL);

  // Flush on visibility change (catches iOS tab kills)
  const onVisibilityChange = () => {
    if (document.visibilityState === 'hidden') {
      flushToIDB();
    }
  };
  document.addEventListener('visibilitychange', onVisibilityChange);

  // Flush + submit when coming back online
  const onOnline = () => {
    flushToIDB().then(submitToBackend).catch(() => {});
  };
  window.addEventListener('online', onOnline);

  // Global error handlers
  const onError = (event: ErrorEvent) => {
    captureLog('error', 'uncaught', [
      event.message,
      `at ${event.filename}:${event.lineno}:${event.colno}`,
    ]);
  };
  window.addEventListener('error', onError);

  const onUnhandledRejection = (event: PromiseRejectionEvent) => {
    const reason = event.reason instanceof Error
      ? `${event.reason.message}\n${event.reason.stack}`
      : String(event.reason);
    captureLog('error', 'uncaught', ['Unhandled promise rejection:', reason]);
  };
  window.addEventListener('unhandledrejection', onUnhandledRejection);

  return () => {
    initialized = false;
    if (writeTimer) clearInterval(writeTimer);
    if (submitTimer) clearInterval(submitTimer);
    document.removeEventListener('visibilitychange', onVisibilityChange);
    window.removeEventListener('online', onOnline);
    window.removeEventListener('error', onError);
    window.removeEventListener('unhandledrejection', onUnhandledRejection);
  };
}
