import { create } from 'zustand';

interface SelectionState {
  // Selected track IDs
  selectedIds: Set<string>;

  // Last clicked ID for shift-select
  lastClickedId: string | null;

  // Selection mode toggle (shows checkboxes)
  selectionMode: boolean;

  // Track being edited (single or first of bulk)
  editingTrackId: string | null;

  // Actions
  toggleSelection: (trackId: string) => void;
  selectRange: (toId: string, allIds: string[]) => void;
  selectAll: (trackIds: string[]) => void;
  clearSelection: () => void;
  setSelectionMode: (enabled: boolean) => void;
  setEditingTrackId: (trackId: string | null) => void;

  // Computed
  isSelected: (trackId: string) => boolean;
  getSelectedCount: () => number;
  getSelectedIds: () => string[];
}

export const useSelectionStore = create<SelectionState>((set, get) => ({
  selectedIds: new Set(),
  lastClickedId: null,
  selectionMode: false,
  editingTrackId: null,

  toggleSelection: (trackId: string) => {
    set((state) => {
      const newSet = new Set(state.selectedIds);
      if (newSet.has(trackId)) {
        newSet.delete(trackId);
      } else {
        newSet.add(trackId);
      }
      return {
        selectedIds: newSet,
        lastClickedId: trackId,
        // Auto-enable selection mode when selecting
        selectionMode: newSet.size > 0 ? true : state.selectionMode,
      };
    });
  },

  selectRange: (toId: string, allIds: string[]) => {
    const { lastClickedId, selectedIds } = get();
    if (!lastClickedId) {
      // No previous click, just select the target
      set({
        selectedIds: new Set([toId]),
        lastClickedId: toId,
        selectionMode: true,
      });
      return;
    }

    const fromIndex = allIds.indexOf(lastClickedId);
    const toIndex = allIds.indexOf(toId);

    if (fromIndex === -1 || toIndex === -1) {
      // Can't find indices, just toggle
      get().toggleSelection(toId);
      return;
    }

    const start = Math.min(fromIndex, toIndex);
    const end = Math.max(fromIndex, toIndex);

    const newSet = new Set(selectedIds);
    for (let i = start; i <= end; i++) {
      newSet.add(allIds[i]);
    }

    set({
      selectedIds: newSet,
      lastClickedId: toId,
      selectionMode: true,
    });
  },

  selectAll: (trackIds: string[]) => {
    set({
      selectedIds: new Set(trackIds),
      selectionMode: true,
    });
  },

  clearSelection: () => {
    set({
      selectedIds: new Set(),
      lastClickedId: null,
      selectionMode: false,
    });
  },

  setSelectionMode: (enabled: boolean) => {
    set({
      selectionMode: enabled,
      // Clear selection when exiting selection mode
      ...(enabled ? {} : { selectedIds: new Set(), lastClickedId: null }),
    });
  },

  setEditingTrackId: (trackId: string | null) => {
    set({ editingTrackId: trackId });
  },

  isSelected: (trackId: string) => {
    return get().selectedIds.has(trackId);
  },

  getSelectedCount: () => {
    return get().selectedIds.size;
  },

  getSelectedIds: () => {
    return Array.from(get().selectedIds);
  },
}));
