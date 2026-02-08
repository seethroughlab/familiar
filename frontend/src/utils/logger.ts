/**
 * Namespaced logger utility.
 *
 * Usage:
 *   import { createLogger } from '../utils/logger';
 *   const log = createLogger('MyModule');
 *   log.debug('loaded');   // [MyModule] loaded  (dev only)
 *   log.error('fail', e);  // [MyModule] fail Error...  (always)
 *
 * debug/info/warn are dev-only (gated on import.meta.env.DEV).
 * error is always logged (real failures matter in production).
 */

const isDev = import.meta.env.DEV;
const noop = () => {};

interface Logger {
  debug: (...args: unknown[]) => void;
  info: (...args: unknown[]) => void;
  warn: (...args: unknown[]) => void;
  error: (...args: unknown[]) => void;
}

export function createLogger(namespace: string): Logger {
  const tag = `[${namespace}]`;
  return {
    debug: isDev ? (...args: unknown[]) => console.debug(tag, ...args) : noop,
    info: isDev ? (...args: unknown[]) => console.log(tag, ...args) : noop,
    warn: isDev ? (...args: unknown[]) => console.warn(tag, ...args) : noop,
    error: (...args: unknown[]) => console.error(tag, ...args),
  };
}

// Backwards-compatible default export
export const logger = createLogger('app');
export default logger;
