/**
 * Shared formatting utilities.
 */

/** Format seconds as M:SS or --:-- for null/zero */
export function formatDuration(seconds: number | null | undefined): string {
  if (typeof seconds !== 'number' || !seconds) return '--:--';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}
