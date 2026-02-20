/**
 * Generic multi-select hook with shift-range, ctrl-toggle, and plain-select.
 *
 * Manages selectedIds Set + lastClickedId for range selection.
 * Consumed by PlaylistTrackList and reusable by other list views.
 */
import { useState, useCallback } from 'react';

export interface UseMultiSelectResult {
  selectedIds: Set<string>;
  lastClickedId: string | null;
  /** Handle click with modifier key support: shift=range, ctrl/cmd=toggle, plain=select-only */
  handleItemClick: (id: string, index: number, event: { shiftKey: boolean; metaKey: boolean; ctrlKey: boolean }, orderedIds: string[]) => void;
  /** Toggle a single item */
  toggleItem: (id: string) => void;
  /** Select all items */
  selectAll: (ids: string[]) => void;
  /** Clear selection */
  clearSelection: () => void;
  /** Check if an item is selected */
  isSelected: (id: string) => boolean;
}

export function useMultiSelect(): UseMultiSelectResult {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [lastClickedId, setLastClickedId] = useState<string | null>(null);

  const handleItemClick = useCallback(
    (id: string, index: number, event: { shiftKey: boolean; metaKey: boolean; ctrlKey: boolean }, orderedIds: string[]) => {
      if (event.shiftKey && lastClickedId) {
        // Shift-click: select range from last clicked to current
        const lastIdx = orderedIds.indexOf(lastClickedId);
        if (lastIdx !== -1) {
          const [start, end] = lastIdx < index ? [lastIdx, index] : [index, lastIdx];
          const rangeIds = orderedIds.slice(start, end + 1);
          setSelectedIds(prev => new Set([...prev, ...rangeIds]));
        } else {
          // lastClickedId not in current list, just select this one
          setSelectedIds(new Set([id]));
          setLastClickedId(id);
        }
      } else if (event.metaKey || event.ctrlKey) {
        // Ctrl/Cmd-click: toggle single item
        setSelectedIds(prev => {
          const next = new Set(prev);
          if (next.has(id)) {
            next.delete(id);
          } else {
            next.add(id);
          }
          return next;
        });
        setLastClickedId(id);
      } else {
        // Plain click: select only this item
        setSelectedIds(new Set([id]));
        setLastClickedId(id);
      }
    },
    [lastClickedId],
  );

  const toggleItem = useCallback((id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const selectAll = useCallback((ids: string[]) => {
    setSelectedIds(new Set(ids));
  }, []);

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set());
    setLastClickedId(null);
  }, []);

  const isSelected = useCallback((id: string) => selectedIds.has(id), [selectedIds]);

  return {
    selectedIds,
    lastClickedId,
    handleItemClick,
    toggleItem,
    selectAll,
    clearSelection,
    isSelected,
  };
}
