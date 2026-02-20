/**
 * Hook returning the responsive column count matching Tailwind grid breakpoints.
 *
 * Breakpoints: grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6
 *
 * Uses matchMedia listeners so the value updates on resize without polling.
 */
import { useState, useEffect } from 'react';

// Tailwind default breakpoints (px)
const BREAKPOINTS = [
  { min: 1280, cols: 6 }, // xl
  { min: 1024, cols: 5 }, // lg
  { min: 768, cols: 4 },  // md
  { min: 640, cols: 3 },  // sm
];
const DEFAULT_COLS = 2;

function getColumns(): number {
  for (const bp of BREAKPOINTS) {
    if (window.matchMedia(`(min-width: ${bp.min}px)`).matches) {
      return bp.cols;
    }
  }
  return DEFAULT_COLS;
}

export function useGridColumns(): number {
  const [cols, setCols] = useState(getColumns);

  useEffect(() => {
    const queries = BREAKPOINTS.map((bp) => window.matchMedia(`(min-width: ${bp.min}px)`));

    const handler = () => setCols(getColumns());

    for (const mql of queries) {
      mql.addEventListener('change', handler);
    }

    return () => {
      for (const mql of queries) {
        mql.removeEventListener('change', handler);
      }
    };
  }, []);

  return cols;
}
