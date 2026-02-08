/**
 * Tests for columnStore - column visibility, ordering, resize, persistence.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useColumnStore, getVisibleColumns } from '../columnStore';
import type { ColumnConfig } from '../columnStore';

describe('columnStore', () => {
  beforeEach(() => {
    // Reset to defaults
    useColumnStore.getState().resetToDefaults();
  });

  describe('initial state', () => {
    it('should have default columns', () => {
      const { columns } = useColumnStore.getState();
      expect(columns.length).toBeGreaterThan(0);
      expect(columns[0].id).toBe('artist');
    });

    it('should have artist, album, duration visible by default', () => {
      const { columns } = useColumnStore.getState();
      const visible = columns.filter((c) => c.visible).map((c) => c.id);
      expect(visible).toContain('artist');
      expect(visible).toContain('album');
      expect(visible).toContain('duration');
    });

    it('should have year, genre hidden by default', () => {
      const { columns } = useColumnStore.getState();
      const year = columns.find((c) => c.id === 'year');
      const genre = columns.find((c) => c.id === 'genre');
      expect(year?.visible).toBe(false);
      expect(genre?.visible).toBe(false);
    });

    it('should have no active sort', () => {
      const { sortBy, sortOrder } = useColumnStore.getState();
      expect(sortBy).toBeNull();
      expect(sortOrder).toBe('asc');
    });
  });

  describe('toggleColumn', () => {
    it('should toggle column visibility', () => {
      const { toggleColumn } = useColumnStore.getState();

      // year starts hidden
      expect(useColumnStore.getState().columns.find((c) => c.id === 'year')?.visible).toBe(false);

      toggleColumn('year');
      expect(useColumnStore.getState().columns.find((c) => c.id === 'year')?.visible).toBe(true);

      toggleColumn('year');
      expect(useColumnStore.getState().columns.find((c) => c.id === 'year')?.visible).toBe(false);
    });

    it('should not affect other columns', () => {
      const { toggleColumn } = useColumnStore.getState();
      const beforeArtist = useColumnStore.getState().columns.find((c) => c.id === 'artist')?.visible;

      toggleColumn('year');

      const afterArtist = useColumnStore.getState().columns.find((c) => c.id === 'artist')?.visible;
      expect(afterArtist).toBe(beforeArtist);
    });
  });

  describe('reorderColumns', () => {
    it('should move column from one position to another', () => {
      const { reorderColumns } = useColumnStore.getState();

      // artist is at index 0, album at index 1
      reorderColumns(0, 1);

      const { columns } = useColumnStore.getState();
      expect(columns[0].id).toBe('album');
      expect(columns[1].id).toBe('artist');
    });

    it('should move column to the end', () => {
      const { reorderColumns, columns } = useColumnStore.getState();
      const lastIndex = columns.length - 1;

      reorderColumns(0, lastIndex);

      const newColumns = useColumnStore.getState().columns;
      expect(newColumns[lastIndex].id).toBe('artist');
      expect(newColumns[0].id).toBe('album');
    });
  });

  describe('setColumnWidth', () => {
    it('should set a custom width for a column', () => {
      const { setColumnWidth } = useColumnStore.getState();
      setColumnWidth('artist', 200);

      const col = useColumnStore.getState().columns.find((c) => c.id === 'artist');
      expect(col?.width).toBe(200);
    });

    it('should not affect other columns', () => {
      const { setColumnWidth } = useColumnStore.getState();
      setColumnWidth('artist', 200);

      const album = useColumnStore.getState().columns.find((c) => c.id === 'album');
      // After resetToDefaults, all columns have width: null
      expect(album?.width).toBeNull();
    });
  });

  describe('resetColumnWidth', () => {
    it('should reset a column width to null', () => {
      const { setColumnWidth, resetColumnWidth } = useColumnStore.getState();

      setColumnWidth('artist', 200);
      resetColumnWidth('artist');

      const col = useColumnStore.getState().columns.find((c) => c.id === 'artist');
      expect(col?.width).toBeNull();
    });
  });

  describe('resetToDefaults', () => {
    it('should reset columns, widths, and sort', () => {
      const { toggleColumn, setColumnWidth, toggleSort, resetToDefaults } = useColumnStore.getState();

      // Make some changes
      toggleColumn('year');
      setColumnWidth('artist', 200);
      toggleSort('artist');

      resetToDefaults();

      const state = useColumnStore.getState();
      expect(state.columns.find((c) => c.id === 'year')?.visible).toBe(false);
      expect(state.columns.every((c) => c.width === null)).toBe(true);
      expect(state.sortBy).toBeNull();
      expect(state.sortOrder).toBe('asc');
    });
  });

  describe('setSortBy', () => {
    it('should set sort column', () => {
      useColumnStore.getState().setSortBy('artist');
      expect(useColumnStore.getState().sortBy).toBe('artist');
    });

    it('should set sort column with explicit order', () => {
      useColumnStore.getState().setSortBy('artist', 'desc');
      const state = useColumnStore.getState();
      expect(state.sortBy).toBe('artist');
      expect(state.sortOrder).toBe('desc');
    });

    it('should preserve current sort order when no order given', () => {
      useColumnStore.setState({ sortOrder: 'desc' });
      useColumnStore.getState().setSortBy('artist');
      expect(useColumnStore.getState().sortOrder).toBe('desc');
    });

    it('should clear sort with null', () => {
      useColumnStore.getState().setSortBy('artist');
      useColumnStore.getState().setSortBy(null);
      expect(useColumnStore.getState().sortBy).toBeNull();
    });
  });

  describe('toggleSort', () => {
    it('should set ascending on new column', () => {
      useColumnStore.getState().toggleSort('artist');
      const state = useColumnStore.getState();
      expect(state.sortBy).toBe('artist');
      expect(state.sortOrder).toBe('asc');
    });

    it('should toggle asc -> desc on same column', () => {
      useColumnStore.getState().toggleSort('artist');
      useColumnStore.getState().toggleSort('artist');
      const state = useColumnStore.getState();
      expect(state.sortBy).toBe('artist');
      expect(state.sortOrder).toBe('desc');
    });

    it('should clear sort (desc -> off) on same column', () => {
      useColumnStore.getState().toggleSort('artist');
      useColumnStore.getState().toggleSort('artist');
      useColumnStore.getState().toggleSort('artist');
      const state = useColumnStore.getState();
      expect(state.sortBy).toBeNull();
      expect(state.sortOrder).toBe('asc');
    });

    it('should reset to asc when clicking a different column', () => {
      useColumnStore.getState().toggleSort('artist');
      useColumnStore.getState().toggleSort('artist'); // desc
      useColumnStore.getState().toggleSort('album'); // new column -> asc

      const state = useColumnStore.getState();
      expect(state.sortBy).toBe('album');
      expect(state.sortOrder).toBe('asc');
    });
  });
});

describe('getVisibleColumns', () => {
  it('should return only visible column IDs in order', () => {
    const columns: ColumnConfig[] = [
      { id: 'artist', visible: true },
      { id: 'album', visible: false },
      { id: 'duration', visible: true },
      { id: 'year', visible: true },
    ];

    expect(getVisibleColumns(columns)).toEqual(['artist', 'duration', 'year']);
  });

  it('should return empty array when nothing visible', () => {
    const columns: ColumnConfig[] = [
      { id: 'artist', visible: false },
      { id: 'album', visible: false },
    ];

    expect(getVisibleColumns(columns)).toEqual([]);
  });
});
