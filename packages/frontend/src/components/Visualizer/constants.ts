/** Default visualizer shown on first load. */
/**
 * The same default the Apple app's menu uses (`beat-tiles`). They disagreed, so a page told nothing drew
 * a different visualizer from the one the app's menu ticked.
 */
export const DEFAULT_VISUALIZER_ID = 'beat-tiles';

/**
 * localStorage key for persisted visualizer preference.
 *
 * `VISUALIZER_IDS` used to sit here, listing the built-in ids "so a plugin claiming one is refused".
 * Nothing ever imported it, so nothing was ever refused by it — and by the time it was removed its
 * docblock was false twice over: it named `music-video`, which ADR-0085 retired, and it did not name
 * `spectrum`, which ships. A list with no caller cannot go stale loudly (ADR-0077).
 */
export const VISUALIZER_STORAGE_KEY = 'familiar-visualizer';
