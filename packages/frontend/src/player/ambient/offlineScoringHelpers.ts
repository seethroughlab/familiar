/**
 * Helper for offline scoring — snippet window suggestion (client-side mirror
 * of the backend's suggest_snippet_window).
 */

export function suggestSnippetWindow(
  durationSeconds: number | null,
  energyShape: string | null,
): [number, number] {
  if (!durationSeconds || durationSeconds < 30) {
    return [0.1, 0.9];
  }

  const startGuard = Math.min(10 / durationSeconds, 0.15);
  const endGuard = Math.min(20 / durationSeconds, 0.15);

  let startPct = Math.max(0.25, startGuard);
  let endPct = Math.min(0.70, 1.0 - endGuard);

  if (energyShape === 'building') {
    startPct = Math.max(0.35, startGuard);
    endPct = Math.min(0.80, 1.0 - endGuard);
  } else if (energyShape === 'declining') {
    startPct = Math.max(0.15, startGuard);
    endPct = Math.min(0.55, 1.0 - endGuard);
  } else if (energyShape === 'peak_middle') {
    startPct = Math.max(0.30, startGuard);
    endPct = Math.min(0.65, 1.0 - endGuard);
  }

  return [
    Math.round(startPct * 10000) / 10000,
    Math.round(endPct * 10000) / 10000,
  ];
}
