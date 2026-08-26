/** Default visualizer shown on first load. */
export const DEFAULT_VISUALIZER_ID = 'reactive-terrain';

/**
 * localStorage key for persisted visualizer preference.
 *
 * `VISUALIZER_IDS` used to sit here, listing the built-in ids "so a plugin claiming one is refused".
 * Nothing ever imported it, so nothing was ever refused by it — and by the time it was removed its
 * docblock was false twice over: it named `music-video`, which ADR-0085 retired, and it did not name
 * `spectrum`, which ships. A list with no caller cannot go stale loudly (ADR-0077).
 */
export const VISUALIZER_STORAGE_KEY = 'familiar-visualizer';
