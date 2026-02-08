/**
 * Tests for selectionStore - multi-select logic for track lists.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useSelectionStore } from '../selectionStore';

describe('selectionStore', () => {
  beforeEach(() => {
    useSelectionStore.setState({
      selectedIds: new Set(),
      lastClickedId: null,
      selectionMode: false,
      editingTrackId: null,
    });
  });

  describe('toggleSelection', () => {
    it('should select an unselected track', () => {
      useSelectionStore.getState().toggleSelection('track-1');

      const state = useSelectionStore.getState();
      expect(state.selectedIds.has('track-1')).toBe(true);
      expect(state.lastClickedId).toBe('track-1');
    });

    it('should deselect a selected track', () => {
      useSelectionStore.getState().toggleSelection('track-1');
      useSelectionStore.getState().toggleSelection('track-1');

      const state = useSelectionStore.getState();
      expect(state.selectedIds.has('track-1')).toBe(false);
    });

    it('should auto-enable selection mode when selecting', () => {
      expect(useSelectionStore.getState().selectionMode).toBe(false);

      useSelectionStore.getState().toggleSelection('track-1');
      expect(useSelectionStore.getState().selectionMode).toBe(true);
    });

    it('should keep selection mode when deselecting (still has items)', () => {
      useSelectionStore.getState().toggleSelection('track-1');
      useSelectionStore.getState().toggleSelection('track-2');
      useSelectionStore.getState().toggleSelection('track-1'); // deselect

      expect(useSelectionStore.getState().selectionMode).toBe(true);
    });

    it('should update lastClickedId', () => {
      useSelectionStore.getState().toggleSelection('track-1');
      useSelectionStore.getState().toggleSelection('track-2');

      expect(useSelectionStore.getState().lastClickedId).toBe('track-2');
    });
  });

  describe('selectRange', () => {
    const allIds = ['a', 'b', 'c', 'd', 'e'];

    it('should select single track when no previous click', () => {
      useSelectionStore.getState().selectRange('c', allIds);

      const state = useSelectionStore.getState();
      expect(state.selectedIds.size).toBe(1);
      expect(state.selectedIds.has('c')).toBe(true);
      expect(state.lastClickedId).toBe('c');
      expect(state.selectionMode).toBe(true);
    });

    it('should select range from last clicked to target (forward)', () => {
      useSelectionStore.getState().toggleSelection('b'); // set lastClickedId
      useSelectionStore.getState().selectRange('d', allIds);

      const state = useSelectionStore.getState();
      expect(state.selectedIds.has('b')).toBe(true);
      expect(state.selectedIds.has('c')).toBe(true);
      expect(state.selectedIds.has('d')).toBe(true);
      expect(state.selectedIds.size).toBe(3); // b was already selected + c + d
    });

    it('should select range from last clicked to target (backward)', () => {
      useSelectionStore.getState().toggleSelection('d'); // set lastClickedId
      useSelectionStore.getState().selectRange('b', allIds);

      const state = useSelectionStore.getState();
      expect(state.selectedIds.has('b')).toBe(true);
      expect(state.selectedIds.has('c')).toBe(true);
      expect(state.selectedIds.has('d')).toBe(true);
    });

    it('should add to existing selection (not replace)', () => {
      useSelectionStore.getState().toggleSelection('a'); // select a, lastClicked=a
      useSelectionStore.getState().selectRange('c', allIds); // select a-c range

      const state = useSelectionStore.getState();
      expect(state.selectedIds.has('a')).toBe(true);
      expect(state.selectedIds.has('b')).toBe(true);
      expect(state.selectedIds.has('c')).toBe(true);
    });

    it('should fallback to toggleSelection when ID not in list', () => {
      useSelectionStore.getState().toggleSelection('a'); // set lastClickedId
      useSelectionStore.getState().selectRange('z', allIds); // z is not in list

      // Should toggle 'z' since index can't be found
      const state = useSelectionStore.getState();
      expect(state.selectedIds.has('z')).toBe(true);
    });
  });

  describe('selectAll', () => {
    it('should select all provided IDs', () => {
      useSelectionStore.getState().selectAll(['a', 'b', 'c']);

      const state = useSelectionStore.getState();
      expect(state.selectedIds.size).toBe(3);
      expect(state.selectionMode).toBe(true);
    });

    it('should replace previous selection', () => {
      useSelectionStore.getState().toggleSelection('x');
      useSelectionStore.getState().selectAll(['a', 'b']);

      const state = useSelectionStore.getState();
      expect(state.selectedIds.size).toBe(2);
      expect(state.selectedIds.has('x')).toBe(false);
    });
  });

  describe('clearSelection', () => {
    it('should clear all selected IDs and exit selection mode', () => {
      useSelectionStore.getState().toggleSelection('a');
      useSelectionStore.getState().toggleSelection('b');
      useSelectionStore.getState().clearSelection();

      const state = useSelectionStore.getState();
      expect(state.selectedIds.size).toBe(0);
      expect(state.lastClickedId).toBeNull();
      expect(state.selectionMode).toBe(false);
    });
  });

  describe('setSelectionMode', () => {
    it('should enable selection mode', () => {
      useSelectionStore.getState().setSelectionMode(true);
      expect(useSelectionStore.getState().selectionMode).toBe(true);
    });

    it('should clear selection when disabling', () => {
      useSelectionStore.getState().toggleSelection('a');
      useSelectionStore.getState().setSelectionMode(false);

      const state = useSelectionStore.getState();
      expect(state.selectionMode).toBe(false);
      expect(state.selectedIds.size).toBe(0);
      expect(state.lastClickedId).toBeNull();
    });
  });

  describe('setEditingTrackId', () => {
    it('should set and clear editing track ID', () => {
      useSelectionStore.getState().setEditingTrackId('track-1');
      expect(useSelectionStore.getState().editingTrackId).toBe('track-1');

      useSelectionStore.getState().setEditingTrackId(null);
      expect(useSelectionStore.getState().editingTrackId).toBeNull();
    });
  });

  describe('computed helpers', () => {
    it('isSelected should check if a track is selected', () => {
      useSelectionStore.getState().toggleSelection('a');

      const { isSelected } = useSelectionStore.getState();
      expect(isSelected('a')).toBe(true);
      expect(isSelected('b')).toBe(false);
    });

    it('getSelectedCount should return count', () => {
      useSelectionStore.getState().selectAll(['a', 'b', 'c']);
      expect(useSelectionStore.getState().getSelectedCount()).toBe(3);
    });

    it('getSelectedIds should return array of IDs', () => {
      useSelectionStore.getState().selectAll(['a', 'b']);

      const ids = useSelectionStore.getState().getSelectedIds();
      expect(ids).toHaveLength(2);
      expect(ids).toContain('a');
      expect(ids).toContain('b');
    });
  });
});
