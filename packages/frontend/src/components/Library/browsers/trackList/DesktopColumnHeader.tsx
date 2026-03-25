/**
 * Desktop column header with drag-drop reordering, sorting, and resizing.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { ChevronUp, ChevronDown } from 'lucide-react';
import { useColumnStore, getVisibleColumns } from '../../../../stores/columnStore';
import { getColumnDef } from '../../columnDefinitions';

// Minimum column width in pixels
const MIN_COLUMN_WIDTH = 50;

export interface DesktopColumnHeaderProps {
  gridColumns: string;
}

export function DesktopColumnHeader({ gridColumns }: DesktopColumnHeaderProps) {
  const columns = useColumnStore((state) => state.columns);
  const reorderColumns = useColumnStore((state) => state.reorderColumns);
  const sortBy = useColumnStore((state) => state.sortBy);
  const sortOrder = useColumnStore((state) => state.sortOrder);
  const toggleSort = useColumnStore((state) => state.toggleSort);
  const setSortBy = useColumnStore((state) => state.setSortBy);
  const setColumnWidth = useColumnStore((state) => state.setColumnWidth);
  const resetColumnWidth = useColumnStore((state) => state.resetColumnWidth);

  const visibleColumnIds = useMemo(() => getVisibleColumns(columns), [columns]);

  // Drag & drop state for columns
  const [draggedColId, setDraggedColId] = useState<string | null>(null);
  const [dropTargetId, setDropTargetId] = useState<string | null>(null);

  // Resize state for columns
  const [resizing, setResizing] = useState<{
    columnId: string;
    headerEl: HTMLElement;
  } | null>(null);

  // Drag handlers for column reordering
  const handleDragStart = (colId: string) => {
    setDraggedColId(colId);
  };

  const handleDragOver = (e: React.DragEvent, colId: string) => {
    e.preventDefault();
    if (draggedColId && draggedColId !== colId) {
      setDropTargetId(colId);
    }
  };

  const handleDragLeave = () => {
    setDropTargetId(null);
  };

  const handleDrop = (e: React.DragEvent, targetColId: string) => {
    e.preventDefault();
    if (draggedColId && draggedColId !== targetColId) {
      const fromIndex = columns.findIndex((c) => c.id === draggedColId);
      const toIndex = columns.findIndex((c) => c.id === targetColId);
      if (fromIndex !== -1 && toIndex !== -1) {
        reorderColumns(fromIndex, toIndex);
      }
    }
    setDraggedColId(null);
    setDropTargetId(null);
  };

  const handleDragEnd = () => {
    setDraggedColId(null);
    setDropTargetId(null);
  };

  // Resize handlers
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

  return (
    <div
      className="grid gap-4 px-4 py-2 text-sm text-zinc-400 border-b border-zinc-800 flex-shrink-0"
      style={{ gridTemplateColumns: gridColumns }}
    >
      <div
        onClick={() => setSortBy(null)}
        className={`cursor-pointer hover:text-white flex items-center gap-1 ${
          sortBy === null ? 'text-white' : ''
        }`}
        title="Click to sort by default order"
      >
        <span>#</span>
        {sortBy === null && (
          <ChevronDown className="w-3 h-3 flex-shrink-0" />
        )}
      </div>
      <div
        onClick={() => toggleSort('title')}
        className={`cursor-pointer hover:text-white flex items-center gap-1 ${
          sortBy === 'title' ? 'text-white' : ''
        }`}
        title="Click to sort by Title"
      >
        <span>Title</span>
        {sortBy === 'title' && (
          sortOrder === 'asc' ? (
            <ChevronUp className="w-3 h-3 flex-shrink-0" />
          ) : (
            <ChevronDown className="w-3 h-3 flex-shrink-0" />
          )
        )}
      </div>
      {visibleColumnIds.map((colId) => {
        const colDef = getColumnDef(colId);
        if (!colDef) return null;
        const isDragging = draggedColId === colId;
        const isDropTarget = dropTargetId === colId;
        const isSortable = !!colDef.sortField;
        const isSorted = sortBy === colId;
        return (
          <div key={colId} className="relative">
            <div
              draggable
              onDragStart={() => handleDragStart(colId)}
              onDragOver={(e) => handleDragOver(e, colId)}
              onDragLeave={handleDragLeave}
              onDrop={(e) => handleDrop(e, colId)}
              onDragEnd={handleDragEnd}
              onClick={(e) => {
                // Only sort on click, not drag
                if (isSortable && !draggedColId) {
                  e.stopPropagation();
                  toggleSort(colId);
                }
              }}
              className={`select-none truncate pr-2 flex items-center gap-1 ${
                colDef.align === 'right'
                  ? 'justify-end'
                  : colDef.align === 'center'
                  ? 'justify-center'
                  : ''
              } ${isDragging ? 'opacity-50' : ''} ${
                isDropTarget ? 'border-l-2 border-green-500' : ''
              } ${isSortable ? 'cursor-pointer hover:text-white' : 'cursor-grab'} ${
                isSorted ? 'text-white' : ''
              }`}
              title={isSortable ? `Click to sort by ${colDef.label}, drag to reorder` : `${colDef.label} (drag to reorder)`}
            >
              <span>{colDef.shortLabel || colDef.label}</span>
              {isSorted && (
                sortOrder === 'asc' ? (
                  <ChevronUp className="w-3 h-3 flex-shrink-0" />
                ) : (
                  <ChevronDown className="w-3 h-3 flex-shrink-0" />
                )
              )}
            </div>

            {/* Resize handle */}
            <div
              className={`absolute right-0 top-1 bottom-1 w-1.5 cursor-col-resize
                         transition-colors border-r border-transparent
                         hover:border-zinc-500 hover:bg-zinc-500/20
                         ${resizing?.columnId === colId ? 'border-zinc-400 bg-zinc-500/30' : ''}`}
              onMouseDown={(e) => handleResizeStart(colId, e)}
              onDoubleClick={() => resetColumnWidth(colId)}
              title="Drag to resize, double-click to reset"
            />
          </div>
        );
      })}
      <div></div>
      <div></div>
    </div>
  );
}
