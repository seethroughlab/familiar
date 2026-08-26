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
import type { RemoteLogEntry } from './remoteLogTypes';
import { frontendLogsApi } from '../api';
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
 * Submit buffered entries to the backend.
 *
 * **No local database.** These used to be spooled into IndexedDB and drained from there, which
 * made a log survive a page close. ADR-0071 removed that store, and the buffer flushes on a
 * one-second timer and on `pagehide`, so what is lost is at most a second of diagnostics.
 *
 * Entries go back on the buffer if the request fails, so a transient outage does not lose them.
 */
async function submitToBackend(): Promise<void> {
  if (buffer.length === 0) return;

  const entries = buffer.slice(0, SUBMIT_BATCH);
  buffer = buffer.slice(entries.length);

  try {
    await frontendLogsApi.ingest(entries.map((e) => ({
      level: e.level,
      namespace: e.namespace,
      message: e.message,
      timestamp: e.createdAt.toISOString(),
      context: e.context,
    })));
  } catch {
    buffer = entries.concat(buffer).slice(-LOCAL_CAP);
  }
}

/**
 * Force an immediate flush + submit cycle. Used by the Settings UI.
 */
export async function flushNow(): Promise<void> {
  await submitToBackend();
}

/**
 * Count of buffered entries not yet accepted by the backend.
 */
export async function getPendingCount(): Promise<number> {
  return buffer.length;
}

/**
 * Drop everything buffered locally.
 */
export async function clearLocalLogs(): Promise<void> {
  buffer = [];
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
  writeTimer = setInterval(submitToBackend, WRITE_INTERVAL);

  // Submit IDB entries to backend on a timer
  submitTimer = setInterval(submitToBackend, SUBMIT_INTERVAL);

  // Flush on visibility change (catches iOS tab kills)
  const onVisibilityChange = () => {
    if (document.visibilityState === 'hidden') {
      submitToBackend();
    }
  };
  document.addEventListener('visibilitychange', onVisibilityChange);

  // Flush + submit when coming back online
  const onOnline = () => {
    submitToBackend().then(submitToBackend).catch(() => {});
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
