/**
 * Namespaced logger utility.
 *
 * Usage:
 *   import { createLogger } from '../utils/logger';
 *   const log = createLogger('MyModule');
 *   log.debug('loaded');   // [MyModule] loaded  (dev only)
 *   log.error('fail', e);  // [MyModule] fail Error...  (always)
 *
 * debug/info/warn are dev-only by default (gated on import.meta.env.DEV).
 * error is always logged (real failures matter in production).
 *
 * Runtime debug toggle (same convention as the `debug` npm package):
 *   localStorage.debug = 'AudioEngine'       // one namespace
 *   localStorage.debug = 'AudioEngine,app'   // comma-separated
 *   localStorage.debug = '*'                 // all namespaces
 * Set the flag, refresh the page. Checked once at logger creation time.
 */

const isDev = import.meta.env.DEV;
const noop = () => {};

function isDebugEnabled(namespace: string): boolean {
  try {
    const flag = localStorage.getItem('debug');
    if (!flag) return false;
    if (flag === '*') return true;
    return flag.split(',').some(ns => ns.trim() === namespace);
  } catch {
    return false; // private browsing or localStorage unavailable
  }
}

interface Logger {
  debug: (...args: unknown[]) => void;
  info: (...args: unknown[]) => void;
  warn: (...args: unknown[]) => void;
  error: (...args: unknown[]) => void;
}

export function createLogger(namespace: string, opts?: { forceVerbose?: boolean }): Logger {
  const tag = `[${namespace}]`;
  const verbose = isDev || opts?.forceVerbose || isDebugEnabled(namespace);
  return {
    debug: verbose ? (...args: unknown[]) => console.debug(tag, ...args) : noop,
    info: verbose ? (...args: unknown[]) => console.log(tag, ...args) : noop,
    warn: verbose ? (...args: unknown[]) => console.warn(tag, ...args) : noop,
    error: (...args: unknown[]) => console.error(tag, ...args),
  };
}

// Backwards-compatible default export
export const logger = createLogger('app');
export default logger;
