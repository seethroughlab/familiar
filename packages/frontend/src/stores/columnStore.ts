import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface ColumnConfig {
  id: string;
  visible: boolean;
  width?: number | null;  // null = default width from columnDefinitions, number = custom pixels
}

// Default column configuration (order matters)
const DEFAULT_COLUMNS: ColumnConfig[] = [
  { id: 'artist', visible: true },
  { id: 'album', visible: true },
  { id: 'duration', visible: true },
  { id: 'year', visible: false },
  { id: 'genre', visible: false },
  { id: 'trackNum', visible: false },
  { id: 'format', visible: false },
  { id: 'lastPlayed', visible: false },
  { id: 'bpm', visible: false },
  { id: 'key', visible: false },
  { id: 'energy', visible: false },
  { id: 'danceability', visible: false },
  { id: 'valence', visible: false },
  { id: 'acousticness', visible: false },
  { id: 'instrumentalness', visible: false },
];

interface ColumnState {
  columns: ColumnConfig[];
  sortBy: string | null;      // Column ID being sorted
  sortOrder: 'asc' | 'desc';
  toggleColumn: (id: string) => void;
  reorderColumns: (fromIndex: number, toIndex: number) => void;
  setColumnWidth: (id: string, width: number) => void;
  resetColumnWidth: (id: string) => void;
  resetToDefaults: () => void;
  setSortBy: (columnId: string | null, order?: 'asc' | 'desc') => void;
  toggleSort: (columnId: string) => void;  // Click toggles asc/desc/off
}

export const useColumnStore = create<ColumnState>()(
  persist(
    (set) => ({
      columns: DEFAULT_COLUMNS,
      sortBy: null,
      sortOrder: 'asc',

      toggleColumn: (id: string) => {
        set((state) => ({
          columns: state.columns.map((col) =>
            col.id === id ? { ...col, visible: !col.visible } : col
          ),
        }));
      },

      reorderColumns: (fromIndex: number, toIndex: number) => {
        set((state) => {
          const newColumns = [...state.columns];
          const [removed] = newColumns.splice(fromIndex, 1);
          newColumns.splice(toIndex, 0, removed);
          return { columns: newColumns };
        });
      },

      setColumnWidth: (id: string, width: number) => {
        set((state) => ({
          columns: state.columns.map((col) =>
            col.id === id ? { ...col, width } : col
          ),
        }));
      },

      resetColumnWidth: (id: string) => {
        set((state) => ({
          columns: state.columns.map((col) =>
            col.id === id ? { ...col, width: null } : col
          ),
        }));
      },

      resetToDefaults: () => {
        // Reset to defaults including clearing all custom widths and sort
        set({
          columns: DEFAULT_COLUMNS.map(col => ({ ...col, width: null })),
          sortBy: null,
          sortOrder: 'asc',
        });
      },

      setSortBy: (columnId: string | null, order?: 'asc' | 'desc') => {
        set((state) => ({
          sortBy: columnId,
          sortOrder: order ?? state.sortOrder,
        }));
      },

      toggleSort: (columnId: string) => {
        set((state) => {
          if (state.sortBy !== columnId) {
            // Clicking a new column: sort ascending
            return { sortBy: columnId, sortOrder: 'asc' };
          } else if (state.sortOrder === 'asc') {
            // Clicking same column in asc: switch to desc
            return { sortOrder: 'desc' };
          } else {
            // Clicking same column in desc: clear sort (back to default)
            return { sortBy: null, sortOrder: 'asc' };
          }
        });
      },
    }),
    {
      name: 'familiar-columns',
      // Merge stored columns with defaults to handle new columns added in updates
      merge: (persistedState, currentState) => {
        const persisted = persistedState as Partial<ColumnState>;
        if (!persisted.columns) return currentState;

        // Start with persisted columns that still exist in defaults
        const mergedColumns: ColumnConfig[] = [];
        const seenIds = new Set<string>();

        // First, add persisted columns in their saved order (if they exist in defaults)
        for (const col of persisted.columns) {
          const defaultCol = DEFAULT_COLUMNS.find((d) => d.id === col.id);
          if (defaultCol) {
            mergedColumns.push({ ...col });
            seenIds.add(col.id);
          }
        }

        // Then add any new default columns that weren't in persisted state
        for (const col of DEFAULT_COLUMNS) {
          if (!seenIds.has(col.id)) {
            mergedColumns.push({ ...col });
          }
        }

        return {
          ...currentState,
          columns: mergedColumns,
          // Preserve persisted sort state
          sortBy: persisted.sortBy ?? currentState.sortBy,
          sortOrder: persisted.sortOrder ?? currentState.sortOrder,
        };
      },
    }
  )
);

// Helper to get visible columns in order
export const getVisibleColumns = (columns: ColumnConfig[]): string[] => {
  return columns.filter((col) => col.visible).map((col) => col.id);
};
