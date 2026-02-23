/**
 * Shared utilities for columnar playlist rendering.
 * Provides grid column building, local sort state, and client-side sorting.
 */
import { useState, useCallback, useMemo } from 'react';
import { COLUMN_DEFINITIONS, getColumnDef } from '../Library/columnDefinitions';
import type { ColumnConfig } from '../../stores/columnStore';
import { getVisibleColumns } from '../../stores/columnStore';
import type { Track } from '../../types';

/**
 * Build CSS grid-template-columns string for playlist rows.
 * Layout: index (3rem) | title (1fr) | dynamic columns... | trailing columns...
 */
export function buildGridColumns(
  columns: ColumnConfig[],
  trailingColumns: string[] = ['3rem', '4.5rem'],
): string {
  const visibleIds = getVisibleColumns(columns);
  const cols: string[] = ['3rem', '1fr']; // index + title

  for (const colId of visibleIds) {
    const col = columns.find(c => c.id === colId);
    const customWidth = col?.width;
    if (customWidth != null) {
      cols.push(`${customWidth}px`);
    } else {
      const colDef = COLUMN_DEFINITIONS.find(d => d.id === colId);
      cols.push(colDef?.width || '1fr');
    }
  }

  cols.push(...trailingColumns);
  return cols.join(' ');
}

/**
 * Local sort state hook — isolated from the library's columnStore sort
 * so playlist sort doesn't affect library sort and vice versa.
 * Uses the same tri-state cycle: asc -> desc -> clear.
 */
export function useLocalSort(persistKey?: string) {
  const storageKey = persistKey ? `familiar-sort-${persistKey}` : null;

  const [sortBy, setSortBy] = useState<string | null>(() => {
    if (!storageKey) return null;
    try {
      const stored = localStorage.getItem(storageKey);
      if (stored) return JSON.parse(stored).sortBy ?? null;
    } catch { /* ignore */ }
    return null;
  });
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>(() => {
    if (!storageKey) return 'asc';
    try {
      const stored = localStorage.getItem(storageKey);
      if (stored) return JSON.parse(stored).sortOrder ?? 'asc';
    } catch { /* ignore */ }
    return 'asc';
  });

  const persist = useCallback((newSortBy: string | null, newSortOrder: 'asc' | 'desc') => {
    if (!storageKey) return;
    if (newSortBy === null) {
      localStorage.removeItem(storageKey);
    } else {
      localStorage.setItem(storageKey, JSON.stringify({ sortBy: newSortBy, sortOrder: newSortOrder }));
    }
  }, [storageKey]);

  const toggleSort = useCallback((columnId: string) => {
    setSortBy(prev => {
      if (prev !== columnId) {
        setSortOrder('asc');
        persist(columnId, 'asc');
        return columnId;
      } else if (sortOrder === 'asc') {
        setSortOrder('desc');
        persist(columnId, 'desc');
        return columnId;
      } else {
        setSortOrder('asc');
        persist(null, 'asc');
        return null;
      }
    });
  }, [sortOrder, persist]);

  const clearSort = useCallback(() => {
    setSortBy(null);
    setSortOrder('asc');
    persist(null, 'asc');
  }, [persist]);

  return { sortBy, sortOrder, toggleSort, clearSort };
}

/**
 * Client-side sort for playlist tracks using column definitions.
 * `getTrack` extracts the Track-shaped object from each item (for lists
 * where items wrap tracks, like FavoritesListItem).
 */
export function useSortedTracks<T>(
  items: T[],
  sortBy: string | null,
  sortOrder: 'asc' | 'desc',
  getTrack: (item: T) => Track | null,
): T[] {
  return useMemo(() => {
    if (!sortBy || items.length === 0) return items;

    const sorted = [...items];
    sorted.sort((a, b) => {
      const trackA = getTrack(a);
      const trackB = getTrack(b);
      if (!trackA || !trackB) {
        // Null tracks (e.g. unmatched) go to the end
        if (!trackA && !trackB) return 0;
        return trackA ? -1 : 1;
      }

      let valA: string | number | null | undefined;
      let valB: string | number | null | undefined;

      if (sortBy === 'title') {
        valA = trackA.title;
        valB = trackB.title;
      } else {
        const colDef = getColumnDef(sortBy);
        if (!colDef) return 0;
        valA = colDef.getValue(trackA);
        valB = colDef.getValue(trackB);
      }

      // Nulls last
      if (valA == null && valB == null) return 0;
      if (valA == null) return 1;
      if (valB == null) return -1;

      let cmp: number;
      if (typeof valA === 'string' && typeof valB === 'string') {
        cmp = valA.localeCompare(valB, undefined, { sensitivity: 'base' });
      } else {
        cmp = Number(valA) - Number(valB);
      }

      return sortOrder === 'desc' ? -cmp : cmp;
    });

    return sorted;
  }, [items, sortBy, sortOrder, getTrack]);
}
