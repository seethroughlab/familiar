import { useState, useCallback, useEffect } from 'react';
import { useColumnStore } from '../stores/columnStore';

const MIN_COLUMN_WIDTH = 50;

/**
 * Shared hook for column resize via mouse drag.
 * Manages resize state, mouse listeners, cursor style, and column store updates.
 */
export function useColumnResize() {
  const setColumnWidth = useColumnStore((state) => state.setColumnWidth);
  const resetColumnWidth = useColumnStore((state) => state.resetColumnWidth);
  const [resizing, setResizing] = useState<{
    columnId: string;
    headerEl: HTMLElement;
  } | null>(null);

  const handleResizeStart = useCallback((columnId: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();

    const headerEl = e.currentTarget.parentElement;
    if (!headerEl) return;

    setResizing({ columnId, headerEl });
  }, []);

  // Handle resize mouse move and mouse up
  useEffect(() => {
    if (!resizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      const left = resizing.headerEl.getBoundingClientRect().left;
      const newWidth = Math.max(MIN_COLUMN_WIDTH, e.clientX - left);
      setColumnWidth(resizing.columnId, newWidth);
    };

    const handleMouseUp = () => {
      setResizing(null);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [resizing, setColumnWidth]);

  // Apply resize cursor and prevent text selection during resize
  useEffect(() => {
    if (resizing) {
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      return () => {
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      };
    }
  }, [resizing]);

  return {
    resizingColumnId: resizing?.columnId ?? null,
    handleResizeStart,
    resetColumnWidth,
  };
}
